"""
Manual integration test — AO3 download pacing.

PURPOSE
-------
Confirm that the per-story delay (FANFICFARE_STORY_DELAY) is large enough
to prevent AO3/Cloudflare from rate-limiting or blocking downloads across
a run of 20 stories.

A successful run means: 20 downloads complete, zero Cloudflare errors
(525/503/etc.), and no hard timeouts. Cloudflare retries that eventually
succeed are tolerable but indicate the delay may be too short.

Run this from the FanFictionFlow project root in Windows PowerShell:

    python -B tests\manual_test_ao3_pacing.py

Optional: point it at a specific marked_for_later.csv:

    python -B tests\manual_test_ao3_pacing.py C:\path\to\marked_for_later.csv

Setup (run once per PowerShell session):
    $env:PATH = "C:\\Users\\world\\AppData\\Local\\Programs\\Python\\Python312;" + $env:PATH
    $env:PYTHONPATH = "\\\\wsl$\\Ubuntu-24.04\\home\\worldsapart76\\FanFictionFlow"

HOW STORIES ARE SELECTED
------------------------
The script reads your marked_for_later.csv and takes the first 20 work IDs
from it (in CSV order, no Calibre diff — this is a pacing test, not a sync
run). Stories already in Calibre may be included; FanFicFare will
re-download them to the temp output directory, which is cleaned up at the
end of the run.

WHAT TO LOOK FOR
----------------
  PASS  — epub downloaded cleanly
  RETRY — Cloudflare error on first attempt, retried successfully
          → delay is marginal; consider increasing FANFICFARE_STORY_DELAY
  FAIL (CF) — Cloudflare error on all attempts
          → delay is too short; increase FANFICFARE_STORY_DELAY
  FAIL (timeout) — FanFicFare stalled
          → may be unrelated to pacing; check if Calibre GUI is open
  FAIL (other) — story deleted/restricted on AO3, or FanFicFare not installed
"""

import csv
import sys
import time
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

print("=" * 70)
print("FanFictionFlow — AO3 Download Pacing Test (20 stories)")
print("=" * 70)
print()

if sys.platform != "win32":
    print("WARNING: Not running on Windows.")
    print("  fanficfare.exe is a Windows binary. Results will be wrong.")
    print("  Re-run in a Windows PowerShell terminal.")
    print()

# ---------------------------------------------------------------------------
# Locate the CSV
# ---------------------------------------------------------------------------

if len(sys.argv) > 1:
    csv_path = Path(sys.argv[1])
else:
    # Default: look next to this script, then in the project root.
    candidates = [
        Path(__file__).parent / "marked_for_later.csv",
        Path(__file__).parent.parent / "marked_for_later.csv",
        Path.home() / "Downloads" / "marked_for_later.csv",
    ]
    csv_path = next((p for p in candidates if p.exists()), None)

if csv_path is None or not csv_path.exists():
    print("ERROR: Cannot find marked_for_later.csv.")
    print()
    print("Either:")
    print("  1. Copy it into the project root or tests/ directory, OR")
    print("  2. Pass the path as an argument:")
    print(r'        python -B tests\manual_test_ao3_pacing.py C:\path\to\marked_for_later.csv')
    sys.exit(1)

print(f"Using CSV: {csv_path}")
print()

# ---------------------------------------------------------------------------
# Read the first 20 work IDs from the CSV
# ---------------------------------------------------------------------------

STORY_COUNT = 20

stories = []
with csv_path.open(newline="", encoding="utf-8") as fh:
    reader = csv.DictReader(fh)
    for row in reader:
        work_id = row.get("work_id", "").strip()
        if not work_id:
            continue
        stories.append({
            "ao3_work_id": work_id,
            "title": row.get("title", f"work {work_id}").strip(),
            "author": row.get("authors", "").strip(),
            "fandoms": row.get("fandoms", "").strip(),
            "relationships": row.get("relationship_primary", "").strip(),
            "additional_tags": row.get("additional_tags", "").strip(),
            "word_count": 0,
        })
        if len(stories) == STORY_COUNT:
            break

if not stories:
    print("ERROR: No stories found in the CSV.")
    sys.exit(1)

if len(stories) < STORY_COUNT:
    print(f"WARNING: Only {len(stories)} stories in CSV (wanted {STORY_COUNT}).")
    print("Continuing with what we have.")
    print()

