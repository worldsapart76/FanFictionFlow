"""
Tests for normalize/ship.py — Milestone 3.

All tests are pure unit tests using mocked or inline data; no real Calibre
library is required.
"""

import pytest
from orchestrator.normalize.ship import normalize_ship, normalize_stories, ShipResult


# ---------------------------------------------------------------------------
# Rule 1 — Alias suffix stripping
# ---------------------------------------------------------------------------

class TestRule1AliasSuffixStripping:
    def test_single_segment_alias_stripped(self):
        result = normalize_ship("Lee Minho | Lee Know")
        assert result.cleaned == "Lee Minho"

    def test_both_segments_stripped(self):
        result = normalize_ship("Lee Minho | Lee Know/Han Jisung | Han")
        assert result.cleaned == "Lee Minho/Han Jisung"

    def test_trailing_alias_stripped(self):
        result = normalize_ship("Yang Jeongin | I.N/Lee Felix")
        assert result.cleaned == "Yang Jeongin/Lee Felix"

    def test_no_alias_suffix_unchanged(self):
        result = normalize_ship("Draco Malfoy/Hermione Granger")
        assert result.cleaned == "Draco Malfoy/Hermione Granger"

    def test_raw_preserved_unchanged(self):
        raw = "Lee Minho | Lee Know/Han Jisung | Han"
        result = normalize_ship(raw)
        assert result.raw == raw


# ---------------------------------------------------------------------------
# Rule 2 — Fandom disambiguation stripping
# ---------------------------------------------------------------------------

class TestRule2FandomDisambiguation:
    def test_single_segment_fandom_stripped(self):
        result = normalize_ship("Lee Felix (Stray Kids)")
        assert result.cleaned == "Lee Felix"

    def test_both_segments_fandom_stripped(self):
        result = normalize_ship("Lee Felix (Stray Kids)/Yang Jeongin (Stray Kids)")
        assert result.cleaned == "Lee Felix/Yang Jeongin"

    def test_no_fandom_tag_unchanged(self):
        result = normalize_ship("Bang Chan/Lee Minho")
        assert result.cleaned == "Bang Chan/Lee Minho"

    def test_non_trailing_parens_not_stripped(self):
        # Parens in the middle of a name should not be removed
        result = normalize_ship('James "Bucky" Barnes/Clint Barton')
        assert result.cleaned == 'James "Bucky" Barnes/Clint Barton'


# ---------------------------------------------------------------------------
# Rules 1 + 2 combined
# ---------------------------------------------------------------------------

class TestRules1And2Combined:
    def test_alias_then_fandom_both_stripped(self):
        # "Yang Jeongin | I.N/Lee Felix (Stray Kids)" → "Yang Jeongin/Lee Felix"
        result = normalize_ship("Yang Jeongin | I.N/Lee Felix (Stray Kids)")
        assert result.cleaned == "Yang Jeongin/Lee Felix"

    def test_fixture_row_4(self):
        # Exact row from marked_for_later.csv fixture
        result = normalize_ship("Yang Jeongin | I.N/Lee Felix (Stray Kids)")
        assert result.cleaned == "Yang Jeongin/Lee Felix"


# ---------------------------------------------------------------------------
# Rule 3 — Poly detection
# ---------------------------------------------------------------------------

class TestRule3PolyDetection:
    def test_three_names_is_poly(self):
        result = normalize_ship("Bang Chan/Lee Minho/Han Jisung")
        assert result.value == "Poly"
        assert result.status == "auto"

    def test_four_names_is_poly(self):
        result = normalize_ship("A/B/C/D")
        assert result.value == "Poly"

    def test_two_distinct_names_not_poly(self):
        result = normalize_ship("Bang Chan/Lee Minho", additional_tags="Angst")
        assert result.value != "Poly"

    def test_everyone_alone_is_poly(self):
        result = normalize_ship("Everyone")
        assert result.value == "Poly"
        assert result.status == "auto"

    def test_everyone_with_other_name_is_poly(self):
        result = normalize_ship("Everyone/Bang Chan")
        assert result.value == "Poly"

    def test_polyamory_tag_is_poly(self):
        result = normalize_ship("Bang Chan/Lee Minho", additional_tags="Polyamory")
        assert result.value == "Poly"

    def test_polyamory_negotiations_tag_is_poly(self):
        result = normalize_ship(
            "Bang Chan/Lee Minho", additional_tags="Polyamory Negotiations"
        )
        assert result.value == "Poly"

    def test_polyamory_in_pipe_separated_tags_is_poly(self):
        result = normalize_ship(
            "Bang Chan/Lee Minho",
            additional_tags="Angst ||| Polyamory ||| Fluff",
        )
        assert result.value == "Poly"

    def test_poly_fires_after_rules_1_and_2(self):
        # 3 distinct names after alias/fandom cleaning → Poly
        result = normalize_ship(
            "Bang Chan (Stray Kids)/Lee Minho | Lee Know/Han Jisung | Han"
        )
        assert result.value == "Poly"
        assert result.cleaned == "Bang Chan/Lee Minho/Han Jisung"

    def test_poly_raw_preserved(self):
        raw = "Bang Chan (Stray Kids)/Lee Minho | Lee Know/Han Jisung | Han"
        result = normalize_ship(raw)
        assert result.raw == raw

    def test_poly_reason_is_none(self):
        result = normalize_ship("A/B/C")
        assert result.reason is None


