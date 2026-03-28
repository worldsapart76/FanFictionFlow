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
| Boox Palma USB path | Configurable by user at runtime |

Always use these paths as defaults in config. Never hardcode them inside logic modules — always read from `config.py`.

---

## Related Repositories

**This repo** (`fanfictionflow`) contains:
- `orchestrator/` — the Python app (primary build target)
- `extensions/tampermonkey/` — AO3 Marked for Later CSV export userscript (keep, may enhance)
- `extensions/read-status-badge/` — AO3 Read Status Badge Chrome extension (keep, may enhance)

**External repo — Calibre Browser Android app:**
https://github.com/worldsapart76/CalibreFanFicBrowser

This Android app consumes the Calibre library CSV export and the epub files. **Any change to CSV column names, field formats, or output structure must be cross-referenced against this repo to ensure compatibility.** Do not break its input format without explicitly flagging it.

---

## Architecture Constraints

- **Windows only.** Use `subprocess` for CLI calls, `pathlib.Path` for all file paths.
- **Python only** for the orchestrator. No Node, no Electron.
- **Calibre stays.** Do not design around replacing it. All library reads/writes go through `calibredb` CLI.
- **FanFicFare** handles AO3 epub downloads. Installed as a standalone pip package (`pip install fanficfare`) on the Windows side — not invoked through Calibre's plugin interface. Do not build a custom downloader.
- **FanFicFare rate-limiting.** AO3/Cloudflare will trigger rate-limiting if downloads happen in rapid succession. The primary mitigation is `FANFICFARE_STORY_DELAY` (default: 30s) — a pause after **every individual story**. A secondary `FANFICFARE_BATCH_DELAY` (default: 10s) adds an extra cooldown at each batch boundary on top of the story delay. Both are user-configurable in `config.py`.
- **FanFicFare stalls** after a handful of downloads without any pause. The batch structure (default: 5 stories per batch) combined with the story delay addresses this.
- **Cloudflare 525 errors.** AO3 sits behind Cloudflare which can return transient SSL errors (525, 524, 503, 502, 429). These are detected in FanFicFare's output and retried automatically up to `FANFICFARE_RETRY_COUNT` times (default: 3) with `FANFICFARE_RETRY_DELAY` seconds between attempts (default: 60s). Timeouts and non-CF errors are not retried.
- **Calibre GUI locking.** `calibredb` fails if Calibre GUI is open. Detect this at startup and warn the user before proceeding.
- **GUI framework:** `tkinter` or `PySimpleGUI` — lightweight, no install friction. Do not use frameworks requiring separate installation steps that would be unfamiliar to a moderate-technical user.

---

## Input Files

| File | Source | Notes |
|---|---|---|
| `marked_for_later.csv` | AO3 Tampermonkey export | ~20 pages max per export; only stories not yet in Calibre matter |
| `read_status_export.csv` | Calibre Browser Android app | Optional; present only when user has updated read statuses on device |

The Tampermonkey export intentionally covers only recent pages (~20), not the full AO3 history. Stories in Calibre but absent from the export are expected and fine — the diff logic only cares about stories in the export that are not yet in Calibre.

---

## Core Sync Flow

1. **Ingest & Diff** — Parse `marked_for_later.csv`, query Calibre for existing `#ao3_work_id` values, identify new stories only
2. **Download** — Use FanFicFare to download epubs in batches with delays
3. **Import** — `calibredb add` each epub, capture assigned Calibre IDs
4. **Normalize metadata** — Apply ship and collection normalization rules (see below), produce auto-resolved and flagged results
5. **Review & Confirm** — Show review queue UI; user confirms before ANY write to Calibre
6. **Write metadata** — `calibredb set_custom` for `#ao3_work_id`, `#collection`, `#primaryship`, `#wordcount`, `#readstatus`
7. **Apply read status overrides** — If `read_status_export.csv` present, apply after metadata write
8. **Export outputs** — Calibre library CSV for Read Status Badge and Calibre Browser; copy epubs + CSV to Boox Palma USB path

**Nothing writes to Calibre before step 6. The review queue is mandatory, not optional.**

---

## Metadata Normalization Rules

