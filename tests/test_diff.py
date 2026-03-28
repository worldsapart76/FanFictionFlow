"""
Unit tests for orchestrator/sync/diff.py.

All tests use in-memory data or the fixture CSV — no real Calibre required.
"""

import textwrap
from pathlib import Path

import pytest

from orchestrator.sync import diff


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_CSV = Path(__file__).parent / "fixtures" / "marked_for_later.csv"


def _write_csv(tmp_path: Path, content: str) -> Path:
    """Write a CSV string to a temp file and return its path."""
    p = tmp_path / "marked_for_later.csv"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


_MINIMAL_CSV = """\
    work_id,title,authors,fandoms,relationship_primary,additional_tags,words
    11111,Story A,Author A,Fandom X,Ship A/B,Tag1,10000
    22222,Story B,Author B,Fandom Y,Ship C/D,Tag2,20000
    33333,Story C,Author C,Fandom Z,Ship E/F,Tag3,30000
"""


# ---------------------------------------------------------------------------
# parse_marked_for_later — file errors
# ---------------------------------------------------------------------------

class TestParseMarkedForLaterFileErrors:
    def test_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="nonexistent.csv"):
            diff.parse_marked_for_later(tmp_path / "nonexistent.csv")

    def test_raises_value_error_on_missing_columns(self, tmp_path):
        p = _write_csv(tmp_path, "work_id,title\n12345,Story\n")
        with pytest.raises(ValueError, match="missing required columns"):
            diff.parse_marked_for_later(p)

    def test_error_message_names_missing_columns(self, tmp_path):
        # Only work_id present — many columns missing
        p = _write_csv(tmp_path, "work_id\n12345\n")
        with pytest.raises(ValueError) as exc_info:
            diff.parse_marked_for_later(p)
        msg = str(exc_info.value)
        assert "authors" in msg or "fandoms" in msg  # at least one named

    def test_returns_empty_list_for_empty_file(self, tmp_path):
        # Header only, no rows
        p = _write_csv(tmp_path,
            "work_id,title,authors,fandoms,relationship_primary,additional_tags,words\n")
        result = diff.parse_marked_for_later(p)
        assert result == []


# ---------------------------------------------------------------------------
# parse_marked_for_later — field mapping
# ---------------------------------------------------------------------------

class TestParseMarkedForLaterFieldMapping:
    def test_renames_work_id_to_ao3_work_id(self, tmp_path):
        p = _write_csv(tmp_path, _MINIMAL_CSV)
        result = diff.parse_marked_for_later(p)
        assert "ao3_work_id" in result[0]
        assert "work_id" not in result[0]

    def test_all_expected_keys_present(self, tmp_path):
        p = _write_csv(tmp_path, _MINIMAL_CSV)
        result = diff.parse_marked_for_later(p)
        expected_keys = {"ao3_work_id", "title", "author", "fandoms",
                         "relationships", "additional_tags", "word_count"}
        assert set(result[0].keys()) == expected_keys

    def test_values_are_stripped(self, tmp_path):
        p = _write_csv(tmp_path,
            "work_id,title,authors,fandoms,relationship_primary,additional_tags,words\n"
            "  99999  ,  My Story  ,  Author  ,  Fandom  ,  Ship  ,  Tags  ,  5000  \n"
        )
        result = diff.parse_marked_for_later(p)
        assert result[0]["ao3_work_id"] == "99999"
        assert result[0]["title"] == "My Story"

    def test_word_count_parsed_as_int(self, tmp_path):
        p = _write_csv(tmp_path, _MINIMAL_CSV)
        result = diff.parse_marked_for_later(p)
        assert result[0]["word_count"] == 10000
        assert isinstance(result[0]["word_count"], int)

    def test_comma_formatted_word_count(self, tmp_path):
        p = _write_csv(tmp_path,
            "work_id,title,authors,fandoms,relationship_primary,additional_tags,words\n"
            '12345,Story,Author,Fandom,Ship,Tags,"120,000"\n'
        )
        result = diff.parse_marked_for_later(p)
        assert result[0]["word_count"] == 120000

    def test_blank_word_count_returns_zero(self, tmp_path):
        p = _write_csv(tmp_path,
            "work_id,title,authors,fandoms,relationship_primary,additional_tags,words\n"
            "12345,Story,Author,Fandom,Ship,Tags,\n"
        )
        result = diff.parse_marked_for_later(p)
        assert result[0]["word_count"] == 0

    def test_non_numeric_word_count_returns_zero(self, tmp_path):
        p = _write_csv(tmp_path,
            "work_id,title,authors,fandoms,relationship_primary,additional_tags,words\n"
            "12345,Story,Author,Fandom,Ship,Tags,unknown\n"
        )
        result = diff.parse_marked_for_later(p)
        assert result[0]["word_count"] == 0