# ---------------------------------------------------------------------------
# Rule 4 — Calibre library lookup
# ---------------------------------------------------------------------------

class TestRule4CalibreLibraryLookup:
    def test_exact_match_returns_canonical(self):
        result = normalize_ship(
            "Draco/Hermione",
            existing_ships=["Draco/Hermione", "Katniss/Peeta"],
        )
        assert result.value == "Draco/Hermione"
        assert result.status == "auto"

    def test_case_insensitive_match_returns_canonical_casing(self):
        result = normalize_ship(
            "draco/hermione",
            existing_ships=["Draco/Hermione"],
        )
        assert result.value == "Draco/Hermione"  # canonical casing from library

    def test_first_match_used(self):
        result = normalize_ship(
            "A/B",
            existing_ships=["A/B", "a/b"],
        )
        assert result.value == "A/B"

    def test_no_library_match_falls_through_to_rule5(self):
        overrides = {"Katniss Everdeen/Peeta Mellark": "Katniss/Peeta"}
        result = normalize_ship(
            "Katniss Everdeen/Peeta Mellark",
            existing_ships=["Draco/Hermione"],
            overrides=overrides,
        )
        # Rule 4 miss (no match), Rule 5 hit → override applied
        assert result.value == "Katniss/Peeta"
        assert result.status == "auto"

    def test_whitespace_in_existing_ships_normalized(self):
        result = normalize_ship(
            "Draco/Hermione",
            existing_ships=["  Draco/Hermione  "],
        )
        assert result.value == "Draco/Hermione"

    def test_empty_existing_ships_falls_through(self):
        result = normalize_ship("Draco/Hermione", existing_ships=[])
        # No library → check overrides; default overrides don't contain this
        assert result.status in ("auto", "review")

    def test_rule4_takes_priority_over_rule5(self):
        # If library contains an exact (or case-insensitive) match, use it
        # even if an override also exists.
        overrides = {"Katniss Everdeen/Peeta Mellark": "Katniss/Peeta"}
        result = normalize_ship(
            "Katniss Everdeen/Peeta Mellark",
            existing_ships=["Katniss Everdeen/Peeta Mellark"],
            overrides=overrides,
        )
        # Rule 4 found it first → canonical library value returned
        assert result.value == "Katniss Everdeen/Peeta Mellark"


# ---------------------------------------------------------------------------
# Rule 5 — Shortname override table
# ---------------------------------------------------------------------------

