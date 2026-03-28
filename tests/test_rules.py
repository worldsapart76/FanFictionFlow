"""
Tests for normalize/rules.py — Milestone 4.

All tests are pure unit tests; no real Calibre library required.
The keyword table is passed explicitly to avoid coupling tests to config.
"""

import pytest
from orchestrator.normalize.rules import (
    normalize_collection,
    normalize_stories_collection,
    CollectionResult,
)

# Minimal keyword table used across tests
KEYWORDS = [
    ("Stray Kids", "Stray Kids"),
    ("ATEEZ", "ATEEZ"),
    ("Hunger Games", "Hunger Games"),
    ("Harry Potter", "Harry Potter"),
    ("Batman", "DCU"),
    ("DCU", "DCU"),
    ("DC Comics", "DCU"),
    ("Marvel", "Marvel"),
    ("Avengers", "Marvel"),
    ("Pride and Prejudice", "Jane Austen"),
    ("Jane Austen", "Jane Austen"),
    ("Roswell New Mexico", "Roswell"),
    ("Mass Effect", "Mass Effect"),
    ("Dragon Age", "Dragon Age"),
    ("Shadowhunters", "Shadowhunters"),
    ("Mortal Instruments", "Shadowhunters"),
    ("Star Wars", "Star Wars"),
    ("Teen Wolf", "Teen Wolf"),
    ("Witcher", "Witcher"),
    ("Skyrim", "Skyrim"),
    ("Elder Scrolls", "Skyrim"),
]


# ---------------------------------------------------------------------------
# Auto-resolved cases
# ---------------------------------------------------------------------------

class TestAutoResolved:
    def test_single_fandom_match(self):
        result = normalize_collection("Stray Kids RPF", keywords=KEYWORDS)
        assert result.status == "auto"
        assert result.value == "Stray Kids"

    def test_hunger_games(self):
        result = normalize_collection("Hunger Games - Suzanne Collins", keywords=KEYWORDS)
        assert result.status == "auto"
        assert result.value == "Hunger Games"

    def test_harry_potter(self):
        result = normalize_collection("Harry Potter - J. K. Rowling", keywords=KEYWORDS)
        assert result.status == "auto"
        assert result.value == "Harry Potter"

    def test_dcu_via_batman_keyword(self):
        result = normalize_collection("Batman (Comics)", keywords=KEYWORDS)
        assert result.status == "auto"
        assert result.value == "DCU"

    def test_dcu_via_dcu_keyword(self):
        result = normalize_collection("DCU", keywords=KEYWORDS)
        assert result.status == "auto"
        assert result.value == "DCU"

    def test_dcu_via_dc_comics_keyword(self):
        result = normalize_collection("DC Comics", keywords=KEYWORDS)
        assert result.status == "auto"
        assert result.value == "DCU"

    def test_marvel_via_avengers(self):
        result = normalize_collection("The Avengers (Marvel Movies)", keywords=KEYWORDS)
        assert result.status == "auto"
        assert result.value == "Marvel"

    def test_shadowhunters_via_mortal_instruments(self):
        result = normalize_collection("The Mortal Instruments - Cassandra Clare", keywords=KEYWORDS)
        assert result.status == "auto"
        assert result.value == "Shadowhunters"

    def test_skyrim_via_elder_scrolls(self):
        result = normalize_collection("Elder Scrolls V: Skyrim", keywords=KEYWORDS)
        assert result.status == "auto"
        assert result.value == "Skyrim"

    def test_raw_preserved(self):
        raw = "Stray Kids RPF"
        result = normalize_collection(raw, keywords=KEYWORDS)
        assert result.raw == raw

    def test_reason_is_none_when_auto(self):
        result = normalize_collection("ATEEZ RPF", keywords=KEYWORDS)
        assert result.reason is None


# ---------------------------------------------------------------------------
# Case-insensitive matching
# ---------------------------------------------------------------------------

class TestCaseInsensitive:
    def test_keyword_match_uppercase_fandoms(self):
        result = normalize_collection("STRAY KIDS RPF", keywords=KEYWORDS)
        assert result.status == "auto"
        assert result.value == "Stray Kids"

    def test_keyword_match_lowercase_fandoms(self):
        result = normalize_collection("stray kids rpf", keywords=KEYWORDS)
        assert result.status == "auto"
        assert result.value == "Stray Kids"

    def test_keyword_match_mixed_case(self):
        result = normalize_collection("Hunger games - Suzanne Collins", keywords=KEYWORDS)
        assert result.status == "auto"
        assert result.value == "Hunger Games"


# ---------------------------------------------------------------------------
# Multiple keywords → same collection (not a conflict)
# ---------------------------------------------------------------------------