### Primary Ship (`#primaryship`)

Apply rules in order:

**Rule 1 — Strip alias suffixes**
Within each name segment, strip ` | Alias` and everything after it.
- `Lee Minho | Lee Know` → `Lee Minho`
- `Han Jisung | Han` → `Han Jisung`
- `Yang Jeongin | I.N` → `Yang Jeongin`

**Rule 2 — Strip fandom disambiguation suffixes**
Remove parenthetical fandom tags appended to character names.
- `Lee Felix (Stray Kids)` → `Lee Felix`
- `Bang Chan (Stray Kids)` → `Bang Chan`

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

> Note: Some ships use fan-preferred shortnames (e.g., Malex) that have already been normalized directly in the Calibre library. These will resolve via Rule 4 without needing an override entry.

**Unresolved → review queue:**
- Cleaned value not found in Calibre and no shortname override exists
- Blank, malformed, or non-standard tag format (e.g., `hyunibinnie - Relationship`)
- Tag appears to be a friendship/non-romantic relationship (e.g., contains `&` rather than `/`)

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

## Build Order

Build and test in this sequence. Each module should be independently testable before moving to the next.

1. `sync/calibre.py` — `calibredb` CLI wrapper; fetch library, set_custom, add books, detect if GUI is open
2. `sync/diff.py` — parse Tampermonkey CSV, compare against Calibre ao3_work_ids, return new stories list
3. `normalize/ship.py` — ship normalization Rules 1–5 with unit tests against known AO3 → Calibre pairs
4. `normalize/rules.py` — collection keyword matching engine
5. `normalize/review.py` — review queue UI logic, testable against mock data
6. `sync/ao3.py` — FanFicFare integration, batched download with configurable delays
7. `sync/metadata.py` — map story records to Calibre field format
8. `export/library_csv.py` — Calibre export for Read Status Badge and Calibre Browser
9. `export/boox_transfer.py` — USB file copy to Boox Palma
10. `main.py` + `config.py` — GUI shell, path configuration, wire all modules together
11. End-to-end integration test against real Calibre library
12. Phase 2: AO3 browser opener (open story URLs in browser tabs post-sync)

---

## Phase 2 (Do Not Build Yet)

After core sync is stable: add a **browser opener** that collects AO3 URLs for stories needing manual attention and opens them all as browser tabs in one click. Uses `webbrowser.open()` with short delays between tabs. No AO3 authentication required.

**FanFicFare failure queue:** Any story that fails to download during the core sync — regardless of failure type (Cloudflare retries exhausted, login blocked, timeout, deleted/private story, FanFicFare executable error) — should be queued for the browser opener as an AO3 URL for manual download. Implementation: call `failed_downloads(results)` on the `download_stories()` return value, then collect `build_ao3_url(r.story["ao3_work_id"])` for each. Do not retry failed downloads inline during sync — queue them for the browser opener pass.

---

## Pending — Do Before Starting Next Milestone

> **Run `manual_test_boox_transfer.py` and confirm PASS before beginning milestone 10.**
>
> The Boox Palma ADB transfer (milestone 9) has passing unit tests but the manual integration test has not been run yet. The test must succeed end-to-end — device detected, files pushed, overwrite confirmed — before the milestone is considered complete.
>
> ```powershell
> python -B tests\manual_test_boox_transfer.py
> ```
>
> Remove this section once the test passes.

---

## Session Notes

### Completed milestones

