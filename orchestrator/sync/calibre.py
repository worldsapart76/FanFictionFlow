"""
calibredb CLI wrapper.

All reads and writes to the Calibre library go through this module.
No other module should invoke calibredb directly.

Custom column names used by this project:
  #ao3_work_id   — AO3 work ID (text)
  #collection    — fandom collection (text)
  #primaryship   — primary ship (text)
  #wordcount     — word count (int)
  #readstatus    — read status (text)
"""

import json
import re
import subprocess
from pathlib import Path

import psutil

from orchestrator import config


# ---------------------------------------------------------------------------
# GUI detection
# ---------------------------------------------------------------------------

def is_gui_open() -> bool:
    """Return True if the Calibre GUI process is currently running."""
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() == "calibre.exe":
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


# ---------------------------------------------------------------------------
# Library reads
# ---------------------------------------------------------------------------

def fetch_library() -> list[dict]:
    """
    Return all books in the Calibre library as a list of dicts.

    Each dict contains at minimum:
      id, title, authors, #ao3_work_id, #collection, #primaryship,
      #wordcount, #readstatus

    Note: calibredb list returns custom columns with a '*' prefix
    (e.g. '*ao3_work_id'). This function normalizes those keys to '#'
    so the rest of the codebase uses a consistent '#' convention.
    """
    result = _run([
        "list",
        "--library-path", str(config.LIBRARY_PATH),
        "--fields", "id,title,authors,*ao3_work_id,*collection,*primaryship,*wordcount,*readstatus",
        "--for-machine",  # JSON output
    ])
    books = json.loads(result.stdout)
    return [_normalize_keys(book) for book in books]


def _normalize_keys(book: dict) -> dict:
    """Replace calibredb's '*' custom-column prefix with '#'."""
    return {
        (key.replace("*", "#", 1) if key.startswith("*") else key): value
        for key, value in book.items()
    }


def fetch_existing_ship_values() -> list[str]:
    """Return all distinct non-empty #primaryship values in the library."""
    books = fetch_library()
    seen: set[str] = set()
    values: list[str] = []
    for book in books:
        val = (book.get("#primaryship") or "").strip()
        if val and val not in seen:
            seen.add(val)
            values.append(val)
    return sorted(values)


# ---------------------------------------------------------------------------
# Library writes
# ---------------------------------------------------------------------------

def add_book(epub_path: Path) -> int:
    """
    Add an epub to the Calibre library.

    Returns the Calibre book ID assigned to the new entry.
    Raises RuntimeError if the ID cannot be parsed from calibredb output.
    """
    result = _run([
        "add",
        "--library-path", str(config.LIBRARY_PATH),
        str(epub_path),
    ])
    # calibredb add prints: "Added book ids: 1234"
    match = re.search(r"Added book ids:\s*(\d+)", result.stdout)
    if not match:
        raise RuntimeError(
            f"Could not parse Calibre ID from calibredb add output:\n{result.stdout}"
        )
    return int(match.group(1))


def set_custom(calibre_id: int, field: str, value: str | int) -> None:
    """
    Set a custom column value for a single book.

    Args:
        calibre_id: Calibre book ID.
        field:      Column name including the # prefix (e.g. "#ao3_work_id").
        value:      Value to write. Integers are converted to strings.
    """
    _run([
        "set_custom",
        "--library-path", str(config.LIBRARY_PATH),
        field.lstrip("#"),   # calibredb set_custom takes name without #
        str(calibre_id),
        str(value),
    ])


def set_metadata_fields(calibre_id: int, fields: dict[str, str | int]) -> None:
    """
    Convenience wrapper: write multiple custom fields for one book.

    Args:
        calibre_id: Calibre book ID.
        fields:     Dict of {field_name: value} (field names include #).
    """
    for field, value in fields.items():
        set_custom(calibre_id, field, value)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_csv(output_path: Path) -> None:
    """
    Export the full library catalog to a CSV file via calibredb catalog.

    The output format must remain compatible with the CalibreFanFicBrowser
    Android app. Do not change column arguments without cross-referencing
    https://github.com/worldsapart76/CalibreFanFicBrowser.
    """
    _run([
        "catalog",
        "--library-path", str(config.LIBRARY_PATH),
        str(output_path),
    ])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(args: list[str]) -> subprocess.CompletedProcess:
    """
    Run calibredb with the given arguments.

    Raises:
        FileNotFoundError: if the calibredb executable does not exist.
        subprocess.CalledProcessError: if calibredb exits with a non-zero code.
    """
    cmd = [str(config.CALIBREDB_PATH)] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result