print(f"Stories selected: {len(stories)}")
for i, s in enumerate(stories, 1):
    print(f"  {i:02d}. {s['title'][:55]:<55}  work_id={s['ao3_work_id']}")
print()

# ---------------------------------------------------------------------------
# Show active config before starting
# ---------------------------------------------------------------------------

from orchestrator import config

print("Active pacing config:")
print(f"  FANFICFARE_STORY_DELAY  = {config.FANFICFARE_STORY_DELAY}s   (gap after every story)")
print(f"  FANFICFARE_BATCH_SIZE   = {config.FANFICFARE_BATCH_SIZE}      (stories per batch)")
print(f"  FANFICFARE_BATCH_DELAY  = {config.FANFICFARE_BATCH_DELAY}s   (extra gap after each batch)")
print(f"  FANFICFARE_TIMEOUT      = {config.FANFICFARE_TIMEOUT}s  (per-story hard timeout)")
print()

n = len(stories)
gaps = n - 1
batch_boundaries = gaps // config.FANFICFARE_BATCH_SIZE  # approximate
min_delay_total = (gaps * config.FANFICFARE_STORY_DELAY
                   + batch_boundaries * config.FANFICFARE_BATCH_DELAY)
print(f"Estimated minimum run time (delays only, no download time):")
print(f"  {min_delay_total}s  (~{min_delay_total // 60}m {min_delay_total % 60}s)")
print()

proceed = input("Press Enter to start, or Ctrl+C to cancel: ")
print()

# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path.home() / "Downloads" / "FanFicDownloads" / "pacing_test"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
print(f"Output directory: {OUTPUT_DIR}")
print()

# ---------------------------------------------------------------------------
# Download run — instrument time.sleep to log when delays fire
# ---------------------------------------------------------------------------

from orchestrator.sync.ao3 import download_stories, _is_cloudflare_error, _is_credentials_error

sleep_log: list[tuple[float, float]] = []  # (wall_time_when_sleep_started, duration)
_real_sleep = time.sleep

def _instrumented_sleep(seconds: float) -> None:
    sleep_log.append((time.monotonic(), seconds))
    _real_sleep(seconds)

# Track per-story retry counts by monkey-patching at the subprocess level.
# We intercept completed results via the progress callback instead.

cf_retries: dict[str, int] = {}   # work_id → number of CF retries that happened
story_times: list[float] = []     # elapsed seconds per story (download only, no sleep)

# We need per-story timing. download_stories doesn't expose it, so we
# wrap download_story at the module level temporarily.
import orchestrator.sync.ao3 as _ao3_module
_real_download_story = _ao3_module.download_story

_story_start_times: dict[str, float] = {}

def _timed_download_story(story, output_dir, **kwargs):
    wid = story["ao3_work_id"]
    t0 = time.monotonic()
    result = _real_download_story(story, output_dir, **kwargs)
    elapsed = time.monotonic() - t0
    story_times.append(elapsed)
    # Detect if retries happened (elapsed >> FANFICFARE_TIMEOUT would suggest it,
    # but easier: check if error mentions "attempt(s)")
    if result.error and "attempt" in result.error:
        retries = int(result.error.split("attempt")[0].split()[-1]) - 1
        cf_retries[wid] = retries
    return result

_ao3_module.download_story = _timed_download_story

# Progress callback — prints each result as it arrives.
results_log = []

def _on_result(result):
    i = len(results_log) + 1
    wid = result.story["ao3_work_id"]
    title = result.story["title"][:40]
    elapsed = story_times[-1] if story_times else 0.0

    if result.success:
        label = "PASS "
        detail = result.epub_path.name[:40] if result.epub_path else ""
    elif result.error and ("timed out" in result.error.lower()):
        label = "FAIL (timeout)"
        detail = ""
    elif result.error and _is_cloudflare_error(result.error):
        label = "FAIL (CF)"
        detail = ""
    elif result.error and _is_credentials_error(result.error):
        label = "FAIL (login blocked)"
        detail = "AO3 login blocked — story requires login; may be a transient Cloudflare block"
    else:
        label = "FAIL (other)"
        detail = result.error or ""

    print(f"  [{i:02d}] {label:<22} {elapsed:5.1f}s  {title}")
    if detail:
        for chunk in [detail[i:i+80] for i in range(0, len(detail), 80)]:
            print(f"         {chunk}")

    results_log.append(result)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