class TestMultipleKeywordsSameCollection:
    def test_batman_and_dcu_both_in_fandoms_resolves_to_dcu(self):
        # Both "Batman" and "DCU" keywords match, but both map to "DCU" — no conflict
        result = normalize_collection("Batman (Comics) | DCU", keywords=KEYWORDS)
        assert result.status == "auto"
        assert result.value == "DCU"

    def test_shadowhunters_and_mortal_instruments_same_collection(self):
        result = normalize_collection(
            "Shadowhunters (TV) | The Mortal Instruments", keywords=KEYWORDS
        )
        assert result.status == "auto"
        assert result.value == "Shadowhunters"

    def test_marvel_and_avengers_same_collection(self):
        result = normalize_collection(
            "Marvel Cinematic Universe | The Avengers", keywords=KEYWORDS
        )
        assert result.status == "auto"
        assert result.value == "Marvel"


# ---------------------------------------------------------------------------
# Multiple distinct collections → review queue
# ---------------------------------------------------------------------------

class TestMultipleFandomsConflict:
    def test_two_distinct_collections_flagged(self):
        result = normalize_collection("Stray Kids RPF | Harry Potter", keywords=KEYWORDS)
        assert result.status == "review"
        assert result.value is None

    def test_conflict_reason_mentions_both_collections(self):
        result = normalize_collection("Stray Kids RPF | Harry Potter", keywords=KEYWORDS)
        assert "Stray Kids" in result.reason
        assert "Harry Potter" in result.reason

    def test_crossover_three_fandoms_flagged(self):
        result = normalize_collection(
            "Stray Kids RPF | ATEEZ RPF | Harry Potter", keywords=KEYWORDS
        )
        assert result.status == "review"

    def test_dcu_and_marvel_crossover_flagged(self):
        result = normalize_collection("DCU | Marvel", keywords=KEYWORDS)
        assert result.status == "review"
        assert result.value is None


# ---------------------------------------------------------------------------
# No match → review queue
# ---------------------------------------------------------------------------

class TestNoMatch:
    def test_unknown_fandom_flagged(self):
        result = normalize_collection("Some Original Fiction", keywords=KEYWORDS)
        assert result.status == "review"
        assert result.value is None

    def test_no_match_reason(self):
        result = normalize_collection("Some Original Fiction", keywords=KEYWORDS)
        assert result.reason == "no matching fandom keyword"

    def test_partial_keyword_not_matched(self):
        # "Star" should not match "Star Wars" unless it actually appears
        result = normalize_collection("Star Trek - All Media Types", keywords=KEYWORDS)
        assert result.status == "review"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_blank_fandoms_flagged(self):
        result = normalize_collection("", keywords=KEYWORDS)
        assert result.status == "review"
        assert result.reason == "blank fandoms field"
        assert result.value is None

    def test_whitespace_only_fandoms_flagged(self):
        result = normalize_collection("   ", keywords=KEYWORDS)
        assert result.status == "review"
        assert result.reason == "blank fandoms field"

    def test_raw_blank_preserved(self):
        result = normalize_collection("", keywords=KEYWORDS)
        assert result.raw == ""

    def test_roswell_new_mexico(self):
        # "Roswell New Mexico" is a multi-word keyword; must not partially match on "Roswell"
        # if a different "Roswell" entry existed. Also checks multi-word keywords work.
        result = normalize_collection("Roswell New Mexico (TV)", keywords=KEYWORDS)
        assert result.status == "auto"
        assert result.value == "Roswell"

    def test_first_match_wins_ordering(self):
        # "Stray Kids" comes before "ATEEZ" in table; only one should win here
        result = normalize_collection("Stray Kids RPF", keywords=KEYWORDS)
        assert result.value == "Stray Kids"

    def test_default_keywords_from_config(self):
        # Smoke test: calling without explicit keywords uses config defaults
        result = normalize_collection("Stray Kids RPF")
        assert result.status == "auto"
        assert result.value == "Stray Kids"


# ---------------------------------------------------------------------------
# normalize_stories_collection batch helper
# ---------------------------------------------------------------------------

class TestNormalizeStoriesCollection:
    def test_returns_pairs(self):
        stories = [
            {"fandoms": "Stray Kids RPF", "title": "Story A"},
            {"fandoms": "Unknown Fandom", "title": "Story B"},
        ]
        results = normalize_stories_collection(stories, keywords=KEYWORDS)
        assert len(results) == 2
        assert results[0][0]["title"] == "Story A"
        assert results[0][1].status == "auto"
        assert results[1][1].status == "review"

    def test_missing_fandoms_key_treated_as_blank(self):
        stories = [{"title": "Story with no fandoms key"}]
        results = normalize_stories_collection(stories, keywords=KEYWORDS)
        assert results[0][1].status == "review"
        assert results[0][1].reason == "blank fandoms field"

    def test_empty_list(self):
        assert normalize_stories_collection([], keywords=KEYWORDS) == []

    def test_order_preserved(self):
        stories = [{"fandoms": f"Fandom {i}", "id": i} for i in range(5)]
        results = normalize_stories_collection(stories, keywords=KEYWORDS)
        for i, (story, _) in enumerate(results):
            assert story["id"] == i
