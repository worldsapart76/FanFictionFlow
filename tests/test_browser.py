"""
Unit tests for sync/browser.py — Phase 2 browser opener.

No real browser is opened; webbrowser.open and time.sleep are patched.
Run in WSL with:
    python3.12 -m pytest tests/test_browser.py
"""

from __future__ import annotations

from unittest.mock import call, patch

import pytest

from orchestrator.sync.ao3 import DownloadResult
from orchestrator.sync.browser import (
    CATEGORY_CLOUDFLARE,
    CATEGORY_FAILED,
    CATEGORY_LOGIN,
    categorize_failure,
    curation_needed,
    open_curation_in_browser,
    open_failed_in_browser,
    urls_for_failures,
)
from orchestrator.sync.readstatus import ReadStatusSyncResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(work_id: str, error: str | None = None) -> DownloadResult:
    return DownloadResult(
        story={"ao3_work_id": work_id, "title": f"Story {work_id}"},
        error=error,
    )


def _make_rs_result(
    updated: list[int] | None = None,
    statuses: dict[int, str] | None = None,
    work_ids: dict[int, str] | None = None,
    titles: dict[int, str] | None = None,
) -> ReadStatusSyncResult:
    rs = ReadStatusSyncResult()
    rs.updated = updated or []
    rs.updated_statuses = statuses or {}
    rs.updated_ao3_work_ids = work_ids or {}
    rs.updated_titles = titles or {}
    return rs


# ---------------------------------------------------------------------------
# categorize_failure
# ---------------------------------------------------------------------------


class TestCategorizeFailed:
    def test_no_error_returns_failed(self):
        r = _make_result("1")
        assert categorize_failure(r) == CATEGORY_FAILED

    def test_credentials_error_performlogin(self):
        r = _make_result("1", error="Error: performLogin failed with 403")
        assert categorize_failure(r) == CATEGORY_LOGIN

    def test_credentials_error_login_url(self):
        r = _make_result("1", error="POST archiveofourown.org/users/login 403")
        assert categorize_failure(r) == CATEGORY_LOGIN

    def test_cloudflare_error_525(self):
        r = _make_result("1", error="SSL handshake failed: cloudflare 525")
        assert categorize_failure(r) == CATEGORY_CLOUDFLARE

    def test_credentials_takes_priority_over_cloudflare(self):
        # Output that matches both detectors — credentials wins.
        r = _make_result(
            "1",
            error="performLogin cloudflare 525 error block",
        )
        assert categorize_failure(r) == CATEGORY_LOGIN

    def test_generic_error_returns_failed(self):
        r = _make_result("1", error="Story has been deleted or is restricted.")
        assert categorize_failure(r) == CATEGORY_FAILED


# ---------------------------------------------------------------------------
# urls_for_failures
# ---------------------------------------------------------------------------


class TestUrlsForFailures:
    def test_empty_returns_empty(self):
        assert urls_for_failures([]) == []

    def test_correct_urls_built(self):
        results = [_make_result("111"), _make_result("222")]
        urls = urls_for_failures(results)
        assert urls == [
            "https://archiveofourown.org/works/111",
            "https://archiveofourown.org/works/222",
        ]

    def test_order_preserved(self):
        ids = ["9", "7", "3"]
        results = [_make_result(i) for i in ids]
        urls = urls_for_failures(results)
        assert [u.split("/")[-1] for u in urls] == ids


# ---------------------------------------------------------------------------
# open_failed_in_browser
# ---------------------------------------------------------------------------


class TestOpenFailedInBrowser:
    def test_opens_each_url_with_new_2(self):
        results = [_make_result("1"), _make_result("2")]
        with patch("webbrowser.open") as mock_open:
            open_failed_in_browser(results, tab_delay=0)
        assert mock_open.call_count == 2
        for c in mock_open.call_args_list:
            assert c.kwargs.get("new") == 2 or c.args[1] == 2

    def test_no_delay_after_last_url(self):
        results = [_make_result(str(i)) for i in range(3)]
        with patch("webbrowser.open"), patch("time.sleep") as mock_sleep:
            open_failed_in_browser(results, tab_delay=0.5)
        # 3 urls → sleep called between 1st/2nd and 2nd/3rd, not after 3rd
        assert mock_sleep.call_count == 2

    def test_tab_delay_zero_skips_sleep(self):
        results = [_make_result("1"), _make_result("2")]
        with patch("webbrowser.open"), patch("time.sleep") as mock_sleep:
            open_failed_in_browser(results, tab_delay=0)
        mock_sleep.assert_not_called()

    def test_empty_list_does_nothing(self):
        with patch("webbrowser.open") as mock_open, patch("time.sleep") as mock_sleep:
            open_failed_in_browser([], tab_delay=0)
        mock_open.assert_not_called()
        mock_sleep.assert_not_called()

    def test_custom_tab_delay_respected(self):
        results = [_make_result("1"), _make_result("2")]
        with patch("webbrowser.open"), patch("time.sleep") as mock_sleep:
            open_failed_in_browser(results, tab_delay=2.5)
        mock_sleep.assert_called_once_with(2.5)

    def test_default_tab_delay_from_config(self):
        results = [_make_result("1"), _make_result("2")]
        with patch("orchestrator.sync.browser.config") as mock_cfg, \
             patch("webbrowser.open"), \
             patch("time.sleep") as mock_sleep:
            mock_cfg.BROWSER_TAB_DELAY = 3.0
            open_failed_in_browser(results)
        mock_sleep.assert_called_once_with(3.0)


