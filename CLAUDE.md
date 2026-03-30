# CLAUDE.md — FanFictionFlow

This file is read at the start of every Claude Code session. Follow these instructions persistently throughout all work on this project.

---

## What This Project Is

A Python desktop orchestrator for Windows that automates a fan fiction library management workflow. It replaces manual spreadsheet work and PowerShell scripts, and connects AO3 (Archive of Our Own) to a Calibre ebook library to a Boox Palma e-reader.

The design principle: **the user clicks a button. Everything else is invisible.**

---

## System Paths

| Resource | Path |
|---|---|
| Calibre library | `F:\Dropbox\Reading\Ebooks\FanFiction` |
| calibredb executable | `C:\Program Files\Calibre2\calibredb.exe` |
| Epub download directory | Configurable by user at runtime |

Always use these paths as defaults in config. Never hardcode them inside logic modules — always read from `config.py`.

---

## Related Repositories

**This repo** (`fanfictionflow`) contains:
- `orchestrator/` — the Python app (primary build target)
- `extensions/tampermonkey/` — AO3 Marked for Later CSV export userscript (keep, may enhance)
- `extensions/read-status-badge/` — AO3 Read Status Badge Chrome extension (keep, may enhance)

**External repo — Calibre Browser Android app:**
https://github.com/worldsapart76/CalibreFanFicBrowser

This Android app consumes the Calibre library CSV export and the epub files. **Any change to CSV column names, field formats, epub naming, or output structure must be cross-referenced against this repo to ensure compatibility.** Do not break its input format without explicitly flagging it.

---

## Architecture Constraints

- **Windows only.** Use `subprocess` for CLI calls, `pathlib.Path` for all file paths.
- **Python only** for the orchestrator. No Node, no Electron.
- **Calibre stays.** Do not design around replacing it. All library reads/writes go through `calibredb` CLI.
- **FanFicFare** handles AO3 epub downloads. Installed as a standalone pip package (`pip install fanficfare`) on the Windows side — not invoked through Calibre's plugin interface. Do not build a custom downloader.
- **FanFicFare rate-limiting.** AO3/Cloudflare will trigger rate-limiting if downloads happen in rapid succession. The primary mitigation is `FANFICFARE_STORY_DELAY` (default: 20s) — a pause after **every individual story**. A secondary `FANFICFARE_BATCH_DELAY` (default: 10s) adds an extra cooldown at each batch boundary on top of the story delay. Both are user-configurable in `config.py`.
- **FanFicFare stalls** after a handful of downloads without any pause. The batch structure (default: 5 stories per batch) combined with the story delay addresses this.
- **Cloudflare 525 errors and all other failures are not retried.** Any failure (Cloudflare error, login block, deleted story, timeout) is returned immediately and goes to the Phase 2 browser opener queue for manual download. `_is_cloudflare_error()` is retained in `ao3.py` for failure categorisation in `browser.py`.
- **AO3 login blocks (403 on login endpoint)** — Cloudflare bot-detection blocks FanFicFare's login POST even with correct credentials. This is confirmed behaviour, not a bug. Detected via `performLogin` or `archiveofourown.org/users/login` in FanFicFare output → `DownloadResult.credentials_error = True`. These go to the Phase 2 browser opener queue. Do not attempt to fix the Cloudflare block inline.
- **Calibre GUI locking.** `calibredb` fails if Calibre GUI is open. Detect this at startup and warn the user before proceeding.
- **GUI framework:** `tkinter` — lightweight, no install friction. Do not use frameworks requiring separate installation steps.

---

## Input Files

| File | Source | Notes |
|---|---|---|
| `marked_for_later.csv` | AO3 Tampermonkey export | ~20 pages max per export; only stories not yet in Calibre matter |
| `palma_readstatus_overrides.csv` | CalibreFanFicBrowser Android app | Optional; selected dynamically via Settings UI; contains Calibre ID + read status for all library books |

CSV columns from Tampermonkey export: `work_id`, `authors`, `relationship_primary`, `words`. Multi-value fields use ` ||| ` as separator. The `NO_AO3` sentinel in `ao3_work_id` is harmless — treated as "already in library."

