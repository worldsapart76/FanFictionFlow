# FanFictionFlow & CalibreFanFicBrowser — Planned Enhancements

This document captures the full design discussion from April 2025 covering AO3 API
research, FFF improvements, Calibre server integration, Palma transfer, and the
CalibreFanFicBrowser redesign. It is intended as a complete context handoff for future
development sessions.

---

## 1. AO3 API / Scraping Library Research

### Libraries evaluated

| Library | Language | Status | Relevant? |
|---|---|---|---|
| Medium Node.js scraper | JavaScript | Tutorial only | No |
| pub.dev `ao3` | Dart | Active | No |
| `wendytg/ao3_api` | Python | Archived Sep 2025 | Methodology only |
| `alexwlchan/ao3` | Python | Archived Sep 2025 | Methodology only |
| `ArmindoFlores/ao3_api` | Python | Active (v2.3.1 Jan 2025) | **Yes** |

### Key finding — ArmindoFlores/ao3_api

The only viable Python option. PyPI package `ao3-api`, MIT license, actively maintained.

**`Session.get_marked_for_later()` is fully implemented** and fetches exactly the list
the Tampermonkey script currently exports:

```
GET /users/{username}/readings?page={n}&show=to-read
```

The `&show=to-read` parameter is the critical detail — it filters the readings endpoint
to "Marked for Later" only, which is a separate list from Bookmarks and general reading
history.

Rate limiting: explicit `Requester` class, 12 requests per 60-second window, `sleep=1`
between pages, `timeout_sleep=60` on HTTP 429.

Authentication: `POST /users/login` with `authenticity_token` (CSRF), username,
password. Checks for HTTP 302 redirect on success.

### Archived library value

Both archived libraries use `requests` + `BeautifulSoup` and are worth reading as
implementation references even though they are not pip-installable as dependencies.
`alexwlchan/ao3` has clean pagination and session patterns. The core approaches are
still valid — AO3's HTML structure has not changed significantly.

---

## 2. Tampermonkey Script Analysis

**File:** `extensions/tampermonkey/ao3_readings_exporter.user.js` (saved April 2025)

### The `relationship_primary` field

This was the critical thing to understand before evaluating the ao3-api approach.

`relationship_primary` in the CSV is **not a computed or ranked value**. It is simply:

```javascript
w.relationships[0]  // first relationship tag in AO3's DOM order
```

AO3 lists the author's primary ship first. The script trusts that ordering and takes
the first element. There is no scoring, heuristic, or selection logic.

**Implication:** Replicating this in Python when using ao3-api is trivial:
```python
relationships[0] if relationships else ""
```

No logic needs to be ported. The normalization intelligence lives entirely in
`normalize/ship.py` (Rules 1–5) on the Python side, which is correct and stays there.

### Other fields the script produces

The script exports significantly more than the app currently uses:
`work_id`, `title`, `authors`, `link`, `fandoms`, `relationship_primary`,
`relationship_additional`, `characters`, `warnings`, `categories`, `rating`,
`language`, `words`, `chapters`, `complete`, `kudos`, `bookmarks`, `hits`,
`updated_raw`, `viewed_raw`, `additional_tags`, `summary`

The app currently uses: `work_id`, `title`, `authors`, `fandoms`,
`relationship_primary`, `additional_tags`, `words`.

---

## 3. FFF Improvements Identified

### 3a. Replace Tampermonkey CSV export with programmatic AO3 fetch

**Status:** Backlog — see `BACKLOG.md`

The largest friction reduction available. The user currently has to open AO3 in a
browser, wait for the Tampermonkey script to scrape ~20 pages, export a CSV, and load
it into the app. This entire step can be eliminated.

**Recommended approach:** Build a thin `sync/ao3_client.py` (~80 lines) using `requests`
+ `BeautifulSoup` based on `ao3-api`'s patterns. Do not take `ao3-api` as a pip
dependency — implement only what is needed:

- `login(username, password) → requests.Session`
- `get_marked_for_later(session, username) → list[dict]`

Story dicts produced must match the format `diff.py` already expects — `diff.py` does
not change. Gate behind a Settings toggle: "Fetch from AO3 directly" vs "Load from CSV
file". CSV path stays as fallback.

AO3 credentials are already stored via `credentials.py` for FanFicFare — reuse that
infrastructure.

**Before implementing:** Verify `&show=to-read` still works with a live AO3 session.
Confirmed working as of January 2025 per ao3-api release history.

**What this does not fix:** FanFicFare Cloudflare/login blocking. That is the epub
download layer, entirely separate from reading-list fetching.

### 3b. Eliminate redundant `fetch_library()` call

**Status:** Backlog — see `BACKLOG.md`

In `_phase1_background`, `calibre.fetch_library()` is called at line 406 for the diff.
Then at line 545, `calibre.fetch_existing_ship_values()` is called — but that function
internally calls `fetch_library()` again. On a 6,700-book library this is a redundant
~60–90 second calibredb invocation.

The inconsistency is clear in the same block: `existing_collections` is correctly
derived from the already-loaded `library` (line 548), but `existing_ships` is not.

Fix: derive ships from the already-loaded `library` in `_phase1_background`, matching
the collections pattern. `fetch_existing_ship_values()` stays in `calibre.py` for
standalone step paths that legitimately need it.

---

## 4. Calibre Content Server Integration

### What the server provides