# ---------------------------------------------------------------------------
# parse_marked_for_later — row handling
# ---------------------------------------------------------------------------

class TestParseMarkedForLaterRows:
    def test_returns_all_rows(self, tmp_path):
        p = _write_csv(tmp_path, _MINIMAL_CSV)
        result = diff.parse_marked_for_later(p)
        assert len(result) == 3

    def test_skips_rows_with_blank_work_id(self, tmp_path):
        p = _write_csv(tmp_path,
            "work_id,title,authors,fandoms,relationship_primary,additional_tags,words\n"
            "11111,Story A,Author A,Fandom,Ship,Tags,1000\n"
            ",Story B,Author B,Fandom,Ship,Tags,2000\n"   # blank work_id
            "33333,Story C,Author C,Fandom,Ship,Tags,3000\n"
        )
        result = diff.parse_marked_for_later(p)
        assert len(result) == 2
        assert all(r["ao3_work_id"] for r in result)

    def test_preserves_row_order(self, tmp_path):
        p = _write_csv(tmp_path, _MINIMAL_CSV)
        result = diff.parse_marked_for_later(p)
        assert [r["ao3_work_id"] for r in result] == ["11111", "22222", "33333"]


# ---------------------------------------------------------------------------
# parse_marked_for_later — fixture file (integration-style)
# ---------------------------------------------------------------------------

class TestParseFixtureFile:
    def test_loads_fixture_csv(self):
        result = diff.parse_marked_for_later(FIXTURE_CSV)
        assert len(result) == 10

    def test_fixture_work_ids_are_strings(self):
        result = diff.parse_marked_for_later(FIXTURE_CSV)
        assert all(isinstance(r["ao3_work_id"], str) for r in result)

    def test_fixture_specific_row(self):
        result = diff.parse_marked_for_later(FIXTURE_CSV)
        hunger_games = next(r for r in result if r["ao3_work_id"] == "23456789")
        assert hunger_games["title"] == "District 13 Rendezvous"
        assert hunger_games["fandoms"] == "Hunger Games"
        assert hunger_games["word_count"] == 42000

    def test_fixture_relationships_preserved(self):
        result = diff.parse_marked_for_later(FIXTURE_CSV)
        first = next(r for r in result if r["ao3_work_id"] == "12345678")
        assert "Lee Minho | Lee Know/Han Jisung | Han" in first["relationships"]


# ---------------------------------------------------------------------------
# extract_existing_ids
# ---------------------------------------------------------------------------

class TestExtractExistingIds:
    def test_returns_set_of_ids(self):
        library = [
            {"#ao3_work_id": "11111", "title": "Story A"},
            {"#ao3_work_id": "22222", "title": "Story B"},
        ]
        result = diff.extract_existing_ids(library)
        assert result == {"11111", "22222"}

    def test_skips_none_values(self):
        library = [
            {"#ao3_work_id": None},
            {"#ao3_work_id": "99999"},
        ]
        result = diff.extract_existing_ids(library)
        assert result == {"99999"}

    def test_skips_blank_strings(self):
        library = [
            {"#ao3_work_id": ""},
            {"#ao3_work_id": "  "},
            {"#ao3_work_id": "12345"},
        ]
        result = diff.extract_existing_ids(library)
        assert result == {"12345"}

    def test_normalizes_int_ids_to_string(self):
        # calibredb may return numeric IDs as ints in JSON
        library = [{"#ao3_work_id": 55555}]
        result = diff.extract_existing_ids(library)
        assert "55555" in result

    def test_strips_whitespace_from_ids(self):
        library = [{"#ao3_work_id": "  12345  "}]
        result = diff.extract_existing_ids(library)
        assert "12345" in result

    def test_returns_empty_set_for_empty_library(self):
        assert diff.extract_existing_ids([]) == set()

    def test_missing_ao3_work_id_key_is_skipped(self):
        library = [{"title": "No ID field"}]
        result = diff.extract_existing_ids(library)
        assert result == set()


