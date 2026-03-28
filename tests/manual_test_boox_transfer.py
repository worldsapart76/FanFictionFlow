"""
Manual integration test for export/boox_transfer.py — Milestone 9.

Run this from the FanFictionFlow project root on WINDOWS with your
Boox Palma connected via USB (USB debugging enabled):

  python -B tests\manual_test_boox_transfer.py

The test pushes two small dummy files to the device via ADB and verifies
the remote paths appear in the result. Both files are removed from the
device afterwards (unless you choose to keep them for visual confirmation).

If the device is not connected or ADB cannot reach it, the test exits
early with a clear message — this is the expected behaviour.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

print("=" * 60)
print("FanFictionFlow — Milestone 9 Manual Integration Test")
print("Boox Palma ADB Transfer")
print("=" * 60)
print()

from orchestrator import config
from orchestrator.export.boox_transfer import (
    BooxNotConnectedError,
    _adb_base,
    transfer_to_boox,
)

adb = _adb_base()

# ---------------------------------------------------------------------------
# Test 1: ADB reachability
# ---------------------------------------------------------------------------
print("--- Test 1: ADB device detection ---")
print(f"  BOOX_ADB_CMD     : {config.BOOX_ADB_CMD}")
print(f"  BOOX_DEVICE_SERIAL: {config.BOOX_DEVICE_SERIAL!r} (empty = any device)")
print(f"  BOOX_DEVICE_PATH : {config.BOOX_DEVICE_PATH}")
print()

try:
    proc = subprocess.run(adb + ["get-state"], capture_output=True, text=True, timeout=10)
    state = proc.stdout.strip()
    print(f"  adb get-state → {state!r}")
    if state != "device":
        print()
        print("  Device not ready.")
        print("  -> Check USB connection and that USB debugging is enabled.")
        if proc.stderr:
            print(f"  -> ADB error: {proc.stderr.strip()}")
        sys.exit(1)
    print("  Device ready.")
except FileNotFoundError:
    print(f"  ERROR: ADB executable not found: {config.BOOX_ADB_CMD!r}")
    print("  -> Install ADB or update BOOX_ADB_CMD in config.py.")
    sys.exit(1)

print()

# ---------------------------------------------------------------------------
# Test 2: Push epub + CSV to device
# ---------------------------------------------------------------------------
print("--- Test 2: Push epub + CSV ---")

with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp)

    dummy_epub = src / "FFF_test_story.epub"
    dummy_epub.write_bytes(b"FanFictionFlow integration test epub - safe to delete")

    dummy_csv = src / "FFF_test_library.csv"
    dummy_csv.write_text("id,title\n1,Test Story\n", encoding="utf-8")

    print(f"  Pushing to device path: {config.BOOX_DEVICE_PATH}")
    print(f"    epub : {dummy_epub.name}")
    print(f"    csv  : {dummy_csv.name}")
    print()

    try:
        result = transfer_to_boox(
            epub_paths=[dummy_epub],
            csv_path=dummy_csv,
        )
    except BooxNotConnectedError as exc:
        print(f"  FAIL — {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"  ERROR: {exc}")
        sys.exit(1)

    if result.failed:
        print(f"  FAIL — {len(result.failed)} file(s) failed:")
        for src_path, msg in result.failed:
            print(f"    {src_path.name}: {msg}")
    else:
        print(f"  PASS — {len(result.copied)} file(s) pushed:")
        for remote in result.copied:
            print(f"    {remote}")

print()

# ---------------------------------------------------------------------------
# Test 3: Overwrite (push same epub with different content)
# ---------------------------------------------------------------------------
print("--- Test 3: Overwrite existing file ---")

with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp)
    overwrite_epub = src / "FFF_test_story.epub"
    overwrite_epub.write_bytes(b"OVERWRITTEN content")

    try:
        result = transfer_to_boox(epub_paths=[overwrite_epub])
        if result.failed:
            print(f"  FAIL — {result.failed[0][1]}")
        else:
            # Verify content on device via adb shell cat
            remote = result.copied[0]
            proc = subprocess.run(
                adb + ["shell", "cat", remote],
                capture_output=True,
                timeout=10,
            )
            if proc.stdout == b"OVERWRITTEN content":
                print("  PASS — overwrite confirmed on device.")
            else:
                print(f"  FAIL — unexpected content: {proc.stdout!r}")
    except Exception as exc:
        print(f"  ERROR: {exc}")

print()

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
print("--- Cleanup ---")
keep = input("  Keep test files on device for visual check? (y/n): ").strip().lower()

if keep != "y":
    removed = []
    for name in ("FFF_test_story.epub", "FFF_test_library.csv"):
        remote = f"{config.BOOX_DEVICE_PATH}/{name}"
        proc = subprocess.run(
            adb + ["shell", "rm", "-f", remote],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            removed.append(name)
        else:
            print(f"  WARNING: could not remove {remote}: {proc.stderr.strip()}")
    if removed:
        print(f"  Removed from device: {', '.join(removed)}")
else:
    print(f"  Files left at {config.BOOX_DEVICE_PATH}/ on device.")

print()
print("=" * 60)
print("Done.")
