"""
sync/ao3.py — Milestone 6: FanFicFare integration.

Downloads AO3 stories as epubs using the FanFicFare CLI, in batches
with configurable delays to avoid rate-limiting and the FanFicFare
stall issue that occurs after a handful of sequential downloads.

FanFicFare must be installed on the Windows side:
    pip install fanficfare

Or available via the configured FANFICFARE_CMD path in config.py.

AO3 work URL format:
    https://archiveofourown.org/works/<work_id>
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_CACHE_FILENAME = ".fanficflow_cache.json"


def _interruptible_sleep(seconds: int, cancel_event: threading.Event | None) -> bool:
    """
    Sleep for up to `seconds`, waking immediately if cancel_event is set.

    Returns True if the sleep was cut short by a cancel signal, False if the
    full duration elapsed normally.
    """
    if cancel_event is None:
        time.sleep(seconds)
        return False
    return cancel_event.wait(timeout=seconds)

from orchestrator import config

AO3_WORK_URL = "https://archiveofourown.org/works/{work_id}"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class DownloadResult:
    """Result of attempting to download one AO3 story."""

    story: dict                        # original story dict from diff.py
    epub_path: Path | None = field(default=None)  # None if download failed
    error: str | None = field(default=None)
    skipped: bool = field(default=False)  # True when an existing epub was reused

    @property
    def success(self) -> bool:
        return self.epub_path is not None

    @property
    def credentials_error(self) -> bool:
        """True if the failure was caused by missing or invalid AO3 credentials."""
        return bool(self.error and _is_credentials_error(self.error))


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def build_ao3_url(work_id: str) -> str:
    """Return the canonical AO3 work URL for the given work ID."""
    return AO3_WORK_URL.format(work_id=work_id)


# ---------------------------------------------------------------------------
# Pre-download epub detection
# ---------------------------------------------------------------------------


def find_existing_epub(work_id: str, output_dir: Path) -> Path | None:
    """
    Return an epub already present in output_dir for the given work_id, or None.

    Two checks are performed in order:

    1. Glob for ``*<work_id>*.epub`` — catches files where FanFicFare included
       the work ID in the filename (common) and any epub the user manually placed
       there and named to include the work ID.

    2. Cache lookup in ``.fanficflow_cache.json`` — catches previously downloaded
       files whose names don't contain the work ID.  This file is written by
       ``_cache_epub`` after every successful download.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Filename contains the work_id.
    matches = list(output_dir.glob(f"*{work_id}*.epub"))
    if matches:
        return max(matches, key=lambda p: p.stat().st_mtime)

    # 2. Cache file mapping.
    cache_path = output_dir / _CACHE_FILENAME
    if cache_path.exists():
        try:
            cache: dict = json.loads(cache_path.read_text(encoding="utf-8"))
            name = cache.get(work_id)
            if name:
                cached = output_dir / name
                if cached.exists():
                    return cached
        except Exception:
            pass

    return None


def _cache_epub(work_id: str, epub_path: Path, output_dir: Path) -> None:
    """Record work_id → filename in the download cache after a successful download."""
    cache_path = output_dir / _CACHE_FILENAME
    try:
        cache: dict = {}
        if cache_path.exists():
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        cache[work_id] = epub_path.name
        cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Credentials error detection
# ---------------------------------------------------------------------------


def _is_credentials_error(output: str) -> bool:
    """
    Return True if FanFicFare's output indicates an AO3 login failure.

    This happens when a story requires login (registered users only, or
    adult content gating) and either no credentials are configured or the
    credentials are wrong. FanFicFare surfaces this as a 403 on the AO3
    login endpoint, and the traceback always passes through performLogin.
    """
    lower = output.lower()
    return "performlogin" in lower or "archiveofourown.org/users/login" in lower


# ---------------------------------------------------------------------------
# Cloudflare error detection
# ---------------------------------------------------------------------------

# HTTP status codes returned by Cloudflare that are transient and retryable.
# 525 — SSL Handshake Failed (most common AO3/Cloudflare error)
# 524 — A Timeout Occurred
# 503 — Service Unavailable (CF under load)
# 502 — Bad Gateway
# 429 — Too Many Requests (rate limiting)
_CLOUDFLARE_RETRYABLE_CODES = {"525", "524", "503", "502", "429"}