The Tampermonkey export intentionally covers only recent pages (~20), not the full AO3 history. Stories in Calibre but absent from the export are expected — the diff logic only cares about stories in the export that are not yet in Calibre.

---

## Core Sync Flow

1. **Ingest & Diff** — Parse `marked_for_later.csv`, query Calibre for existing `#ao3_work_id` values, identify new stories only
2. **Download** — Use FanFicFare to download epubs in batches with delays
3. **Import** — `calibredb add` each epub, capture assigned Calibre IDs; `add_book()` returns `(calibre_id, is_fresh)` — `is_fresh=False` for duplicates found via fallback search
4. **Normalize metadata** — Apply ship and collection normalization rules (see below), produce auto-resolved and flagged results
5. **Review & Confirm** — Show review queue UI; user confirms before ANY write to Calibre
6. **Write metadata** — `calibredb set_custom` for `#ao3_work_id`, `#collection`, `#primaryship`, `#wordcount`, `#readstatus`; `#readstatus` is only written for `fresh_calibre_ids` — existing books are skipped to avoid overwriting their statuses
7. **Apply Palma read status overrides** — If `palma_readstatus_path` is configured in settings and the file exists, diff the CSV against current Calibre values and write only mismatches. Rows with status `"Unread"` are skipped (device default, not an explicit user action). Values are normalised before writing: `"DNF"` → all-caps, all others → title case.
8. **Export outputs** — Calibre library CSV for Read Status Badge and Calibre Browser; push epubs + CSV to Boox Palma via ADB

**Nothing writes to Calibre before step 6. The review queue is mandatory, not optional.**

---

## Metadata Normalization Rules

### Primary Ship (`#primaryship`)

Apply rules in order:

**Rule 1 — Strip alias suffixes**
Within each name segment, strip ` | Alias` and everything after it.
- `Lee Minho | Lee Know` → `Lee Minho`
- `Han Jisung | Han` → `Han Jisung`

**Rule 2 — Strip fandom disambiguation suffixes**
Remove parenthetical fandom tags appended to character names.
- `Lee Felix (Stray Kids)` → `Lee Felix`

**Rule 3 — Poly detection (any one signal triggers Poly)**
After Rules 1 & 2:
1. Splitting on `/` yields 3 or more distinct names
2. Any name segment is `Everyone`
3. `additional_tags` field contains `Polyamory` or `Polyamory Negotiations`

If any signal fires → `#primaryship = Poly`. Skip remaining rules.

**Rule 4 — Calibre library lookup**
Check cleaned value against existing `#primaryship` values in Calibre (case-insensitive). If match found, use the canonical Calibre value exactly. This handles the majority of cases.

**Rule 5 — Shortname override table**
Apply known full-name → shortname mappings. This table is stored in config and is user-editable:

| Cleaned AO3 value | Calibre value |
|---|---|
| `Katniss Everdeen/Peeta Mellark` | `Katniss/Peeta` |
| `Elizabeth Bennet/Fitzwilliam Darcy` | `Darcy/Elizabeth` |
| `James "Bucky" Barnes/Clint Barton` | `Bucky/Clint` |
| `Jason Todd/Tim Drake` | `Tim Drake/Jason Todd` |
| `Regulus Black/James Potter` | `Regulus/James` |

> Note: Some ships use fan-preferred shortnames (e.g., Malex) already normalized in the Calibre library. These resolve via Rule 4.

**Unresolved → review queue:**
- Cleaned value not found in Calibre and no shortname override exists
- Blank, malformed, or non-standard tag format (e.g., `hyunibinnie - Relationship`)
- Tag contains `&` rather than `/` (friendship, not romantic)

### Collection (`#collection`)

Derived from the AO3 `fandoms` field via keyword matching. First keyword match wins.

**Keyword table (user-editable in config):**

