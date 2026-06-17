# TX GoElect ENR Adapter — Design Spec

**Date:** 2026-06-17  
**State:** Texas  
**Source:** CivixApps GoElect ENR (`goelect.txelections.civixapps.com`)  
**Target elections:** November 2026 General (primary/runoff data already certified)  
**Uniform Election Date:** November 3, 2026 (General Election — not a primary)

---

## Overview

Texas election night results are served by the CivixApps GoElect ENR platform — a public JSON API backed by AWS S3, no authentication required. The adapter follows the same 3-layer pattern as WA/FL/AZ: a client module, mappers, Celery tasks for election/race seeding, and a results polling adapter.

The November 2026 General Election is not yet registered in the ENR system (expected September–October 2026). The adapter handles discovery dynamically via `electionConstants` polling plus a sequential ID probe.

**Texas election calendar:** Primary March 3 → Primary Runoff May 26 → Uniform Election Date (General) November 3.

---

## API Endpoints

Base URL: `https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr`

| Endpoint | Purpose | Response wrapper |
|----------|---------|-----------------|
| `GET /electionConstants` | Election discovery index | `{"upload": "<b64>"}` |
| `GET /election/{id}` | Full results + Lookups | Direct JSON, fields individually b64 |
| `GET /election/countyInfo/{id}` | Per-county breakdowns (all races) | `{"upload": "<b64>"}` |

All requests use a browser `User-Agent` header. The site is behind Cloudflare with a passive challenge — standard `requests` has worked without active bot challenges; monitor for future tightening.

**Version detection:** The `Version` field on `GET /election/{id}` returns `"enr/{id}/{n}/"` where `n` is an integer that increments each S3 update. Cache `n` to detect changes without re-parsing. Unknown election IDs return `{"Version": ""}` with HTTP 200 (not 404).

---

## Architecture

```
integrations/tx_goelect/
    client.py       — HTTP + base64 decode helpers, tolerant field decoder
    mappers.py      — field mappers for Election, Race, Candidate, county fragment
    tasks.py        — sync_tx_elections (Stage 1), sync_tx_races (Stage 2)
    apps.py
    exceptions.py
    tests/
        test_client.py
        test_mappers.py
        test_tasks.py
        fixtures/
            enr_56181_election.json     # sanitized SD4 special election payload
            enr_58315_runoff_subset.json  # sanitized Republican Runoff subset
            enr_56181_county_info.json  # sanitized countyInfo payload

results/adapters/tx.py          — TxAdapter (results polling)
results/tests/test_tx_adapter.py
elections/migrations/0019_tx_goelect_race_source.py
```

---

## Client (`integrations/tx_goelect/client.py`)

```python
class TxGoElectClient:
    def get_election_constants() -> dict       # decoded electionInfo
    def get_election_data(id: int) -> dict     # decoded sub-fields + version int
    def get_county_results(id: int) -> dict    # decoded county dict keyed by CivixApps county ID
    def get_version(id: int) -> int | None     # n from "enr/{id}/{n}/" or None if not live
    def probe_election(id: int) -> bool        # True if election is live
```

**Base64 helpers:**
- `electionConstants` and `countyInfo` responses: decode `resp.json()["upload"]` → JSON
- `election/{id}` response: each sub-field (`Home`, `Lookups`, `Race`, `OfficeSummary`, `Federal`, `StateWide`, `StateWideQ`, `Districted`) is individually base64-encoded; `Version` is a plain string

**Tolerant field decoder:** `get_election_data` decodes each known sub-field individually. Missing fields (field absent or empty string) decode to `{}` or `[]` without raising. Unknown top-level keys are logged at DEBUG level so schema drift is visible in logs without breaking ingestion.

**Retry:** 3 attempts on 429/5xx, same pattern as `WaVoteWaClient`. `get_version` on an unknown ID returns `None` (no retry needed — 200 with empty Version is expected).

---

## Mappers (`integrations/tx_goelect/mappers.py`)

### `map_election(election_id, meta, home)`
- **Election date:** parse `Home["ElecDate"]` (MMDDYYYY) → `date`
- **Election type** from CivixApps type code:
  - `P` → PRIMARY, `RU` → PRIMARY_RUNOFF, `GE` → GENERAL
  - `S` / `SR` → SPECIAL, `GR` → GENERAL_RUNOFF
- **source_metadata:** `{"tx_election_id": int(election_id)}`
- **source_id:** `f"tx_goelect:{election_id}"`

### `map_race(election_obj, office, office_type_name)`
- **race_type:** CANDIDATE for all office types; MEASURE for PROPOSITIONS
- **geography_scope:** `"statewide"` if `office["SSO"]` is 0 or absent; `"district"` otherwise
- **jurisdiction:** district label built from office name + `SSO` (e.g. `"District 6"`)
- **source_id:** `f"tx_goelect:{election_id}:office:{office['ID']}"` — stable composite key across syncs
- **source_metadata:** `{"tx_election_id": ..., "tx_office_id": office["ID"], "office_type": office_type_name}`

