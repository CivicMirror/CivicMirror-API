# Phase 3: Remaining States — Election, Race, Candidate & Results Coverage

## Context

Phase 2 complete as of 2026-05-31: all 10 source adapters route through the aggregation ingest layer. Ten states are fully active (CA, WV, CO, SC, MA, VA, IA + Civic/FEC/OpenStates as enrichment). 40+ states have no race/results coverage beyond what Google Civic API happens to provide.

**Driving deadline:** Summer 2026 primary wave — NJ June 3, NY June 25, AZ July 28, WA/MI August 4, FL August 18 — then the November 2026 general. Results coverage before each primary date is the priority.

**Scope:** Statewide races (governor, legislature, US Congress, statewide ballot measures) + county-level when a state's data portal naturally exposes local races in the same feed without extra work.

**Architecture decisions that govern this work:** See `docs/adr/ADR-007-Phase3-State-Expansion.md`.

---

## Three-Tier Adapter Model

| Tier | What it builds | Effort | When to use |
|---|---|---|---|
| **A — Clarity-only** | `results/adapters/XX.py` (2 lines) | 1–2 hrs | State uses Clarity ENR; elections/races come from Civic API |
| **B — Full SOS adapter** | `integrations/XX_sos/` + results adapter | 2–5 days | State has a structured programmatic source (REST, FTP, Socrata) |
| **C — Civic-only** | Nothing new | 0 hrs | No good programmatic source; Civic API populates what it can |

---

## Group 1: Clarity Sweep (highest ROI — ship first)

Probe each candidate state before building. A confirmed state is a 2-line adapter:

```python
# backend/results/adapters/XX.py
from .clarity import ClarityAdapter
from .registry import register

@register
class XXAdapter(ClarityAdapter):
    state = "XX"
```

**Probe results (completed 2026-05-31):**

