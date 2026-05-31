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

**States to probe — verify Clarity before building:**

| State | Notes |
|---|---|
| NJ | Primary June 3 — probe immediately |
| KY | High probability Clarity |
| NV | High probability Clarity |
| NH | High probability Clarity |
| DE | High probability Clarity |
| AK | High probability Clarity |
| OK | High probability Clarity |
| LA | High probability Clarity |
| ND | Investigate |
| WY | Investigate |
| NE | Investigate |
| MS | Investigate |
| KS | Investigate |
| IN | Investigate |
| ID | Investigate |
| MT | Investigate |
| SD | Investigate |
| RI | Investigate |
| ME | Investigate |
| AR | Investigate |
| HI | Investigate |
| VT | Investigate |
| WI | Investigate |

**Probe command:**
```bash
# Replace STATE and electionId with a recent election from that state
curl -s "https://results.enr.clarityelections.com/{STATE}/{electionId}/current_ver.txt"
# Version string = Clarity confirmed. 404/empty = not on Clarity.
```

After confirming:
1. Create `backend/results/adapters/XX.py`
2. Set `results_url` in Django admin per election when that election goes live
3. `poll-pending-results` picks it up automatically — no scheduler change needed

---

## Group 2: Full Adapters — Summer Primary States

Ordered by primary date.

### NJ — New Jersey (June 3 primary — URGENT)

- Primary: June 3, 2026
- **First:** Verify Clarity (probe `results.enr.clarityelections.com/NJ/...`). If confirmed → Tier A, ship today.
- If not Clarity: source is `electionresults.nj.gov` — needs research
- No existing `integrations/nj_*`

### NY — New York (June 25 primary)

- Flateau Act (effective April 2026) mandates election district-level data
- Source: `data.ny.gov` Socrata/SODA or `elections.ny.gov` portal
- Verify Clarity first; if not, build Tier B using Socrata SODA pattern
- Research doc: `docs/state-research/NY/NY-Election_Research.md`

### AZ — Arizona (July 28 primary)

- **Tier 1 source:** FTP XML feed at `ftp://ftp.azsos.gov/ElectionResults/` — real-time (<2 min on election night)
- Not on Clarity — requires custom results adapter
- Build Tier B: FTP XML client + parser + mapper + Stage 1/2 tasks
- Research doc: `docs/state-research/AZ/AZ-Election_Research.md`

### WA — Washington (August 4 primary)

- Structured CSV/Excel downloads from `sos.wa.gov`
- All mail-in state — results on a known schedule
- Build Tier B when data format confirmed
- Research doc: `docs/state-research/WA/WA-Election_Research.md`

### MI — Michigan (August 4 primary)

- REST API at `michiganelections.io` — currently returning 503 (offline as of 2026-05-23)
- Monitor for recovery; `/positions`, `/proposals` endpoints give races
- Build Tier B when API is back online
- Research doc: `docs/state-research/MI/MI-Election_Research.md`

### FL — Florida (August 18 primary)

- Florida "Election Watch" — Excel/tab-delimited/pipe-delimited downloads
- Precinct-level data available from 2012
- Build Tier B: file download + parse + ingest
- Research doc: `docs/state-research/FL/FL-Election_Research.md`

---

## Group 3: Full Adapters — November 2026 General Wave

After summer primaries are covered, build for the November 2026 general election:

| State | Source | Notes |
|---|---|---|
| **TX** | `sos.state.tx.us` downloads | Large state (30M voters); research needed |
| **NC** | FTP site + election night dashboard (5–10 min) | Weekly updates; high value |
| **GA** | Partial Clarity + state portal | Verify Clarity scope first |
| **OH** | XLSX downloads (DATA Act 2023) | Daily county snapshots from 88 counties |
| **PA** | Socrata `data.pa.gov` | Awaiting 2026 data publication |
| **IL** | `elections.il.gov` Vote Total Search | 1998–present |
| **CT** | Socrata `data.ct.gov` | Historical 1787+; verify Clarity too |
| **MN** | Downloads + interactive dashboard | `sos.mn.gov` |
| **OR** | Downloads | High ballot-measure activity |

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