class TestRule5ShortnameOverrides:
    def test_katniss_peeta(self):
        overrides = {"Katniss Everdeen/Peeta Mellark": "Katniss/Peeta"}
        result = normalize_ship(
            "Katniss Everdeen/Peeta Mellark",
            existing_ships=[],
            overrides=overrides,
        )
        assert result.value == "Katniss/Peeta"
        assert result.status == "auto"

    def test_darcy_elizabeth(self):
        overrides = {"Elizabeth Bennet/Fitzwilliam Darcy": "Darcy/Elizabeth"}
        result = normalize_ship(
            "Elizabeth Bennet/Fitzwilliam Darcy",
            existing_ships=[],
            overrides=overrides,
        )
        assert result.value == "Darcy/Elizabeth"

    def test_bucky_clint(self):
        overrides = {'James "Bucky" Barnes/Clint Barton': "Bucky/Clint"}
        result = normalize_ship(
            'James "Bucky" Barnes/Clint Barton',
            existing_ships=[],
            overrides=overrides,
        )
        assert result.value == "Bucky/Clint"

    def test_jason_tim(self):
        overrides = {"Jason Todd/Tim Drake": "Tim Drake/Jason Todd"}
        result = normalize_ship(
            "Jason Todd/Tim Drake",
            existing_ships=[],
            overrides=overrides,
        )
        assert result.value == "Tim Drake/Jason Todd"

    def test_regulus_james(self):
        overrides = {"Regulus Black/James Potter": "Regulus/James"}
        result = normalize_ship(
            "Regulus Black/James Potter",
            existing_ships=[],
            overrides=overrides,
        )
        assert result.value == "Regulus/James"

    def test_override_not_applied_when_library_match_found(self):
        # Rule 4 has priority — if library contains the cleaned value, use it
        overrides = {"Regulus Black/James Potter": "Regulus/James"}
        result = normalize_ship(
            "Regulus Black/James Potter",
            existing_ships=["Regulus Black/James Potter"],
            overrides=overrides,
        )
        assert result.value == "Regulus Black/James Potter"

    def test_empty_overrides_dict_falls_to_review(self):
        result = normalize_ship(
            "Unknown Ship/Unknown Character",
            existing_ships=[],
            overrides={},
        )
        assert result.status == "review"

    def test_override_case_sensitive(self):
        # Override lookup is exact/case-sensitive; wrong casing → no match
        overrides = {"Katniss Everdeen/Peeta Mellark": "Katniss/Peeta"}
        result = normalize_ship(
            "katniss everdeen/peeta mellark",
            existing_ships=[],
            overrides=overrides,
        )
        assert result.status == "review"


# ---------------------------------------------------------------------------
# Review queue — flagged cases
# ---------------------------------------------------------------------------

class TestReviewQueueCases:
    def test_blank_string_flagged(self):
        result = normalize_ship("")
        assert result.status == "review"
        assert result.value is None

    def test_whitespace_only_flagged(self):
        result = normalize_ship("   ")
        assert result.status == "review"
        assert result.value is None

    def test_ampersand_friendship_flagged(self):
        result = normalize_ship("Hermione Granger & Ron Weasley")
        assert result.status == "review"
        assert result.value is None

    def test_ampersand_alone_flagged(self):
        result = normalize_ship("A & B")
        assert result.status == "review"

    def test_nonstandard_dash_format_flagged(self):
        result = normalize_ship("hyunibinnie - Relationship")
        assert result.status == "review"
        assert result.value is None

    def test_unresolved_no_library_no_override(self):
        result = normalize_ship(
            "Some New/Unknown Character",
            existing_ships=["Draco/Hermione"],
            overrides={},
        )
        assert result.status == "review"
        assert result.value is None

    def test_review_result_has_reason(self):
        result = normalize_ship("")
        assert result.reason is not None
        assert len(result.reason) > 0

    def test_unresolved_reason_populated(self):
        result = normalize_ship(
            "Some New/Unknown Character",
            existing_ships=[],
            overrides={},
        )
        assert result.reason is not None


# ---------------------------------------------------------------------------
# Fixture data — known rows from marked_for_later.csv
# ---------------------------------------------------------------------------

