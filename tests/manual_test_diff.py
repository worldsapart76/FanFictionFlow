"""
Manual integration test for orchestrator/sync/diff.py.

Run this from the FanFictionFlow project root on WINDOWS:
  python tests\manual_test_diff.py

Do NOT run in WSL — fetch_library() calls calibredb.exe, which is a
Windows binary and cannot be reached from WSL.
"""

import sys
from pathlib import Path

FIXTURE_CSV = Path(__file__).parent / "fixtures" / "ao3_to_read.csv"

print("=" * 60)
print("FanFictionFlow — Milestone 2 Manual Integration Tests")
print("=" * 60)
print()

if sys.platform != "win32":
    print("WARNING: Not running on Windows.")
    print("  fetch_library() will fail — calibredb.exe is a Windows binary.")
    print("  Re-run this script in a Windows Python terminal.")
    print()

# ---------------------------------------------------------------------------
# Test 1: Parse real Tampermonkey CSV
# ---------------------------------------------------------------------------
print("--- Test 1: parse_marked_for_later() on ao3_to_read.csv ---")
try:
    from orchestrator.sync.diff import parse_marked_for_later
    stories = parse_marked_for_later(FIXTURE_CSV)
    print(f"  Rows parsed    : {len(stories)}  (expected 20)")

    first = stories[0]
    print(f"  First work_id  : {first['ao3_work_id']}  (expected 50930248)")
    print(f"  First title    : {first['title']}")
    print(f"  First author   : {first['author']}")
    print(f"  First fandoms  : {first['fandoms']}")
    print(f"  First ship     : {first['relationships']}")
    print(f"  First wordcount: {first['word_count']}  (expected int, not string)")
    print(f"  word_count type: {type(first['word_count']).__name__}  (expected int)")

    last = stories[-1]
    print(f"  Last work_id   : {last['ao3_work_id']}  (expected 43968159)")

    blanks = [s for s in stories if not s["ao3_work_id"]]
    print(f"  Blank work_ids : {len(blanks)}  (expected 0)")

    assert len(stories) == 20, f"Expected 20 rows, got {len(stories)}"
    assert first["ao3_work_id"] == "50930248"
    assert last["ao3_work_id"] == "43968159"
    assert isinstance(first["word_count"], int)
    assert len(blanks) == 0
    print("  PASS")
except Exception as e:
    print(f"  FAIL: {e}")
print()

# ---------------------------------------------------------------------------
# Test 2: extract_existing_ids from live Calibre library
# ---------------------------------------------------------------------------
print("--- Test 2: extract_existing_ids() from live Calibre library ---")
try:
    from orchestrator.sync.calibre import fetch_library
    from orchestrator.sync.diff import extract_existing_ids
    library = fetch_library()
    existing_ids = extract_existing_ids(library)
    print(f"  Library books  : {len(library)}")
    print(f"  With ao3_work_id: {len(existing_ids)}")
    no_ao3 = sum(1 for b in library if str(b.get("#ao3_work_id") or "").strip() == "NO_AO3")
    print(f"  'NO_AO3' entries: {no_ao3}  (non-AO3 books; harmless in set)")
    print(f"  'NO_AO3' in set : {'NO_AO3' in existing_ids}  (expected True — benign, no export row matches it)")

    # NO_AO3 is a valid non-blank sentinel and is correctly included in the set.
    # It will never match a real AO3 work_id (which are always numeric strings),
    # so its presence does not cause false "already imported" results.
    assert "NO_AO3" in existing_ids, "NO_AO3 sentinel should be in set (it is a non-blank value)"
    print("  PASS")
except Exception as e:
    print(f"  FAIL: {e}")
print()

# ---------------------------------------------------------------------------
# Test 3: Full diff — ao3_to_read.csv vs live Calibre library
# ---------------------------------------------------------------------------
print("--- Test 3: get_new_stories() — full diff against live library ---")
try:
    from orchestrator.sync.calibre import fetch_library
    from orchestrator.sync.diff import get_new_stories, extract_existing_ids

    library = fetch_library()
    new_stories = get_new_stories(FIXTURE_CSV, library)
    existing_ids = extract_existing_ids(library)

    in_library = [s for s in stories if s["ao3_work_id"] in existing_ids]
    not_in_library = new_stories

    print(f"  Stories in CSV          : {len(stories)}")
    print(f"  Already in Calibre      : {len(in_library)}")
    print(f"  New (not yet imported)  : {len(not_in_library)}")
    print()

    if in_library:
        print("  Stories already in library (should NOT appear in new list):")
        for s in in_library:
            print(f"    [{s['ao3_work_id']}] {s['title']}")
    else:
        print("  No stories from the CSV are already in Calibre.")
    print()

    if not_in_library:
        print("  New stories to import:")
        for s in not_in_library:
            print(f"    [{s['ao3_work_id']}] {s['title']} — {s['relationships']}")
    else:
        print("  All stories in the CSV are already in Calibre.")
    print()

    # Cross-check: every new story's ID must not be in the library
    leaked = [s for s in not_in_library if s["ao3_work_id"] in existing_ids]
    assert not leaked, f"These should have been filtered: {leaked}"
    # Cross-check: in_library + not_in_library == total
    assert len(in_library) + len(not_in_library) == len(stories)
    print("  PASS")
except Exception as e:
    print(f"  FAIL: {e}")
print()

print("=" * 60)
print("Done.")
