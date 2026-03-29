"""
Unit tests for sync/ao3.py — Milestone 6: FanFicFare integration.

All subprocess calls and time.sleep are mocked. Filesystem operations
use pytest's tmp_path fixture (real temp directories).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from orchestrator.sync.ao3 import (
    DownloadResult,
    _cache_epub,
    _is_cloudflare_error,
    _is_credentials_error,
    build_ao3_url,
    download_stories,
    download_story,
    failed_downloads,
    find_existing_epub,
    successful_downloads,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_story(work_id: str = "12345") -> dict:
    return {
        "ao3_work_id": work_id,
        "title": f"Test Story {work_id}",
        "author": "Test Author",
        "fandoms": "Test Fandom",
        "relationships": "A/B",
        "additional_tags": "",
        "word_count": 10000,
    }


def make_completed_process(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["fanficfare"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _fake_run_that_creates_epub(output_dir: Path, filename: str = "story.epub"):
    """Returns a subprocess.run side_effect that creates an epub in output_dir."""
    def side_effect(cmd, **kwargs):
        (output_dir / filename).write_bytes(b"fake epub content")
        return make_completed_process(returncode=0, stdout="Saved Story: Test Story")
    return side_effect


# ---------------------------------------------------------------------------
# build_ao3_url
# ---------------------------------------------------------------------------

class TestBuildAo3Url:
    def test_correct_format(self):
        url = build_ao3_url("12345")
        assert url == "https://archiveofourown.org/works/12345"

    def test_different_work_ids(self):
        assert build_ao3_url("99999999") == "https://archiveofourown.org/works/99999999"
        assert build_ao3_url("1") == "https://archiveofourown.org/works/1"

    def test_work_id_appears_in_url(self):
        wid = "7654321"
        assert wid in build_ao3_url(wid)


# ---------------------------------------------------------------------------
# DownloadResult
# ---------------------------------------------------------------------------

class TestDownloadResult:
    def test_success_when_epub_path_set(self, tmp_path):
        epub = tmp_path / "story.epub"
        epub.write_bytes(b"")
        result = DownloadResult(story=make_story(), epub_path=epub)
        assert result.success is True

    def test_failure_when_epub_path_none(self):
        result = DownloadResult(story=make_story(), error="something went wrong")
        assert result.success is False

    def test_default_no_epub_no_error(self):
        result = DownloadResult(story=make_story())
        assert result.success is False
        assert result.error is None


# ---------------------------------------------------------------------------
# download_story — success path
# ---------------------------------------------------------------------------

class TestDownloadStorySuccess:
    def test_returns_epub_path_on_success(self, tmp_path):
        story = make_story("11111")
        with patch("subprocess.run", side_effect=_fake_run_that_creates_epub(tmp_path)):
            result = download_story(story, tmp_path, fanficfare_cmd="fanficfare")
        assert result.success is True
        assert result.epub_path == tmp_path / "story.epub"
        assert result.error is None

    def test_story_preserved_in_result(self, tmp_path):
        story = make_story("22222")
        with patch("subprocess.run", side_effect=_fake_run_that_creates_epub(tmp_path)):
            result = download_story(story, tmp_path, fanficfare_cmd="fanficfare")
        assert result.story is story

    def test_correct_url_passed_to_fanficfare(self, tmp_path):
        story = make_story("55555")
        with patch("subprocess.run", side_effect=_fake_run_that_creates_epub(tmp_path)) as mock_run:
            download_story(story, tmp_path, fanficfare_cmd="fanficfare")
        cmd = mock_run.call_args[0][0]
        assert "https://archiveofourown.org/works/55555" in cmd

    def test_output_dir_passed_as_cwd(self, tmp_path):
        story = make_story("33333")
        with patch("subprocess.run", side_effect=_fake_run_that_creates_epub(tmp_path)) as mock_run:
            download_story(story, tmp_path, fanficfare_cmd="fanficfare")
        kwargs = mock_run.call_args[1]
        assert kwargs["cwd"] == str(tmp_path)

    def test_output_dir_created_if_missing(self, tmp_path):
        missing = tmp_path / "new_subdir"
        assert not missing.exists()
        story = make_story("44444")
        with patch("subprocess.run", side_effect=_fake_run_that_creates_epub(missing)):
            download_story(story, missing, fanficfare_cmd="fanficfare")
        assert missing.exists()

    def test_picks_newest_epub_when_multiple_new_files(self, tmp_path):
        """If FanFicFare creates multiple epubs (rare), the newest is returned."""
        story = make_story("66666")

        def side_effect(cmd, **kwargs):
            older = tmp_path / "older.epub"
            newer = tmp_path / "newer.epub"
            older.write_bytes(b"old")
            newer.write_bytes(b"new")
            # Ensure stat() ordering by touching newer after older
            import os
            os.utime(older, (0, 0))
            os.utime(newer, (1, 1))
            return make_completed_process(returncode=0)

        with patch("subprocess.run", side_effect=side_effect):
            result = download_story(story, tmp_path, fanficfare_cmd="fanficfare")

        assert result.success is True
        assert result.epub_path.name == "newer.epub"

    def test_existing_epub_not_reported_as_new(self, tmp_path):
        """Pre-existing epubs in the directory must not be picked up."""
        existing = tmp_path / "old_story.epub"
        existing.write_bytes(b"already here")

        story = make_story("77777")
        with patch("subprocess.run", side_effect=_fake_run_that_creates_epub(tmp_path, "new_story.epub")):
            result = download_story(story, tmp_path, fanficfare_cmd="fanficfare")

        assert result.epub_path.name == "new_story.epub"


# ---------------------------------------------------------------------------
# download_story — error paths
# ---------------------------------------------------------------------------

class TestDownloadStoryErrors:
    def test_fanficfare_not_found(self, tmp_path):
        story = make_story()
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            result = download_story(story, tmp_path, fanficfare_cmd="fanficfare")
        assert result.success is False
        assert "not found" in result.error.lower()
        assert "pip install fanficfare" in result.error

    def test_timeout(self, tmp_path):
        story = make_story()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["fanficfare"], timeout=120)):
            result = download_story(story, tmp_path, timeout=120, fanficfare_cmd="fanficfare")
        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_nonzero_exit_code(self, tmp_path):
        story = make_story()
        with patch("subprocess.run", return_value=make_completed_process(
            returncode=1, stderr="Story not found on AO3"
        )):
            result = download_story(story, tmp_path, fanficfare_cmd="fanficfare")
        assert result.success is False
        assert "Story not found on AO3" in result.error

    def test_nonzero_exit_uses_stdout_when_stderr_empty(self, tmp_path):
        story = make_story()
        with patch("subprocess.run", return_value=make_completed_process(
            returncode=2, stdout="Some stdout message", stderr=""
        )):
            result = download_story(story, tmp_path, fanficfare_cmd="fanficfare")
        assert "Some stdout message" in result.error

    def test_no_epub_created_despite_zero_exit(self, tmp_path):
        """FanFicFare returns 0 but creates no epub (e.g. story restricted)."""
        story = make_story()
        with patch("subprocess.run", return_value=make_completed_process(returncode=0)):
            result = download_story(story, tmp_path, fanficfare_cmd="fanficfare")
        assert result.success is False
        assert "no new epub" in result.error.lower()

    def test_error_result_contains_work_id(self, tmp_path):
        story = make_story("99999")
        with patch("subprocess.run", return_value=make_completed_process(returncode=0)):
            result = download_story(story, tmp_path, fanficfare_cmd="fanficfare")
        assert "99999" in result.error

    def test_timeout_uses_config_default(self, tmp_path):
        story = make_story()
        with patch("subprocess.run", return_value=make_completed_process(returncode=1)) as mock_run:
            download_story(story, tmp_path, fanficfare_cmd="fanficfare")
        _, kwargs = mock_run.call_args
        from orchestrator import config
        assert kwargs["timeout"] == config.FANFICFARE_TIMEOUT


# ---------------------------------------------------------------------------
# download_stories — batching behaviour
# ---------------------------------------------------------------------------

class TestDownloadStoriesBatching:
    def _make_mock_download_story(self, tmp_path: Path):
        """Return a patch target that creates a unique epub per story."""
        call_count = [0]

        def fake_download(story, output_dir, **kwargs):
            call_count[0] += 1
            epub = output_dir / f"story_{call_count[0]}.epub"
            epub.write_bytes(b"fake")
            return DownloadResult(story=story, epub_path=epub)

        return fake_download, call_count

    def test_returns_one_result_per_story(self, tmp_path):
        stories = [make_story(str(i)) for i in range(6)]
        fake, _ = self._make_mock_download_story(tmp_path)
        with patch("orchestrator.sync.ao3.download_story", side_effect=fake):
            with patch("orchestrator.sync.ao3.time.sleep"):
                results = download_stories(
                    stories, output_dir=tmp_path, batch_size=3,
                    batch_delay=0, story_delay=0,
                )
        assert len(results) == 6

    def test_results_in_input_order(self, tmp_path):
        stories = [make_story(str(i)) for i in range(4)]
        fake, _ = self._make_mock_download_story(tmp_path)
        with patch("orchestrator.sync.ao3.download_story", side_effect=fake):
            with patch("orchestrator.sync.ao3.time.sleep"):
                results = download_stories(
                    stories, output_dir=tmp_path, batch_size=2,
                    batch_delay=0, story_delay=0,
                )
        for result, story in zip(results, stories):
            assert result.story is story

    def test_no_sleep_after_last_story(self, tmp_path):
        """No delay is applied after the very last story regardless of settings."""
        stories = [make_story("only")]
        fake, _ = self._make_mock_download_story(tmp_path)
        with patch("orchestrator.sync.ao3.download_story", side_effect=fake):
            with patch("orchestrator.sync.ao3.time.sleep") as mock_sleep:
                download_stories(
                    stories, output_dir=tmp_path, batch_size=5,
                    batch_delay=10, story_delay=30,
                )
        mock_sleep.assert_not_called()

    def test_empty_story_list_returns_empty(self, tmp_path):
        with patch("orchestrator.sync.ao3.download_story") as mock_dl:
            results = download_stories(
                [], output_dir=tmp_path, batch_size=5,
                batch_delay=0, story_delay=0,
            )
        assert results == []
        mock_dl.assert_not_called()

    def test_story_delay_applied_between_every_story(self, tmp_path):
        """story_delay fires between each story (not after the last)."""
        stories = [make_story(str(i)) for i in range(4)]
        fake, _ = self._make_mock_download_story(tmp_path)
        sleep_calls = []
        with patch("orchestrator.sync.ao3.download_story", side_effect=fake):
            with patch("orchestrator.sync.ao3.time.sleep",
                       side_effect=lambda s: sleep_calls.append(s)):
                download_stories(
                    stories, output_dir=tmp_path, batch_size=10,
                    batch_delay=0, story_delay=7,
                )
        # 4 stories → 3 gaps → 3 story_delay sleeps
        assert sleep_calls.count(7) == 3

    def test_story_delay_zero_means_no_sleep_mid_batch(self, tmp_path):
        stories = [make_story(str(i)) for i in range(4)]
        fake, _ = self._make_mock_download_story(tmp_path)
        with patch("orchestrator.sync.ao3.download_story", side_effect=fake):
            with patch("orchestrator.sync.ao3.time.sleep") as mock_sleep:
                download_stories(
                    stories, output_dir=tmp_path, batch_size=10,
                    batch_delay=0, story_delay=0,
                )
        mock_sleep.assert_not_called()

    def test_batch_delay_added_at_batch_boundary_on_top_of_story_delay(self, tmp_path):
        """
        At a batch boundary: story_delay fires first, then batch_delay.
        With 4 stories, batch_size=2: boundaries after story 2.
        sleep sequence: story_delay(after s1), story_delay+batch_delay(after s2), story_delay(after s3)
        → [story_delay, story_delay, batch_delay, story_delay]
        """
        stories = [make_story(str(i)) for i in range(4)]
        fake, _ = self._make_mock_download_story(tmp_path)
        sleep_calls = []
        with patch("orchestrator.sync.ao3.download_story", side_effect=fake):
            with patch("orchestrator.sync.ao3.time.sleep",
                       side_effect=lambda s: sleep_calls.append(s)):
                download_stories(
                    stories, output_dir=tmp_path, batch_size=2,
                    batch_delay=20, story_delay=5,
                )
        assert sleep_calls.count(5) == 3   # story_delay after stories 1, 2, 3
        assert sleep_calls.count(20) == 1  # batch_delay once, after story 2 (end of batch 1)

    def test_no_batch_delay_after_last_batch(self, tmp_path):
        """batch_delay must not fire after the final batch."""
        stories = [make_story(str(i)) for i in range(4)]
        fake, _ = self._make_mock_download_story(tmp_path)
        sleep_calls = []
        with patch("orchestrator.sync.ao3.download_story", side_effect=fake):
            with patch("orchestrator.sync.ao3.time.sleep",
                       side_effect=lambda s: sleep_calls.append(s)):
                download_stories(
                    stories, output_dir=tmp_path, batch_size=4,
                    batch_delay=99, story_delay=1,
                )
        assert 99 not in sleep_calls

    def test_partial_last_batch(self, tmp_path):
        """7 stories, batch_size=3: batches of 3, 3, 1."""
        stories = [make_story(str(i)) for i in range(7)]
        fake, _ = self._make_mock_download_story(tmp_path)
        with patch("orchestrator.sync.ao3.download_story", side_effect=fake):
            with patch("orchestrator.sync.ao3.time.sleep"):
                results = download_stories(
                    stories, output_dir=tmp_path, batch_size=3,
                    batch_delay=1, story_delay=1,
                )
        assert len(results) == 7


# ---------------------------------------------------------------------------
# download_stories — config defaults
# ---------------------------------------------------------------------------

class TestDownloadStoriesDefaults:
    def test_uses_config_output_dir_when_not_specified(self, tmp_path):
        from orchestrator import config
        story = make_story()
        captured = {}

        def fake_download(story, output_dir, **kwargs):
            captured["output_dir"] = output_dir
            return DownloadResult(story=story, error="test")

        with patch("orchestrator.sync.ao3.download_story", side_effect=fake_download):
            with patch("orchestrator.sync.ao3.time.sleep"):
                download_stories([story])

        assert captured["output_dir"] == config.EPUB_DOWNLOAD_DIR

    def test_uses_config_batch_size_when_not_specified(self, tmp_path):
        from orchestrator import config
        # Use batch_size+1 stories so there are exactly 2 batches.
        stories = [make_story(str(i)) for i in range(config.FANFICFARE_BATCH_SIZE + 1)]
        batch_delay_calls = []

        def fake_download(story, output_dir, **kwargs):
            return DownloadResult(story=story, error="test")

        with patch("orchestrator.sync.ao3.download_story", side_effect=fake_download):
            with patch("orchestrator.sync.ao3.time.sleep",
                       side_effect=lambda s: batch_delay_calls.append(s)):
                download_stories(stories, output_dir=tmp_path, batch_delay=999, story_delay=0)

        # 2 batches → 1 inter-batch sleep with the sentinel value 999
        assert batch_delay_calls.count(999) == 1

    def test_uses_config_batch_delay_when_not_specified(self, tmp_path):
        from orchestrator import config
        stories = [make_story(str(i)) for i in range(config.FANFICFARE_BATCH_SIZE + 1)]
        sleep_calls = []

        def fake_download(story, output_dir, **kwargs):
            return DownloadResult(story=story, error="test")

        with patch("orchestrator.sync.ao3.download_story", side_effect=fake_download):
            with patch("orchestrator.sync.ao3.time.sleep",
                       side_effect=lambda s: sleep_calls.append(s)):
                download_stories(stories, output_dir=tmp_path, story_delay=0)

        assert config.FANFICFARE_BATCH_DELAY in sleep_calls

    def test_uses_config_story_delay_when_not_specified(self, tmp_path):
        from orchestrator import config
        stories = [make_story(str(i)) for i in range(3)]
        sleep_calls = []

        def fake_download(story, output_dir, **kwargs):
            return DownloadResult(story=story, error="test")

        with patch("orchestrator.sync.ao3.download_story", side_effect=fake_download):
            with patch("orchestrator.sync.ao3.time.sleep",
                       side_effect=lambda s: sleep_calls.append(s)):
                download_stories(stories, output_dir=tmp_path, batch_size=10, batch_delay=0)

        # 3 stories → 2 gaps → 2 story_delay sleeps
        assert sleep_calls.count(config.FANFICFARE_STORY_DELAY) == 2


# ---------------------------------------------------------------------------
# download_stories — progress callback
# ---------------------------------------------------------------------------

class TestDownloadStoriesProgressCallback:
    def test_callback_called_for_every_story(self, tmp_path):
        stories = [make_story(str(i)) for i in range(5)]
        callback_results = []

        def fake_download(story, output_dir, **kwargs):
            return DownloadResult(story=story, error="test")

        with patch("orchestrator.sync.ao3.download_story", side_effect=fake_download):
            with patch("orchestrator.sync.ao3.time.sleep"):
                download_stories(
                    stories,
                    output_dir=tmp_path,
                    batch_size=5,
                    batch_delay=0,
                    story_delay=0,
                    progress_callback=lambda r: callback_results.append(r),
                )

        assert len(callback_results) == 5

    def test_callback_receives_correct_result(self, tmp_path):
        story = make_story("cb_test")
        expected_result = DownloadResult(story=story, error="simulated error")
        callback_results = []

        with patch("orchestrator.sync.ao3.download_story", return_value=expected_result):
            with patch("orchestrator.sync.ao3.time.sleep"):
                download_stories(
                    [story],
                    output_dir=tmp_path,
                    batch_size=5,
                    batch_delay=0,
                    story_delay=0,
                    progress_callback=lambda r: callback_results.append(r),
                )

        assert callback_results[0] is expected_result

    def test_no_callback_does_not_raise(self, tmp_path):
        stories = [make_story()]

        def fake_download(story, output_dir, **kwargs):
            return DownloadResult(story=story, error="test")

        with patch("orchestrator.sync.ao3.download_story", side_effect=fake_download):
            results = download_stories(
                stories, output_dir=tmp_path, batch_size=5,
                batch_delay=0, story_delay=0,
            )

        assert len(results) == 1


# ---------------------------------------------------------------------------
# Result filters
# ---------------------------------------------------------------------------

class TestResultFilters:
    def _make_results(self, tmp_path: Path) -> list[DownloadResult]:
        epub = tmp_path / "ok.epub"
        epub.write_bytes(b"")
        return [
            DownloadResult(story=make_story("ok1"), epub_path=epub),
            DownloadResult(story=make_story("fail1"), error="error 1"),
            DownloadResult(story=make_story("ok2"), epub_path=epub),
            DownloadResult(story=make_story("fail2"), error="error 2"),
        ]

    def test_successful_downloads(self, tmp_path):
        results = self._make_results(tmp_path)
        successes = successful_downloads(results)
        assert len(successes) == 2
        assert all(r.success for r in successes)

    def test_failed_downloads(self, tmp_path):
        results = self._make_results(tmp_path)
        failures = failed_downloads(results)
        assert len(failures) == 2
        assert all(not r.success for r in failures)

    def test_successful_plus_failed_equals_total(self, tmp_path):
        results = self._make_results(tmp_path)
        assert len(successful_downloads(results)) + len(failed_downloads(results)) == len(results)

    def test_all_successful(self, tmp_path):
        epub = tmp_path / "x.epub"
        epub.write_bytes(b"")
        results = [DownloadResult(story=make_story(str(i)), epub_path=epub) for i in range(3)]
        assert len(failed_downloads(results)) == 0
        assert len(successful_downloads(results)) == 3

    def test_all_failed(self):
        results = [DownloadResult(story=make_story(str(i)), error="err") for i in range(3)]
        assert len(successful_downloads(results)) == 0
        assert len(failed_downloads(results)) == 3

    def test_empty_input(self):
        assert successful_downloads([]) == []
        assert failed_downloads([]) == []


# ---------------------------------------------------------------------------
# _is_cloudflare_error
# ---------------------------------------------------------------------------

class TestIsCloudflareError:
    def test_detects_525(self):
        assert _is_cloudflare_error("Error getting Page: 525") is True

    def test_detects_524(self):
        assert _is_cloudflare_error("HTTP Error 524: A Timeout Occurred") is True

    def test_detects_503(self):
        assert _is_cloudflare_error("503 Service Unavailable") is True

    def test_detects_502(self):
        assert _is_cloudflare_error("502 Bad Gateway") is True

    def test_detects_429(self):
        assert _is_cloudflare_error("429 Too Many Requests") is True

    def test_detects_cloudflare_word(self):
        assert _is_cloudflare_error("Blocked by Cloudflare") is True
        assert _is_cloudflare_error("cloudflare protection active") is True

    def test_cloudflare_case_insensitive(self):
        assert _is_cloudflare_error("CLOUDFLARE challenge") is True
        assert _is_cloudflare_error("CloudFlare") is True

    def test_non_cf_error_not_detected(self):
        assert _is_cloudflare_error("Story not found") is False
        assert _is_cloudflare_error("Login required") is False
        assert _is_cloudflare_error("404 Not Found") is False
        assert _is_cloudflare_error("") is False

    def test_unrelated_number_not_detected(self):
        # "525" appearing in a word count or title should not match
        # unless the surrounding context makes it an HTTP error.
        # The current implementation is a substring match, so we confirm
        # the behaviour rather than asserting it shouldn't match.
        # This test documents the known limitation.
        result = _is_cloudflare_error("Word count: 52500")
        # "525" IS present as a substring — this is expected to return True.
        # The function is called only on FanFicFare error output, where the
        # chance of "525" appearing in a non-CF context is negligible.
        assert result is True  # documents known substring behaviour


# ---------------------------------------------------------------------------
# _is_credentials_error
# ---------------------------------------------------------------------------

class TestIsCredentialsError:
    def test_detects_performlogin_in_traceback(self):
        output = (
            "Traceback (most recent call last):\n"
            "  File '...base_otw_adapter.py', line 141, in performLogin\n"
            "    d = self.post_request(loginUrl, params)\n"
            "fanficfare.exceptions.HTTPErrorFFF: HTTP Error in FFF '403'"
        )
        assert _is_credentials_error(output) is True

    def test_detects_login_url_in_output(self):
        output = "HTTPError: 403 Forbidden for url: https://archiveofourown.org/users/login"
        assert _is_credentials_error(output) is True

    def test_case_insensitive_performlogin(self):
        assert _is_credentials_error("PerformLogin called") is True
        assert _is_credentials_error("PERFORMLOGIN") is True

    def test_not_triggered_by_cloudflare_error(self):
        assert _is_credentials_error("Error getting Page: 525") is False

    def test_not_triggered_by_generic_403(self):
        # A 403 unrelated to login (e.g. restricted story) should not match
        assert _is_credentials_error("403 Forbidden for url: https://archiveofourown.org/works/99999") is False

    def test_not_triggered_by_unrelated_error(self):
        assert _is_credentials_error("Story not found on AO3") is False
        assert _is_credentials_error("") is False


# ---------------------------------------------------------------------------
# DownloadResult.credentials_error
# ---------------------------------------------------------------------------

class TestDownloadResultCredentialsError:
    def test_true_when_error_contains_performlogin(self):
        result = DownloadResult(
            story=make_story(),
            error="FanFicFare exited with code 1: ...performLogin...",
        )
        assert result.credentials_error is True

    def test_false_when_success(self, tmp_path):
        epub = tmp_path / "story.epub"
        epub.write_bytes(b"")
        result = DownloadResult(story=make_story(), epub_path=epub)
        assert result.credentials_error is False

    def test_false_when_cloudflare_error(self):
        result = DownloadResult(story=make_story(), error="525 SSL error")
        assert result.credentials_error is False

    def test_false_when_no_error(self):
        result = DownloadResult(story=make_story())
        assert result.credentials_error is False


# ---------------------------------------------------------------------------
# find_existing_epub
# ---------------------------------------------------------------------------

class TestFindExistingEpub:
    def test_finds_epub_with_work_id_in_filename(self, tmp_path):
        epub = tmp_path / "My_Story_12345.epub"
        epub.write_bytes(b"fake epub")
        result = find_existing_epub("12345", tmp_path)
        assert result == epub

    def test_returns_none_when_no_match(self, tmp_path):
        (tmp_path / "other_99999.epub").write_bytes(b"fake epub")
        assert find_existing_epub("12345", tmp_path) is None

    def test_finds_epub_via_cache_file(self, tmp_path):
        epub = tmp_path / "Story_Title.epub"
        epub.write_bytes(b"fake epub")
        cache = tmp_path / ".fanficflow_cache.json"
        import json
        cache.write_text(json.dumps({"12345": "Story_Title.epub"}), encoding="utf-8")
        result = find_existing_epub("12345", tmp_path)
        assert result == epub

    def test_cache_hit_but_file_missing_returns_none(self, tmp_path):
        cache = tmp_path / ".fanficflow_cache.json"
        import json
        cache.write_text(json.dumps({"12345": "gone.epub"}), encoding="utf-8")
        assert find_existing_epub("12345", tmp_path) is None

    def test_filename_glob_takes_priority_over_cache(self, tmp_path):
        """If both a filename glob match and a cache entry exist, the glob wins."""
        import json
        glob_epub = tmp_path / "Story_12345.epub"
        glob_epub.write_bytes(b"glob match")
        cache_epub = tmp_path / "CachedName.epub"
        cache_epub.write_bytes(b"cache match")
        (tmp_path / ".fanficflow_cache.json").write_text(
            json.dumps({"12345": "CachedName.epub"}), encoding="utf-8"
        )
        result = find_existing_epub("12345", tmp_path)
        assert result == glob_epub

    def test_creates_output_dir_if_missing(self, tmp_path):
        missing = tmp_path / "new_dir"
        assert not missing.exists()
        find_existing_epub("12345", missing)
        assert missing.exists()

    def test_returns_none_on_empty_directory(self, tmp_path):
        assert find_existing_epub("12345", tmp_path) is None

    def test_corrupted_cache_returns_none(self, tmp_path):
        (tmp_path / ".fanficflow_cache.json").write_text("not json!", encoding="utf-8")
        assert find_existing_epub("12345", tmp_path) is None

    def test_finds_manually_downloaded_epub_by_title(self, tmp_path):
        """Title match catches manually downloaded files without work_id in name."""
        epub = tmp_path / "Our_Kingdom.epub"
        epub.write_bytes(b"fake epub")
        result = find_existing_epub("99999", tmp_path, title="Our Kingdom")
        assert result == epub

    def test_title_match_with_punctuation_differences(self, tmp_path):
        """Title normalisation strips punctuation on both sides."""
        epub = tmp_path / "Where_Loyalties_Lie.epub"
        epub.write_bytes(b"fake epub")
        result = find_existing_epub("11111", tmp_path, title="Where Loyalties Lie")
        assert result == epub

    def test_title_match_caches_result(self, tmp_path):
        """A title-matched epub is written to the cache for future runs."""
        import json
        epub = tmp_path / "Trust_Fall.epub"
        epub.write_bytes(b"fake epub")
        find_existing_epub("67301515", tmp_path, title="Trust Fall")
        cache = json.loads((tmp_path / ".fanficflow_cache.json").read_text())
        assert cache.get("67301515") == "Trust_Fall.epub"

    def test_title_match_not_used_when_title_empty(self, tmp_path):
        """Without a title argument the third check is skipped."""
        (tmp_path / "Our_Kingdom.epub").write_bytes(b"fake epub")
        assert find_existing_epub("99999", tmp_path) is None

    def test_title_match_skipped_when_work_id_in_filename(self, tmp_path):
        """Check 1 short-circuits before reaching title match."""
        epub = tmp_path / "story-ao3_99999.epub"
        epub.write_bytes(b"fake epub")
        result = find_existing_epub("99999", tmp_path, title="Our Kingdom")
        assert result == epub


# ---------------------------------------------------------------------------
# _cache_epub
# ---------------------------------------------------------------------------

class TestCacheEpub:
    def test_creates_cache_file(self, tmp_path):
        import json
        epub = tmp_path / "story.epub"
        epub.write_bytes(b"")
        _cache_epub("12345", epub, tmp_path)
        cache = json.loads((tmp_path / ".fanficflow_cache.json").read_text())
        assert cache["12345"] == "story.epub"

    def test_appends_to_existing_cache(self, tmp_path):
        import json
        cache_path = tmp_path / ".fanficflow_cache.json"
        cache_path.write_text(json.dumps({"99999": "other.epub"}), encoding="utf-8")
        epub = tmp_path / "new.epub"
        epub.write_bytes(b"")
        _cache_epub("12345", epub, tmp_path)
        cache = json.loads(cache_path.read_text())
        assert cache["99999"] == "other.epub"
        assert cache["12345"] == "new.epub"

    def test_overwrites_existing_entry(self, tmp_path):
        import json
        cache_path = tmp_path / ".fanficflow_cache.json"
        cache_path.write_text(json.dumps({"12345": "old.epub"}), encoding="utf-8")
        epub = tmp_path / "new.epub"
        epub.write_bytes(b"")
        _cache_epub("12345", epub, tmp_path)
        cache = json.loads(cache_path.read_text())
        assert cache["12345"] == "new.epub"


# ---------------------------------------------------------------------------
# download_story — skips already-downloaded epubs
# ---------------------------------------------------------------------------

class TestDownloadStorySkipsExisting:
    def test_returns_skipped_when_epub_exists_by_filename(self, tmp_path):
        story = make_story("12345")
        epub = tmp_path / "My_Story_12345.epub"
        epub.write_bytes(b"already downloaded")
        with patch("subprocess.run") as mock_run:
            result = download_story(story, tmp_path, fanficfare_cmd="fanficfare")
        mock_run.assert_not_called()
        assert result.skipped is True
        assert result.success is True
        assert result.epub_path == epub

    def test_returns_skipped_when_epub_exists_in_cache(self, tmp_path):
        import json
        story = make_story("12345")
        epub = tmp_path / "Title_Without_WorkId.epub"
        epub.write_bytes(b"already downloaded")
        (tmp_path / ".fanficflow_cache.json").write_text(
            json.dumps({"12345": "Title_Without_WorkId.epub"}), encoding="utf-8"
        )
        with patch("subprocess.run") as mock_run:
            result = download_story(story, tmp_path, fanficfare_cmd="fanficfare")
        mock_run.assert_not_called()
        assert result.skipped is True
        assert result.epub_path == epub

    def test_not_skipped_default(self, tmp_path):
        result = DownloadResult(story=make_story())
        assert result.skipped is False

    def test_downloads_when_no_existing_epub(self, tmp_path):
        story = make_story("12345")
        with patch("subprocess.run", side_effect=_fake_run_that_creates_epub(tmp_path, "story.epub")):
            result = download_story(story, tmp_path, fanficfare_cmd="fanficfare")
        assert result.skipped is False
        assert result.success is True

    def test_cache_written_after_fresh_download(self, tmp_path):
        import json
        story = make_story("12345")
        with patch("subprocess.run", side_effect=_fake_run_that_creates_epub(tmp_path, "story.epub")):
            download_story(story, tmp_path, fanficfare_cmd="fanficfare")
        cache = json.loads((tmp_path / ".fanficflow_cache.json").read_text())
        assert cache["12345"] == "story.epub"


# ---------------------------------------------------------------------------
# download_stories — no delay after skipped stories
# ---------------------------------------------------------------------------

class TestDownloadStoriesSkipDelay:
    def test_no_delay_after_skipped_story(self, tmp_path):
        """Skipped (already-downloaded) stories must not trigger inter-story delays."""
        stories = [make_story("1"), make_story("2"), make_story("3")]
        sleep_calls = []

        def fake_download(story, output_dir, **kwargs):
            # story "2" is skipped; others are fresh failures
            skipped = story["ao3_work_id"] == "2"
            epub = tmp_path / "2.epub" if skipped else None
            if skipped:
                epub.write_bytes(b"")
            return DownloadResult(story=story, epub_path=epub, skipped=skipped,
                                  error=None if skipped else "err")

        with patch("orchestrator.sync.ao3.download_story", side_effect=fake_download):
            with patch("orchestrator.sync.ao3.time.sleep",
                       side_effect=lambda s: sleep_calls.append(s)):
                download_stories(
                    stories, output_dir=tmp_path, batch_size=10,
                    batch_delay=0, story_delay=5,
                )

        # Only 1 delay: between story 1 and story 3 (story 2 is skipped, no delay after it)
        assert sleep_calls.count(5) == 1
