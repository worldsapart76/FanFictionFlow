"""
repair_readstatus.py — Restore non-Unread #readstatus values from CSV.

Reads FanFicsCatalog03272026_current.csv (source of truth) and writes the
correct #readstatus back to Calibre for every book whose status is NOT
"Unread" (i.e. Favorite, Read, DNF, Priority — 257 books total).

Run from PowerShell on Windows:
    python -B tests\repair_readstatus.py
"""

import csv
import subprocess
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# Configuration — adjust if needed
# ---------------------------------------------------------------------------

CALIBREDB = r"C:\Program Files\Calibre2\calibredb.exe"
LIBRARY_PATH = r"F:\Dropbox\Reading\Ebooks\FanFiction"
CSV_PATH = r"F:\Dropbox\Reading\Ebooks\FanFicsCatalog03272026_current.csv"

# ---------------------------------------------------------------------------

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def load_csv(path: str) -> dict[int, str]:
    """Return {calibre_id: readstatus} for every row in the CSV."""
    mapping: dict[int, str] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                cid = int(row["id"])
                status = row["#readstatus"].strip()
                if status:
                    mapping[cid] = status
            except (KeyError, ValueError):
                continue
    return mapping


def set_custom_individual(ids: list[int], value: str) -> tuple[int, int]:
    """
    Fallback: set #readstatus one book at a time.

    Returns (ok_count, fail_count).
    """
    ok = fail = 0
    for cid in ids:
        cmd = [
            CALIBREDB,
            "set_custom",
            "--library-path", LIBRARY_PATH,
            "readstatus",
            str(cid),
            value,
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                creationflags=_NO_WINDOW,
            )
            if result.returncode == 0:
                ok += 1
            else:
                print(f"    FAIL id={cid}: {result.stderr.strip()}")
                fail += 1
        except Exception as e:
            print(f"    EXCEPTION id={cid}: {e}")
            fail += 1
    return ok, fail


SKIP_STATUSES = {"Unread"}


def main() -> None:
    print(f"Loading CSV: {CSV_PATH}")
    mapping = load_csv(CSV_PATH)
    print(f"  {len(mapping)} books loaded from CSV.")

    # Group by status value, skipping Unread.
    by_status: dict[str, list[int]] = defaultdict(list)
    for cid, status in mapping.items():
        if status not in SKIP_STATUSES:
            by_status[status].append(cid)

    print("\nBooks to restore (non-Unread only):")
    for status, ids in sorted(by_status.items(), key=lambda x: -len(x[1])):
        print(f"  {status!r}: {len(ids)} books")
    total_to_restore = sum(len(ids) for ids in by_status.values())
    print(f"  Total: {total_to_restore} books")

    print("\nRestoring #readstatus values...")
    total_ok = total_fail = 0

    for status, ids in sorted(by_status.items(), key=lambda x: -len(x[1])):
        print(f"\n  [{status}] — {len(ids)} books")
        ok, fail = set_custom_individual(ids, status)
        total_ok += ok
        total_fail += fail
        print(f"    {ok} ok, {fail} failed")

    print(f"\nDone. {total_ok} books updated, {total_fail} failed.")
    if total_fail:
        print("Check output above for failure details.")


if __name__ == "__main__":
    main()
