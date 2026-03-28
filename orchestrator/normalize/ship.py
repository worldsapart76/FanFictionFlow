"""
normalize/ship.py — Milestone 3: Ship normalization.

Applies the 5-rule normalization pipeline to a raw AO3 relationship_primary
value and returns a ShipResult indicating the proposed Calibre #primaryship
value and whether it was auto-resolved or flagged for review.

Rules (applied in order):
    1. Strip alias suffixes  ("Lee Minho | Lee Know" → "Lee Minho")
    2. Strip fandom disambiguation ("Lee Felix (Stray Kids)" → "Lee Felix")
    3. Poly detection (3+ names, "Everyone", or Polyamory in additional_tags)
    4. Calibre library lookup (case-insensitive match against existing values)
    5. Shortname override table (config.SHIP_SHORTNAME_OVERRIDES)
    Else → review queue
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from orchestrator import config


@dataclass
class ShipResult:
    """Result of normalizing a single AO3 ship value."""

    raw: str            # original, unmodified AO3 input
    cleaned: str        # after Rules 1 & 2; same as raw if rules inapplicable
    value: str | None   # proposed Calibre #primaryship; None if unresolved
    status: str         # "auto" | "review"
    reason: str | None  # human-readable explanation when status == "review"


def normalize_ship(
    raw_ship: str,
    additional_tags: str = "",
    existing_ships: list[str] | None = None,
    overrides: dict[str, str] | None = None,
) -> ShipResult:
    """
    Normalize a raw AO3 relationship_primary value to a Calibre #primaryship.

    Args:
        raw_ship:       The raw value from the Tampermonkey CSV
                        (relationship_primary field).
        additional_tags: The additional_tags field from the same row; used for
                        Poly detection (Rule 3).
        existing_ships: All distinct #primaryship values currently in the
                        Calibre library.  Pass an empty list (or None) to skip
                        Rule 4 (useful in unit tests that don't have library data).
        overrides:      Shortname override table.  Defaults to
                        config.SHIP_SHORTNAME_OVERRIDES.

    Returns:
        ShipResult with status "auto" (value resolved) or "review" (user
        action required).
    """
    if overrides is None:
        overrides = config.SHIP_SHORTNAME_OVERRIDES
    if existing_ships is None:
        existing_ships = []

    raw = raw_ship.strip() if raw_ship else ""

    # --- Pre-flight: structural issues that skip all rules ---

    if not raw:
        return ShipResult(
            raw="", cleaned="", value=None, status="review", reason="blank ship"
        )

    if "&" in raw:
        return ShipResult(
            raw=raw, cleaned=raw, value=None, status="review",
            reason="friendship/non-romantic relationship (contains '&')",
        )

    # Non-standard tag format, e.g. "hyunibinnie - Relationship"
    if re.search(r"\s-\s\w", raw):
        return ShipResult(
            raw=raw, cleaned=raw, value=None, status="review",
            reason="non-standard tag format",
        )

    # --- Rules 1 & 2: clean each name segment ---

    segments_raw = raw.split("/")
    cleaned_segments = [_clean_name(s) for s in segments_raw]
    cleaned_segments = [s for s in cleaned_segments if s]

    if not cleaned_segments:
        return ShipResult(
            raw=raw, cleaned=raw, value=None, status="review",
            reason="malformed ship tag",
        )

    cleaned = "/".join(cleaned_segments)

    # --- Rule 3: Poly detection ---

    if _is_poly(cleaned_segments, additional_tags):
        return ShipResult(
            raw=raw, cleaned=cleaned, value="Poly", status="auto", reason=None
        )

    # --- Rule 4: Calibre library lookup (case-insensitive) ---

    cleaned_lower = cleaned.lower()
    for existing in existing_ships:
        if existing.strip().lower() == cleaned_lower:
            return ShipResult(
                raw=raw, cleaned=cleaned, value=existing.strip(),
                status="auto", reason=None,
            )

    # --- Rule 5: Shortname override table ---

    if cleaned in overrides:
        return ShipResult(
            raw=raw, cleaned=cleaned, value=overrides[cleaned],
            status="auto", reason=None,
        )

    # --- Unresolved → review queue ---

    return ShipResult(
        raw=raw, cleaned=cleaned, value=None, status="review",
        reason="no match in Calibre library or override table",
    )


def normalize_stories(
    stories: list[dict],
    existing_ships: list[str] | None = None,
    overrides: dict[str, str] | None = None,
) -> list[tuple[dict, ShipResult]]:
    """
    Apply normalize_ship to every story in a list.

    Args:
        stories:        Story dicts as returned by diff.parse_marked_for_later().
        existing_ships: Passed through to normalize_ship (Rule 4).
        overrides:      Passed through to normalize_ship (Rule 5).

    Returns:
        List of (story_dict, ShipResult) pairs in original order.
    """
    return [
        (
            story,
            normalize_ship(
                raw_ship=story.get("relationships", ""),
                additional_tags=story.get("additional_tags", ""),
                existing_ships=existing_ships,
                overrides=overrides,
            ),
        )
        for story in stories
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean_name(segment: str) -> str:
    """Apply Rules 1 and 2 to a single name segment."""
    s = segment.strip()
    # Rule 1: strip alias suffix — everything from " | " onwards
    pipe_idx = s.find(" | ")
    if pipe_idx != -1:
        s = s[:pipe_idx].strip()
    # Rule 2: strip trailing fandom disambiguation, e.g. " (Stray Kids)"
    s = re.sub(r"\s*\([^)]+\)\s*$", "", s).strip()
    return s


def _is_poly(cleaned_segments: list[str], additional_tags: str) -> bool:
    """Return True if any Poly signal fires (Rule 3)."""
    # Signal 1: 3 or more distinct names after cleaning
    if len(set(cleaned_segments)) >= 3:
        return True
    # Signal 2: any name segment is "Everyone" (case-insensitive)
    if any(s.lower() == "everyone" for s in cleaned_segments):
        return True
    # Signal 3: additional_tags contains "Polyamory" (covers "Polyamory Negotiations")
    if "polyamory" in additional_tags.lower():
        return True
    return False
