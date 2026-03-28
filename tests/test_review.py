"""
Tests for normalize/review.py — Milestone 5.

All tests are pure unit tests; no Calibre or GUI required.
ShipResult and CollectionResult objects are constructed directly to keep
tests independent of the normalizer implementations.
"""

import pytest
from orchestrator.normalize.ship import ShipResult
from orchestrator.normalize.rules import CollectionResult
from orchestrator.normalize.review import (
    ReviewRow,
    build_review_queue,
    set_ship_override,
    set_collection_override,
    unresolved_rows,
    all_resolved,
    auto_rows,
    flagged_rows,
    get_confirmed_stories,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _auto_ship(value: str = "Chan/Minho") -> ShipResult:
    return ShipResult(raw=value, cleaned=value, value=value, status="auto", reason=None)


def _flagged_ship(raw: str = "Unknown/Ship") -> ShipResult:
    return ShipResult(raw=raw, cleaned=raw, value=None, status="review",
                      reason="no match in Calibre library or override table")


def _auto_col(value: str = "Stray Kids") -> CollectionResult:
    return CollectionResult(raw=value, value=value, status="auto", reason=None)


def _flagged_col(raw: str = "Unknown Fandom") -> CollectionResult:
    return CollectionResult(raw=raw, value=None, status="review",
                            reason="no matching fandom keyword")


def _story(title: str = "Test Story", work_id: str = "12345") -> dict:
    return {
        "ao3_work_id": work_id,
        "title": title,
        "author": "Author",
        "fandoms": "Stray Kids",
        "relationships": "Chan/Minho",
        "additional_tags": "",
        "word_count": "10000",
    }


def _make_queue(
    n_auto: int = 0,
    n_ship_flagged: int = 0,
    n_col_flagged: int = 0,
    n_both_flagged: int = 0,
) -> tuple[list[tuple[dict, ShipResult]], list[tuple[dict, CollectionResult]]]:
    """Build parallel ship/collection result lists for build_review_queue."""
    ship_results: list[tuple[dict, ShipResult]] = []
    coll_results: list[tuple[dict, CollectionResult]] = []

    idx = 0
    for _ in range(n_auto):
        s = _story(f"Auto Story {idx}", str(idx))
        ship_results.append((s, _auto_ship()))
        coll_results.append((s, _auto_col()))
        idx += 1

    for _ in range(n_ship_flagged):
        s = _story(f"Ship-Flagged Story {idx}", str(idx))
        ship_results.append((s, _flagged_ship()))
        coll_results.append((s, _auto_col()))
        idx += 1

    for _ in range(n_col_flagged):
        s = _story(f"Col-Flagged Story {idx}", str(idx))
        ship_results.append((s, _auto_ship()))
        coll_results.append((s, _flagged_col()))
        idx += 1

    for _ in range(n_both_flagged):
        s = _story(f"Both-Flagged Story {idx}", str(idx))
        ship_results.append((s, _flagged_ship()))
        coll_results.append((s, _flagged_col()))
        idx += 1

    return ship_results, coll_results


# ---------------------------------------------------------------------------
# build_review_queue
# ---------------------------------------------------------------------------


class TestBuildReviewQueue:
    def test_empty_input_returns_empty_queue(self):
        assert build_review_queue([], []) == []

    def test_all_auto_rows_pre_populate_resolved_values(self):
        ship, col = _make_queue(n_auto=3)
        queue = build_review_queue(ship, col)
        assert len(queue) == 3
        for row in queue:
            assert row.resolved_ship == "Chan/Minho"
            assert row.resolved_collection == "Stray Kids"

    def test_flagged_ship_leaves_resolved_ship_none(self):
        ship, col = _make_queue(n_ship_flagged=1)
        queue = build_review_queue(ship, col)
        assert queue[0].resolved_ship is None
        assert queue[0].resolved_collection == "Stray Kids"

    def test_flagged_collection_leaves_resolved_collection_none(self):
        ship, col = _make_queue(n_col_flagged=1)
        queue = build_review_queue(ship, col)
        assert queue[0].resolved_ship == "Chan/Minho"
        assert queue[0].resolved_collection is None

    def test_both_flagged_leaves_both_none(self):
        ship, col = _make_queue(n_both_flagged=1)
        queue = build_review_queue(ship, col)
        assert queue[0].resolved_ship is None
        assert queue[0].resolved_collection is None

    def test_mixed_queue_correct_length(self):
        ship, col = _make_queue(n_auto=2, n_ship_flagged=1, n_both_flagged=1)
        queue = build_review_queue(ship, col)
        assert len(queue) == 4

    def test_mismatched_lengths_raise(self):
        ship, col = _make_queue(n_auto=2)
        with pytest.raises(ValueError, match="length"):
            build_review_queue(ship, col[:1])

    def test_story_dict_preserved_on_row(self):
        story = _story("My Fic", "99999")
        ship = [(story, _auto_ship())]
        col = [(story, _auto_col())]
        queue = build_review_queue(ship, col)
        assert queue[0].story["title"] == "My Fic"
        assert queue[0].story["ao3_work_id"] == "99999"

    def test_ship_overridden_defaults_false(self):
        ship, col = _make_queue(n_auto=1)
        queue = build_review_queue(ship, col)
        assert queue[0].ship_overridden is False
        assert queue[0].collection_overridden is False


# ---------------------------------------------------------------------------
# ReviewRow.needs_review
# ---------------------------------------------------------------------------


class TestNeedsReview:
    def test_auto_auto_no_review(self):
        row = ReviewRow(_story(), _auto_ship(), _auto_col())
        assert row.needs_review is False

    def test_flagged_ship_needs_review(self):
        row = ReviewRow(_story(), _flagged_ship(), _auto_col())
        assert row.needs_review is True

    def test_flagged_collection_needs_review(self):
        row = ReviewRow(_story(), _auto_ship(), _flagged_col())
        assert row.needs_review is True

    def test_both_flagged_needs_review(self):
        row = ReviewRow(_story(), _flagged_ship(), _flagged_col())
        assert row.needs_review is True


# ---------------------------------------------------------------------------
# ReviewRow.is_resolved
# ---------------------------------------------------------------------------


class TestIsResolved:
    def test_none_ship_not_resolved(self):
        row = ReviewRow(_story(), _flagged_ship(), _auto_col(),
                        resolved_ship=None, resolved_collection="Stray Kids")
        assert row.is_resolved is False

    def test_none_collection_not_resolved(self):
        row = ReviewRow(_story(), _auto_ship(), _flagged_col(),
                        resolved_ship="Chan/Minho", resolved_collection=None)
        assert row.is_resolved is False

    def test_both_set_resolved(self):
        row = ReviewRow(_story(), _auto_ship(), _auto_col(),
                        resolved_ship="Chan/Minho", resolved_collection="Stray Kids")
        assert row.is_resolved is True

    def test_empty_string_ship_not_resolved(self):
        row = ReviewRow(_story(), _auto_ship(), _auto_col(),
                        resolved_ship="", resolved_collection="Stray Kids")
        assert row.is_resolved is False

    def test_empty_string_collection_not_resolved(self):
        row = ReviewRow(_story(), _auto_ship(), _auto_col(),
                        resolved_ship="Chan/Minho", resolved_collection="")
        assert row.is_resolved is False


# ---------------------------------------------------------------------------
# set_ship_override / set_collection_override
# ---------------------------------------------------------------------------


class TestSetOverrides:
    def test_set_ship_override_on_flagged_row(self):
        ship, col = _make_queue(n_ship_flagged=1)
        queue = build_review_queue(ship, col)
        set_ship_override(queue[0], "Chan/Felix")
        assert queue[0].resolved_ship == "Chan/Felix"
        assert queue[0].ship_overridden is True

    def test_set_collection_override_on_flagged_row(self):
        ship, col = _make_queue(n_col_flagged=1)
        queue = build_review_queue(ship, col)
        set_collection_override(queue[0], "ATEEZ")
        assert queue[0].resolved_collection == "ATEEZ"
        assert queue[0].collection_overridden is True

    def test_set_ship_override_on_auto_row_allowed(self):
        ship, col = _make_queue(n_auto=1)
        queue = build_review_queue(ship, col)
        set_ship_override(queue[0], "Poly")
        assert queue[0].resolved_ship == "Poly"
        assert queue[0].ship_overridden is True

    def test_set_collection_override_on_auto_row_allowed(self):
        ship, col = _make_queue(n_auto=1)
        queue = build_review_queue(ship, col)
        set_collection_override(queue[0], "Marvel")
        assert queue[0].resolved_collection == "Marvel"
        assert queue[0].collection_overridden is True

    def test_blank_ship_override_raises(self):
        ship, col = _make_queue(n_ship_flagged=1)
        queue = build_review_queue(ship, col)
        with pytest.raises(ValueError, match="blank"):
            set_ship_override(queue[0], "")

    def test_whitespace_only_ship_override_raises(self):
        ship, col = _make_queue(n_ship_flagged=1)
        queue = build_review_queue(ship, col)
        with pytest.raises(ValueError, match="blank"):
            set_ship_override(queue[0], "   ")

    def test_blank_collection_override_raises(self):
        ship, col = _make_queue(n_col_flagged=1)
        queue = build_review_queue(ship, col)
        with pytest.raises(ValueError, match="blank"):
            set_collection_override(queue[0], "")

    def test_override_value_is_stripped(self):
        ship, col = _make_queue(n_ship_flagged=1)
        queue = build_review_queue(ship, col)
        set_ship_override(queue[0], "  Chan/Felix  ")
        assert queue[0].resolved_ship == "Chan/Felix"


# ---------------------------------------------------------------------------
# all_resolved / unresolved_rows
# ---------------------------------------------------------------------------


class TestQueueValidation:
    def test_empty_queue_is_all_resolved(self):
        assert all_resolved([]) is True
        assert unresolved_rows([]) == []

    def test_all_auto_queue_is_resolved(self):
        ship, col = _make_queue(n_auto=3)
        queue = build_review_queue(ship, col)
        assert all_resolved(queue) is True
        assert unresolved_rows(queue) == []

    def test_flagged_row_makes_queue_unresolved(self):
        ship, col = _make_queue(n_auto=2, n_ship_flagged=1)
        queue = build_review_queue(ship, col)
        assert all_resolved(queue) is False
        assert len(unresolved_rows(queue)) == 1

    def test_multiple_flagged_rows_counted_correctly(self):
        ship, col = _make_queue(n_both_flagged=3)
        queue = build_review_queue(ship, col)
        assert all_resolved(queue) is False
        assert len(unresolved_rows(queue)) == 3

    def test_resolving_all_flagged_rows_makes_queue_resolved(self):
        ship, col = _make_queue(n_ship_flagged=2)
        queue = build_review_queue(ship, col)
        assert all_resolved(queue) is False
        for row in unresolved_rows(queue):
            set_ship_override(row, "Woosan")
        assert all_resolved(queue) is True

    def test_partial_resolution_still_unresolved(self):
        ship, col = _make_queue(n_ship_flagged=2)
        queue = build_review_queue(ship, col)
        set_ship_override(queue[0], "Woosan")
        assert all_resolved(queue) is False
        assert len(unresolved_rows(queue)) == 1


# ---------------------------------------------------------------------------
# auto_rows / flagged_rows
# ---------------------------------------------------------------------------


class TestAutoAndFlaggedHelpers:
    def test_all_auto(self):
        ship, col = _make_queue(n_auto=3)
        queue = build_review_queue(ship, col)
        assert len(auto_rows(queue)) == 3
        assert len(flagged_rows(queue)) == 0

    def test_all_flagged(self):
        ship, col = _make_queue(n_both_flagged=2)
        queue = build_review_queue(ship, col)
        assert len(auto_rows(queue)) == 0
        assert len(flagged_rows(queue)) == 2

    def test_mixed(self):
        ship, col = _make_queue(n_auto=3, n_ship_flagged=1, n_col_flagged=2)
        queue = build_review_queue(ship, col)
        assert len(auto_rows(queue)) == 3
        assert len(flagged_rows(queue)) == 3


# ---------------------------------------------------------------------------
# get_confirmed_stories
# ---------------------------------------------------------------------------


class TestGetConfirmedStories:
    def test_all_auto_returns_correct_records(self):
        ship, col = _make_queue(n_auto=2)
        queue = build_review_queue(ship, col)
        confirmed = get_confirmed_stories(queue)
        assert len(confirmed) == 2
        for record in confirmed:
            assert record["resolved_ship"] == "Chan/Minho"
            assert record["resolved_collection"] == "Stray Kids"

    def test_returns_copy_does_not_mutate_original(self):
        story = _story("Immutable", "77777")
        ship = [(story, _auto_ship())]
        col = [(story, _auto_col())]
        queue = build_review_queue(ship, col)
        confirmed = get_confirmed_stories(queue)
        confirmed[0]["title"] = "MUTATED"
        assert queue[0].story["title"] == "Immutable"

    def test_unresolved_queue_raises(self):
        ship, col = _make_queue(n_ship_flagged=1)
        queue = build_review_queue(ship, col)
        with pytest.raises(ValueError, match="unresolved"):
            get_confirmed_stories(queue)

    def test_error_message_names_unresolved_title(self):
        story = _story("The Flagged Fic", "11111")
        ship = [(story, _flagged_ship())]
        col = [(story, _auto_col())]
        queue = build_review_queue(ship, col)
        with pytest.raises(ValueError, match="The Flagged Fic"):
            get_confirmed_stories(queue)

    def test_error_message_truncates_at_five(self):
        ship, col = _make_queue(n_both_flagged=7)
        queue = build_review_queue(ship, col)
        with pytest.raises(ValueError, match="and 2 more"):
            get_confirmed_stories(queue)

    def test_resolving_flagged_then_confirming_works(self):
        # _make_queue generates auto rows first (index 0), then ship-flagged (index 1)
        ship, col = _make_queue(n_auto=1, n_ship_flagged=1)
        queue = build_review_queue(ship, col)
        set_ship_override(queue[1], "Hyunlix")
        confirmed = get_confirmed_stories(queue)
        assert confirmed[0]["resolved_ship"] == "Chan/Minho"
        assert confirmed[1]["resolved_ship"] == "Hyunlix"

    def test_override_on_auto_row_reflected_in_confirmed(self):
        ship, col = _make_queue(n_auto=1)
        queue = build_review_queue(ship, col)
        set_ship_override(queue[0], "Poly")
        confirmed = get_confirmed_stories(queue)
        assert confirmed[0]["resolved_ship"] == "Poly"

    def test_original_story_fields_present_in_confirmed(self):
        story = _story("Complete Story", "55555")
        ship = [(story, _auto_ship())]
        col = [(story, _auto_col())]
        queue = build_review_queue(ship, col)
        confirmed = get_confirmed_stories(queue)
        assert confirmed[0]["title"] == "Complete Story"
        assert confirmed[0]["ao3_work_id"] == "55555"
        assert confirmed[0]["author"] == "Author"

    def test_empty_queue_returns_empty_list(self):
        assert get_confirmed_stories([]) == []
