"""
Manual integration test — Milestone 11: End-to-end sync pipeline.

Exercises the complete FanFictionFlow pipeline against your real Calibre
library on Windows. No network calls are made; AO3 downloads are stubbed
with a minimal synthetic epub.

Run from the FanFictionFlow project root on WINDOWS:
    python -B tests\\manual_test_e2e.py

Stages
------
  1  Module imports        — verify all orchestrator modules load cleanly
  2  Calibre GUI check     — warn if GUI is open (test proceeds regardless)
  3  Library fetch         — fetch_library() against real Calibre database
  4  Diff                  — parse synthetic CSV, diff against live library
  5  Normalisation         — ship + collection rules against real library data
  6  Review queue          — build_review_queue(), verify structure
  7  Import + metadata     — calibredb add dummy epub, write all 5 fields,
                             read back and verify, then remove test book
  8  Library CSV export    — export_library_csv() to a temp directory
  9  Summary               — pass/fail count

The write test (stage 7) is interactive: you must confirm before anything
is added to Calibre.  On any error the test book is cleaned up automatically.
"""

from __future__ import annotations

import io
import sys
import tempfile
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

print("=" * 62)
print("FanFictionFlow — Milestone 11: End-to-End Integration Test")
print("=" * 62)
print()

if sys.platform != "win32":
    print("WARNING: Not running on Windows.")
    print("  calibredb.exe calls and psutil GUI detection will fail.")
    print("  Re-run this script in a Windows Python terminal.")
    print()

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

_results: list[tuple[str, str, str]] = []   # (stage, status, detail)
_test_calibre_id: int | None = None          # cleaned up in stage 7 teardown


def _record(stage: str, ok: bool | None, detail: str = "") -> bool:
    """Print and record a test result. Returns ok."""
    if ok is None:
        status = "SKIP"
        mark = "-"
    elif ok:
        status = "PASS"
        mark = "v"
    else:
        status = "FAIL"
        mark = "X"
    _results.append((stage, status, detail))
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{mark}] {stage}: {status}{suffix}")
    return bool(ok)


# ---------------------------------------------------------------------------
# Synthetic test data
#
# Two stories designed to exercise both the auto-resolve and flagged paths
# through normalisation:
#
#   story_a: Stray Kids fic with alias-suffixed ship.
#            After stripping aliases, ship becomes "Bang Chan/Lee Minho"
#            (or similar). Will resolve via Rule 4 if that ship is in
#            the library; otherwise lands in the review queue.
#
#   story_b: Unknown fandom.  Collection keyword match will fail → review.
# ---------------------------------------------------------------------------

_SYNTHETIC_STORIES = [
    {
        "ao3_work_id": "FFF_TEST_001",
        "title": "FFF Test Story Alpha",
        "author": "FFF Test Author",
        "fandoms": "Stray Kids (K-pop RPF)",
        "relationships": "Bang Chan (Stray Kids)/Lee Minho | Lee Know",
        "additional_tags": "Fluff",
        "word_count": 12345,
    },
    {
        "ao3_work_id": "FFF_TEST_002",
        "title": "FFF Test Story Beta",
        "author": "FFF Test Author",
        "fandoms": "Fictional Unknown Fandom XYZ",
        "relationships": "Character A/Character B",
        "additional_tags": "",
        "word_count": 5678,
    },
]

# Synthetic marked_for_later CSV (work IDs chosen to not be in the library)
_SYNTHETIC_CSV = (
    "work_id,title,authors,fandoms,relationship_primary,"
    "relationship_additional,additional_tags,words\n"
    "FFF_TEST_001,FFF Test Story Alpha,FFF Test Author,"
    "\"Stray Kids (K-pop RPF)\","
    "\"Bang Chan (Stray Kids)/Lee Minho | Lee Know\",,Fluff,12345\n"
    "FFF_TEST_002,FFF Test Story Beta,FFF Test Author,"
    "Fictional Unknown Fandom XYZ,"
    "Character A/Character B,,,5678\n"
)


