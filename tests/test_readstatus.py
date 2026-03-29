"""
Unit tests for sync/readstatus.py.

All tests mock calibre calls — no real Calibre library or calibredb binary
needed. Run in WSL with:
    python3.12 -m pytest tests/test_readstatus.py
"""

import io
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from orchestrator.sync.readstatus import (
    ReadStatusSyncResult,
    _normalize_status,
    parse_palma_csv,
    sync_readstatus_from_palma,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_csv(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "palma_readstatus_overrides.csv"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# _normalize_status
# ---------------------------------------------------------------------------

class TestNormalizeStatus:
    def test_dnf_is_all_caps(self):
        assert _normalize_status("dnf") == "DNF"
        assert _normalize_status("Dnf") == "DNF"
        assert _normalize_status("DNF") == "DNF"

    def test_read_is_title_case(self):
        assert _normalize_status("read") == "Read"
        assert _normalize_status("READ") == "Read"

    def test_unread_is_title_case(self):
        assert _normalize_status("unread") == "Unread"
        assert _normalize_status("UNREAD") == "Unread"

    def test_favorite_is_title_case(self):
        assert _normalize_status("favorite") == "Favorite"
        assert _normalize_status("FAVORITE") == "Favorite"
        assert _normalize_status("Favorite") == "Favorite"

    def test_priority_is_title_case(self):
        assert _normalize_status("priority") == "Priority"


# ---------------------------------------------------------------------------
# parse_palma_csv
# ---------------------------------------------------------------------------

class TestParsePalmaCsv:
    def test_standard_columns(self, tmp_path):
        csv = _write_csv(tmp_path, "id,readstatus\n1,read\n2,Favorite\n3,unread\n")
        result = parse_palma_csv(csv)
        assert result == {1: "read", 2: "Favorite", 3: "unread"}

    def test_alternate_column_names(self, tmp_path):
        csv = _write_csv(tmp_path, "calibre_id,#readstatus\n10,DNF\n20,read\n")
        result = parse_palma_csv(csv)
        assert result == {10: "DNF", 20: "read"}

    def test_case_insensitive_column_match(self, tmp_path):
        csv = _write_csv(tmp_path, "ID,ReadStatus\n5,Priority\n")
        result = parse_palma_csv(csv)
        assert result == {5: "Priority"}

    def test_skips_rows_with_empty_status(self, tmp_path):
        csv = _write_csv(tmp_path, "id,readstatus\n1,read\n2,\n3,Favorite\n")
        result = parse_palma_csv(csv)
        assert result == {1: "read", 3: "Favorite"}

    def test_skips_rows_with_non_integer_id(self, tmp_path):
        csv = _write_csv(tmp_path, "id,readstatus\nabc,read\n2,Favorite\n")
        result = parse_palma_csv(csv)
        assert result == {2: "Favorite"}

    def test_missing_id_column_raises(self, tmp_path):
        csv = _write_csv(tmp_path, "book_id,readstatus\n1,read\n")
        with pytest.raises(ValueError, match="No ID column"):
            parse_palma_csv(csv)

    def test_missing_status_column_raises(self, tmp_path):
        csv = _write_csv(tmp_path, "id,status_value\n1,read\n")
        with pytest.raises(ValueError, match="No status column"):
            parse_palma_csv(csv)

    def test_empty_file_returns_empty_dict(self, tmp_path):
        csv = _write_csv(tmp_path, "id,readstatus\n")
        result = parse_palma_csv(csv)
        assert result == {}

    def test_utf8_bom_handled(self, tmp_path):
        # BOM prefix — common from Windows CSV exports.
        p = tmp_path / "bom.csv"
        p.write_bytes(b"\xef\xbb\xbfid,readstatus\r\n7,read\r\n")
        result = parse_palma_csv(p)
        assert result == {7: "read"}


# ---------------------------------------------------------------------------
# sync_readstatus_from_palma
# ---------------------------------------------------------------------------

_LIBRARY = [
    {"id": 1, "#readstatus": "unread", "title": "Story One", "#ao3_work_id": "111"},
    {"id": 2, "#readstatus": "read",   "title": "Story Two", "#ao3_work_id": "222"},
    {"id": 3, "#readstatus": "Favorite", "title": "Story Three", "#ao3_work_id": "333"},
    {"id": 4, "#readstatus": "unread", "title": "Story Four", "#ao3_work_id": "444"},
]


class TestSyncReadstatusFromPalma:
    def _run(self, tmp_path, csv_content, library=None):
        csv = _write_csv(tmp_path, csv_content)
        lib = library if library is not None else _LIBRARY
        with patch("orchestrator.sync.readstatus.calibre.fetch_library", return_value=lib), \
             patch("orchestrator.sync.readstatus.calibre.set_custom") as mock_set, \
             patch("orchestrator.sync.readstatus.calibre.touch_last_modified"):
            result = sync_readstatus_from_palma(csv)
        return result, mock_set

    def test_updates_changed_entries(self, tmp_path):
        result, mock_set = self._run(
            tmp_path, "id,readstatus\n1,read\n2,read\n"
        )
        # id=1 changes unread→read; id=2 is already read → skipped
        assert 1 in result.updated
        assert 2 in result.skipped
        mock_set.assert_called_once_with(1, "#readstatus", "Read")

    def test_skips_matching_status(self, tmp_path):
        result, mock_set = self._run(
            tmp_path, "id,readstatus\n2,read\n3,Favorite\n"
        )
        assert result.updated == []
        assert set(result.skipped) == {2, 3}
        mock_set.assert_not_called()

    def test_skips_unknown_calibre_id(self, tmp_path):
        result, mock_set = self._run(
            tmp_path, "id,readstatus\n999,read\n"
        )
        assert 999 in result.skipped
        mock_set.assert_not_called()

    def test_case_insensitive_status_comparison(self, tmp_path):
        # Library has "unread"; CSV has "Unread" — should be treated as same.
        result, mock_set = self._run(
            tmp_path, "id,readstatus\n1,Unread\n"
        )
        assert 1 in result.skipped
        mock_set.assert_not_called()

    def test_skips_unread_status_even_when_calibre_differs(self, tmp_path):
        # id=3 is "Favorite" in the library but CSV says "unread".
        # "unread" is the Palma default — syncing it back would silently
        # overwrite deliberate status values, so it must be skipped.
        result, mock_set = self._run(
            tmp_path, "id,readstatus\n3,unread\n"
        )
        assert 3 in result.skipped
        mock_set.assert_not_called()

    def test_skips_unread_case_variants(self, tmp_path):
        # "Unread", "UNREAD", "unread" are all treated as the default to skip.
        result, mock_set = self._run(
            tmp_path, "id,readstatus\n3,UNREAD\n"
        )
        assert 3 in result.skipped
        mock_set.assert_not_called()

    def test_records_failed_writes(self, tmp_path):
        csv = _write_csv(tmp_path, "id,readstatus\n1,read\n")
        with patch("orchestrator.sync.readstatus.calibre.fetch_library", return_value=_LIBRARY), \
             patch(
                 "orchestrator.sync.readstatus.calibre.set_custom",
                 side_effect=RuntimeError("calibredb error"),
             ), \
             patch("orchestrator.sync.readstatus.calibre.touch_last_modified"):
            result = sync_readstatus_from_palma(csv)
        assert result.updated == []
        assert len(result.failed) == 1
        assert result.failed[0][0] == 1
        assert "calibredb error" in result.failed[0][1]

    def test_multiple_updates(self, tmp_path):
        result, mock_set = self._run(
            tmp_path,
            "id,readstatus\n1,read\n4,Favorite\n2,read\n",
        )
        # id=1 unread→read (changed), id=4 unread→Favorite (changed),
        # id=2 read→read (same)
        assert set(result.updated) == {1, 4}
        assert 2 in result.skipped
        assert mock_set.call_count == 2

    def test_empty_library_skips_all(self, tmp_path):
        result, mock_set = self._run(
            tmp_path, "id,readstatus\n1,read\n", library=[]
        )
        assert result.updated == []
        assert 1 in result.skipped
        mock_set.assert_not_called()

    def test_book_with_no_readstatus_in_library(self, tmp_path):
        # A library book where #readstatus is None/missing.
        library = [{"id": 5, "#readstatus": None}]
        result, mock_set = self._run(
            tmp_path, "id,readstatus\n5,read\n", library=library
        )
        assert 5 in result.updated
        mock_set.assert_called_once_with(5, "#readstatus", "Read")

    def test_updated_metadata_fields_populated(self, tmp_path):
        # id=1 transitions unread→read; verify the 3 new dict fields.
        result, _ = self._run(tmp_path, "id,readstatus\n1,read\n")
        assert result.updated_titles[1] == "Story One"
        assert result.updated_ao3_work_ids[1] == "111"
        assert result.updated_statuses[1] == "Read"

    def test_updated_metadata_fields_absent_for_skipped(self, tmp_path):
        # id=2 already has status "read" → skipped; new dict fields stay empty.
        result, _ = self._run(tmp_path, "id,readstatus\n2,read\n")
        assert 2 in result.skipped
        assert 2 not in result.updated_titles
        assert 2 not in result.updated_ao3_work_ids
        assert 2 not in result.updated_statuses
