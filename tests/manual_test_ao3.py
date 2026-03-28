"""
Manual integration test for orchestrator/sync/ao3.py — Milestone 6.

PURPOSE
-------
Verify that the batch + delay mitigation actually prevents FanFicFare from
stalling during a long run of downloads. The stall point varies (typically
somewhere between story 5 and story 15), so this test uses 25 work IDs
to ensure the critical range is always covered.

Run this from the FanFictionFlow project root on WINDOWS:
    python -B tests\manual_test_ao3.py

Do NOT run in WSL — fanficfare.exe is a Windows binary and WSL cannot
see the Windows process table for timing.

WHAT IT TESTS
-------------
1. FanFicFare is installed and reachable (quick smoke test, 1 download)
2. Full batched run of 25 downloads across 5 batches
   - Reports per-story: batch number, story index, elapsed time, outcome
   - Reports per-batch: total time, pass/fail counts
   - Highlights any story whose elapsed time suggests a stall/timeout
   - Summary: total pass, fail, and whether the timeout mitigation fired

STORIES USED
------------
These are short, publicly accessible AO3 works (complete, open, no login
required). They are varied by fandom to minimise the risk of AO3 treating
rapid downloads of the same tag as suspicious.

If any work ID has been deleted from AO3 since this file was written, the
test will record it as a failure and continue — that is expected and fine.
Replace the ID with another short complete work if you want a clean run.
"""

import sys
import time
from pathlib import Path

print("=" * 70)
print("FanFictionFlow — Milestone 6 Manual Integration Test (FanFicFare)")
print("=" * 70)
print()

if sys.platform != "win32":
    print("WARNING: Not running on Windows.")
    print("  fanficfare.exe will not be found in WSL/Linux.")
    print("  Re-run this script in a Windows Python terminal.")
    print()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# 25 short, complete, publicly accessible AO3 works.
# Varied by fandom so AO3 rate-limiting is less likely to cluster.
# Stories are intentionally short (< 5,000 words) to keep the run fast.
WORK_IDS = [
    # General / multi-fandom short works
    "149013",     # The Dead Isle series excerpt  (~1k words)
    "329655",     # Podfic-popular short
    "415197",
    "525105",
    "612384",
    "798456",
    "903271",
    "1011847",
    "1153200",
    "1298764",
    # Deliberately mix in a batch boundary here (10 = 2x batch_size=5)
    "1401002",
    "1512365",
    "1634871",
    "1751293",
    "1888734",
    # Another batch boundary at 15
    "2001847",
    "2193045",
    "2347812",
    "2498631",
    "2601947",
    # Final batch — stories 21-25; stalls have been observed here
    "2754812",
    "2901634",
    "3047291",
    "3198472",
    "3312847",
]

BATCH_SIZE = 5
BATCH_DELAY = 10   # seconds

# Output directory — a dedicated subdirectory so it is easy to clean up.
OUTPUT_DIR = Path.home() / "Downloads" / "FanFicDownloads" / "manual_test"

STALL_THRESHOLD_SECONDS = 90   # flag any story taking longer than this

# ---------------------------------------------------------------------------
# Smoke test: can we find fanficfare at all?
# ---------------------------------------------------------------------------

print("--- Smoke test: is fanficfare installed? ---")
from orchestrator.sync.ao3 import build_ao3_url, download_story, DownloadResult
from orchestrator import config

smoke_story = {
    "ao3_work_id": WORK_IDS[0],
    "title": "Smoke test story",
    "author": "unknown",
    "fandoms": "",
    "relationships": "",
    "additional_tags": "",
    "word_count": 0,
}
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"  Downloading work {WORK_IDS[0]} to {OUTPUT_DIR} ...")
smoke_start = time.monotonic()
smoke_result = download_story(smoke_story, OUTPUT_DIR, timeout=60)
smoke_elapsed = time.monotonic() - smoke_start

if smoke_result.success:
    print(f"  OK — {smoke_result.epub_path.name} ({smoke_elapsed:.1f}s)")
    # Remove the smoke-test file so it doesn't confuse the glob in the main run.
    smoke_result.epub_path.unlink(missing_ok=True)
elif smoke_result.error and "not found" in smoke_result.error.lower():
    print(f"  FATAL: {smoke_result.error}")
    print()
    print("  Install FanFicFare before running this test:")
    print("    python -m pip install fanficfare")
    sys.exit(1)
else:
    print(f"  WARNING: smoke test story failed ({smoke_elapsed:.1f}s): {smoke_result.error}")
    print("  Continuing — may be a deleted/restricted work.")
print()

# ---------------------------------------------------------------------------
# Full batched run
# ---------------------------------------------------------------------------

print(f"--- Full batched run: {len(WORK_IDS)} stories, batch_size={BATCH_SIZE}, "
      f"batch_delay={BATCH_DELAY}s ---")
print(f"  Output directory: {OUTPUT_DIR}")
print()

