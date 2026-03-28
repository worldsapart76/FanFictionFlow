"""
sync/metadata.py — Milestone 7: Metadata mapping.

Maps confirmed story records (from normalize/review.py get_confirmed_stories())
to Calibre custom field writes via the calibredb CLI wrapper.

Called after:
  - calibredb add (which assigns a Calibre book ID per story)
  - Review queue confirmation (which provides resolved_ship, resolved_collection)

Fields written per book:
  #ao3_work_id   — AO3 work ID (from diff.py)
  #collection    — fandom collection (resolved by normalize/rules.py)
  #primaryship   — primary ship (resolved by normalize/ship.py)
  #wordcount     — word count (from diff.py)
  #readstatus    — new imports default to config.DEFAULT_READ_STATUS
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orchestrator import config
from orchestrator.sync import calibre


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class MetadataResult:
    """Result of writing metadata for one story."""

    calibre_id: int
    story: dict
    fields_written: dict[str, str | int] = field(default_factory=dict)
    error: str | None = field(default=None)

    @property
    def success(self) -> bool:
        return self.error is None


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------


def build_metadata(
    story: dict,
    read_status: str | None = None,
    write_readstatus: bool = True,
) -> dict[str, str | int]:
    """
    Build the Calibre custom field dict for one confirmed story.

    Args:
        story:            Confirmed story dict from get_confirmed_stories().
                          Must contain ao3_work_id, word_count, resolved_ship,
                          resolved_collection.
        read_status:      Override the default read status for this story.
                          Defaults to config.DEFAULT_READ_STATUS.
        write_readstatus: When False, ``#readstatus`` is omitted from the
                          returned dict.  Pass False for books that already
                          existed in Calibre so their existing status is
                          preserved.

    Returns:
        Dict of {field_name: value} ready for calibre.set_metadata_fields().
    """
    fields: dict[str, str | int] = {
        "#ao3_work_id": str(story["ao3_work_id"]),
        "#collection": str(story["resolved_collection"]),
        "#primaryship": str(story["resolved_ship"]),
        "#wordcount": int(story.get("word_count", 0)),
    }
    if write_readstatus:
        if read_status is None:
            read_status = config.DEFAULT_READ_STATUS
        fields["#readstatus"] = str(read_status)
    return fields


# ---------------------------------------------------------------------------
# Single-story write
# ---------------------------------------------------------------------------


def write_metadata(
    calibre_id: int,
    story: dict,
    read_status: str | None = None,
    write_readstatus: bool = True,
) -> MetadataResult:
    """
    Write all custom metadata fields for one newly imported book.

    Args:
        calibre_id:       Calibre book ID assigned by calibredb add.
        story:            Confirmed story dict from get_confirmed_stories().
        read_status:      Override read status. Defaults to config.DEFAULT_READ_STATUS.
        write_readstatus: When False, ``#readstatus`` is not written — use for
                          books that already existed in Calibre so their status
                          is preserved.

    Returns:
        MetadataResult with fields_written populated on success, error set on
        failure. A calibredb error does not raise — it is captured in the result
        so the caller can continue writing other stories and report failures in
        aggregate.
    """
    fields = build_metadata(story, read_status=read_status, write_readstatus=write_readstatus)
    try:
        calibre.set_metadata_fields(calibre_id, fields)
    except Exception as exc:
        return MetadataResult(calibre_id=calibre_id, story=story, error=str(exc))
    return MetadataResult(calibre_id=calibre_id, story=story, fields_written=fields)


# ---------------------------------------------------------------------------
# Batch write
# ---------------------------------------------------------------------------


def write_all_metadata(
    imports: list[tuple[int, dict]],
    read_status: str | None = None,
    fresh_ids: set[int] | None = None,
) -> list[MetadataResult]:
    """
    Write metadata for a list of newly imported books.

    Args:
        imports:     List of (calibre_id, confirmed_story_dict) pairs in the
                     order returned by calibredb add.
        read_status: Default read status for all new imports.
                     Defaults to config.DEFAULT_READ_STATUS.
        fresh_ids:   Set of calibre IDs that were genuinely newly added (not
                     already present in the library).  Only books in this set
                     receive a ``#readstatus`` write.  When None (the default),
                     all books receive it — preserving backwards compatibility.

    Returns:
        List of MetadataResult in the same order as imports.
    """
    return [
        write_metadata(
            calibre_id,
            story,
            read_status=read_status,
            write_readstatus=(fresh_ids is None or calibre_id in fresh_ids),
        )
        for calibre_id, story in imports
    ]


# ---------------------------------------------------------------------------
# Result filters
# ---------------------------------------------------------------------------


def successful_writes(results: list[MetadataResult]) -> list[MetadataResult]:
    """Return only the results where the metadata write succeeded."""
    return [r for r in results if r.success]


def failed_writes(results: list[MetadataResult]) -> list[MetadataResult]:
    """Return only the results where the metadata write failed."""
    return [r for r in results if not r.success]