| Milestone | Module | Tests | Notes |
|---|---|---|---|
| 1 — Calibre CLI Foundation | `config.py`, `sync/calibre.py` | 22 unit + manual integration | FanFicFare via CLI, tkinter, python3.12 locked in |
| 2 — Ingest & Diff | `sync/diff.py` | 41 unit + manual integration | Real CSV columns: `work_id`, `authors`, `relationship_primary`, `words`; multi-value sep ` \|\|\| `; 6,697 books in library; `NO_AO3` sentinel harmless |
| 3 — Ship Normalization | `normalize/ship.py` | 62 unit (no integration needed) | `ShipResult` dataclass; Rule 4 case-insensitive (canonical casing returned); Rule 5 case-sensitive; `&` / ` - word` / blank flagged for review |
| 4 — Collection Matching | `normalize/rules.py` | 34 unit (no integration needed) | `CollectionResult` dataclass; multi-keyword same-collection auto-resolves; multi-collection conflict → review; batch helper `normalize_stories_collection` |
| 5 — Review Queue Logic | `normalize/review.py` | 44 unit (no integration needed) | `ReviewRow` dataclass; `build_review_queue`, set/get overrides, `all_resolved`, `unresolved_rows`, `auto_rows`, `flagged_rows`, `get_confirmed_stories`; raises on unresolved; deepcopy prevents mutation |
| 6 — FanFicFare Integration | `sync/ao3.py`, `credentials.py` | 91 unit + manual pacing test | Download failures queued for Phase 2 browser opener; see credentials note below |
| 7 — Metadata Mapping | `sync/metadata.py` | 33 unit (no integration needed) | `MetadataResult` dataclass; errors captured per-story (batch continues); `read_status` override param hooks into sync step 7 |
| 8 — Library CSV Export | `export/library_csv.py` | 30 unit (no integration needed) | `EXPORT_COLUMNS` defines stable 8-column output; missing fields → `""`; extra calibredb fields ignored; `export_library_csv()` returns resolved path |
| 9 — Boox Transfer | `export/boox_transfer.py` | 29 unit + manual integration | Palma connects as MTP (no drive letter) — uses ADB push; `BooxNotConnectedError` on `adb get-state` failure; per-file failures in `TransferResult.failed`; `BOOX_ADB_CMD`, `BOOX_DEVICE_SERIAL`, `BOOX_DEVICE_PATH` in config |

### Boox Palma transfer — ADB, not USB mass storage

The Palma connects as an MTP portable device ("Palma 2 > Internal shared storage" in Explorer), **not** as a drive letter. Standard `pathlib`/`shutil` file operations cannot reach MTP devices. Transfer uses `adb push` via subprocess instead.

- **USB debugging must be enabled** on the Palma: Settings → Security → Developer options → USB debugging.
- ADB is installed at the Windows system level (`winget install Google.PlatformTools`); `adb` is on PATH.
- `BOOX_USB_PATH` has been removed from `config.py`. Replaced by:
  - `BOOX_ADB_CMD = "adb"` — executable name (on PATH); update to full path if needed
  - `BOOX_DEVICE_SERIAL = ""` — empty = first connected device; set if multiple ADB devices attached
  - `BOOX_DEVICE_PATH = "/sdcard/Books"` — destination directory on device
- `_check_connected()` runs `adb get-state` and raises `BooxNotConnectedError` if the device isn't in state `"device"` or ADB executable is not found.
- `TransferResult.copied` contains **remote path strings** (e.g. `/sdcard/Books/story.epub`), not local `Path` objects, since the destination is on the Android filesystem.

### Credentials / login block note (relevant to milestone 10 GUI)

- `credentials.py` owns read/write of `personal.ini`. `write_ao3_credentials(username, password)` will be called from the GUI settings dialog (milestone 10).
- **403 on the AO3 login endpoint with correct credentials is a Cloudflare bot-detection block**, not a wrong-password error. Detected via `performLogin` or `archiveofourown.org/users/login` in FanFicFare output → `DownloadResult.credentials_error = True`. The GUI must distinguish this from a genuine bad-password error when surfacing login failures to the user.

---

## Testing Environment

### Two environments, two purposes

| Test type | Where to run | Python command |
|---|---|---|
| Unit tests (mocked) | WSL terminal | `python3.12 -m pytest tests/` |
| Calibre CLI integration | Windows PowerShell | `python -B tests\manual_test_calibre.py` |
| Diff / CSV integration | Windows PowerShell | `python -B tests\manual_test_diff.py` |
| FanFicFare full run | Windows PowerShell | `python -B tests\manual_test_ao3.py` |
| FanFicFare pacing test | Windows PowerShell | `python -B tests\manual_test_ao3_pacing.py` |
| Boox ADB transfer | Windows PowerShell | `python -B tests\manual_test_boox_transfer.py` |