# ---------------------------------------------------------------------------
# curation_needed
# ---------------------------------------------------------------------------


class TestCurationNeeded:
    def test_empty_result_returns_empty(self):
        rs = _make_rs_result()
        assert curation_needed(rs) == []

    def test_priority_excluded(self):
        rs = _make_rs_result(
            updated=[1],
            statuses={1: "Priority"},
            work_ids={1: "111"},
        )
        assert curation_needed(rs) == []

    def test_favorite_read_dnf_included(self):
        rs = _make_rs_result(
            updated=[1, 2, 3],
            statuses={1: "Favorite", 2: "Read", 3: "DNF"},
            work_ids={1: "111", 2: "222", 3: "333"},
        )
        assert set(curation_needed(rs)) == {1, 2, 3}

    def test_missing_ao3_work_id_excluded(self):
        rs = _make_rs_result(
            updated=[1, 2],
            statuses={1: "Favorite", 2: "Read"},
            work_ids={1: "111", 2: ""},  # empty string → excluded
        )
        assert curation_needed(rs) == [1]

    def test_order_preserved(self):
        rs = _make_rs_result(
            updated=[3, 1, 2],
            statuses={1: "Read", 2: "Favorite", 3: "DNF"},
            work_ids={1: "1", 2: "2", 3: "3"},
        )
        assert curation_needed(rs) == [3, 1, 2]


# ---------------------------------------------------------------------------
# open_curation_in_browser
# ---------------------------------------------------------------------------


class TestOpenCurationInBrowser:
    def _rs(self, cids_statuses: dict[int, tuple[str, str]]) -> ReadStatusSyncResult:
        """Build a ReadStatusSyncResult from {cid: (work_id, status)} dict."""
        return _make_rs_result(
            updated=list(cids_statuses.keys()),
            statuses={cid: st for cid, (wid, st) in cids_statuses.items()},
            work_ids={cid: wid for cid, (wid, st) in cids_statuses.items()},
        )

    def test_correct_urls_opened(self):
        rs = self._rs({1: ("111", "Favorite"), 2: ("222", "Read")})
        with patch("webbrowser.open") as mock_open:
            open_curation_in_browser(rs, tab_delay=0)
        opened = [c.args[0] for c in mock_open.call_args_list]
        assert "https://archiveofourown.org/works/111" in opened
        assert "https://archiveofourown.org/works/222" in opened

    def test_favorites_opened_before_others(self):
        rs = self._rs({1: ("111", "Read"), 2: ("222", "Favorite")})
        with patch("webbrowser.open") as mock_open:
            open_curation_in_browser(rs, tab_delay=0)
        opened = [c.args[0] for c in mock_open.call_args_list]
        fav_idx = next(i for i, u in enumerate(opened) if "222" in u)
        read_idx = next(i for i, u in enumerate(opened) if "111" in u)
        assert fav_idx < read_idx

    def test_tab_delay_zero_skips_sleep(self):
        rs = self._rs({1: ("111", "Read"), 2: ("222", "Favorite")})
        with patch("webbrowser.open"), patch("time.sleep") as mock_sleep:
            open_curation_in_browser(rs, tab_delay=0)
        mock_sleep.assert_not_called()

    def test_empty_curation_does_nothing(self):
        rs = _make_rs_result(
            updated=[1],
            statuses={1: "Priority"},
            work_ids={1: "111"},
        )
        with patch("webbrowser.open") as mock_open:
            open_curation_in_browser(rs, tab_delay=0)
        mock_open.assert_not_called()