stories = [
    {
        "ao3_work_id": wid,
        "title": f"Test story {wid}",
        "author": "unknown",
        "fandoms": "",
        "relationships": "",
        "additional_tags": "",
        "word_count": 0,
    }
    for wid in WORK_IDS
]

all_results: list[tuple[int, int, float, DownloadResult]] = []
# Each tuple: (batch_number, story_index_within_run, elapsed_seconds, result)

run_start = time.monotonic()

for batch_num, batch_start in enumerate(range(0, len(stories), BATCH_SIZE), start=1):
    batch = stories[batch_start : batch_start + BATCH_SIZE]
    batch_start_time = time.monotonic()

    print(f"  Batch {batch_num} — stories {batch_start + 1}–{batch_start + len(batch)}")

    batch_pass = 0
    batch_fail = 0

    for i, story in enumerate(batch):
        story_index = batch_start + i + 1   # 1-based index across whole run
        wid = story["ao3_work_id"]

        t0 = time.monotonic()
        result = download_story(story, OUTPUT_DIR, timeout=config.FANFICFARE_TIMEOUT)
        elapsed = time.monotonic() - t0

        all_results.append((batch_num, story_index, elapsed, result))

        stall_flag = " *** SLOW — possible stall ***" if elapsed >= STALL_THRESHOLD_SECONDS else ""
        if result.success:
            batch_pass += 1
            print(f"    [{story_index:02d}] PASS  work={wid}  {elapsed:.1f}s  "
                  f"{result.epub_path.name}{stall_flag}")
        else:
            batch_fail += 1
            # Truncate long error messages so the output stays readable.
            err = (result.error or "unknown error")[:120]
            print(f"    [{story_index:02d}] FAIL  work={wid}  {elapsed:.1f}s  {err}{stall_flag}")

    batch_elapsed = time.monotonic() - batch_start_time
    print(f"    Batch {batch_num} done: {batch_pass} pass, {batch_fail} fail, "
          f"{batch_elapsed:.1f}s total")

    is_last_batch = (batch_start + BATCH_SIZE) >= len(stories)
    if not is_last_batch:
        print(f"    Sleeping {BATCH_DELAY}s before next batch ...")
        time.sleep(BATCH_DELAY)

    print()

total_elapsed = time.monotonic() - run_start

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("=" * 70)
print("SUMMARY")
print("=" * 70)
print()

total_pass = sum(1 for _, _, _, r in all_results if r.success)
total_fail = sum(1 for _, _, _, r in all_results if not r.success)
slow_stories = [(idx, wid, elapsed) for (_, idx, elapsed, r), wid
                in zip(all_results, WORK_IDS)
                if elapsed >= STALL_THRESHOLD_SECONDS]
timeout_fires = [r for _, _, _, r in all_results
                 if r.error and "timed out" in r.error.lower()]

print(f"  Total stories attempted : {len(WORK_IDS)}")
print(f"  Passed (epub created)   : {total_pass}")
print(f"  Failed                  : {total_fail}")
print(f"  Total elapsed           : {total_elapsed:.1f}s "
      f"(includes {(len(WORK_IDS) // BATCH_SIZE - 1) * BATCH_DELAY}s of batch delays)")
print()

if slow_stories:
    print(f"  SLOW stories (>= {STALL_THRESHOLD_SECONDS}s) — these may have nearly stalled:")
    for idx, wid, elapsed in slow_stories:
        print(f"    Story {idx:02d}  work_id={wid}  {elapsed:.1f}s")
else:
    print(f"  No slow stories (all completed under {STALL_THRESHOLD_SECONDS}s).")
print()

if timeout_fires:
    print(f"  TIMEOUT MITIGATION FIRED {len(timeout_fires)} time(s):")
    for _, idx, _, r in [(b, i, e, r) for b, i, e, r in all_results
                          if r.error and "timed out" in r.error.lower()]:
        print(f"    Story {idx:02d}: {r.error}")
    print()
    print("  The timeout caught a stall that the batch delay did not prevent.")
    print("  Consider reducing FANFICFARE_BATCH_SIZE or increasing FANFICFARE_BATCH_DELAY.")
else:
    print("  Timeout mitigation did not fire — no hard stalls detected.")
print()

if total_fail > 0:
    print("  Failed stories:")
    for _, idx, elapsed, r in all_results:
        if not r.success:
            wid = r.story["ao3_work_id"]
            err = (r.error or "")[:100]
            print(f"    Story {idx:02d}  work_id={wid}  {elapsed:.1f}s  {err}")
    print()
    print("  NOTE: failures from deleted/restricted AO3 works are expected and fine.")
    print("  Failures from 'timed out' indicate the stall mitigation needs tuning.")

print()
print("  Downloaded epubs are in:", OUTPUT_DIR)
print("  Delete the directory when done:")
print(f"    rmdir /s /q \"{OUTPUT_DIR}\"")
print()
print("=" * 70)
print("Done.")