def _make_minimal_epub(title: str = "FFF Test Story") -> bytes:
    """
    Return bytes of a minimal but structurally valid EPUB 2.0 file.

    calibredb add is fairly forgiving; this covers the required package
    structure so the import succeeds cleanly.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype must be first and uncompressed
        zf.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/epub+zip",
        )
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            "  <rootfiles>"
            '    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>'
            "  </rootfiles>"
            "</container>",
        )
        zf.writestr(
            "content.opf",
            f'<?xml version="1.0" encoding="utf-8"?>'
            f'<package version="2.0" xmlns="http://www.idpf.org/2007/opf"'
            f' unique-identifier="uid">'
            f"  <metadata xmlns:dc=\"http://purl.org/dc/elements/1.1/\">"
            f"    <dc:title>{title}</dc:title>"
            f"    <dc:creator>FFF Integration Test</dc:creator>"
            f"    <dc:identifier id=\"uid\">fff-test-001</dc:identifier>"
            f"    <dc:language>en</dc:language>"
            f"  </metadata>"
            f'  <manifest>'
            f'    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            f'    <item id="content" href="content.html" media-type="application/xhtml+xml"/>'
            f"  </manifest>"
            f'  <spine toc="ncx"><itemref idref="content"/></spine>'
            f"</package>",
        )
        zf.writestr(
            "toc.ncx",
            '<?xml version="1.0"?>'
            '<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"'
            ' "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">'
            '<ncx version="2005-1" xmlns="http://www.daisy.org/z3986/2005/ncx/">'
            "  <head/><docTitle><text>FFF Test</text></docTitle>"
            "  <navMap><navPoint id=\"n1\" playOrder=\"1\">"
            "    <navLabel><text>Content</text></navLabel>"
            '    <content src="content.html"/>'
            "  </navPoint></navMap>"
            "</ncx>",
        )
        zf.writestr(
            "content.html",
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>"
            "<!DOCTYPE html PUBLIC \"-//W3C//DTD XHTML 1.1//EN\""
            " \"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd\">"
            '<html xmlns="http://www.w3.org/1999/xhtml">'
            "<head><title>FFF Test Story</title></head>"
            "<body><p>FanFictionFlow integration test — safe to delete.</p></body>"
            "</html>",
        )
    return buf.getvalue()


# ===========================================================================
# Stage 1 — Module imports
# ===========================================================================

print("--- Stage 1: Module imports ---")
try:
    from orchestrator import config
    from orchestrator.sync import calibre, diff
    from orchestrator.normalize import ship as ship_module
    from orchestrator.normalize import rules as rules_module
    from orchestrator.normalize import review as review_module
    from orchestrator.sync import metadata as metadata_module
    from orchestrator.export import library_csv
    _record("Module imports", True)
except Exception as exc:
    _record("Module imports", False, str(exc))
    print()
    print("FATAL: Cannot continue without all modules loading.")
    sys.exit(1)
print()

# ===========================================================================
# Stage 2 — Calibre GUI check
# ===========================================================================

print("--- Stage 2: Calibre GUI check ---")
try:
    gui_open = calibre.is_gui_open()
    if gui_open:
        _record("GUI check", None, "Calibre GUI is OPEN — calibredb calls may fail")
        print("         -> Close Calibre before running write tests.")
    else:
        _record("GUI check", True, "Calibre GUI not running")
except Exception as exc:
    _record("GUI check", None, f"Could not check (likely not on Windows): {exc}")
print()

# ===========================================================================
# Stage 3 — Library fetch
# ===========================================================================

print("--- Stage 3: fetch_library() ---")
library: list[dict] = []
try:
    library = calibre.fetch_library()
    n = len(library)
    ao3_ids = {
        b.get("#ao3_work_id", "").strip()
        for b in library
        if b.get("#ao3_work_id", "").strip()
    }
    _record("fetch_library", True, f"{n} books, {len(ao3_ids)} with #ao3_work_id")
    if library:
        sample = library[0]
        print(f"         Sample book  : {sample.get('title', '?')!r}")
        print(f"         Custom fields: "
              f"#ao3_work_id={sample.get('#ao3_work_id')!r}  "
              f"#collection={sample.get('#collection')!r}  "
              f"#primaryship={sample.get('#primaryship')!r}")
except Exception as exc:
    _record("fetch_library", False, str(exc))
    library = []
    print()
    print("FATAL: Cannot run diff/normalisation without a library fetch.")
    sys.exit(1)
print()

# ===========================================================================
# Stage 4 — Diff (synthetic CSV vs real library)
# ===========================================================================

print("--- Stage 4: Diff ---")
new_stories: list[dict] = []
try:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(_SYNTHETIC_CSV)
        csv_path = Path(tmp.name)

    new_stories = diff.get_new_stories(csv_path, library)
    # FFF_TEST_001 / FFF_TEST_002 should not be in the real library
    # (their ao3_work_ids are non-numeric strings starting with "FFF_TEST_")
    expected_new = 2
    ok = len(new_stories) == expected_new
    _record(
        "Diff",
        ok,
        f"Expected {expected_new} new stories, got {len(new_stories)}",
    )
    for s in new_stories:
        print(f"         New: {s['ao3_work_id']} — {s.get('title', '?')!r}")

    csv_path.unlink(missing_ok=True)
except Exception as exc:
    _record("Diff", False, str(exc))
print()

# ===========================================================================
# Stage 5 — Normalisation (ship + collection)
# ===========================================================================

print("--- Stage 5: Normalisation ---")
ship_results = []
collection_results = []
try:
    if not new_stories:
        _record("Ship normalisation", None, "skipped (no new stories from diff)")
        _record("Collection normalisation", None, "skipped")
    else:
        existing_ships = calibre.fetch_existing_ship_values()
        ship_results = ship_module.normalize_stories(
            new_stories, existing_ships=existing_ships
        )
        n_ships = len(ship_results)
        n_auto_ships = sum(1 for _, r in ship_results if r.status == "auto")
        _record(
            "Ship normalisation",
            True,
            f"{n_ships} stories: {n_auto_ships} auto, "
            f"{n_ships - n_auto_ships} flagged",
        )
        for _, r in ship_results:
            flag = "REVIEW" if r.status == "review" else "auto  "
            print(f"         [{flag}] {r.value!r}")

        collection_results = rules_module.normalize_stories_collection(new_stories)
        n_col = len(collection_results)
        n_auto_col = sum(1 for _, r in collection_results if r.status == "auto")
        _record(
            "Collection normalisation",
            True,
            f"{n_col} stories: {n_auto_col} auto, "
            f"{n_col - n_auto_col} flagged",
        )
        for _, r in collection_results:
            flag = "REVIEW" if r.status == "review" else "auto  "
            print(f"         [{flag}] {r.value!r}")
except Exception as exc:
    _record("Ship normalisation", False, str(exc))
    _record("Collection normalisation", False, str(exc))
print()

# ===========================================================================
# Stage 6 — Review queue
# ===========================================================================

print("--- Stage 6: Review queue ---")
queue: list = []
try:
    if not ship_results or not collection_results:
        _record("Review queue", None, "skipped (no normalisation results)")
    else:
        queue = review_module.build_review_queue(ship_results, collection_results)
        n_total = len(queue)
        n_flagged = len(review_module.flagged_rows(queue))
        n_auto = len(review_module.auto_rows(queue))
        ok = n_total == len(new_stories)
        _record(
            "Review queue",
            ok,
            f"{n_total} rows: {n_auto} auto, {n_flagged} flagged",
        )
        # story_b (unknown fandom) should always be flagged for collection
        any_flagged = n_flagged > 0
        _record(
            "Review queue — flagged rows present",
            any_flagged,
            "story_b (unknown fandom) should require review",
        )
except Exception as exc:
    _record("Review queue", False, str(exc))
print()

# ===========================================================================
# Stage 7 — Import + metadata write (interactive)
# ===========================================================================

print("--- Stage 7: Import + metadata write (interactive) ---")
print()
print("  This stage adds a dummy epub to your Calibre library, writes all")
print("  5 metadata fields, verifies the values were written, then removes")
print("  the test book. No permanent changes are made.")
print()

do_write = input("  Proceed with write test? (y/n): ").strip().lower() == "y"
print()

if not do_write:
    _record("Import + metadata", None, "skipped by user")
else:
    try:
        # Build a synthetic confirmed story (as returned by get_confirmed_stories)
        confirmed_story = {
            "ao3_work_id": "FFF_TEST_WRITE",
            "title": "FFF Integration Test — Safe to Delete",
            "author": "FFF Test Author",
            "fandoms": "Stray Kids (K-pop RPF)",
            "relationships": "Bang Chan/Lee Minho",
            "additional_tags": "",
            "word_count": 99999,
            "resolved_ship": "FFF_TEST_SHIP",
            "resolved_collection": "FFF_TEST_COLLECTION",
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            epub_path = Path(tmp_dir) / "fff_test_story.epub"
            epub_path.write_bytes(_make_minimal_epub("FFF Integration Test"))

            # calibredb add (120s timeout — a hang beyond this means the library
            # is locked, most likely by the Calibre GUI)
            print("  Adding test epub to Calibre…")
            try:
                _test_calibre_id, _ = calibre.add_book(epub_path, timeout=120)
            except __import__("subprocess").TimeoutExpired:
                _record(
                    "calibredb add",
                    False,
                    "timed out after 120s — close Calibre GUI and retry",
                )
                raise
            print(f"  Assigned Calibre ID: {_test_calibre_id}")
            _record(
                "calibredb add",
                True,
                f"ID {_test_calibre_id}",
            )

            # Write all 5 metadata fields
            print("  Writing metadata fields…")
            result = metadata_module.write_metadata(_test_calibre_id, confirmed_story)
            if result.success:
                _record(
                    "Metadata write",
                    True,
                    f"fields: {list(result.fields_written.keys())}",
                )
            else:
                _record("Metadata write", False, result.error or "unknown error")
                raise RuntimeError(result.error)

            # Read back and verify all fields
            print("  Verifying metadata via fetch_library…")
            refreshed = calibre.fetch_library()
            test_book = next(
                (b for b in refreshed if b.get("id") == _test_calibre_id), None
            )
            if test_book is None:
                _record("Metadata verify", False, "test book not found in library")
            else:
                expected = {
                    "#ao3_work_id": "FFF_TEST_WRITE",
                    "#collection": "FFF_TEST_COLLECTION",
                    "#primaryship": "FFF_TEST_SHIP",
                    "#wordcount": 99999,
                    "#readstatus": str(config.DEFAULT_READ_STATUS),
                }
                mismatches = []
                for field, exp_val in expected.items():
                    actual_val = test_book.get(field)
                    # calibredb returns integers for numeric columns
                    if str(actual_val) != str(exp_val):
                        mismatches.append(
                            f"{field}: expected {exp_val!r}, got {actual_val!r}"
                        )
                if mismatches:
                    _record(
                        "Metadata verify",
                        False,
                        "; ".join(mismatches),
                    )
                else:
                    _record("Metadata verify", True, "all 5 fields correct")

    except Exception as exc:
        _record("Import + metadata", False, str(exc))
        import traceback
        traceback.print_exc()
    finally:
        # Always clean up the test book
        if _test_calibre_id is not None:
            print(f"  Removing test book (Calibre ID {_test_calibre_id})…")
            try:
                calibre.remove_book(_test_calibre_id)
                _record("Cleanup (remove_book)", True, f"ID {_test_calibre_id} removed")
                _test_calibre_id = None
            except Exception as exc:
                _record(
                    "Cleanup (remove_book)",
                    False,
                    f"MANUAL CLEANUP NEEDED: calibredb remove {_test_calibre_id} — {exc}",
                )
print()

# ===========================================================================
# Stage 8 — Library CSV export
# ===========================================================================

print("--- Stage 8: Library CSV export ---")
try:
    with tempfile.TemporaryDirectory() as tmp_dir:
        csv_out = library_csv.export_library_csv(
            output_path=Path(tmp_dir) / "calibre_library.csv"
        )
        if csv_out.exists():
            size = csv_out.stat().st_size
            # Count rows (excluding header)
            with csv_out.open(encoding="utf-8") as fh:
                row_count = sum(1 for _ in fh) - 1
            _record(
                "Library CSV export",
                True,
                f"{row_count} book rows, {size:,} bytes",
            )
        else:
            _record("Library CSV export", False, "output file not created")
except Exception as exc:
    _record("Library CSV export", False, str(exc))
print()

# ===========================================================================
# Summary
# ===========================================================================

print("=" * 62)
print("Summary")
print("=" * 62)

n_pass = sum(1 for _, s, _ in _results if s == "PASS")
n_fail = sum(1 for _, s, _ in _results if s == "FAIL")
n_skip = sum(1 for _, s, _ in _results if s == "SKIP")

col_w = max(len(name) for name, _, _ in _results)
for name, status, detail in _results:
    mark = "v" if status == "PASS" else ("X" if status == "FAIL" else "-")
    suffix = f"  ({detail})" if detail and status != "PASS" else ""
    print(f"  [{mark}] {name:<{col_w}}  {status}{suffix}")

print()
print(f"  {n_pass} passed  |  {n_fail} failed  |  {n_skip} skipped")
print()
if n_fail == 0:
    print("All tests passed.")
else:
    print(f"{n_fail} test(s) FAILED — see details above.")
    sys.exit(1)