def _is_cloudflare_error(output: str) -> bool:
    """
    Return True if FanFicFare's output looks like a transient Cloudflare error.

    Checks both for the word "cloudflare" and for known retryable HTTP status
    codes. FanFicFare typically surfaces these as "Error getting Page: 525" or
    similar in stderr/stdout.
    """
    lower = output.lower()
    if "cloudflare" in lower:
        return True
    return any(code in output for code in _CLOUDFLARE_RETRYABLE_CODES)


# ---------------------------------------------------------------------------
# Single-story download
# ---------------------------------------------------------------------------


def download_story(
    story: dict,
    output_dir: Path,
    *,
    timeout: int | None = None,
    fanficfare_cmd: str | None = None,
    extra_options: list[str] | None = None,
    cancel_event: threading.Event | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> DownloadResult:
    """
    Download one AO3 story as an epub via the FanFicFare CLI.

    Detects the output file by comparing directory contents before and after
    the download — this is reliable regardless of FanFicFare's filename logic.

    Failures are not retried. Any failure (Cloudflare error, login block,
    deleted story, timeout) is returned immediately so the caller can send
    the story to the Phase 2 browser opener queue.

    Args:
        story:          Story dict (must contain 'ao3_work_id').
        output_dir:     Directory to write the epub into.
        timeout:        Per-download timeout in seconds. Defaults to
                        config.FANFICFARE_TIMEOUT.
        fanficfare_cmd: FanFicFare executable name or path. Defaults to
                        config.FANFICFARE_CMD.

    Returns:
        DownloadResult with epub_path set on success, error set on failure.
    """
    if timeout is None:
        timeout = config.FANFICFARE_TIMEOUT
    if fanficfare_cmd is None:
        fanficfare_cmd = config.FANFICFARE_CMD
    if extra_options is None:
        extra_options = config.FANFICFARE_EXTRA_OPTIONS

    work_id = story["ao3_work_id"]
    url = build_ao3_url(work_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check whether this story was already downloaded (previous run or manual).
    existing = find_existing_epub(work_id, output_dir)
    if existing is not None:
        return DownloadResult(story=story, epub_path=existing, skipped=True)

    before: set[Path] = set(output_dir.glob("*.epub"))
    option_flags = [flag for opt in extra_options for flag in ("-o", opt)]

    try:
        proc = subprocess.run(
            [fanficfare_cmd, *option_flags, url],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            cwd=str(output_dir),
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError:
        return DownloadResult(
            story=story,
            error=(
                f"FanFicFare executable not found: {fanficfare_cmd!r}. "
                "Install it with: pip install fanficfare"
            ),
        )
    except subprocess.TimeoutExpired:
        return DownloadResult(
            story=story,
            error=f"FanFicFare timed out after {timeout} s (work_id={work_id})",
        )

    if proc.returncode == 0:
        after: set[Path] = set(output_dir.glob("*.epub"))
        new_files = after - before
        if not new_files:
            return DownloadResult(
                story=story,
                error=(
                    "FanFicFare reported success but no new epub was found "
                    f"in {output_dir} (work_id={work_id})"
                ),
            )
        # More than one new file is unexpected but possible for very long
        # stories that FanFicFare splits. Pick the most recently modified.
        epub_path = max(new_files, key=lambda p: p.stat().st_mtime)
        _cache_epub(work_id, epub_path, output_dir)
        return DownloadResult(story=story, epub_path=epub_path)

    detail = (proc.stderr.strip() or proc.stdout.strip() or "no output")
    return DownloadResult(
        story=story,
        error=f"FanFicFare exited with code {proc.returncode}: {detail}",
    )


# ---------------------------------------------------------------------------
# Batched download
# ---------------------------------------------------------------------------


def download_stories(
    stories: list[dict],
    output_dir: Path | None = None,
    batch_size: int | None = None,
    batch_delay: int | None = None,
    story_delay: int | None = None,
    timeout: int | None = None,
    fanficfare_cmd: str | None = None,
    extra_options: list[str] | None = None,
    progress_callback: Callable[[DownloadResult], None] | None = None,
    cancel_event: threading.Event | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> list[DownloadResult]:
    """
    Download a list of AO3 stories as epubs, in batches with delays.

    Two levels of pacing are applied to avoid triggering AO3/Cloudflare
    rate-limiting:

      story_delay  — pause after every individual story (except the last).
                     This is the primary throttle. A burst of back-to-back
                     downloads within a batch is what triggers AO3 detection,
                     so spacing every story is more effective than only pausing
                     between batches.

      batch_delay  — additional pause between batches, on top of story_delay.
                     Provides a longer cooldown after each batch completes.

    FanFicFare can also stall after a handful of sequential downloads;
    the batch structure with its delays helps prevent this too.

    Failures are not retried — any failed story is returned as-is for the
    Phase 2 browser opener queue.

    Args:
        stories:           Story dicts from diff.py (each must have 'ao3_work_id').
        output_dir:        Directory to save epubs. Defaults to
                           config.EPUB_DOWNLOAD_DIR.
        batch_size:        Number of stories per batch. Defaults to
                           config.FANFICFARE_BATCH_SIZE.
        batch_delay:       Extra seconds to pause between batches (added after
                           the story_delay for the last story in the batch).
                           Defaults to config.FANFICFARE_BATCH_DELAY.
        story_delay:       Seconds to pause after each story. Defaults to
                           config.FANFICFARE_STORY_DELAY.
        timeout:           Per-download timeout in seconds. Defaults to
                           config.FANFICFARE_TIMEOUT.
        fanficfare_cmd:    FanFicFare executable. Defaults to
                           config.FANFICFARE_CMD.
        progress_callback: Called with each DownloadResult immediately after
                           it completes (before any post-story sleep).

    Returns:
        List of DownloadResult in the same order as the input stories.
    """
    if output_dir is None:
        output_dir = config.EPUB_DOWNLOAD_DIR
    if batch_size is None:
        batch_size = config.FANFICFARE_BATCH_SIZE
    if batch_delay is None:
        batch_delay = config.FANFICFARE_BATCH_DELAY
    if story_delay is None:
        story_delay = config.FANFICFARE_STORY_DELAY
    if timeout is None:
        timeout = config.FANFICFARE_TIMEOUT
    if fanficfare_cmd is None:
        fanficfare_cmd = config.FANFICFARE_CMD
    if extra_options is None:
        extra_options = config.FANFICFARE_EXTRA_OPTIONS

    results: list[DownloadResult] = []
    total = len(stories)
    cancelled = False

    for batch_start in range(0, total, batch_size):
        if cancelled:
            break
        batch = stories[batch_start : batch_start + batch_size]

        for batch_pos, story in enumerate(batch):
            # Check for cancellation before starting each story.
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break

            story_index = batch_start + batch_pos  # 0-based index across whole run
            is_last_story = (story_index == total - 1)
            is_last_in_batch = (batch_pos == len(batch) - 1)

            title = story.get("title") or story["ao3_work_id"]
            if status_callback is not None:
                status_callback(
                    f"[{story_index + 1}/{total}] Downloading: {title!r}"
                )

            result = download_story(
                story,
                output_dir,
                timeout=timeout,
                fanficfare_cmd=fanficfare_cmd,
                extra_options=extra_options,
                cancel_event=cancel_event,
                status_callback=status_callback,
            )
            results.append(result)
            if progress_callback is not None:
                progress_callback(result)

            # Skipped stories (already downloaded) don't count as network
            # activity, so no delay is needed after them.
            if result.skipped:
                continue

            if is_last_story:
                # No delay after the very last story.
                break

            if is_last_in_batch:
                # End of a batch: story_delay + batch_delay gives a longer
                # cooldown between batches.
                if story_delay > 0:
                    if status_callback is not None:
                        status_callback(
                            f"  Batch complete — waiting {story_delay}s "
                            f"(story delay) + {batch_delay}s (batch cooldown)…"
                        )
                    if _interruptible_sleep(story_delay, cancel_event):
                        cancelled = True
                        break
                if batch_delay > 0 and not cancelled:
                    if _interruptible_sleep(batch_delay, cancel_event):
                        cancelled = True
                        break
            else:
                # Mid-batch: standard per-story delay.
                if story_delay > 0:
                    if status_callback is not None:
                        status_callback(
                            f"  Waiting {story_delay}s before next download…"
                        )
                    if _interruptible_sleep(story_delay, cancel_event):
                        cancelled = True
                        break

    return results


# ---------------------------------------------------------------------------
# Result filters
# ---------------------------------------------------------------------------


def successful_downloads(results: list[DownloadResult]) -> list[DownloadResult]:
    """Return only the results where the download succeeded."""
    return [r for r in results if r.success]


def failed_downloads(results: list[DownloadResult]) -> list[DownloadResult]:
    """Return only the results where the download failed."""
    return [r for r in results if not r.success]
