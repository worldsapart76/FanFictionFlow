"""
Unit tests for export/library_csv.py — Milestone 8.

All tests mock calibre.fetch_library so no real Calibre library or
calibredb binary is needed. These run in WSL with:
    python3.12 -m pytest tests/test_library_csv.py
"""

import csv
import subprocess
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from orchestrator import config
from orchestrator.export.library_csv import (
    EXPORT_COLUMNS,
    _write_csv,
    export_library_csv,
    find_latest_csv,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _book(**overrides) -> dict:
    """Minimal book dict as returned by calibre.fetch_library()."""
    base = {
        "id": 1,
        "title": "Test Story",
        "authors": "Test Author",
        "tags": "tag1, tag2",
        "comments": "A story description.",
        "#ao3_work_id": "12345",
        "#collection": "Hunger Games",
        "#primaryship": "Katniss/Peeta",
        "#wordcount": 50000,
        "#readstatus": "unread",
    }
    base.update(overrides)
    return base


def _read_csv(path: Path) -> tuple[list[str], list[dict]]:
    """Return (headers, rows) from a CSV file."""
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        rows = list(reader)
    return headers, rows


# ---------------------------------------------------------------------------
# EXPORT_COLUMNS — structural integrity
# ---------------------------------------------------------------------------


class TestExportColumns:
    def test_contains_all_expected_columns(self):
        expected = {
            "id", "title", "authors", "tags", "comments",
            "#ao3_work_id", "#collection", "#primaryship",
            "#wordcount", "#readstatus",
        }
        assert set(EXPORT_COLUMNS) == expected

    def test_no_duplicate_columns(self):
        assert len(EXPORT_COLUMNS) == len(set(EXPORT_COLUMNS))

    def test_id_is_first_column(self):
        assert EXPORT_COLUMNS[0] == "id"

    def test_is_a_list(self):
        assert isinstance(EXPORT_COLUMNS, list)


# ---------------------------------------------------------------------------
# _write_csv — header and row structure
# ---------------------------------------------------------------------------


class TestWriteCsv:
    def test_writes_header_row(self, tmp_path):
        out = tmp_path / "out.csv"
        _write_csv([], out)
        headers, rows = _read_csv(out)
        assert headers == EXPORT_COLUMNS

    def test_empty_books_produces_header_only(self, tmp_path):
        out = tmp_path / "out.csv"
        _write_csv([], out)
        _, rows = _read_csv(out)
        assert rows == []

    def test_one_row_per_book(self, tmp_path):
        out = tmp_path / "out.csv"
        books = [_book(id=i) for i in range(5)]
        _write_csv(books, out)
        _, rows = _read_csv(out)
        assert len(rows) == 5

    def test_book_fields_appear_in_correct_columns(self, tmp_path):
        out = tmp_path / "out.csv"
        _write_csv([_book()], out)
        _, rows = _read_csv(out)
        row = rows[0]
        assert row["id"] == "1"
        assert row["title"] == "Test Story"
        assert row["authors"] == "Test Author"
        assert row["#ao3_work_id"] == "12345"
        assert row["#collection"] == "Hunger Games"
        assert row["#primaryship"] == "Katniss/Peeta"
        assert row["#wordcount"] == "50000"
        assert row["#readstatus"] == "unread"

    def test_missing_field_written_as_empty_string(self, tmp_path):
        out = tmp_path / "out.csv"
        book = {"id": 1, "title": "Partial Book"}  # most fields absent
        _write_csv([book], out)
        _, rows = _read_csv(out)
        row = rows[0]
        assert row["#ao3_work_id"] == ""
        assert row["#collection"] == ""
        assert row["#primaryship"] == ""
        assert row["#readstatus"] == ""

    def test_extra_calibre_fields_ignored(self, tmp_path):
        out = tmp_path / "out.csv"
        book = _book()
        book["series"] = "My Series"
        book["#custom_extra"] = "extra"
        _write_csv([book], out)
        headers, rows = _read_csv(out)
        assert "series" not in headers
        assert "#custom_extra" not in headers

    def test_special_chars_in_title(self, tmp_path):
        out = tmp_path / "out.csv"
        book = _book(title='Title with "quotes" and, commas')
        _write_csv([book], out)
        _, rows = _read_csv(out)
        assert rows[0]["title"] == 'Title with "quotes" and, commas'

    def test_unicode_in_fields(self, tmp_path):
        out = tmp_path / "out.csv"
        book = _book(title="한국어 제목", authors="작가")
        _write_csv([book], out)
        _, rows = _read_csv(out)
        assert rows[0]["title"] == "한국어 제목"
        assert rows[0]["authors"] == "작가"

    def test_multiple_authors_preserved(self, tmp_path):
        out = tmp_path / "out.csv"
        book = _book(authors="Author One & Author Two")
        _write_csv([book], out)
        _, rows = _read_csv(out)
        assert rows[0]["authors"] == "Author One & Author Two"

    def test_file_encoding_is_utf8(self, tmp_path):
        out = tmp_path / "out.csv"
        book = _book(title="Café au lait")
        _write_csv([book], out)
        raw = out.read_bytes()
        assert "Café au lait".encode("utf-8") in raw

    def test_integer_wordcount_written_as_string(self, tmp_path):
        out = tmp_path / "out.csv"
        _write_csv([_book(**{"#wordcount": 123456})], out)
        _, rows = _read_csv(out)
        assert rows[0]["#wordcount"] == "123456"

    def test_zero_wordcount(self, tmp_path):
        out = tmp_path / "out.csv"
        _write_csv([_book(**{"#wordcount": 0})], out)
        _, rows = _read_csv(out)
        assert rows[0]["#wordcount"] == "0"

    def test_rows_in_same_order_as_books(self, tmp_path):
        out = tmp_path / "out.csv"
        books = [_book(id=i, title=f"Story {i}") for i in range(10)]
        _write_csv(books, out)
        _, rows = _read_csv(out)
        for i, row in enumerate(rows):
            assert row["title"] == f"Story {i}"


# ---------------------------------------------------------------------------
# export_library_csv — fetch and write integration
# ---------------------------------------------------------------------------


class TestExportLibraryCsv:
    def test_calls_fetch_library_once(self, tmp_path):
        out = tmp_path / "lib.csv"
        with patch("orchestrator.export.library_csv.calibre.fetch_library", return_value=[]) as mock_fetch:
            export_library_csv(output_path=out)
        mock_fetch.assert_called_once()

    def test_writes_csv_at_given_path(self, tmp_path):
        out = tmp_path / "lib.csv"
        with patch("orchestrator.export.library_csv.calibre.fetch_library", return_value=[_book()]):
            export_library_csv(output_path=out)
        assert out.exists()

    def test_returns_resolved_path(self, tmp_path):
        out = tmp_path / "lib.csv"
        with patch("orchestrator.export.library_csv.calibre.fetch_library", return_value=[]):
            result = export_library_csv(output_path=out)
        assert result == out.resolve()

    def test_default_path_uses_timestamped_filename(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LIBRARY_CSV_PATH", tmp_path / "library_csv.csv")
        with patch("orchestrator.export.library_csv.calibre.fetch_library", return_value=[]):
            result = export_library_csv()
        assert result.parent == tmp_path.resolve()
        assert result.name.startswith("library_csv_")
        assert result.suffix == ".csv"

    def test_default_path_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LIBRARY_CSV_PATH", tmp_path / "library_csv.csv")
        with patch("orchestrator.export.library_csv.calibre.fetch_library", return_value=[]):
            export_library_csv()
        assert any(tmp_path.glob("library_csv_*.csv"))

    def test_csv_contains_all_books(self, tmp_path):
        books = [_book(id=i, **{"#ao3_work_id": str(i)}) for i in range(20)]
        out = tmp_path / "lib.csv"
        with patch("orchestrator.export.library_csv.calibre.fetch_library", return_value=books):
            export_library_csv(output_path=out)
        _, rows = _read_csv(out)
        assert len(rows) == 20

    def test_csv_has_correct_headers(self, tmp_path):
        out = tmp_path / "lib.csv"
        with patch("orchestrator.export.library_csv.calibre.fetch_library", return_value=[]):
            export_library_csv(output_path=out)
        headers, _ = _read_csv(out)
        assert headers == EXPORT_COLUMNS

    def test_fetch_library_error_propagates(self, tmp_path):
        out = tmp_path / "lib.csv"
        with patch(
            "orchestrator.export.library_csv.calibre.fetch_library",
            side_effect=subprocess.CalledProcessError(1, "calibredb"),
        ):
            with pytest.raises(subprocess.CalledProcessError):
                export_library_csv(output_path=out)

    def test_write_error_propagates(self, tmp_path):
        bad_path = tmp_path / "nonexistent_dir" / "lib.csv"
        with patch("orchestrator.export.library_csv.calibre.fetch_library", return_value=[]):
            with pytest.raises(OSError):
                export_library_csv(output_path=bad_path)

    def test_readstatus_from_library_in_csv(self, tmp_path):
        out = tmp_path / "lib.csv"
        books = [_book(**{"#readstatus": "read"})]
        with patch("orchestrator.export.library_csv.calibre.fetch_library", return_value=books):
            export_library_csv(output_path=out)
        _, rows = _read_csv(out)
        assert rows[0]["#readstatus"] == "read"

    def test_ao3_work_id_from_library_in_csv(self, tmp_path):
        out = tmp_path / "lib.csv"
        books = [_book(**{"#ao3_work_id": "99999"})]
        with patch("orchestrator.export.library_csv.calibre.fetch_library", return_value=books):
            export_library_csv(output_path=out)
        _, rows = _read_csv(out)
        assert rows[0]["#ao3_work_id"] == "99999"

    def test_overwrites_existing_file(self, tmp_path):
        out = tmp_path / "lib.csv"
        out.write_text("old content")
        with patch("orchestrator.export.library_csv.calibre.fetch_library", return_value=[_book()]):
            export_library_csv(output_path=out)
        _, rows = _read_csv(out)
        assert len(rows) == 1
        assert rows[0]["title"] == "Test Story"

    def test_empty_library_produces_header_only_csv(self, tmp_path):
        out = tmp_path / "lib.csv"
        with patch("orchestrator.export.library_csv.calibre.fetch_library", return_value=[]):
            export_library_csv(output_path=out)
        headers, rows = _read_csv(out)
        assert headers == EXPORT_COLUMNS
        assert rows == []


class TestFindLatestCsv:
    def test_returns_none_when_no_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LIBRARY_CSV_PATH", tmp_path / "library_csv.csv")
        assert find_latest_csv() is None

    def test_returns_only_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LIBRARY_CSV_PATH", tmp_path / "library_csv.csv")
        f = tmp_path / "library_csv_20260101_120000.csv"
        f.touch()
        assert find_latest_csv() == f

    def test_returns_most_recent_by_timestamp(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LIBRARY_CSV_PATH", tmp_path / "library_csv.csv")
        older = tmp_path / "library_csv_20260101_120000.csv"
        newer = tmp_path / "library_csv_20260328_090000.csv"
        older.touch()
        newer.touch()
        assert find_latest_csv() == newer

    def test_ignores_non_matching_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "LIBRARY_CSV_PATH", tmp_path / "library_csv.csv")
        (tmp_path / "library_csv.csv").touch()
        (tmp_path / "other.csv").touch()
        assert find_latest_csv() is None