### `map_candidate(election_id, office_id, ballot_option)`
- **name:** from `BN` (full name field)
- **party:** from `P` (`DEM` / `REP` / empty string)
- **source_id:** `f"tx_goelect:{election_id}:office:{office_id}:candidate:{ballot_option['ID']}"` — collision-safe across elections and offices
- **source_metadata:** `{"tx_candidate_id": id, "party_abbreviation": party}`

### `map_county_fragment(county_lookup_entry)`
- Returns lowercase county name, e.g. `"harris"` from `{"CN": "HARRIS", "MID": 48201}`
- `MID` stored in `raw` as `county_mid` (CivixApps internal field — likely FIPS 48xxx but not guaranteed; verify against live samples before treating as authoritative FIPS)

---

## Tasks (`integrations/tx_goelect/tasks.py`)

### `sync_tx_elections` — Stage 1 (daily via Cloud Scheduler)

1. Call `get_election_constants()` — enumerate elections where `O == "Y"` (online)
2. For each election ID not yet in DB: call `get_election_data(id)`, extract `Lookups`
3. Upsert `Election` via `ingest.ingest_election()` with `tx_election_id` in `source_metadata`
4. Queue `sync_tx_races(election_pk, tx_election_id)` per new/updated election (staggered countdown)
5. **Sequential ID probe** for November General (see below)
6. Standard `SyncLog` + Celery retry on retryable errors

### Sequential ID Probe (within `sync_tx_elections`)

Detects new elections — including the November 2026 General — before they appear in `electionConstants`:

- Watermark key: `tx_goelect:probe_watermark` in cache (initialized to 58315, the highest known ID)
- Each run: scan sequentially from `watermark + 1`
- **Stop after 50 consecutive misses** — nothing new registered; try tomorrow
- **On hit: ingest all valid elections** — do not discard specials, locals, or county elections. Classify and tag each with normalized metadata (see below), then queue `sync_tx_races` for it
- Update watermark to highest ID probed each run regardless of hit/miss
- Typical cost: ≤50 HTTP calls/day when no new elections; ≤100 on the day new elections appear

**Election classification metadata** (stored in `Election.source_metadata` for every discovered election):

```python
{
    "tx_election_id": 59001,
    "enr_slug": None,                       # TX uses integer IDs, not date slugs
    "election_scope": "statewide",          # statewide | federal | county | local | unknown
    "election_type_code": "GE",             # raw CivixApps code: GE, P, RU, S, SR, GR
    "source_date": "2026-11-03",            # parsed from Home["ElecDate"] MMDDYYYY
    "is_target_general_2026": True,         # True only if type==GE and date==2026-11-03
}
```

`is_target_general_2026` is the only field the results adapter and race seeding tasks use to prioritize full processing. All other discovered elections are ingested and tagged but downstream jobs can choose whether to seed full races/results immediately or defer them for future local-election support.

### `sync_tx_races(election_pk, tx_election_id)` — Stage 2 (queued by Stage 1)

1. Fetch `get_election_data(tx_election_id)` → extract `Lookups`, `Race`, `OfficeSummary`
2. Build office-type lookup from `Lookups.OfficeType`
3. Upsert `Race` records from `Lookups.Office` joined to `Race.OfficeTypes`; use composite `source_id`
4. Upsert `Candidate` records from `OfficeSummary`; use composite `source_id` including `office_id` and `candidate_id`
5. Set `election.last_synced_at`
6. Standard `SyncLog` + retry

---

## Results Adapter (`results/adapters/tx.py`)

```python
@register
class TxAdapter(StateResultsAdapter):
    state = "TX"
```

### `fetch_results(election_date, election_id)`

1. Load `tx_election_id` from `election.source_metadata` — return `mapping_confidence="none"` if absent
2. Call `get_version(tx_election_id)` → compare `n` against cache key `tx_goelect:ver:{election_id}`
3. If `n` unchanged and non-None: return `AdapterResult(unchanged=True)`
4. Call `get_election_data(tx_election_id)` and `get_county_results(tx_election_id)`
5. Determine `result_type`:
   - `"complete_unofficial"` if `Home["CR"] == Home["CT"]` and `Home["PR"] == Home["PT"]` — all counties and precincts have reported, but not certified
   - `"unofficial"` otherwise
   - `"official"` reserved for when GoElect exposes an explicit certification flag (not yet observed in HAR; revisit when the General is live)
6. Parse `OfficeSummary` → candidate statewide `ResultRow`s (`jurisdiction_fragment=""`); parse `StateWideQ` → proposition statewide `ResultRow`s (`option_label` instead of `candidate_name`)
7. Parse `countyInfo` → county `ResultRow`s (`jurisdiction_fragment=county_name_slug`)
8. Preserve in `raw`: `tx_candidate_id`, `tx_election_id`, `tx_office_id`, `county_mid` (raw MID value from Lookups)
9. Cache new `n`, return `AdapterResult(mapping_confidence="full", source_version=str(n))`