| Keyword | Collection |
|---|---|
| `Stray Kids` | `Stray Kids` |
| `ATEEZ` | `ATEEZ` |
| `Hunger Games` | `Hunger Games` |
| `Harry Potter` | `Harry Potter` |
| `Batman`, `DCU`, `DC Comics` | `DCU` |
| `Marvel`, `Avengers` | `Marvel` |
| `Pride and Prejudice`, `Jane Austen` | `Jane Austen` |
| `Roswell New Mexico` | `Roswell` |
| `Mass Effect` | `Mass Effect` |
| `Dragon Age` | `Dragon Age` |
| `Shadowhunters`, `Mortal Instruments` | `Shadowhunters` |
| `Star Wars` | `Star Wars` |
| `Teen Wolf` | `Teen Wolf` |
| `Witcher` | `Witcher` |
| `Skyrim`, `Elder Scrolls` | `Skyrim` |

**Multi-fandom tiebreaker:** If multiple keywords match, use the primary ship to determine which fandom the story belongs to.

**No match → review queue.**

### Review Queue UI

Displayed after normalization, before any Calibre writes.

- Table: Story title | Raw AO3 fandom | Proposed collection | Raw AO3 ship | Proposed ship | Status (Auto / Review)
- Auto-resolved rows visible but collapsed
- Flagged rows require user action: edit inline or select from existing Calibre values via dropdown
- "Confirm & Write" button triggers all Calibre updates
- No partial writes — all or nothing per sync run

---

## Boox Palma Transfer

The Palma connects as an MTP portable device ("Palma 2 > Internal shared storage" in Explorer), **not** as a drive letter. Standard `pathlib`/`shutil` file operations cannot reach MTP devices. Transfer uses `adb push` via subprocess instead.

- **USB debugging must be enabled** on the Palma: Settings → Security → Developer options → USB debugging.
- ADB is installed at the Windows system level (`winget install Google.PlatformTools`); `adb` is on PATH.
- ADB config: `BOOX_ADB_CMD`, `BOOX_DEVICE_SERIAL`, `BOOX_DEVICE_PATH` in `config.py`.