class TestFixtureData:
    """
    Validates the full pipeline against representative rows from
    tests/fixtures/marked_for_later.csv.
    """

    CALIBRE_SHIPS = ["Draco/Hermione", "Katniss/Peeta", "Regulus/James",
                     "Choi San/Jung Wooyoung", "Kim Hongjoong/Choi Seonghwa"]

    def test_row1_stray_kids_alias_stripping(self):
        # "Lee Minho | Lee Know/Han Jisung | Han" → cleaned "Lee Minho/Han Jisung"
        result = normalize_ship(
            "Lee Minho | Lee Know/Han Jisung | Han",
            existing_ships=self.CALIBRE_SHIPS,
            overrides={},
        )
        assert result.cleaned == "Lee Minho/Han Jisung"
        assert result.status == "review"  # not in our test library subset

    def test_row2_katniss_peeta_via_override(self):
        overrides = {"Katniss Everdeen/Peeta Mellark": "Katniss/Peeta"}
        result = normalize_ship(
            "Katniss Everdeen/Peeta Mellark",
            existing_ships=self.CALIBRE_SHIPS,
            overrides=overrides,
        )
        assert result.value == "Katniss/Peeta"
        assert result.status == "auto"

    def test_row3_regulus_james_via_override(self):
        overrides = {"Regulus Black/James Potter": "Regulus/James"}
        result = normalize_ship(
            "Regulus Black/James Potter",
            existing_ships=self.CALIBRE_SHIPS,
            overrides=overrides,
        )
        assert result.value == "Regulus/James"
        assert result.status == "auto"

    def test_row4_alias_and_fandom_disambiguation(self):
        # "Yang Jeongin | I.N/Lee Felix (Stray Kids)" → "Yang Jeongin/Lee Felix"
        result = normalize_ship(
            "Yang Jeongin | I.N/Lee Felix (Stray Kids)",
            existing_ships=self.CALIBRE_SHIPS,
            overrides={},
        )
        assert result.cleaned == "Yang Jeongin/Lee Felix"
        assert result.status == "review"  # not in our test library subset

    def test_row5_existing_ship_library_match(self):
        result = normalize_ship(
            "Choi San/Jung Wooyoung",
            existing_ships=self.CALIBRE_SHIPS,
        )
        assert result.value == "Choi San/Jung Wooyoung"
        assert result.status == "auto"

    def test_row6_multi_fandom_ship_library_match(self):
        result = normalize_ship(
            "Kim Hongjoong/Choi Seonghwa",
            existing_ships=self.CALIBRE_SHIPS,
        )
        assert result.value == "Kim Hongjoong/Choi Seonghwa"
        assert result.status == "auto"

    def test_row8_poly_alias_and_fandom_combined(self):
        # 3 names after cleaning → Poly; also Polyamory tag confirms it
        result = normalize_ship(
            "Bang Chan (Stray Kids)/Lee Minho | Lee Know/Han Jisung | Han",
            additional_tags="Polyamory ||| Fluff ||| Getting Together",
        )
        assert result.value == "Poly"
        assert result.status == "auto"

    def test_row9_everyone_poly(self):
        result = normalize_ship(
            "Everyone",
            additional_tags="Polyamory Negotiations ||| Fix-It",
        )
        assert result.value == "Poly"
        assert result.status == "auto"

    def test_row10_no_match_goes_to_review(self):
        result = normalize_ship(
            "Original Character/Original Character",
            existing_ships=self.CALIBRE_SHIPS,
            overrides={},
        )
        assert result.status == "review"


# ---------------------------------------------------------------------------
# normalize_stories — batch convenience function
# ---------------------------------------------------------------------------

class TestNormalizeStories:
    def test_returns_one_pair_per_story(self):
        stories = [
            {"relationships": "Draco/Hermione", "additional_tags": ""},
            {"relationships": "", "additional_tags": ""},
        ]
        results = normalize_stories(stories, existing_ships=["Draco/Hermione"])
        assert len(results) == 2

    def test_each_pair_contains_story_and_result(self):
        story = {"relationships": "Draco/Hermione", "additional_tags": ""}
        results = normalize_stories([story], existing_ships=["Draco/Hermione"])
        returned_story, ship_result = results[0]
        assert returned_story is story
        assert isinstance(ship_result, ShipResult)

    def test_auto_resolved_story(self):
        story = {"relationships": "Draco/Hermione", "additional_tags": ""}
        results = normalize_stories([story], existing_ships=["Draco/Hermione"])
        _, result = results[0]
        assert result.status == "auto"
        assert result.value == "Draco/Hermione"

    def test_review_story(self):
        story = {"relationships": "Unknown/Character", "additional_tags": ""}
        results = normalize_stories([story], existing_ships=[], overrides={})
        _, result = results[0]
        assert result.status == "review"

    def test_empty_stories_returns_empty(self):
        assert normalize_stories([]) == []

    def test_missing_relationships_key_treated_as_blank(self):
        story = {"additional_tags": ""}  # no 'relationships' key
        results = normalize_stories([story])
        _, result = results[0]
        assert result.status == "review"

    def test_missing_additional_tags_treated_as_empty(self):
        story = {"relationships": "A/B/C"}  # no 'additional_tags' key
        results = normalize_stories([story])
        _, result = results[0]
        assert result.value == "Poly"

    def test_preserves_order(self):
        ships = ["Draco/Hermione", "Unknown/Character", "A/B/C"]
        stories = [
            {"relationships": s, "additional_tags": ""} for s in ships
        ]
        results = normalize_stories(
            stories,
            existing_ships=["Draco/Hermione"],
            overrides={},
        )
        assert results[0][1].value == "Draco/Hermione"
        assert results[1][1].status == "review"
        assert results[2][1].value == "Poly"
