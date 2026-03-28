"""
export/library_csv.py — Milestone 8: Calibre library CSV export.

Exports the full Calibre library as a CSV file consumed by:
  - Read Status Badge Chrome extension
  - CalibreFanFicBrowser Android app
    (https://github.com/worldsapart76/CalibreFanFicBrowser)

WARNING: Do not change EXPORT_COLUMNS names or order without cross-referencing
the CalibreFanFicBrowser repo — it parses this file by column name.
"""

from __future__ import annotations

import csv
from pathlib import Path

from orchestrator import config
from orchestrator.sync import calibre


# ---------------------------------------------------------------------------
# Column definition
# ---------------------------------------------------------------------------

# Stable column names written to the CSV.
# Consumers (Read Status Badge, CalibreFanFicBrowser) depend on these names.
# Keys match what calibre.fetch_library() returns after * → # normalisation.
EXPORT_COLUMNS: list[str] = [
    "id",
    "title",
    "authors",
    "#ao3_work_id",
    "#collection",
    "#primaryship",
    "#wordcount",
    "#readstatus",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def export_library_csv(output_path: Path | None = None) -> Path:
    """
    Export the full Calibre library as a UTF-8 CSV file.

    Fetches all books via calibredb and writes them with the stable column
    set defined in EXPORT_COLUMNS. Extra fields returned by calibredb are
    silently ignored; missing fields are written as empty strings.

    Args:
        output_path: Destination file path. Defaults to
                     config.LIBRARY_CSV_FILENAME in the current directory.

    Returns:
        Resolved absolute path to the written CSV file.

    Raises:
        subprocess.CalledProcessError: if calibredb exits non-zero.
        OSError: if the output file cannot be written.
    """
    if output_path is None:
        output_path = Path(config.LIBRARY_CSV_FILENAME)

    books = calibre.fetch_library()
    _write_csv(books, output_path)
    return output_path.resolve()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _write_csv(books: list[dict], output_path: Path) -> None:
    """Write books to output_path as a CSV with the EXPORT_COLUMNS header."""
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for book in books:
            writer.writerow({col: book.get(col, "") for col in EXPORT_COLUMNS})