### ResultRow shape

**Statewide row (from OfficeSummary):**
```python
ResultRow(
    candidate_name="KEN PAXTON",      # or option_label for propositions
    vote_count=1234567,
    vote_pct=63.8,
    is_winner=None,                   # ENR does not expose a winner flag
    result_type="complete_unofficial",
    office_title="U.S. SENATOR",
    jurisdiction_fragment="",
    raw={"tx_candidate_id": 36388, "tx_election_id": 58315, "tx_office_id": 5031,
         "party": "REP", "early_votes": 800000}
)
```

**County row (from countyInfo):**
```python
ResultRow(
    candidate_name="KEN PAXTON",
    vote_count=5757,
    vote_pct=73.05,
    is_winner=None,
    result_type="complete_unofficial",
    office_title="U.S. SENATOR",
    jurisdiction_fragment="harris",
    raw={"tx_candidate_id": 36388, "tx_election_id": 58315, "tx_office_id": 5031,
         "county_mid": 48201, "party": "REP", "early_votes": 4394}
)
```

---

## Wiring

### New files
- `integrations/tx_goelect/__init__.py`
- `integrations/tx_goelect/apps.py`
- `integrations/tx_goelect/exceptions.py`
- `integrations/tx_goelect/client.py`
- `integrations/tx_goelect/mappers.py`
- `integrations/tx_goelect/tasks.py`
- `integrations/tx_goelect/tests/__init__.py`
- `integrations/tx_goelect/tests/test_client.py`
- `integrations/tx_goelect/tests/test_mappers.py`
- `integrations/tx_goelect/tests/test_tasks.py`
- `integrations/tx_goelect/tests/fixtures/enr_56181_election.json`
- `integrations/tx_goelect/tests/fixtures/enr_58315_runoff_subset.json`
- `integrations/tx_goelect/tests/fixtures/enr_56181_county_info.json`
- `results/adapters/tx.py`
- `results/tests/test_tx_adapter.py`
- `elections/migrations/0019_tx_goelect_race_source.py`

### Changes to existing files
| File | Change |
|------|--------|
| `config/settings/base.py` | Add `'integrations.tx_goelect'` to `INSTALLED_APPS` |
| `internal/views.py` | Add `sync_tx_goelect_trigger` view |
| `internal/urls.py` | Add `path("tasks/sync-tx-goelect/", ...)` |
| `internal/task_locks.py` | Add `"sync_tx_goelect": (WINDOW_DAILY, 23 * _HOUR)` |
| `results/apps.py` | Add `tx` to `ResultsConfig.ready()` imports |
| `elections/models.py` | Add `TX_GOELECT = "tx_goelect"` to `Race.Source` |
| `.github/workflows/deploy.yml` | Add `sync-tx-goelect` Cloud Scheduler job (05:00 UTC daily) |

**No new secrets or env vars required** — the ENR API is fully public.

---

## Testing Strategy

- **test_client.py** — mock `requests.get`; verify base64 decode (both `upload` wrapper and per-field), version extraction, probe logic (miss/hit/validate), retry on 5xx, tolerant decode of missing fields
- **test_mappers.py** — unit test each mapper with representative payloads; cover MMDDYYYY date parsing, election type inference, district vs statewide scope, proposition race type, composite source_id construction
- **test_tasks.py** — mock client; test election discovery loop (`O == "Y"` filter), watermark probe (50-miss stop, hit-and-continue, GE+date validation gate, non-GE hit skipped), `sync_tx_races` upsert logic
- **test_tx_adapter.py** — mock client; test version cache hit (unchanged), statewide rows, county rows, `complete_unofficial` vs `unofficial` detection, missing `tx_election_id` graceful return
- **Frozen fixtures** — sanitized real responses from known 2026 elections (SD4 special `56181`, Republican Runoff subset `58315`) used in client and mapper tests to validate the full base64 decode pipeline against actual API response shapes, not just constructed mocks

---

## Open Questions / Risks

- **`county_mid` vs FIPS:** `MID` values observed are 48xxx (Texas FIPS range). Store as `county_mid` in `raw`; validate against a Texas county FIPS table during implementation before promoting to `county_fips`. If confirmed, rename in a follow-up.
- **Cloudflare tightening:** Standard `requests` has worked so far. If active challenges appear, may need a rotating proxy (same pattern as `IA_SOS_PROXY_URL`).
- **November General timing:** Expected September–October 2026. The probe watermark catches it within 24 hours of registration. All discovered elections (specials, locals, county) are ingested and tagged; `is_target_general_2026=True` gates full race/results processing for the November General specifically.
- **`is_winner` field:** ENR does not expose a winner flag. Leave `is_winner=None` on all rows; winner determination handled downstream.
- **`official` result_type:** Currently no certification flag observed in ENR. Use `complete_unofficial` when all precincts report. Revisit when the General is live — if GoElect adds a certified flag, promote to `official` at that point.
