"""
sync/browser.py — Phase 2: open AO3 URLs in the default browser.

Two use-cases:
  1. Failed downloads  — stories FanFicFare could not fetch; open for manual download.
  2. AO3 curation      — stories whose Calibre #readstatus was updated from the Palma;
                         open so the user can curate their AO3 bookmarks/marks.
"""

from __future__ import annotations

import time
import webbrowser

from orchestrator import config
from orchestrator.sync.ao3 import (
    DownloadResult,
    _is_cloudflare_error,
    _is_credentials_error,
    build_ao3_url,
)
from orchestrator.sync.readstatus import ReadStatusSyncResult


# ---------------------------------------------------------------------------
# Failed downloads — failure categorisation
# ---------------------------------------------------------------------------

CATEGORY_LOGIN = "Login blocked"
CATEGORY_CLOUDFLARE = "Cloudflare error"
CATEGORY_FAILED = "Download failed"


def categorize_failure(result: DownloadResult) -> str:
    """
    Return a human-readable failure category for a DownloadResult.

    Credentials errors are checked first because a Cloudflare block on the
    login endpoint produces output that matches both detectors.
    """
    if not result.error:
        return CATEGORY_FAILED
    if _is_credentials_error(result.error):
        return CATEGORY_LOGIN
    if _is_cloudflare_error(result.error):
        return CATEGORY_CLOUDFLARE
    return CATEGORY_FAILED


def urls_for_failures(results: list[DownloadResult]) -> list[str]:
    """Return AO3 work URLs for every failed DownloadResult."""
    return [build_ao3_url(r.story["ao3_work_id"]) for r in results]


def open_failed_in_browser(
    results: list[DownloadResult],
    *,
    tab_delay: float | None = None,
) -> None:
    """
    Open each failed story's AO3 URL as a new browser tab.

    Args:
        results:   List of failed DownloadResult objects.
        tab_delay: Seconds between tabs. Defaults to config.BROWSER_TAB_DELAY.
    """
    if tab_delay is None:
        tab_delay = config.BROWSER_TAB_DELAY
    urls = urls_for_failures(results)
    for i, url in enumerate(urls):
        webbrowser.open(url, new=2)
        if tab_delay > 0 and i < len(urls) - 1:
            time.sleep(tab_delay)


# ---------------------------------------------------------------------------
# Palma status updates — AO3 curation
# ---------------------------------------------------------------------------

_SKIP_STATUSES = {"priority"}  # statuses that do not require AO3 curation


def curation_needed(rs_result: ReadStatusSyncResult) -> list[int]:
    """
    Return Calibre IDs of updated books that need AO3 curation.

    Excludes Priority (no AO3 action required) and books without an
    ao3_work_id (can't build a URL for them).
    """
    return [
        cid for cid in rs_result.updated
        if rs_result.updated_statuses.get(cid, "").lower() not in _SKIP_STATUSES
        and rs_result.updated_ao3_work_ids.get(cid)
    ]


def open_curation_in_browser(
    rs_result: ReadStatusSyncResult,
    *,
    tab_delay: float | None = None,
) -> None:
    """
    Open AO3 URLs for books needing curation (Favorite, Read, DNF, etc.).

    Favorites are opened first (they need bookmarking + marking read),
    then all others (mark read only).

    Args:
        rs_result: Result from sync_readstatus_from_palma.
        tab_delay: Seconds between tabs. Defaults to config.BROWSER_TAB_DELAY.
    """
    if tab_delay is None:
        tab_delay = config.BROWSER_TAB_DELAY

    cids = curation_needed(rs_result)
    # Favorites first, then others — matches dialog display order.
    favorites = [c for c in cids if rs_result.updated_statuses.get(c, "").lower() == "favorite"]
    others = [c for c in cids if c not in set(favorites)]
    ordered = favorites + others

    urls = [build_ao3_url(rs_result.updated_ao3_work_ids[cid]) for cid in ordered]
    for i, url in enumerate(urls):
        webbrowser.open(url, new=2)
        if tab_delay > 0 and i < len(urls) - 1:
            time.sleep(tab_delay)