**Epub renaming on transfer:** FanFicFare names epubs as `title-ao3_NNNNNN.epub`. The CalibreFanFicBrowser Android app expects `{calibre_id}-{title}.epub` (matching calibredb's save-to-disk format) so it can match epub files to library CSV rows by Calibre ID. `transfer_to_boox()` accepts a `rename_map: dict[Path, str]` parameter for this purpose. Both the full sync path and the standalone "Transfer to Boox" step build and pass this map automatically.

---

## Phase 2 — Browser Opener (Complete)

Two browser-opener dialogs are triggered automatically during sync. Both use `webbrowser.open(new=2)` with `BROWSER_TAB_DELAY` (default 1s) between tabs.

### Failed Downloads Dialog

Shown after FanFicFare downloads complete, **before** the review queue, whenever one or more stories failed to download. Failures are colour-coded by category:

| Category | Colour | Detection |
|---|---|---|
| Login blocked | Red | `performLogin` or `archiveofourown.org/users/login` in FanFicFare output |
| Cloudflare error | Amber | 525/524/503/502/429 in output |
| Download failed | Neutral | Everything else (deleted story, timeout, etc.) |

User choices: **Open N Stories in Browser** (opens all AO3 URLs for manual download) or **Skip**. Either way proceeds to the review queue. Closing the window = Skip.

Implementation: `sync/browser.py` → `categorize_failure()`, `open_failed_in_browser()`. Dialog class: `FailedDownloadsDialog` in `main.py`. Triggered from `_phase1_background()` and the standalone Download step (`_step_download_bg()`).

### AO3 Curation Dialog

Shown after the Palma read status sync completes (full sync and standalone Sync Read Status step), whenever any `#readstatus` values were updated. **Priority is excluded** — it requires no AO3 action. All others (Favorite, Read, DNF) appear grouped:

- **Favorites — Add to bookmarks & mark read** (Favorite status; amber rows)
- **Others — Mark read only** (Read, DNF, etc.)

Empty groups are omitted. Both groups expanded by default. "Open N Stories in Browser" opens Favorites tabs first, then Others. Closing = Skip.

`ReadStatusSyncResult` was extended with `updated_titles`, `updated_ao3_work_ids`, `updated_statuses` (all `dict[int, str]`, populated on every successful write) to provide the data needed for display and URL construction.

Implementation: `sync/browser.py` → `curation_needed()`, `open_curation_in_browser()`. Dialog class: `AO3CurationDialog` in `main.py`. Triggered from `_phase2_background()` and `_step_sync_readstatus_bg()`.

---

## Current State

All milestones 1–11, Palma read status sync, and Phase 2 browser openers are complete and tested. The app has run successfully end-to-end multiple times on real data. Test suite: **471 passing, 2 pre-existing WSL-only failures** in `test_boox_transfer.py` (the `creationflags=0` mismatch — correct on Windows, irrelevant in WSL).

| Module | Purpose |
|---|---|
| `config.py` | All paths and tunable settings |
| `sync/calibre.py` | `calibredb` CLI wrapper; fetch, add, set_custom, remove |
| `sync/diff.py` | Parse Tampermonkey CSV, diff against Calibre ao3_work_ids |
| `sync/ao3.py` | FanFicFare integration; batched download, pre-download detection, cancel support |
| `sync/metadata.py` | Map story records to Calibre field format |
| `sync/readstatus.py` | Palma read status sync; `parse_palma_csv()`, `sync_readstatus_from_palma()`, `_normalize_status()`; result carries `updated_titles/ao3_work_ids/statuses` |
| `sync/browser.py` | Phase 2 browser opener; failure categorization, `open_failed_in_browser()`, `curation_needed()`, `open_curation_in_browser()` |
| `normalize/ship.py` | Ship normalization Rules 1–5 |
| `normalize/rules.py` | Collection keyword matching |
| `normalize/review.py` | Review queue logic |
| `export/library_csv.py` | Timestamped CSV export; `find_latest_csv()` for standalone transfer step; exports `tags` and `comments` columns (required by CalibreFanFicBrowser — do not remove) |
| `export/boox_transfer.py` | ADB push to Palma; rename_map support |
| `credentials.py` | Read/write AO3 credentials to FanFicFare's `personal.ini` |
| `main.py` | tkinter GUI; two-phase sync; Steps tab for individual re-runs; state persistence |

**Known failure mode — silent metadata write:** `write_metadata()` catches all exceptions per-book and returns an error result. `_phase2_background()` previously logged these failures but still showed green "Sync complete" (fixed: now shows amber "Sync complete — metadata errors" when any metadata write fails). Most likely trigger: Calibre GUI opened during the review queue review period, causing a calibredb lock when the user confirmed. Recovery: re-run Import & Review from the Steps tab — `_find_id_from_epub_filename()` now has a title-based fallback to locate already-imported books whose `#ao3_work_id` was never written, so the sync can proceed and write the metadata correctly.

**Runtime files** (all under `C:\Users\world\.fanficflow\`):
- `settings.json` — epub dir path, marked_for_later path, palma_readstatus_path; persisted across restarts
- `sync_state.json` — diff + import state; enables Steps tab to resume across restarts
- `last_run.log` — full sync truncates; individual steps append with timestamp separator
- `library_csv_YYYYMMDD_HHMMSS.csv` — one file per export; old files accumulate

---

## Testing Environment

### Two environments, two purposes

| Test type | Where to run | Command |
|---|---|---|
| Unit tests (mocked) | WSL terminal | `python3.12 -m pytest tests/` |
| Calibre CLI integration | Windows PowerShell | `python -B tests\manual_test_calibre.py` |
| Diff / CSV integration | Windows PowerShell | `python -B tests\manual_test_diff.py` |
| FanFicFare full run | Windows PowerShell | `python -B tests\manual_test_ao3.py` |
| FanFicFare pacing test | Windows PowerShell | `python -B tests\manual_test_ao3_pacing.py` |
| Boox ADB transfer | Windows PowerShell | `python -B tests\manual_test_boox_transfer.py` |
| End-to-end pipeline | Windows PowerShell | `python -B tests\manual_test_e2e.py` |

Unit tests use mocks and never touch real Calibre or AO3 — they run fine in WSL. Manual integration tests call real Windows binaries or make live network requests — **must run in PowerShell on Windows.**

`manual_test_ao3_pacing.py` is the primary pacing validation script — reads the first 20 stories from `marked_for_later.csv` and gives a pass/fail on whether the current delay settings prevent rate-limiting. Run this after any change to delay settings.

---

### WSL unit test command

```bash
python3.12 -m pytest tests/
```

### Windows PowerShell setup (run once per session)

```powershell
cd "\\wsl$\Ubuntu-24.04\home\worldsapart76\FanFictionFlow"
$env:PATH = "C:\Users\world\AppData\Local\Programs\Python\Python312\Scripts;C:\Users\world\AppData\Local\Programs\Python\Python312;" + $env:PATH
$env:PYTHONPATH = "\\wsl$\Ubuntu-24.04\home\worldsapart76\FanFictionFlow"
```

Scripts must be in PATH — pip-installed executables (fanficfare, etc.) live in `Scripts\`, not the Python root.

### Windows Python location

| | Path |
|---|---|
| Python executable | `C:\Users\world\AppData\Local\Programs\Python\Python312\python.exe` |
| pip | `C:\Users\world\AppData\Local\Programs\Python\Python312\Scripts\pip.exe` |

---

### Known environment quirks

- **`python3` does not exist on Windows** — always use `python` in PowerShell instructions.
- **`python -B` for manual tests** — Python caches `.pyc` bytecode aggressively; use `-B` to avoid running stale versions.
- **WSL cannot see Windows processes** — `is_gui_open()` always returns `False` in WSL. Test from PowerShell.
- **Calibre GUI must be closed** before any integration test that calls calibredb. `is_gui_open()` will warn.
- **calibredb custom column naming** — `calibredb list` uses `*fieldname` prefix for custom columns; `calibre.py` normalizes `*` → `#` internally. All other code uses `#`.
- **`calibredb add` is slow** — ~60–90 seconds on a 6,700-book library. This is normal; add an appropriate timeout.
- **`#` in PowerShell strings** — safe inside double-quoted strings; passes through correctly to calibredb.
- **FanFicFare `-d` is debug, not directory** — output directory is passed via `cwd=` in `subprocess.run`.
- **FanFicFare `-o` expects `key=value`** — extra options go via `FANFICFARE_EXTRA_OPTIONS` in config.
- **`CREATE_NO_WINDOW` on all subprocess calls** — all subprocess calls in `calibre.py`, `ao3.py`, and `boox_transfer.py` pass `creationflags=subprocess.CREATE_NO_WINDOW` (Windows only) to prevent console windows from flashing and stealing focus. **Do not remove this flag.**
- **App launcher** — `launch.bat` in the project root launches the GUI via double-click from Windows Explorer. Uses `pythonw.exe` (no console window). Create a Desktop shortcut for convenience.

---

## What Not To Do

- Do not replace Calibre
- Do not build a custom AO3 epub downloader (use FanFicFare)
- Do not write metadata to Calibre before the review queue is confirmed
- Do not change the Calibre library CSV column names, field formats, or epub naming convention without checking compatibility with https://github.com/worldsapart76/CalibreFanFicBrowser
- Do not remove `tags` or `comments` from `EXPORT_COLUMNS` in `library_csv.py` — the CalibreFanFicBrowser Android app depends on both columns being present
- Do not add GUI frameworks beyond tkinter
- Do not support platforms other than Windows
- Do not remove `creationflags=subprocess.CREATE_NO_WINDOW` from any subprocess call
- Do not redesign the FanFicFare download approach — Cloudflare 403 on login is confirmed; login-gated stories go to the Phase 2 browser opener queue
- Do not write `#readstatus` to existing Calibre books during sync — only `fresh_calibre_ids` (genuinely new imports) receive a `#readstatus` write via `write_all_metadata`. Violating this resets the entire library to "Unread".
- Do not sync `"Unread"` from the Palma CSV back to Calibre — the Android app exports all books with "Unread" as the default; syncing it overwrites deliberate statuses. Only non-default statuses (Read, Favorite, DNF, Priority) are synced.
- Do not write raw status strings from user input or CSV to Calibre — always pass through `_normalize_status()` first (`"DNF"` → all-caps, everything else → title case).
- Do not show green "Sync complete" when `failed_meta` is non-empty in `_phase2_background()` — use amber "Sync complete — metadata errors" so the user knows to re-run Import & Review.