# ---------------------------------------------------------------------------
# diff_against_library
# ---------------------------------------------------------------------------

class TestDiffAgainstLibrary:
    def _stories(self):
        return [
            {"ao3_work_id": "11111", "title": "Story A"},
            {"ao3_work_id": "22222", "title": "Story B"},
            {"ao3_work_id": "33333", "title": "Story C"},
        ]

    def test_returns_only_new_stories(self):
        existing = {"11111", "22222"}
        result = diff.diff_against_library(self._stories(), existing)
        assert len(result) == 1
        assert result[0]["ao3_work_id"] == "33333"

    def test_returns_all_when_none_in_library(self):
        result = diff.diff_against_library(self._stories(), set())
        assert len(result) == 3

    def test_returns_empty_when_all_in_library(self):
        existing = {"11111", "22222", "33333"}
        result = diff.diff_against_library(self._stories(), existing)
        assert result == []

    def test_preserves_order(self):
        existing = {"22222"}
        result = diff.diff_against_library(self._stories(), existing)
        assert [r["ao3_work_id"] for r in result] == ["11111", "33333"]

    def test_returns_empty_for_empty_stories(self):
        result = diff.diff_against_library([], {"11111"})
        assert result == []


# ---------------------------------------------------------------------------
# get_new_stories (integration of parse + extract + diff)
# ---------------------------------------------------------------------------

class TestGetNewStories:
    def test_returns_new_stories_only(self, tmp_path):
        p = _write_csv(tmp_path, _MINIMAL_CSV)
        library = [
            {"#ao3_work_id": "11111", "title": "Story A"},
        ]
        result = diff.get_new_stories(p, library)
        assert len(result) == 2
        assert all(r["ao3_work_id"] != "11111" for r in result)

    def test_returns_all_when_library_empty(self, tmp_path):
        p = _write_csv(tmp_path, _MINIMAL_CSV)
        result = diff.get_new_stories(p, [])
        assert len(result) == 3

    def test_returns_empty_when_all_in_library(self, tmp_path):
        p = _write_csv(tmp_path, _MINIMAL_CSV)
        library = [
            {"#ao3_work_id": "11111"},
            {"#ao3_work_id": "22222"},
            {"#ao3_work_id": "33333"},
        ]
        result = diff.get_new_stories(p, library)
        assert result == []

    def test_with_fixture_csv_partial_library(self):
        # 56789012 is "Already In Your Library" — should be excluded
        library = [{"#ao3_work_id": "56789012"}]
        result = diff.get_new_stories(FIXTURE_CSV, library)
        assert len(result) == 9
        assert all(r["ao3_work_id"] != "56789012" for r in result)

    def test_result_dicts_have_all_fields(self, tmp_path):
        p = _write_csv(tmp_path, _MINIMAL_CSV)
        result = diff.get_new_stories(p, [])
        expected_keys = {"ao3_work_id", "title", "author", "fandoms",
                         "relationships", "additional_tags", "word_count"}
        for story in result:
            assert set(story.keys()) == expected_keys


# ---------------------------------------------------------------------------
# _parse_word_count (internal helper, tested directly)
# ---------------------------------------------------------------------------

class TestParseWordCount:
    def test_plain_integer(self):
        assert diff._parse_word_count("85000") == 85000

    def test_comma_formatted(self):
        assert diff._parse_word_count("85,000") == 85000

    def test_blank_returns_zero(self):
        assert diff._parse_word_count("") == 0

    def test_whitespace_returns_zero(self):
        assert diff._parse_word_count("   ") == 0

    def test_non_numeric_returns_zero(self):
        assert diff._parse_word_count("unknown") == 0

    def test_zero(self):
        assert diff._parse_word_count("0") == 0