Unit tests use mocks and never touch real Calibre or AO3 — they run fine in WSL. Manual integration tests call real Windows binaries or make live network requests, so they **must** run in PowerShell on Windows.

**FanFicFare manual test scripts:**
- `manual_test_ao3.py` — full 25-story batched run using placeholder work IDs. Replace `WORK_IDS` list with real IDs before running.
- `manual_test_ao3_pacing.py` — **primary pacing validation.** Reads the first 20 stories from `marked_for_later.csv` automatically, downloads them with live delays, and gives a pass/fail verdict on whether the current `FANFICFARE_STORY_DELAY` prevents rate-limiting. This is the script to run after any change to delay settings.

---

### WSL unit test command

From the project root in WSL:
```bash
python3.12 -m pytest tests/
```

---

### Windows PowerShell setup (run once per session)

**1. Navigate to the project root:**
```powershell
cd "\\wsl$\Ubuntu-24.04\home\worldsapart76\FanFictionFlow"
```

**2. Add Windows Python and Scripts to PATH:**
```powershell
$env:PATH = "C:\Users\world\AppData\Local\Programs\Python\Python312\Scripts;C:\Users\world\AppData\Local\Programs\Python\Python312;" + $env:PATH
```

> Scripts must be included — pip-installed executables (fanficfare, etc.) live there, not in the Python root.

**3. Set PYTHONPATH so Python can find the orchestrator package:**
```powershell
$env:PYTHONPATH = "\\wsl$\Ubuntu-24.04\home\worldsapart76\FanFictionFlow"
```

**4. Run tests using `python` (not `python3` — that command does not exist on Windows):**
```powershell
python tests\manual_test_calibre.py
```

---

### Windows Python location

| | Path |
|---|---|
| Python executable | `C:\Users\world\AppData\Local\Programs\Python\Python312\python.exe` |
| pip | `C:\Users\world\AppData\Local\Programs\Python\Python312\Scripts\pip.exe` |

Install packages on the Windows side with:
```powershell
python -m pip install <package>
```

---

### Known environment quirks

- **`python3` does not exist on Windows** — always use `python` in PowerShell instructions.
- **WSL cannot see Windows processes** — `is_gui_open()` always returns `False` in WSL. This is correct behaviour; test it from PowerShell.
- **`#` in PowerShell strings** — `#` is safe inside double-quoted strings in PowerShell and passes through correctly to calibredb. No escaping needed.
- **calibredb custom column naming** — `calibredb list` uses `*fieldname` prefix for custom columns (not `#`). The `--fields` argument must also use `*`. `calibre.py` normalizes `*` → `#` internally so all other code uses `#`.
- **Calibre GUI must be closed** before running any integration test that calls calibredb. `is_gui_open()` will warn if it is open.
- **Always use `python -B`** for manual integration tests on Windows — Python caches `.pyc` bytecode aggressively and may run stale versions of recently edited scripts without it.
- **`fanficfare` not found** — `fanficfare.exe` is installed into the `Scripts\` subdirectory by pip, not the Python root. `FANFICFARE_CMD` in `config.py` uses the full path to avoid this. If it ever needs reinstalling: `python -m pip install fanficfare`.
- **FanFicFare `-d` is debug, not directory** — output directory is passed via `cwd=` in `subprocess.run`, not a CLI flag.
- **FanFicFare `-o` expects `key=value`** — passing a bare path to `-o` causes a `ValueError` inside FanFicFare. Extra options go via `FANFICFARE_EXTRA_OPTIONS` in config.
- **AO3 login blocks (403 on login endpoint)** — Cloudflare sometimes blocks FanFicFare's login POST even with correct credentials. These are retried automatically. The `personal.ini` at `%APPDATA%\fanficfare\personal.ini` must contain valid AO3 credentials for stories that require login.

---

## What Not To Do

- Do not replace Calibre
- Do not build a custom AO3 epub downloader (use FanFicFare)
- Do not write metadata to Calibre before the review queue is confirmed
- Do not change the Calibre library CSV output format without checking compatibility with https://github.com/worldsapart76/CalibreFanFicBrowser
- Do not add GUI frameworks beyond tkinter/PySimpleGUI
- Do not support platforms other than Windows
