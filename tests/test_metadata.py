"""
Unit tests for sync/metadata.py — Milestone 7.

All tests mock calibre.set_metadata_fields so no real Calibre library
or calibredb binary is needed. These run in WSL with:
    python3.12 -m pytest tests/test_metadata.py
"""

import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from orchestrator.sync.metadata import (
    MetadataResult,
    build_metadata,
    failed_writes,
    successful_writes,
    write_all_metadata,
    write_metadata,
)
from orchestrator import config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _story(**overrides) -> dict:
    """Minimal confirmed story dict (as returned by get_confirmed_stories())."""
    base = {
        "ao3_work_id": "12345",
        "title": "Test Story",
        "author": "Test Author",
        "word_count": 50000,
        "resolved_ship": "Katniss/Peeta",
        "resolved_collection": "Hunger Games",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# build_metadata
# ---------------------------------------------------------------------------


class TestBuildMetadata:
    def test_all_fields_present(self):
        story = _story()
        result = build_metadata(story)
        assert result["#ao3_work_id"] == "12345"
        assert result["#collection"] == "Hunger Games"
        assert result["#primaryship"] == "Katniss/Peeta"
        assert result["#wordcount"] == 50000
        assert result["#readstatus"] == config.DEFAULT_READ_STATUS

    def test_read_status_default_from_config(self):
        story = _story()
        result = build_metadata(story)
        assert result["#readstatus"] == config.DEFAULT_READ_STATUS

    def test_read_status_override(self):
        story = _story()
        result = build_metadata(story, read_status="read")
        assert result["#readstatus"] == "read"

    def test_wordcount_coerced_to_int(self):
        story = _story(word_count=85000)
        result = build_metadata(story)
        assert isinstance(result["#wordcount"], int)
        assert result["#wordcount"] == 85000

    def test_wordcount_zero_when_missing(self):
        story = _story()
        del story["word_count"]
        result = build_metadata(story)
        assert result["#wordcount"] == 0

    def test_ao3_work_id_coerced_to_str(self):
        story = _story(ao3_work_id=99999)
        result = build_metadata(story)
        assert result["#ao3_work_id"] == "99999"

    def test_ship_coerced_to_str(self):
        story = _story(resolved_ship="Chan/Minho")
        result = build_metadata(story)
        assert result["#primaryship"] == "Chan/Minho"

    def test_collection_coerced_to_str(self):
        story = _story(resolved_collection="Stray Kids")
        result = build_metadata(story)
        assert result["#collection"] == "Stray Kids"

    def test_exact_field_count(self):
        # Exactly 5 fields — no extras, no omissions.
        result = build_metadata(_story())
        assert set(result.keys()) == {
            "#ao3_work_id", "#collection", "#primaryship", "#wordcount", "#readstatus"
        }

    def test_write_readstatus_false_omits_readstatus(self):
        result = build_metadata(_story(), write_readstatus=False)
        assert "#readstatus" not in result
        assert set(result.keys()) == {
            "#ao3_work_id", "#collection", "#primaryship", "#wordcount"
        }

    def test_write_readstatus_false_preserves_other_fields(self):
        result = build_metadata(_story(), write_readstatus=False)
        assert result["#ao3_work_id"] == "12345"
        assert result["#collection"] == "Hunger Games"
        assert result["#primaryship"] == "Katniss/Peeta"
        assert result["#wordcount"] == 50000


# ---------------------------------------------------------------------------
# write_metadata — success path
# ---------------------------------------------------------------------------


class TestWriteMetadataSuccess:
    def test_returns_result_with_fields_written(self):
        with patch("orchestrator.sync.metadata.calibre.set_metadata_fields") as mock_write:
            result = write_metadata(42, _story())

        assert result.success is True
        assert result.calibre_id == 42
        assert result.error is None
        assert result.fields_written["#ao3_work_id"] == "12345"
        assert result.fields_written["#wordcount"] == 50000

    def test_calls_set_metadata_fields_with_correct_id(self):
        with patch("orchestrator.sync.metadata.calibre.set_metadata_fields") as mock_write:
            write_metadata(99, _story())

        mock_write.assert_called_once()
        calibre_id_arg = mock_write.call_args[0][0]
        assert calibre_id_arg == 99

    def test_calls_set_metadata_fields_with_all_fields(self):
        with patch("orchestrator.sync.metadata.calibre.set_metadata_fields") as mock_write:
            write_metadata(1, _story())

        fields_arg = mock_write.call_args[0][1]
        assert set(fields_arg.keys()) == {
            "#ao3_work_id", "#collection", "#primaryship", "#wordcount", "#readstatus"
        }

    def test_write_readstatus_false_omits_readstatus_from_calibre_call(self):
        with patch("orchestrator.sync.metadata.calibre.set_metadata_fields") as mock_write:
            write_metadata(1, _story(), write_readstatus=False)

        fields_arg = mock_write.call_args[0][1]
        assert "#readstatus" not in fields_arg

    def test_read_status_override_passed_through(self):
        with patch("orchestrator.sync.metadata.calibre.set_metadata_fields") as mock_write:
            result = write_metadata(1, _story(), read_status="read")

        assert result.fields_written["#readstatus"] == "read"

    def test_story_preserved_in_result(self):
        story = _story(title="My Story")
        with patch("orchestrator.sync.metadata.calibre.set_metadata_fields"):
            result = write_metadata(5, story)

        assert result.story["title"] == "My Story"


# ---------------------------------------------------------------------------
# write_metadata — error path
# ---------------------------------------------------------------------------


class TestWriteMetadataError:
    def test_calibredb_error_captured_not_raised(self):
        with patch(
            "orchestrator.sync.metadata.calibre.set_metadata_fields",
            side_effect=subprocess.CalledProcessError(1, "calibredb"),
        ):
            result = write_metadata(1, _story())

        assert result.success is False
        assert result.error is not None
        assert result.fields_written == {}

    def test_generic_exception_captured(self):
        with patch(
            "orchestrator.sync.metadata.calibre.set_metadata_fields",
            side_effect=RuntimeError("connection lost"),
        ):
            result = write_metadata(1, _story())

        assert result.success is False
        assert "connection lost" in result.error

    def test_error_result_has_calibre_id(self):
        with patch(
            "orchestrator.sync.metadata.calibre.set_metadata_fields",
            side_effect=RuntimeError("boom"),
        ):
            result = write_metadata(77, _story())

        assert result.calibre_id == 77

    def test_error_result_has_story(self):
        story = _story(title="Broken Story")
        with patch(
            "orchestrator.sync.metadata.calibre.set_metadata_fields",
            side_effect=RuntimeError("boom"),
        ):
            result = write_metadata(1, story)

        assert result.story["title"] == "Broken Story"


# ---------------------------------------------------------------------------
# write_all_metadata
# ---------------------------------------------------------------------------


class TestWriteAllMetadata:
    def test_returns_one_result_per_import(self):
        imports = [(1, _story(ao3_work_id="1")), (2, _story(ao3_work_id="2"))]
        with patch("orchestrator.sync.metadata.calibre.set_metadata_fields"):
            results = write_all_metadata(imports)
        assert len(results) == 2

    def test_results_in_same_order_as_imports(self):
        imports = [
            (10, _story(ao3_work_id="aaa")),
            (20, _story(ao3_work_id="bbb")),
            (30, _story(ao3_work_id="ccc")),
        ]
        with patch("orchestrator.sync.metadata.calibre.set_metadata_fields"):
            results = write_all_metadata(imports)

        assert results[0].calibre_id == 10
        assert results[1].calibre_id == 20
        assert results[2].calibre_id == 30

    def test_empty_list_returns_empty(self):
        with patch("orchestrator.sync.metadata.calibre.set_metadata_fields"):
            results = write_all_metadata([])
        assert results == []

    def test_partial_failure_does_not_abort_batch(self):
        calls = [None, RuntimeError("oops"), None]

        def side_effect(*args, **kwargs):
            val = calls.pop(0)
            if isinstance(val, Exception):
                raise val

        imports = [
            (1, _story(ao3_work_id="a")),
            (2, _story(ao3_work_id="b")),
            (3, _story(ao3_work_id="c")),
        ]
        with patch(
            "orchestrator.sync.metadata.calibre.set_metadata_fields",
            side_effect=side_effect,
        ):
            results = write_all_metadata(imports)

        assert results[0].success is True
        assert results[1].success is False
        assert results[2].success is True

    def test_read_status_override_applied_to_all(self):
        imports = [(1, _story()), (2, _story())]
        with patch("orchestrator.sync.metadata.calibre.set_metadata_fields"):
            results = write_all_metadata(imports, read_status="read")

        for result in results:
            assert result.fields_written["#readstatus"] == "read"

    def test_calls_calibre_once_per_import(self):
        imports = [(i, _story(ao3_work_id=str(i))) for i in range(5)]
        with patch("orchestrator.sync.metadata.calibre.set_metadata_fields") as mock_write:
            write_all_metadata(imports)
        assert mock_write.call_count == 5

    def test_fresh_ids_none_writes_readstatus_to_all(self):
        """Default (fresh_ids=None) writes readstatus to every book."""
        imports = [(1, _story()), (2, _story())]
        with patch("orchestrator.sync.metadata.calibre.set_metadata_fields"):
            results = write_all_metadata(imports, fresh_ids=None)
        for r in results:
            assert "#readstatus" in r.fields_written

    def test_fresh_ids_only_writes_readstatus_to_fresh_books(self):
        """Books not in fresh_ids must not have readstatus written."""
        imports = [(1, _story(ao3_work_id="a")), (2, _story(ao3_work_id="b"))]
        with patch("orchestrator.sync.metadata.calibre.set_metadata_fields"):
            results = write_all_metadata(imports, fresh_ids={1})
        assert "#readstatus" in results[0].fields_written  # book 1 is fresh
        assert "#readstatus" not in results[1].fields_written  # book 2 already existed

    def test_fresh_ids_empty_set_skips_readstatus_for_all(self):
        """An empty fresh_ids set means no book gets readstatus written."""
        imports = [(1, _story()), (2, _story())]
        with patch("orchestrator.sync.metadata.calibre.set_metadata_fields"):
            results = write_all_metadata(imports, fresh_ids=set())
        for r in results:
            assert "#readstatus" not in r.fields_written


# ---------------------------------------------------------------------------
# MetadataResult.success property
# ---------------------------------------------------------------------------


class TestMetadataResultSuccess:
    def test_success_when_no_error(self):
        r = MetadataResult(calibre_id=1, story={}, fields_written={"#ao3_work_id": "x"})
        assert r.success is True

    def test_failure_when_error_set(self):
        r = MetadataResult(calibre_id=1, story={}, error="something went wrong")
        assert r.success is False

    def test_failure_when_error_is_empty_string(self):
        # error="" is not None — treated as failure (won't occur in practice).
        r = MetadataResult(calibre_id=1, story={}, error="")
        assert r.success is False


# ---------------------------------------------------------------------------
# Result filters
# ---------------------------------------------------------------------------


class TestResultFilters:
    def _make_results(self) -> list[MetadataResult]:
        return [
            MetadataResult(calibre_id=1, story={}, fields_written={"#ao3_work_id": "a"}),
            MetadataResult(calibre_id=2, story={}, error="boom"),
            MetadataResult(calibre_id=3, story={}, fields_written={"#ao3_work_id": "c"}),
            MetadataResult(calibre_id=4, story={}, error="also boom"),
        ]

    def test_successful_writes_returns_successes_only(self):
        results = self._make_results()
        successes = successful_writes(results)
        assert len(successes) == 2
        assert all(r.success for r in successes)

    def test_failed_writes_returns_failures_only(self):
        results = self._make_results()
        failures = failed_writes(results)
        assert len(failures) == 2
        assert all(not r.success for r in failures)

    def test_successful_writes_on_all_success(self):
        results = [
            MetadataResult(calibre_id=i, story={}, fields_written={})
            for i in range(3)
        ]
        assert len(successful_writes(results)) == 3

    def test_failed_writes_on_all_success_is_empty(self):
        results = [
            MetadataResult(calibre_id=i, story={}, fields_written={})
            for i in range(3)
        ]
        assert failed_writes(results) == []

    def test_successful_writes_on_all_failure_is_empty(self):
        results = [
            MetadataResult(calibre_id=i, story={}, error="err")
            for i in range(3)
        ]
        assert successful_writes(results) == []

    def test_filters_on_empty_list(self):
        assert successful_writes([]) == []
        assert failed_writes([]) == []
