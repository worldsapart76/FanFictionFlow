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
import datetime
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
                     config.LIBRARY_CSV_PATH (~/.fanficflow/library_csv.csv).

    Returns:
        Resolved absolute path to the written CSV file.

    Raises:
        subprocess.CalledProcessError: if calibredb exits non-zero.
        OSError: if the output file cannot be written.
    """
    if output_path is None:
        csv_dir = config.LIBRARY_CSV_PATH.parent
        csv_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = csv_dir / f"library_csv_{ts}.csv"

    books = calibre.fetch_library()
    _write_csv(books, output_path)
    return output_path.resolve()


def find_latest_csv() -> Path | None:
    """
    Return the most recently exported library CSV, or None if none exists.

    Scans config.LIBRARY_CSV_PATH.parent for library_csv_*.csv files and
    returns the last one when sorted by name (timestamps sort lexicographically).
    """
    csv_dir = config.LIBRARY_CSV_PATH.parent
    candidates = sorted(csv_dir.glob("library_csv_*.csv"))
    return candidates[-1] if candidates else None


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
