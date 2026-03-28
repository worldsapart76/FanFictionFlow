"""
normalize/rules.py — Milestone 4: Collection keyword matching.

Derives a Calibre #collection value from the AO3 fandoms field using a
keyword table stored in config.COLLECTION_KEYWORDS.

Algorithm:
    1. Collect all (keyword, collection) pairs whose keyword appears
       case-insensitively in the fandoms string.
    2. Deduplicate to a set of distinct matched collections.
    3. If exactly one distinct collection matched → auto-resolve.
    4. If multiple distinct collections matched → flag for review;
       user should inspect primary ship to pick the correct fandom.
    5. If no keywords matched → flag for review.
"""

from __future__ import annotations

from dataclasses import dataclass

from orchestrator import config


@dataclass
class CollectionResult:
    """Result of normalizing a single AO3 fandoms value."""

    raw: str            # original, unmodified AO3 fandoms field
    value: str | None   # proposed Calibre #collection; None if unresolved
    status: str         # "auto" | "review"
    reason: str | None  # human-readable explanation when status == "review"


def normalize_collection(
    raw_fandoms: str,
    keywords: list[tuple[str, str]] | None = None,
) -> CollectionResult:
    """
    Derive a Calibre #collection from an AO3 fandoms field.

    Args:
        raw_fandoms: The raw value from the Tampermonkey CSV (fandoms field).
        keywords:    Ordered list of (keyword, collection_name) pairs.
                     Defaults to config.COLLECTION_KEYWORDS.

    Returns:
        CollectionResult with status "auto" (collection resolved) or
        "review" (user action required).
    """
    if keywords is None:
        keywords = config.COLLECTION_KEYWORDS

    raw = raw_fandoms.strip() if raw_fandoms else ""

    if not raw:
        return CollectionResult(
            raw="", value=None, status="review", reason="blank fandoms field"
        )

    raw_lower = raw.lower()

    # Collect all matching collections (preserving first-match order, deduped)
    matched: list[str] = []
    seen: set[str] = set()
    for keyword, collection in keywords:
        if keyword.lower() in raw_lower and collection not in seen:
            matched.append(collection)
            seen.add(collection)

    if len(matched) == 0:
        return CollectionResult(
            raw=raw,
            value=None,
            status="review",
            reason="no matching fandom keyword",
        )

    if len(matched) == 1:
        return CollectionResult(
            raw=raw,
            value=matched[0],
            status="auto",
            reason=None,
        )

    # Multiple distinct collections matched — need human tiebreaker
    joined = ", ".join(matched)
    return CollectionResult(
        raw=raw,
        value=None,
        status="review",
        reason=f"multiple fandoms matched: {joined} — check primary ship",
    )


def normalize_stories_collection(
    stories: list[dict],
    keywords: list[tuple[str, str]] | None = None,
) -> list[tuple[dict, CollectionResult]]:
    """
    Apply normalize_collection to every story in a list.

    Args:
        stories:  Story dicts as returned by diff.parse_marked_for_later().
        keywords: Passed through to normalize_collection.

    Returns:
        List of (story_dict, CollectionResult) pairs in original order.
    """
    return [
        (story, normalize_collection(story.get("fandoms", ""), keywords=keywords))
        for story in stories
    ]
