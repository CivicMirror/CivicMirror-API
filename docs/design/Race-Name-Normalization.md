# Race Name Normalization — Implementation Plan

## Context

Two separate data sources (civic_api and ca_sos) write Race records for the same contest, but their
`office_title` and `ocd_division_id` values differ enough that `race_canonical_key()` generates
distinct keys — creating duplicate Race rows for the same real contest (confirmed: CA Governor 2026,
Race 9609 vs Race 9618).

**Two distinct root causes, both must be fixed for races to merge:**

1. **Title mismatch**: ca_sos emits `"Governor - Statewide Results"`; civic_api emits `"GOVERNOR"`.
   After `normalize_office_title` (which only lowercases + collapses whitespace), the keys are
   `governor - statewide results` vs `governor` → different canonical keys.

2. **OCD mismatch**: civic_api falls back to `election.state` (`"CA"`) when no real OCD ID exists
   (`civic/mappers.py:116`); ca_sos always passes `""`.
   Key components: `CA` vs `NO_OCD` → still different even after title fix alone.

Both fixes together make the keys collide, and `ingest_race`'s existing merge logic (via
`_apply_fields` + `_add_source`) handles the rest automatically.

**Critical migration risk**: `Race.canonical_key` is `unique=True` and stored in the DB. Deploying
stronger normalization without recomputing stored keys means the next sync computes a new key, fails
to match the old stored key, and creates a *fresh* duplicate instead of merging.

---

## ADR: Race Name Normalization Strategy

### Status: Proposed

### Decision
Strengthen `race_canonical_key()` so geographic suffixes and bare state-code OCD values are
normalized away before key construction. This is a passive change: ingest already merges races with
matching keys; making more races match the same key is sufficient.

Complement with a management command that recomputes and de-duplicates existing stored keys before
the next sync runs.

### Alternatives Considered

**A. Normalize only the title (strip geographic qualifiers)**
- *Rejected*: Title fix alone does not collapse `CA` vs `NO_OCD`; still produces duplicate keys for
  the most common CA case.

**B. Fix only the civic mapper OCD fallback**
- *Rejected*: Fixes future CA statewide races but leaves `"Governor - Statewide Results"` still
  generating a different canonical key than `"Governor"`.

**C. Two-pass lookup in `ingest_race` (exact key first, then fuzzy fallback)**
- *Rejected*: Adds stateful lookup complexity and ordering sensitivity to a function that currently
  has zero side-effect ambiguity. The normalization-at-write approach keeps the contract clean.

**D. Chosen: Normalize both title and OCD in `race_canonical_key` + fix civic mapper source**
- Title: strip known geographic qualifiers (`- Statewide Results`, `- Districtwide Results`, etc.)
- OCD: treat bare 2-letter state codes as empty (they were always a civic_api fallback mistake)
- Source fix: stop civic mapper from using `election.state` as OCD fallback (defense-in-depth)
- Backfill command: recompute stored keys + merge collision groups before next sync

---

## Implementation Plan

### 1. `backend/aggregation/identity.py`

**a. Strip geographic qualifiers from `normalize_office_title`:**

```python
_GEO_QUALIFIER_RE = re.compile(
    r"\s*[-–—]\s*(statewide|districtwide|countywide|citywide|nationwide)"
    r"(\s+results?)?\s*$",
    re.IGNORECASE,
)

def normalize_office_title(title: str) -> str:
    cleaned = _GEO_QUALIFIER_RE.sub("", _squash(title))
    return _squash(cleaned).lower()
```

Strips: `" - Statewide Results"`, `" - Statewide"`, `" - Districtwide Results"`, etc.
Does NOT strip district numbers — `"U.S. Representative District 1"` is unaffected.

**b. Normalize bare OCD state codes in `race_canonical_key`:**

```python
_US_STATE_CODES = frozenset(["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
    "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO",
    "MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
    "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC"])

def _normalize_ocd(ocd: str) -> str:
    if not ocd:
        return ""
    return "" if ocd.upper() in _US_STATE_CODES else ocd

def race_canonical_key(election_key, office_title, ocd_division_id, race_type):
    return "|".join([
        election_key,
        normalize_office_title(office_title),
        _normalize_ocd(ocd_division_id) or "NO_OCD",
        race_type,
    ])
```

After both fixes, civic_api's `"GOVERNOR" + "CA"` and ca_sos's `"Governor - Statewide Results" + ""`
both produce `...|governor|NO_OCD|candidate` — identical keys, one merged race.