| State | Probe Result | Tier |
|---|---|---|
| NJ | ⚠️ County-level Clarity only — no state aggregator | B (Nov 2026) |
| KY | ❌ nginx 403 — does NOT use Clarity | Needs research |
| AR | ❌ nginx 403 — does NOT use Clarity → TotalVote/TotalResults REST API | ✅ Tier B complete (PR #10, 2026-06-01) |
| NV | ✅ Clarity confirmed | A |
| NH | ✅ Clarity confirmed | A |
| DE | ✅ Clarity confirmed | A |
| AK | ✅ Clarity confirmed | A |
| OK | ✅ Clarity confirmed | A |
| LA | ✅ Clarity confirmed | A |
| ND | ✅ Clarity confirmed | A |
| WY | ✅ Clarity confirmed | A |
| NE | ✅ Clarity confirmed | A |
| MS | ✅ Clarity confirmed | A |
| KS | ✅ Clarity confirmed | A |
| IN | ✅ Clarity confirmed | A |
| ID | ✅ Clarity confirmed | A |
| MT | ✅ Clarity confirmed | A |
| SD | ✅ Clarity confirmed | A |
| RI | ✅ Clarity confirmed | A |
| ME | ✅ Clarity confirmed | A |
| HI | ✅ Clarity confirmed | A |
| VT | ✅ Clarity confirmed | A |
| WI | ✅ Clarity confirmed | A |

**All 20 Tier A Clarity adapters complete** (commit a938bd2). **KY** still needs a separate research pass — does not use Clarity. **AR** resolved — TotalVote/TotalResults Tier B adapter shipped (PR #10).

After confirming per state:
1. Create `backend/results/adapters/XX.py`
2. Set `results_url` in Django admin per election when that election goes live
3. `poll-pending-results` picks it up automatically — no scheduler change needed

---

## Group 2: Full Adapters — Summer Primary States

Ordered by primary date.

### NJ — New Jersey (November 2026 general — Tier B)

- ~~June 3 primary~~ — too complex to ship in time; moved to November general target
- **Finding (2026-05-31):** NJ uses Clarity at county level — 13 of 21 counties confirmed, no state-level aggregator. A thin `ClarityAdapter` won't work.
- **Required:** Custom multi-county Clarity adapter that reads the per-county election IDs from `nj.gov/state/elections/election-night-results.shtml`, fetches each county's `summary.json`, and aggregates statewide vote totals.
- June 3 county IDs documented in `docs/state-research/NJ/NJ-Election_Research.md`
- **Adapter complexity:** Medium-high — parallel county fetches + vote aggregation across 13+ counties

### NY — New York (June 25 primary)

- Flateau Act (effective April 2026) mandates election district-level data
- Source: `data.ny.gov` Socrata/SODA or `elections.ny.gov` portal
- Verify Clarity first; if not, build Tier B using Socrata SODA pattern
- Research doc: `docs/state-research/NY/NY-Election_Research.md`

### AZ — Arizona (July 28 primary) ✅ Complete

- **Implemented:** HTTPS XML feed at `https://apps.azsos.gov/ftp/ElectionResults/{year}/State/{election_name}/Results.Summary.xml` (HTTP 200 confirmed; original FTP plan superseded)
- Stage 1 (`sync_az_elections`): seeds Election records, fingerprints candidate list HTML, upserts Race + Candidate records for FEDERAL + STATE branches; deduplicates by `az_candidate_id`
- Stage 2 (`az.py`): polls XML feed; `az_election_name` auto-derived from election type; `fileId` change detection avoids redundant ingestion
- Scheduler: `sync-az-sos` daily at 05:00 Phoenix time (`0 5 * * *`, `America/Phoenix`)
- Research doc: `docs/state-research/AZ/AZ-Election_Research.md`

### WA — Washington (August 4 primary) ✅ Complete

- **Implemented:** VoteWA Enhanced Voting ENR API (`api.votewa.gov`)
- Stage 1 (`sync_wa_votewa`): county fan-out via `localityElections[]`; `enr_slug` stored per election; version-cached via `asOf` / `lastUpdated`
- Stage 2 (`wa.py`): polls per-county ENR; `EnhancedVotingAdapter` base; `county_slug` extracted from `jurisdiction.shortName`
- Scheduler: `sync-wa-votewa` daily at 03:00 UTC
- Research doc: `docs/state-research/WA/WA-Election_Research.md`
- Core Coverage: **Full Core**

### MI — Michigan (August 4 primary) ✅ Complete

- **Implemented:** BOE candidate listings for Stage 1 plus MVIC official results ingestion.
- Stage 1 (`sync_mi_elections`): seeds Michigan primary/general elections, races, and candidates from BOE listings.
- Stage 2 (`mi.py`): polls MVIC bulk tab-delimited results with county HTML fallback.
- Research doc: `docs/state-research/MI/MI-Election_Research.md`

### FL — Florida (August 18 primary) ✅ Complete

- **Implemented:** Florida Election Watch file downloads (tab-delimited; URL pattern `dos.myflorida.com/results/`)
- Stage 1 (`sync_fl_elections`): discovers and upserts elections + races + candidates from EW export files
- Stage 2 (`fl.py`): polls same export files for vote totals; idempotency via file hash comparison
- Scheduler: `sync-fl-ew` daily at 04:00 UTC
- Research doc: `docs/state-research/FL/FL-Election_Research.md`
- Core Coverage: **Full Core**

---

## Group 3: Full Adapters — November 2026 General Wave

Build or finalize for the November 3, 2026 general election:

| State | Source | Status | Notes |
|---|---|---|---|
| **TX** | CivixApps GoElect ENR | ✅ Complete (2026-06-17) | Public JSON API, AWS S3-backed; base64-encoded fields; sequential ID probe for election discovery; `sync-tx-goelect` at 05:00 UTC; Full Core Coverage |
| **NC** | NCSBE S3 precinct ZIP | ✅ Adapter built | `nc.py` shipped early; weekly updates; high value; race creation depends on Civic API |
| **GA** | Georgia SOS Enhanced Voting API | ✅ Complete (2026-07-15) | Stage 1 election/race/candidate sync via `sync-ga-sos`; Stage 2 `ga.py`; Full Core Coverage |
| **OH** | XLSX downloads (DATA Act 2023) | ⏳ Research needed | Daily county snapshots from 88 counties |
| **PA** | PA SOS + `electionreturns.pa.gov` | ✅ Complete (2026-07-15) | Stage 1 candidate-list sync via `sync-pa-sos`; Stage 2 `pa.py`; Full Core Coverage |
| **IL** | `elections.il.gov` Vote Total Search | ⏳ Research needed | 1998–present |
| **CT** | ~~Socrata `data.ct.gov`~~ PCC EMS `ctemspublic.tgstg.net` | ✅ Adapter shipped (PR #11, 2026-06-01) | TotalVote transition expected pre-Nov 2026; repoint `source_metadata` to `totalvote_election_id` when live |
| **MN** | Downloads + interactive dashboard | ⏳ Research needed | `sos.mn.gov` |
| **OR** | Downloads | ⏳ Research needed | High ballot-measure activity |
| **KY** | Kentucky SOS | ✅ Stage 1 complete (2026-07-15) | `sync-ky-sos` seeds elections/races/candidates; results ingestion still future work |
| **TN** | Tennessee SOS / ENR | 🧱 Scaffolded | Parser/client scaffolding exists; scheduled Stage 1 task and results adapter still future work |

---

## Group 4: Civic Representative Addresses (quick infrastructure win)

**File:** `backend/integrations/civic/addresses.py` — `REPRESENTATIVE_ADDRESSES` dict

Currently only a subset of states have sample addresses configured. Adding one address per remaining state ensures Civic API returns elections + races for every state where Google has VIP data — no adapter work required.

---

## Implementation Checklist Per Tier

### Tier A — Clarity-Only Adapter

- [ ] Probe Clarity endpoint to confirm state uses it
- [ ] Create `backend/results/adapters/XX.py` (2 lines, inherit `ClarityAdapter`)
- [ ] Set `results_url` in Django admin for active elections when they go live
- [ ] Confirm `poll-pending-results` picks up the state

### Tier B — Full SOS Adapter

- [ ] Confirm data source URL and format from `docs/state-research/XX/`
- [ ] `backend/integrations/XX_sos/exceptions.py` — `XXError`, `XXRetryableError`
- [ ] `backend/integrations/XX_sos/client.py` — HTTP/FTP client with retry
- [ ] `backend/integrations/XX_sos/parsers.py` — raw response → Python dicts
- [ ] `backend/integrations/XX_sos/mappers.py` — `infer_election_type()`, `map_election()`, `map_race()`, `map_candidate()`; use `source_id or canonical_key or ""` pattern for any `build_canonical_key` calls
- [ ] `backend/integrations/XX_sos/tasks.py` — Stage 1 (`sync_XX_elections`) + Stage 2 (`sync_XX_candidates`); SyncLog; fingerprint-based change detection; withdrawn-candidate sweep
- [ ] Add `Race.Source.XX_SOS = 'xx_sos'` to `backend/elections/models.py`
- [ ] Append precedence rows to `backend/aggregation/migrations/_seed_data.py`
- [ ] Create `backend/aggregation/migrations/00NN_seed_xx_sos_precedence.py`
- [ ] Register endpoint in `backend/internal/views.py` and `backend/internal/urls.py`
- [ ] Create Cloud Scheduler job (daily for most states; match `sync-ia-sos` as template)
- [ ] Results adapter: `backend/results/adapters/XX.py` (Clarity wrapper or custom)
- [ ] Tests: mapper unit tests + 2 DB integration tests minimum
- [ ] Deploy → trigger manually → verify canonical rows in API

---

## Precedence Row Template for New State

```python
# backend/aggregation/migrations/_seed_data.py — append:
    ("XX", "results",  "xx_sos",   0),
    ("XX", "results",  "civic_api", 1),
    ("XX", "date",     "xx_sos",   0),
    ("XX", "date",     "civic_api", 1),
    ("XX", "contacts", "civic_api", 0),
    ("XX", "contacts", "xx_sos",   1),
    ("XX", "identity", "civic_api", 0),   # flip to xx_sos=0 if no Civic VIP coverage
    ("XX", "identity", "xx_sos",   1),
```

---

## Key Reference Files

| File | Purpose |
|---|---|
| `backend/integrations/ia_sos/tasks.py` | Canonical two-stage task pattern |
| `backend/integrations/ia_sos/mappers.py` | `infer_election_type`, `map_race`, mapper conventions |
| `backend/aggregation/ingest.py` | `ingest_election/race/candidate` call signatures |
| `backend/aggregation/migrations/_seed_data.py` | Precedence row accumulation |
| `backend/aggregation/migrations/0007_seed_ia_sos_precedence.py` | Migration file template |
| `backend/results/adapters/clarity.py` | `ClarityAdapter` base class |
| `backend/results/adapters/co.py` | Minimal Clarity thin wrapper (2 lines) |
| `backend/internal/views.py` | Task endpoint registration pattern |
| `docs/state-research/` | Per-state data source research (one folder per state) |

---

## Verification Per Deployed State

```bash
INTERNAL_TOKEN=$(gcloud secrets versions access latest --secret=INTERNAL_TASK_TOKEN --project=civicmirror-2026)
API_KEY=$(gcloud secrets versions access latest --secret=CIVICMIRROR_API_KEY --project=civicmirror-2026)

# 1. Trigger sync
curl -s -X POST "https://api.civicmirror.welshrd.com/internal/tasks/sync-XX-sos/" \
  -H "Authorization: Bearer $INTERNAL_TOKEN"

# 2. Verify canonical rows exist with this state as a source
curl -s "https://api.civicmirror.welshrd.com/api/elections/?state=XX" \
  -H "X-Api-Key: $API_KEY" | python3 -m json.tool | grep -E "canonical_key|sources"

# 3. Trigger results poll (after setting results_url in admin)
curl -s -X POST "https://api.civicmirror.welshrd.com/internal/tasks/poll-results/" \
  -H "Authorization: Bearer $INTERNAL_TOKEN"
```

Expected: `canonical_key` is non-null; `sources` array contains `"xx_sos"`.

---

## Out of Scope for Phase 3

- Post-election certified results ingestion (OpenElections/MEDSL) — separate project
- Candidate bios, contact info, photos — no state provides this programmatically
- Municipal/school board elections — no state portal reliably exposes these in the same feed
- Drop `Election.source_id` — tracked in `docs/future-features.md`