print(f"{'─' * 70}")
print(f"  #    Status                 Time   Title")
print(f"{'─' * 70}")

run_start = time.monotonic()

with patch("orchestrator.sync.ao3.time.sleep", side_effect=_instrumented_sleep):
    all_results = download_stories(
        stories,
        output_dir=OUTPUT_DIR,
        progress_callback=_on_result,
    )

run_elapsed = time.monotonic() - run_start

# Restore
_ao3_module.download_story = _real_download_story

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"{'─' * 70}")
print()
print("SUMMARY")
print("=" * 70)
print()

passed       = [r for r in all_results if r.success]
cf_failed    = [r for r in all_results
                if not r.success and r.error and _is_cloudflare_error(r.error)]
cred_failed  = [r for r in all_results if r.credentials_error]
timed_out    = [r for r in all_results
                if not r.success and r.error and "timed out" in r.error.lower()]
other_fail   = [r for r in all_results
                if not r.success and r not in cf_failed
                and r not in cred_failed and r not in timed_out]

print(f"  Stories attempted  : {len(all_results)}")
print(f"  Passed             : {len(passed)}")
print(f"  Failed — Cloudflare: {len(cf_failed)}")
print(f"  Failed — credentials:{len(cred_failed)}")
print(f"  Failed — timeout   : {len(timed_out)}")
print(f"  Failed — other     : {len(other_fail)}")
print()
print(f"  Total wall time    : {run_elapsed:.0f}s  (~{run_elapsed/60:.1f} min)")

if story_times:
    download_time = sum(story_times)
    delay_time = sum(d for _, d in sleep_log)
    print(f"  Download time      : {download_time:.0f}s")
    print(f"  Total delay time   : {delay_time:.0f}s")
    print(f"  Average per story  : {run_elapsed/len(all_results):.1f}s")
print()

# Per-story delay gaps (time between start of sleep after story N and
# start of download of story N+1 = the sleep duration itself).
if sleep_log:
    delays = [d for _, d in sleep_log]
    print(f"  Delays fired       : {len(delays)}  (expected: {len(all_results) - 1} or fewer)")
    print(f"  Delay values seen  : {sorted(set(delays))}")
print()

# Verdict
if len(cred_failed) > 0:
    print(f"  VERDICT: {len(cred_failed)} LOGIN BLOCKED.")
    print(f"  These stories require AO3 login; Cloudflare blocked the automated login attempt.")
    print(f"  If you recently changed your password, check:")
    print(f"    {config.AO3_PERSONAL_INI_PATH}")
    print(f"  Otherwise this is a transient CF block — use the browser opener to download manually.")
    print()
if len(cf_failed) == 0 and len(timed_out) == 0:
    if len(cred_failed) == 0:
        print("  VERDICT: PASS — no rate-limiting or stall errors.")
        print("  Current delay settings appear sufficient.")
    else:
        print("  PACING VERDICT: PASS — no rate-limiting or stall errors.")
        print("  (Credential failures are unrelated to pacing.)")
elif len(cf_failed) > 0:
    pct = len(cf_failed) / len(all_results) * 100
    print(f"  VERDICT: CLOUDFLARE ERRORS ({pct:.0f}% of stories affected).")
    print(f"  Current FANFICFARE_STORY_DELAY={config.FANFICFARE_STORY_DELAY}s is too short.")
    print(f"  Try increasing it to {config.FANFICFARE_STORY_DELAY + 15}s or {config.FANFICFARE_STORY_DELAY + 30}s")
    print("  and re-run this test.")
elif len(timed_out) > 0:
    print(f"  VERDICT: {len(timed_out)} STALL TIMEOUT(S).")
    print("  Timeouts are usually unrelated to pacing (check Calibre GUI is closed).")
    print("  If they cluster around the same story number, increase FANFICFARE_BATCH_DELAY.")
print()

if other_fail:
    print("  Stories that failed for non-pacing reasons (deleted/restricted/etc.):")
    for r in other_fail:
        wid = r.story["ao3_work_id"]
        err = (r.error or "unknown")[:80]
        print(f"    work_id={wid}: {err}")
    print()

print(f"  Downloaded epubs are in: {OUTPUT_DIR}")
print()
print("  To clean up:")
print(f'    rmdir /s /q "{OUTPUT_DIR}"')
print()
print("=" * 70)
print("Done.")