---

### 2. `backend/integrations/civic/mappers.py`

Fix line 116 — defense-in-depth; prevents bare codes from ever reaching `ingest_race`:

```python
# Before:
ocd_id = contest.get("district", {}).get("id") or contest.get("officeDivisionId") or election.state or ""

# After:
raw_ocd = contest.get("district", {}).get("id") or contest.get("officeDivisionId") or ""
ocd_id = raw_ocd if raw_ocd.startswith("ocd-division/") else ""
```

---

### 3. New management command: `backend/elections/management/commands/merge_duplicate_races.py`

**Purpose**: Must run immediately after deploy, before the next `sync-ca-sos` scheduler fires.

**Usage**:
```
python manage.py merge_duplicate_races [--dry-run] [--election-id ID] [--state STATE]
```

**Algorithm**:
1. For each Race in scope, compute `new_key = race_canonical_key(election.canonical_key, race.office_title, race.ocd_division_id, race.race_type)`
2. Group races by `(election_id, new_key)`
3. **Collision groups** (>1 race → same new key): merge
4. **Solo races** where `new_key != current canonical_key`: update key only

**Merge logic for collision groups**:
- Winner = race whose source has lowest `resolve_rank(state, "identity", source)` (highest precedence)
- For each loser candidate: call `ingest.ingest_candidate(race=winner, ...)` to merge fields
- Move `OfficialResult` rows referencing loser candidates → update `candidate_id` to matched winner candidate
- Move `OfficialResult` rows with `race_id=loser, candidate=None` (measure results) → update `race_id`
- Move `MeasureOption` rows from loser → update `race_id` (or merge by label if duplicate)
- Merge loser's `contributing_sources` into winner
- Update winner `canonical_key` to `new_key`
- Delete loser race (cascades to any remaining loser candidates/options)

---

### 4. `backend/aggregation/tests/test_identity.py`

Update `test_normalize_office_title_collapses_whitespace_and_case` (currently expects `"governor - statewide"`):
```python
assert normalize_office_title("  Governor   - Statewide  ") == "governor"
assert normalize_office_title("Governor - Statewide Results") == "governor"
assert normalize_office_title("U.S. Representative District 1 - Statewide Results") == "u.s. representative district 1"
assert normalize_office_title("Governor") == "governor"
```

Add tests for `_normalize_ocd` behavior and the cross-source merge scenario.

Update `test_race_canonical_key_uses_no_ocd_placeholder_when_blank` to also assert that bare state
codes like `"CA"` produce `NO_OCD`.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/aggregation/identity.py` | Add `_GEO_QUALIFIER_RE`, `_US_STATE_CODES`, `_normalize_ocd`; update `normalize_office_title` and `race_canonical_key` |
| `backend/integrations/civic/mappers.py` | Line 116: fix OCD fallback |
| `backend/aggregation/tests/test_identity.py` | Update 1 test, add new assertions |
| `backend/elections/management/commands/merge_duplicate_races.py` | New file |

No model changes. No Django migrations required.

---

## Decision Matrix

| Option | Fixes CA Now | Fixes Future States | Backfill Safe | Code Complexity | Score |
|--------|:---:|:---:|:---:|:---:|:---:|
| Title-only fix | no | partial | yes | low | 2/4 |
| OCD-only fix | no | partial | yes | low | 2/4 |
| Two-pass fuzzy lookup | yes | yes | yes | high | 3/4 |
| **Normalize both + backfill** | **yes** | **yes** | **yes** | **medium** | **4/4** |

---

## Deployment Order (critical)

1. Deploy code changes
2. **Immediately** run `python manage.py merge_duplicate_races` (via Cloud Run Job or shell)
3. Verify with `--dry-run` first if desired
4. Next scheduler run will correctly merge new sources rather than duplicate

The command is idempotent — safe to run multiple times.

---

## Verification

```bash
# 1. Run updated tests
cd backend && pytest aggregation/tests/test_identity.py aggregation/tests/test_ingest.py \
  aggregation/tests/test_ca_end_to_end.py --no-migrations -v

# 2. Dry-run backfill on production (read-only preview)
python manage.py merge_duplicate_races --dry-run --state CA

# 3. Live backfill
python manage.py merge_duplicate_races

# 4. Confirm CA Governor deduplication
# Check that Race 9609 no longer exists, Race 9618 has both sources in contributing_sources
```