The Calibre Content Server exposes:
- `GET /ajax/books?ids=...` — metadata including custom columns
- `GET /ajax/search?query=...` — library search
- `GET /get/epub/{book_id}/filename` — direct epub download
- `GET /opds` — OPDS catalog for compatible apps
- `POST /cdb/cmd` — **write** metadata back to the library (JSON RPC)

The write endpoint is significant — it means external clients (including
CalibreFanFicBrowser) can update `#readstatus` and other custom fields directly,
without going through calibredb CLI or a CSV intermediary.

### Server location: Windows vs Unraid

**Windows (current):** Already running. Library is local. Accessible on LAN while PC
is on. Lowest friction to start using.

**Unraid:** Always-on. Library would need its own synced copy (Dropbox daemon or rclone
from Windows). Enables Palma sync even when PC is off. Correct long-term target once
the integration approach is validated on Windows first.

---

## 5. Palma Transfer — ADB over WiFi

**Current:** `adb push` over USB via `boox_transfer.py`, with `rename_map` to convert
FanFicFare filenames to `{calibre_id}-{title}.epub` format for CalibreFanFicBrowser.

**Improvement:** ADB over WiFi — identical code, no USB cable.

The Boox Palma 2 runs Android 11+ and supports **Wireless Debugging** in Developer
Options — no USB pairing step needed. Once enabled, connect via:

```
adb connect 192.168.x.x:5555
```

In `config.py`, `BOOX_DEVICE_SERIAL` is set to `192.168.x.x:5555` instead of a USB
serial. Zero code changes in `boox_transfer.py`.

**Practical note:** Assign a static IP to the Palma in your router to avoid the serial
changing between sessions.

This improvement is independent of the CalibreFanFicBrowser redesign below and can be
done immediately.

---

## 6. CalibreFanFicBrowser Redesign

### Current model
- Reads a static CSV exported by FFF (`library_csv.py`)
- Opens epub files pushed to the device via ADB by FFF (`boox_transfer.py`)
- Reports read status changes via a CSV export, loaded manually into FFF Settings

### Proposed model — selective sync via Calibre server

User wants: **local files on the Palma** (offline-first, no connectivity dependency for
reading), but wireless delivery rather than USB/ADB push.

The hybrid design:
- CB queries the Calibre server to show what is in the library
- User selects which books to download to the device
- CB downloads chosen epubs from `/get/epub/{book_id}` directly to local storage over WiFi
- Reading uses local files as before — no connectivity needed at read time
- CB writes `#readstatus` changes directly to Calibre via `/cdb/cmd` — no CSV export

This eliminates from FFF:
- `export/boox_transfer.py` — the Palma no longer needs ADB push
- `sync/readstatus.py` — CB writes status directly to Calibre, no CSV intermediary
- The palma CSV path setting in the Settings UI
- The manual "load CSV" step in the sync workflow

This reduces in FFF:
- `export/library_csv.py` — survives only as input for the Read Status Badge Chrome
  extension. No longer needed by CB.

FFF's job ends cleanly at: **metadata written to Calibre.**

### Dependency ordering

CB must implement server reads/writes **before** FFF removes the CSV sync and transfer
code. Sequence:
1. CB: implement server-backed library browsing + selective epub download
2. CB: implement direct `#readstatus` write via server API
3. Validate both work reliably
4. FFF: remove `boox_transfer.py`, `readstatus.py`, related UI and settings
5. FFF: simplify Phase 2 (AO3 curation dialog trigger changes)

### Unraid pays off here

Once CB pulls from the server rather than relying on ADB push, the Palma can sync
anywhere — home network or VPN — regardless of whether the Windows PC is on. This is
the scenario where moving the Calibre server to Unraid has clear value.

---

## 7. Cross-Repo Coordination (FFF + CB)

**Repos:**
- `FanFictionFlow` — Python, VS Code, `C:\Dev\FanFictionFlow` (post-migration)
- `CalibreFanFicBrowser` — Android/Kotlin, Android Studio

**Coordination mechanism:** CLAUDE.md in each repo, not GitHub Projects (solo
developer, unnecessary overhead).

- FFF's `BACKLOG.md` is the primary tracker for cross-cutting items, since FFF is the
  orchestrator and the more active development environment.
- CB's CLAUDE.md (does not yet exist) should describe the FFF relationship, note the
  dependency ordering above, and reference FFF's `BACKLOG.md` for shared context.

**First step when starting CB development:** Create `CLAUDE.md` in the CB repo before
writing any code. It should cover: what CB is, what it consumes from Calibre, the
server integration intent, the FFF dependency ordering, and compatibility constraints
(CSV column names, epub naming) documented in FFF's CLAUDE.md.

---

## 8. Summary of What Changes, What Stays

| Component | Change |
|---|---|
| `sync/ao3_client.py` | New — replaces Tampermonkey CSV as AO3 data source |
| `sync/diff.py` | No change — receives same story dict format regardless of source |
| `sync/ao3.py` | No change — FanFicFare download approach unchanged |
| `sync/calibre.py` | Minor — `_phase1_background` stops calling `fetch_existing_ship_values()` |
| `normalize/` | No change |
| `export/library_csv.py` | Stays — still needed for Read Status Badge Chrome extension |
| `export/boox_transfer.py` | Removed — after CB selective sync is working |
| `sync/readstatus.py` | Removed — after CB writes status directly to Calibre server |
| Settings UI | Simplified — loses CSV path selector and transfer config |
| Phase 2 curation dialog | Stays — trigger mechanism changes when readstatus.py is removed |
| `extensions/tampermonkey/` | Kept as fallback — CSV path remains in app |
