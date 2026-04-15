# FanFictionFlow Backlog

Items here are confirmed, understood, and ready to implement — not speculative.

---

## Performance

### Eliminate redundant `fetch_library()` call in full sync path

**File:** `main.py` line 545, `sync/calibre.py` lines 79–88

**Problem:**
In `_phase1_background`, `calibre.fetch_library()` is called at line 406 to load the
library for the diff. Then at line 545, `calibre.fetch_existing_ship_values()` is called
to get distinct `#primaryship` values for ship normalization — but that function
internally calls `fetch_library()` again. On a 6,700-book library this is a redundant
~60–90 second calibredb invocation.

The inconsistency is visible in the same block: `existing_collections` is correctly
derived from the already-loaded `library` dict (line 548), but `existing_ships` is not.

**Fix:**
In `_phase1_background`, replace the `fetch_existing_ship_values()` call with an inline
derivation from the already-loaded `library`, matching the pattern used for collections:

```python
existing_ships = sorted({
    v for book in library
    if (v := (book.get("#primaryship") or "").strip())
})
```

`fetch_existing_ship_values()` in `calibre.py` stays — the standalone step paths
(e.g. `_step_import_bg`) have no pre-loaded library and legitimately need it.

**Why it exists:**
`fetch_existing_ship_values()` was designed for standalone step use. The full sync path
calling it was an oversight — ships and collections were handled inconsistently.

---

## Future / Exploratory

### Replace Tampermonkey CSV export with programmatic AO3 fetch

**Background:**
Investigated AO3 scraping libraries (2025-04-15). The only viable Python option is
`ArmindoFlores/ao3_api` (PyPI: `ao3-api`, v2.3.1, MIT, actively maintained).

**Key finding:**
`Session.get_marked_for_later()` fetches the AO3 "Marked for Later" list directly via
`/users/{username}/readings?page={n}&show=to-read`. This is exactly the list the
Tampermonkey script exports.

**`relationship_primary` is not a problem:**
The Tampermonkey script produces `relationship_primary` as simply `relationships[0]` —
the first relationship tag in AO3's DOM order. This is trivially replicable in Python:
`work.relationships[0] if work.relationships else ""`. No JS logic needs to be ported.

**Proposed approach:**
Rather than taking `ao3-api` as a dependency, build a thin `sync/ao3_client.py` (~80
lines, `requests` + `BeautifulSoup`) based on the patterns in `ao3-api` and the archived
`alexwlchan/ao3` library. Implement only what is needed:
- `login(username, password)` → `requests.Session`
- `get_marked_for_later(session, username)` → list of story dicts

Gate behind a Settings toggle: "Fetch from AO3 directly" vs "Load from CSV file".
`diff.py` sees the same story dict format regardless of source. CSV path stays as
fallback.

**What this won't fix:**
FanFicFare Cloudflare/login blocking is unrelated — that affects epub downloads, not
reading list fetching.

**Before implementing:**
Verify the `&show=to-read` endpoint still works with a live AO3 session. The ao3-api
library confirmed it as of January 2025.
