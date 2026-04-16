"""
Unit tests for orchestrator/sync/calibre.py.

All tests use mocks — no real Calibre library or calibredb required.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from orchestrator.sync import calibre


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_completed_process(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    proc = subprocess.CompletedProcess(args=[], returncode=returncode)
    proc.stdout = stdout
    proc.stderr = ""
    return proc


# ---------------------------------------------------------------------------
# is_gui_open
# ---------------------------------------------------------------------------

class TestIsGuiOpen:
    def test_returns_true_when_calibre_running(self):
        mock_proc = MagicMock()
        mock_proc.info = {"name": "calibre.exe"}
        with patch("orchestrator.sync.calibre.psutil.process_iter", return_value=[mock_proc]):
            assert calibre.is_gui_open() is True

    def test_returns_true_case_insensitive(self):
        mock_proc = MagicMock()
        mock_proc.info = {"name": "Calibre.EXE"}
        with patch("orchestrator.sync.calibre.psutil.process_iter", return_value=[mock_proc]):
            assert calibre.is_gui_open() is True

    def test_returns_false_when_not_running(self):
        mock_proc = MagicMock()
        mock_proc.info = {"name": "notepad.exe"}
        with patch("orchestrator.sync.calibre.psutil.process_iter", return_value=[mock_proc]):
            assert calibre.is_gui_open() is False

    def test_returns_false_when_no_processes(self):
        with patch("orchestrator.sync.calibre.psutil.process_iter", return_value=[]):
            assert calibre.is_gui_open() is False

    def test_skips_inaccessible_processes(self):
        import psutil
        good_proc = MagicMock()
        good_proc.info = {"name": "explorer.exe"}
        bad_proc = MagicMock()
        bad_proc.info = MagicMock(side_effect=psutil.AccessDenied(pid=99))
        with patch("orchestrator.sync.calibre.psutil.process_iter", return_value=[bad_proc, good_proc]):
            assert calibre.is_gui_open() is False


# ---------------------------------------------------------------------------
# fetch_library
# ---------------------------------------------------------------------------

class TestNormalizeKeys:
    def test_replaces_star_with_hash(self):
        raw = {"*ao3_work_id": "123", "*primaryship": "Katniss/Peeta", "id": 1}
        result = calibre._normalize_keys(raw)
        assert result == {"#ao3_work_id": "123", "#primaryship": "Katniss/Peeta", "id": 1}

    def test_leaves_non_star_keys_unchanged(self):
        raw = {"id": 1, "title": "Story", "authors": "Author"}
        assert calibre._normalize_keys(raw) == raw

    def test_only_replaces_leading_star(self):
        raw = {"*field*name": "val"}
        result = calibre._normalize_keys(raw)
        assert "#field*name" in result


class TestFetchLibrary:
    def test_returns_parsed_json_with_normalized_keys(self):
        # calibredb returns '*' prefix; fetch_library should normalize to '#'
        raw = [
            {"id": 1, "title": "Story One", "authors": "Author A", "*ao3_work_id": "111"},
            {"id": 2, "title": "Story Two", "authors": "Author B", "*ao3_work_id": "222"},
        ]
        mock_result = _make_completed_process(stdout=json.dumps(raw))
        with patch("orchestrator.sync.calibre._run", return_value=mock_result):
            result = calibre.fetch_library()
        assert result[0]["#ao3_work_id"] == "111"
        assert result[1]["#ao3_work_id"] == "222"
        assert "*ao3_work_id" not in result[0]

    def test_passes_library_path(self):
        with patch("orchestrator.sync.calibre._run", return_value=_make_completed_process(stdout="[]")) as mock_run:
            calibre.fetch_library()
        args_passed = mock_run.call_args[0][0]
        assert "--library-path" in args_passed


# ---------------------------------------------------------------------------
# fetch_existing_ship_values
# ---------------------------------------------------------------------------

class TestFetchExistingShipValues:
    def test_returns_sorted_unique_ships(self):
        library = [
            {"#primaryship": "Katniss/Peeta"},
            {"#primaryship": "Katniss/Peeta"},   # duplicate
            {"#primaryship": "Darcy/Elizabeth"},
            {"#primaryship": ""},                 # blank
            {"#primaryship": None},               # None
        ]
        with patch("orchestrator.sync.calibre.fetch_library", return_value=library):
            result = calibre.fetch_existing_ship_values()
        assert result == ["Darcy/Elizabeth", "Katniss/Peeta"]

    def test_returns_empty_list_when_no_ships(self):
        with patch("orchestrator.sync.calibre.fetch_library", return_value=[{"#primaryship": ""}]):
            assert calibre.fetch_existing_ship_values() == []


# ---------------------------------------------------------------------------
# add_book
# ---------------------------------------------------------------------------

class TestAddBook:
    def test_returns_calibre_id_and_fresh_true(self):
        mock_result = _make_completed_process(stdout="Added book ids: 42\n")
        with patch("orchestrator.sync.calibre._run", return_value=mock_result):
            calibre_id, is_fresh = calibre.add_book(Path("story.epub"))
        assert calibre_id == 42
        assert is_fresh is True

    def test_passes_epub_path(self):
        mock_result = _make_completed_process(stdout="Added book ids: 1\n")
        with patch("orchestrator.sync.calibre._run", return_value=mock_result) as mock_run:
            calibre.add_book(Path(r"C:\Downloads\story.epub"))
        args_passed = mock_run.call_args[0][0]
        assert r"C:\Downloads\story.epub" in args_passed

    def test_returns_existing_id_and_fresh_false_when_duplicate(self):
        """When calibredb returns no ID, fallback finds existing book and is_fresh=False."""
        no_id_result = _make_completed_process(stdout="DeDRM output only\n")
        found_result = _make_completed_process(stdout='[{"id": 99}]')
        with patch("orchestrator.sync.calibre._run", side_effect=[no_id_result, found_result]):
            calibre_id, is_fresh = calibre.add_book(Path("Story-ao3_12345.epub"))
        assert calibre_id == 99
        assert is_fresh is False

    def test_falls_back_to_title_search_when_ao3_work_id_not_set(self):
        """If ao3_work_id search returns nothing, title search finds the existing book."""
        no_id_result = _make_completed_process(stdout="DeDRM output only\n")
        empty_ao3 = _make_completed_process(stdout="[]")       # ao3_work_id search
        found_title = _make_completed_process(stdout='[{"id": 77}]')  # title search
        with patch("orchestrator.sync.calibre._run",
                   side_effect=[no_id_result, empty_ao3, found_title]):
            calibre_id, is_fresh = calibre.add_book(Path("Trust Fall-ao3_67301515.epub"))
        assert calibre_id == 77
        assert is_fresh is False

    def test_raises_if_id_not_in_output_and_no_fallback(self):
        no_id_result = _make_completed_process(stdout="Some unexpected output\n")
        # Both ao3_work_id search (via title fallback) and title search return nothing
        empty_result = _make_completed_process(stdout="[]")
        with patch("orchestrator.sync.calibre._run", side_effect=[no_id_result, empty_result]):
            with pytest.raises(RuntimeError, match="Could not parse Calibre ID"):
                calibre.add_book(Path("story_no_ao3id.epub"))


# ---------------------------------------------------------------------------
# set_custom
# ---------------------------------------------------------------------------

class TestSetCustom:
    def test_correct_command_structure(self):
        with patch("orchestrator.sync.calibre._run") as mock_run:
            mock_run.return_value = _make_completed_process()
            calibre.set_custom(42, "#ao3_work_id", "99999")
        args = mock_run.call_args[0][0]
        assert "set_custom" in args
        assert "ao3_work_id" in args   # # stripped
        assert "42" in args
        assert "99999" in args

    def test_strips_hash_prefix(self):
        with patch("orchestrator.sync.calibre._run") as mock_run:
            mock_run.return_value = _make_completed_process()
            calibre.set_custom(1, "#primaryship", "Katniss/Peeta")
        args = mock_run.call_args[0][0]
        # Should contain "primaryship", not "#primaryship"
        assert "primaryship" in args
        assert "#primaryship" not in args

    def test_integer_value_converted_to_string(self):
        with patch("orchestrator.sync.calibre._run") as mock_run:
            mock_run.return_value = _make_completed_process()
            calibre.set_custom(1, "#wordcount", 75000)
        args = mock_run.call_args[0][0]
        assert "75000" in args

    def test_value_with_spaces_passed_as_single_arg(self):
        with patch("orchestrator.sync.calibre._run") as mock_run:
            mock_run.return_value = _make_completed_process()
            calibre.set_custom(1, "#primaryship", "Lee Minho/Han Jisung")
        args = mock_run.call_args[0][0]
        assert "Lee Minho/Han Jisung" in args


# ---------------------------------------------------------------------------
# set_metadata_fields
# ---------------------------------------------------------------------------

class TestSetMetadataFields:
    def test_calls_set_custom_for_each_field(self):
        with patch("orchestrator.sync.calibre.set_custom") as mock_set:
            calibre.set_metadata_fields(5, {
                "#ao3_work_id": "123",
                "#primaryship": "Katniss/Peeta",
                "#wordcount": 50000,
            })
        assert mock_set.call_count == 3
        mock_set.assert_any_call(5, "#ao3_work_id", "123")
        mock_set.assert_any_call(5, "#primaryship", "Katniss/Peeta")
        mock_set.assert_any_call(5, "#wordcount", 50000)


# ---------------------------------------------------------------------------
# export_csv
# ---------------------------------------------------------------------------

class TestExportCsv:
    def test_invokes_catalog_subcommand(self):
        with patch("orchestrator.sync.calibre._run") as mock_run:
            mock_run.return_value = _make_completed_process()
            calibre.export_csv(Path("output.csv"))
        args = mock_run.call_args[0][0]
        assert "catalog" in args

    def test_passes_output_path(self):
        with patch("orchestrator.sync.calibre._run") as mock_run:
            mock_run.return_value = _make_completed_process()
            calibre.export_csv(Path("output/library_csv.csv"))
        args = mock_run.call_args[0][0]
        assert str(Path("output/library_csv.csv")) in args

    def test_passes_library_path(self):
        with patch("orchestrator.sync.calibre._run") as mock_run:
            mock_run.return_value = _make_completed_process()
            calibre.export_csv(Path("output.csv"))
        args = mock_run.call_args[0][0]
        assert "--library-path" in args


# ---------------------------------------------------------------------------
# _run (internal)
# ---------------------------------------------------------------------------

class TestRun:
    def test_raises_on_nonzero_exit(self):
        with patch("subprocess.run") as mock_subproc:
            mock_subproc.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="error msg", stderr="stderr"
            )
            with pytest.raises(subprocess.CalledProcessError):
                calibre._run(["list"])

    def test_returns_completed_process_on_success(self):
        with patch("subprocess.run") as mock_subproc:
            mock_subproc.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            result = calibre._run(["list"])
        assert result.returncode == 0
        assert result.stdout == "ok"
