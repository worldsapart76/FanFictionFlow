"""
Manual integration test for orchestrator/sync/calibre.py.

Run this from the FanFictionFlow project root on WINDOWS:
  python manual_test_calibre.py

Do NOT run in WSL — psutil cannot see Windows processes from WSL,
and calibredb.exe is a Windows binary.
"""

import sys

print("=" * 60)
print("FanFictionFlow — Milestone 1 Manual Integration Tests")
print("=" * 60)
print()

# Confirm we're on Windows
if sys.platform != "win32":
    print("WARNING: Not running on Windows.")
    print("  is_gui_open() will always return False in WSL/Linux.")
    print("  calibredb.exe calls will fail.")
    print("  Re-run this script in a Windows Python terminal.")
    print()

# ---------------------------------------------------------------------------
# Test 1 & 2: GUI detection
# ---------------------------------------------------------------------------
print("--- Test 1/2: is_gui_open() ---")
from orchestrator.sync.calibre import is_gui_open

result = is_gui_open()
print(f"  Calibre GUI detected: {result}")
if sys.platform == "win32":
    print("  -> Open Calibre and run again; should be True.")
    print("  -> Close Calibre and run again; should be False.")
else:
    print("  -> Skipped (must run on Windows)")
print()

# ---------------------------------------------------------------------------
# Test 3: fetch_library
# ---------------------------------------------------------------------------
print("--- Test 3: fetch_library() ---")
try:
    from orchestrator.sync.calibre import fetch_library
    books = fetch_library()
    print(f"  Books found: {len(books)}")
    if books:
        first = books[0]
        print(f"  First book ID   : {first.get('id')}")
        print(f"  First book title: {first.get('title')}")
        print(f"  #ao3_work_id    : {first.get('#ao3_work_id')}")
        print(f"  #primaryship    : {first.get('#primaryship')}")
        print(f"  Keys available  : {list(first.keys())}")
except Exception as e:
    print(f"  ERROR: {e}")
print()

# ---------------------------------------------------------------------------
# Test 4: set_custom (write test)
# ---------------------------------------------------------------------------
print("--- Test 4: set_custom() ---")
print("  Enter a Calibre book ID to test writing to (or press Enter to skip):")
book_id_input = input("  Book ID: ").strip()

if book_id_input:
    try:
        from orchestrator.sync.calibre import set_custom, fetch_library
        book_id = int(book_id_input)

        # Read current value first
        books = fetch_library()
        book = next((b for b in books if b.get("id") == book_id), None)
        if not book:
            print(f"  Book ID {book_id} not found in library.")
        else:
            original = book.get("#readstatus", "")
            print(f"  Current #readstatus: '{original}'")
            set_custom(book_id, "#readstatus", "FFF_TEST")
            print("  Wrote 'FFF_TEST' to #readstatus.")
            print("  -> Open Calibre and confirm #readstatus shows 'FFF_TEST'.")
            restore = input("  Restore original value now? (y/n): ").strip().lower()
            if restore == "y":
                set_custom(book_id, "#readstatus", original)
                print(f"  Restored to '{original}'.")
    except Exception as e:
        print(f"  ERROR: {e}")
else:
    print("  Skipped.")
print()

# ---------------------------------------------------------------------------
# Test 5: --for-machine flag
# ---------------------------------------------------------------------------
print("--- Test 5: --for-machine JSON flag ---")
try:
    import subprocess
    from orchestrator import config
    result = subprocess.run(
        [str(config.CALIBREDB_PATH), "list",
         "--library-path", str(config.LIBRARY_PATH),
         "--for-machine", "--limit", "1"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:
        import json
        data = json.loads(result.stdout)
        print(f"  --for-machine supported. Got {len(data)} record(s).")
    else:
        print("  ERROR or flag not supported:")
        print(f"  {result.stderr.strip()}")
        print("  -> If '--for-machine' is unknown, report back.")
except Exception as e:
    print(f"  ERROR: {e}")
print()

print("=" * 60)
print("Done.")
