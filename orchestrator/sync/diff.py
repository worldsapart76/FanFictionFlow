"""
Ingest & Diff — Milestone 2.

Parses the AO3 Marked for Later CSV export produced by the Tampermonkey
userscript and diffs it against the existing Calibre library to identify
stories that have not yet been imported.

Expected CSV columns (produced by the Tampermonkey export):
    work_id, title, authors, fandoms, relationship_primary,
    relationship_additional, additional_tags, words

Multi-value fields (fandoms, relationships, additional_tags, characters, etc.)
use " ||| " as their internal separator in the Tampermonkey export.
"""

import csv
from pathlib import Path

# Required columns in the Tampermonkey export CSV.
_REQUIRED_COLUMNS = {"work_id", "title", "authors", "fandoms",
                     "relationship_primary", "additional_tags", "words"}


def parse_marked_for_later(csv_path: Path) -> list[dict]:
    """
    Parse the AO3 Marked for Later CSV export.

    Returns a list of story dicts with keys:
        ao3_work_id, title, author, fandoms, relationships,
        additional_tags, word_count

    Rows with a blank work_id are silently skipped (malformed export rows).

    Raises:
        FileNotFoundError: if csv_path does not exist.
        ValueError: if required columns are missing from the file.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Marked for Later CSV not found: {csv_path}")

    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)

        # Validate columns on first access.
        if reader.fieldnames is None:
            return []
        actual = {c.strip() for c in reader.fieldnames}
        missing = _REQUIRED_COLUMNS - actual
        if missing:
            raise ValueError(
                f"marked_for_later.csv is missing required columns: {sorted(missing)}"
            )

        stories: list[dict] = []
        for row in reader:
            work_id = row.get("work_id", "").strip()
            if not work_id:
                continue
            stories.append({
                "ao3_work_id": work_id,
                "title": row.get("title", "").strip(),
                "author": row.get("authors", "").strip(),
                "fandoms": row.get("fandoms", "").strip(),
                "relationships": row.get("relationship_primary", "").strip(),
                "additional_tags": row.get("additional_tags", "").strip(),
                "word_count": _parse_word_count(row.get("words", "")),
            })

    return stories


def extract_existing_ids(library: list[dict]) -> set[str]:
    """
    Return the set of ao3_work_id values already present in the Calibre library.

    Accepts the list of book dicts returned by calibre.fetch_library().
    Normalises values to stripped strings; skips blank/None entries.
    """
    ids: set[str] = set()
    for book in library:
        raw = book.get("#ao3_work_id")
        if raw is None:
            continue
        val = str(raw).strip()
        if val:
            ids.add(val)
    return ids


def diff_against_library(stories: list[dict], existing_ids: set[str]) -> list[dict]:
    """
    Return only the stories whose ao3_work_id is not in existing_ids.

    Preserves the original order from the CSV export.
    """
    return [s for s in stories if s["ao3_work_id"] not in existing_ids]


def get_new_stories(csv_path: Path, library: list[dict]) -> list[dict]:
    """
    Convenience function: parse the CSV and return only stories not yet in Calibre.

    Args:
        csv_path: Path to the marked_for_later.csv export.
        library:  Book list from calibre.fetch_library().

    Returns:
        Ordered list of new story dicts ready for download and import.
    """
    stories = parse_marked_for_later(csv_path)
    existing_ids = extract_existing_ids(library)
    return diff_against_library(stories, existing_ids)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_word_count(raw: str) -> int:
    """
    Convert a raw word count string to an int.

    Accepts plain integers ("85000") and comma-formatted values ("85,000").
    Returns 0 for blank or non-numeric values.
    """
    cleaned = raw.strip().replace(",", "")
    try:
        return int(cleaned)
    except ValueError:
        return 0
