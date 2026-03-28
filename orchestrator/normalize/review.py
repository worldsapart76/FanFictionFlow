"""
normalize/review.py — Milestone 5: Review queue logic.

Combines ship and collection normalization results into a ReviewQueue and
provides the logic the GUI needs to present, validate, and confirm the queue
before any Calibre writes happen.

Responsibilities:
    - Build ReviewRow objects from pre-computed ShipResult / CollectionResult
    - Track user overrides (both for flagged and auto-resolved rows)
    - Validate that every row is resolved before allowing a write
    - Produce the final confirmed story records ready for sync/metadata.py

This module has no GUI code. All display logic lives in main.py.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from orchestrator.normalize.ship import ShipResult
from orchestrator.normalize.rules import CollectionResult


@dataclass
class ReviewRow:
    """One row in the review queue — one story."""

    story: dict                        # original story dict from diff.py
    ship_result: ShipResult            # output of normalize_ship()
    collection_result: CollectionResult  # output of normalize_collection()

    # Resolved values — initialised from the auto result (if auto); else None.
    # The GUI writes user-supplied overrides here for flagged rows.
    resolved_ship: str | None = field(default=None)
    resolved_collection: str | None = field(default=None)

    # Set to True once the user has explicitly touched this row's value,
    # even when the original result was already auto-resolved.
    ship_overridden: bool = field(default=False)
    collection_overridden: bool = field(default=False)

    @property
    def needs_review(self) -> bool:
        """True if either field was flagged for review by the normalizers."""
        return (
            self.ship_result.status == "review"
            or self.collection_result.status == "review"
        )

    @property
    def is_resolved(self) -> bool:
        """
        True when both resolved_ship and resolved_collection are non-empty
        strings.  A row is resolved when:
          - it was auto-resolved by the normalizer (and not later cleared), or
          - the user has supplied override values for every flagged field.
        """
        return bool(self.resolved_ship) and bool(self.resolved_collection)


# ---------------------------------------------------------------------------
# Queue construction
# ---------------------------------------------------------------------------


def build_review_queue(
    ship_results: list[tuple[dict, ShipResult]],
    collection_results: list[tuple[dict, CollectionResult]],
) -> list[ReviewRow]:
    """
    Combine ship and collection normalization results into a ReviewQueue.

    Both input lists must be the same length and correspond to the same
    ordered set of stories (as returned by normalize_stories() and
    normalize_stories_collection() respectively).

    Auto-resolved values are pre-populated into resolved_ship /
    resolved_collection so that rows which need no user action are immediately
    ready for confirmation.

    Args:
        ship_results:       [(story_dict, ShipResult), ...]
        collection_results: [(story_dict, CollectionResult), ...]

    Returns:
        List of ReviewRow in the same order as the input stories.

    Raises:
        ValueError: if the two lists have different lengths.
    """
    if len(ship_results) != len(collection_results):
        raise ValueError(
            f"ship_results length ({len(ship_results)}) does not match "
            f"collection_results length ({len(collection_results)})"
        )

    rows: list[ReviewRow] = []
    for (story, ship_res), (_, coll_res) in zip(ship_results, collection_results):
        row = ReviewRow(
            story=story,
            ship_result=ship_res,
            collection_result=coll_res,
            resolved_ship=ship_res.value if ship_res.status == "auto" else None,
            resolved_collection=coll_res.value if coll_res.status == "auto" else None,
        )
        rows.append(row)

    return rows


# ---------------------------------------------------------------------------
# User override setters
# ---------------------------------------------------------------------------


def set_ship_override(row: ReviewRow, value: str) -> None:
    """
    Apply a user-supplied ship value to a row.

    Works for both flagged ("review") and auto-resolved rows — the user is
    always allowed to change a proposed value.

    Args:
        row:   The ReviewRow to update.
        value: The user's chosen #primaryship value (must be non-empty).

    Raises:
        ValueError: if value is blank.
    """
    value = value.strip()
    if not value:
        raise ValueError("Ship override value must not be blank.")
    row.resolved_ship = value
    row.ship_overridden = True


def set_collection_override(row: ReviewRow, value: str) -> None:
    """
    Apply a user-supplied collection value to a row.

    Args:
        row:   The ReviewRow to update.
        value: The user's chosen #collection value (must be non-empty).

    Raises:
        ValueError: if value is blank.
    """
    value = value.strip()
    if not value:
        raise ValueError("Collection override value must not be blank.")
    row.resolved_collection = value
    row.collection_overridden = True


# ---------------------------------------------------------------------------
# Queue-level helpers
# ---------------------------------------------------------------------------


def unresolved_rows(queue: list[ReviewRow]) -> list[ReviewRow]:
    """Return the subset of rows that still need user action."""
    return [row for row in queue if not row.is_resolved]


def all_resolved(queue: list[ReviewRow]) -> bool:
    """Return True when every row in the queue is resolved."""
    return all(row.is_resolved for row in queue)


def auto_rows(queue: list[ReviewRow]) -> list[ReviewRow]:
    """Return rows that were fully auto-resolved with no flags."""
    return [row for row in queue if not row.needs_review]


def flagged_rows(queue: list[ReviewRow]) -> list[ReviewRow]:
    """Return rows that have at least one flagged field."""
    return [row for row in queue if row.needs_review]


# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------


def get_confirmed_stories(queue: list[ReviewRow]) -> list[dict]:
    """
    Return the final list of story dicts with resolved metadata fields
    merged in, ready for sync/metadata.py to write to Calibre.

    Each returned dict is a shallow copy of the original story dict with two
    extra keys added:
        resolved_ship        — the confirmed #primaryship value
        resolved_collection  — the confirmed #collection value

    Args:
        queue: The fully-resolved ReviewQueue.

    Returns:
        List of augmented story dicts in queue order.

    Raises:
        ValueError: if any row is not yet resolved (i.e. all_resolved() is
                    False).  The error message names the unresolved titles.
    """
    pending = unresolved_rows(queue)
    if pending:
        titles = ", ".join(
            repr(r.story.get("title", "<unknown>")) for r in pending[:5]
        )
        suffix = f" … and {len(pending) - 5} more" if len(pending) > 5 else ""
        raise ValueError(
            f"Cannot confirm: {len(pending)} row(s) still unresolved — "
            f"{titles}{suffix}"
        )

    confirmed: list[dict] = []
    for row in queue:
        record = deepcopy(row.story)
        record["resolved_ship"] = row.resolved_ship
        record["resolved_collection"] = row.resolved_collection
        confirmed.append(record)

    return confirmed
