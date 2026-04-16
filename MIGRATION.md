# Migration to C:\Dev\

Move all projects from WSL and Dropbox to `C:\Dev\` on Windows native. Git is the
source of truth for code — Dropbox sync of dev projects is unnecessary and causes
churn on `__pycache__`, build artifacts, and other generated files.

`C:\Dev\` should not be inside any Dropbox-watched folder.

---

## Pre-flight (do once)

- [ ] Confirm `C:\Dev\` exists and is not inside Dropbox
- [ ] Confirm Windows Git is installed (`git --version` in PowerShell)
- [ ] Confirm Windows Python 3.12 is on PATH (`python --version` in PowerShell)
- [ ] Confirm GitHub authentication works from Windows PowerShell:
  ```powershell
  git clone https://github.com/worldsapart76/FanFictionFlow C:\Dev\_auth_test
  ```
  If it prompts for credentials, sign in once via the browser popup — Windows
  Credential Manager caches it for all subsequent operations.
  Delete `C:\Dev\_auth_test` after confirming auth works.

---

## Project 1 — FanFictionFlow

**From:** `\\wsl$\Ubuntu-24.04\home\worldsapart76\FanFictionFlow`
**To:** `C:\Dev\FanFictionFlow`

### Step 1 — Push everything from WSL

From the WSL terminal (not PowerShell — Git auth in WSL is the current blocker):
```bash
cd ~/FanFictionFlow
git status
git add -A && git commit -m "Pre-migration cleanup"   # only if there are uncommitted changes
git push
```

### Step 2 — Clone to Windows

```powershell
git clone https://github.com/worldsapart76/FanFictionFlow C:\Dev\FanFictionFlow
```

### Step 3 — Update CLAUDE.md

Open `C:\Dev\FanFictionFlow\CLAUDE.md` and make these changes:

**Testing section — WSL unit test command:**
Change:
```
python3.12 -m pytest tests/
```
To:
```
python -m pytest tests/
```

**Primary working directory** (if hardcoded anywhere in the file):
Update to `C:\Dev\FanFictionFlow`

**Remove or update WSL-specific notes** that are no longer relevant:
- "`python3` does not exist on Windows" — already noted for PowerShell, still valid
- "WSL cannot see Windows processes" — remove, no longer a concern
- The 2 pre-existing WSL-only test failures in `test_boox_transfer.py` (`creationflags=0`
  mismatch) — these should now pass on Windows. Run tests and update the Current State
  note in CLAUDE.md if they do.

### Step 4 — Verify tests pass

```powershell
cd C:\Dev\FanFictionFlow
python -m pytest tests/
```

Expected: 471+ passing, 0 failures (the 2 WSL-only failures should now pass on Windows).
If any new failures appear, investigate before proceeding.

### Step 5 — Verify the app launches

```powershell
cd C:\Dev\FanFictionFlow
python main.py
```

Or double-click `launch.bat` — verify it resolves correctly from the new path.
`launch.bat` uses relative paths so it should work without changes.

### Step 6 — Update VS Code workspace

Open `C:\Dev\FanFictionFlow` in VS Code. Confirm Claude Code extension picks up the
new working directory.

### Step 7 — Retire the WSL copy

Once the Windows version is confirmed working:
```bash
# From WSL terminal — only after confirming Windows clone is good
rm -rf ~/FanFictionFlow
```

---

## Project 2 — CalibreFanFicBrowser

**Repo:** `https://github.com/worldsapart76/CalibreFanFicBrowser`
**To:** `C:\Dev\CalibreFanFicBrowser`

### Step 1 — Check current location

If already on Windows (Android Studio project), find where it currently lives.
If it is inside a Dropbox folder, proceed with the move below.
If it is already outside Dropbox, skip to Step 3.

### Step 2 — Push any uncommitted changes

From wherever the project currently lives:
```
git status
git push   (if needed)
```

### Step 3 — Clone to C:\Dev\

```powershell
git clone https://github.com/worldsapart76/CalibreFanFicBrowser C:\Dev\CalibreFanFicBrowser
```

### Step 4 — Reopen in Android Studio

File → Open → `C:\Dev\CalibreFanFicBrowser`

Let Gradle sync complete. Verify the project builds.

### Step 5 — Retire old location

Delete the Dropbox copy only after confirming the build works from `C:\Dev\`.

### Step 6 — Create CLAUDE.md (future work)

When starting the server integration work described in `ENHANCEMENTS.md`, create
`C:\Dev\CalibreFanFicBrowser\CLAUDE.md` before writing any code. See ENHANCEMENTS.md
section 7 for what it should cover.

---

## Project 3 — CollectCore

**To:** `C:\Dev\CollectCore`

### Steps

- [ ] Find current project location
- [ ] Confirm git status is clean / push any uncommitted changes
- [ ] `git clone <remote> C:\Dev\CollectCore`
- [ ] Reopen in VS Code from new location
- [ ] Verify project runs / builds correctly
- [ ] Delete old location (Dropbox copy if applicable)

**Note:** If CollectCore has any hardcoded paths referencing its old location, update
them after cloning.

---

## Project 4 — korean-vocab-game

**To:** `C:\Dev\korean-vocab-game`

### Steps

- [ ] Find current project location
- [ ] Confirm git status is clean / push any uncommitted changes
- [ ] `git clone <remote> C:\Dev\korean-vocab-game`
- [ ] Reopen in appropriate IDE from new location
- [ ] Verify project runs / builds correctly
- [ ] Delete old location (Dropbox copy if applicable)

---

## Post-migration checklist

- [ ] All four projects cloned to `C:\Dev\` and verified working
- [ ] No project folders remaining inside Dropbox
- [ ] WSL `~/FanFictionFlow` deleted
- [ ] `C:\Dev\` confirmed not watched by Dropbox
- [ ] VS Code default project folder updated to `C:\Dev\` if applicable
- [ ] GitHub authentication confirmed working from PowerShell for all repos
