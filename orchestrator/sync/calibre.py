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
import sys
from pathlib import Path

import psutil

# Suppress console window flashes on Windows for every calibredb call.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

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

def add_book(epub_path: Path, timeout: int | None = None) -> tuple[int, bool]:
    """
    Add an epub to the Calibre library.

    Returns ``(calibre_id, is_fresh)`` where ``is_fresh`` is ``True`` when
    calibredb added the book as a new entry, and ``False`` when the book was
    already in the library and the existing ID was found via fallback search.

    The ``is_fresh`` flag is used by callers to decide whether to write
    ``#readstatus`` — existing books may already have a status that should
    not be overwritten.

    Raises RuntimeError if the ID cannot be determined.
    Raises subprocess.TimeoutExpired if the operation exceeds timeout seconds
    (most likely cause: Calibre GUI is holding a library lock).
    """
    result = _run([
        "add",
        "--library-path", str(config.LIBRARY_PATH),
        str(epub_path),
    ], timeout=timeout)
    # calibredb add prints: "Added book ids: 1234"
    match = re.search(r"Added book ids:\s*(\d+)", result.stdout)
    if match:
        return int(match.group(1)), True  # genuinely new book

    # Book is likely already in the library (duplicate detected by calibredb).
    # Try to locate the existing Calibre ID by ao3_work_id in the filename.
    existing_id = _find_id_from_epub_filename(epub_path)
    if existing_id is not None:
        return existing_id, False  # found existing book

    raise RuntimeError(
        f"Could not parse Calibre ID from calibredb add output "
        f"(book may already be in library):\n{result.stdout}"
    )


def _find_id_from_epub_filename(epub_path: Path) -> int | None:
    """
    Try to find the Calibre ID of a book matching the given epub by looking
    up its ao3_work_id (extracted from the filename) in the Calibre library.

    Only searches by ``#ao3_work_id`` — not by title — to avoid false matches
    against pre-existing books that happen to share a title.  Works when the
    book was imported in a previous run and ao3_work_id was successfully
    written to Calibre.
    """
    stem = epub_path.stem  # e.g. "Haebang-ao3_43968159"
    m = re.search(r"ao3_(\d+)", stem)
    if m:
        return _search_first_calibre_id(f"#ao3_work_id:{m.group(1)}")
    return None


def _search_first_calibre_id(search_expr: str) -> int | None:
    """Return the first Calibre ID matching the search expression, or None."""
    try:
        result = _run([
            "list",
            "--library-path", str(config.LIBRARY_PATH),
            "--search", search_expr,
            "--fields", "id",
            "--for-machine",
        ])
        books = json.loads(result.stdout)
        if books:
            return int(books[0]["id"])
    except Exception:
        pass
    return None


def remove_book(calibre_id: int, timeout: int | None = None) -> None:
    """
    Remove a book from the Calibre library by ID.

    Used by the end-to-end integration test to clean up test imports.
    """
    _run([
        "remove",
        "--library-path", str(config.LIBRARY_PATH),
        str(calibre_id),
    ], timeout=timeout)


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

def _run(args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    """
    Run calibredb with the given arguments.

    Args:
        args:    calibredb sub-command and flags.
        timeout: Optional timeout in seconds. Raises subprocess.TimeoutExpired
                 if calibredb does not exit within this time. The most common
                 cause of a hang is the Calibre GUI holding a library lock.

    Raises:
        FileNotFoundError: if the calibredb executable does not exist.
        subprocess.CalledProcessError: if calibredb exits with a non-zero code.
        subprocess.TimeoutExpired: if the process exceeds the timeout.
    """
    cmd = [str(config.CALIBREDB_PATH)] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result
