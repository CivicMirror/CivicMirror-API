# Stage 1 Race Creation — Research & Build Plan

**Created:** 2026-05-23  
**Status:** Research complete, implementation not started  
**Problem:** Many elections in the DB have 0 associated races because the Google Civic API has no data for most state primaries.

---

## The Two-Stage Pipeline

```
Stage 1: Race Creation          Stage 2: Results Ingestion
─────────────────────           ──────────────────────────
"What races exist?"             "Who got how many votes?"
runs: before/during election    runs: election night + after

Current Stage 1 sources:        Current Stage 2 sources:
  • Google Civic API              • Clarity adapter (WV ✅, CO ✅)
  • FEC API (federal only)
  • OpenStates (enrichment only,
    no race creation)
```

**Root cause of missing races:** Civic API only provides data for states where Google loads VIP feed data. CA, WV, LA work. OR, NE, PA, ID, AL, MT, SC, TX do not.

---

## Current Production State (as of 2026-05-23)

| Election ID | State | Election | Races | Status |
|---|---|---|---|---|
| 8 | CA | CA Primary | **38** ✅ | Civic API works |
| 2 | WV | WV Primary | **14** ✅ | Civic API works |
| 12 | LA | LA Primary | **9** ✅ | Civic API works |
| 5 | NE | NE Primary (May 12) | **0** ❌ | Past — no free source |
| 3 | OR | OR Primary (May 19) | **0** ❌ | Past — no free source |
| 6 | PA | PA Primary (May 19) | **0** ❌ | Past — Socrata available |
| 14 | AL | AL Primary | **0** ❌ | Past — no free source |
| 10 | ID | ID Primary | **0** ❌ | Past — no free source |
| 11 | MT | MT Primary | **0** ❌ | Upcoming — Clarity unverified |
| 4 | SC | SC Primary (Jun 9) | **0** ❌ | **UPCOMING — Clarity unverified** |
| 7/9 | TX | TX Runoffs | **0** ❌ | Past — no free source |
| 13 | DC | DC Primary | **0** ❌ | Upcoming |

---

## Reference Code Locations

| File | Description |
|---|---|
| `Adaptors/adapters/ca.py` | Stage 2 stub — returns empty (reference only, do not modify) |
| `Adaptors/adapters/ma.py` | Stage 2 stub — returns empty (reference only, do not modify) |
| `Adaptors/adapters/co.py` | Early Clarity Stage 2 adapter (reference only, do not modify) |
| `backend/results/adapters/wv.py` | **Active** Clarity Stage 2 adapter |
| `backend/results/adapters/co.py` | **Active** Clarity Stage 2 adapter |
| `backend/results/adapters/clarity.py` | Generic Clarity base adapter |
| `backend/results/tasks.py` | `ingest_official_results` — iterates **existing** races only |
| `backend/integrations/openstates/client.py` | `list_people()` only — no elections/candidates endpoint |

---

## Free Data Sources — Stage 1 Capability Assessment

| Source | Stage 1 Capable? | Notes |
|---|---|---|
| **Google Civic API** | ✅ Yes (limited) | Works for CA/WV/LA; no data for most state primaries |
| **FEC API** | ✅ Federal only | Creates federal races for November general election only |
| **OpenStates v3** | ❌ No | Only `/people` endpoint — current legislators, no elections |
| **michiganelections.io** | ✅ Potentially | `/positions`, `/proposals` endpoints; **offline for maintenance as of 2026-05-23** |
| **PA Socrata (data.pa.gov)** | ⚠️ Post-election | Results data — can retroactively bootstrap races |
| **Clarity Elections** | ⚠️ Post-election | Results data — can bootstrap races if task is extended |
| **SC Clarity** | ❓ Unverified | `concept.md` lists SC as Clarity state; SCVotes.gov doesn't confirm |
| **OR SOS** | ❌ Files only | No API; PDF/CSV downloads |
| **AL SOS** | ❌ Files only | No API; Excel/portal |
| **NE SOS** | ❌ Files only | No API; possibly county-level Clarity (unverified) |

---

## Key Architectural Issue

`ingest_official_results` in `backend/results/tasks.py` **requires races to exist first**.  
It iterates `Race.objects.filter(election=election)` — if 0 races, it does nothing.

### Proposed Fix: Auto-create races from results data

When `ingest_official_results` finds 0 races for an election, create them from the results rows:

1. Parse `office_title` from each `ResultRow`
2. `Race.objects.get_or_create(election=election, office_title=...)`
3. Determine `race_type` from row shape (candidate names → `CANDIDATE`; yes/no labels → `MEASURE`)
4. Create `Candidate` or `MeasureOption` rows from result data
5. Proceed with normal result ingestion

This makes the Clarity adapter self-bootstrapping — it can populate an empty election from scratch.

---

## Build Priority

### 🔴 Priority 1 — Verify SC Clarity (SC Primary Jun 9 = ~17 days away)
- Check `https://results.enr.clarityelections.com/SC/` for active 2026 primary
- If confirmed: add `backend/results/adapters/sc.py` (5-line Clarity subclass)
- Set `results_url` on SC election in Django admin
- **Blocker:** Without this, SC will be another empty election

### 🟠 Priority 2 — Extend Clarity adapter to bootstrap races
- Modify `backend/results/tasks.py` `ingest_official_results`:
  - If `Race.objects.filter(election=election).count() == 0`: auto-create from ResultRows
- Benefits WV and CO immediately (retroactive fill); SC/IA/NM when confirmed
- Test: add test for race-bootstrap path in `backend/results/tests/`

### 🟡 Priority 3 — PA Socrata adapter
- Source: `https://data.pa.gov/` Socrata SODA API
- Dataset ID for election results changes per cycle — must look up on data.pa.gov
- Build `backend/integrations/pa/` as combined Stage 1+2 adapter
- Retroactively fills the PA May 19 primary

### 🟢 Priority 4 — Michigan adapter
- Wait for `michiganelections.io` to come back online
- API endpoints:
  - `GET /api/elections/` — list elections
  - `GET /api/positions/?election_id=X` — race/office entries with candidates
  - `GET /api/proposals/?election_id=X` — ballot measures
- Build `backend/integrations/mi/` — genuine Stage 1 (pre-election capable)
- Accept header required: `Accept: application/json; version=2.0`

### 🔵 Priority 5 — Additional Clarity states (verify per election cycle)
States to check at `results.enr.clarityelections.com/{STATE}/`:
- IA, NM, NJ, NE (county-level), MT, CT, MD, SC (see Priority 1)
- Each confirmed = 5-line subclass in `backend/results/adapters/`

---

## States Without Any Free Programmatic Source

No automated adapter possible without file parsing or scraping:
**OR, AL, ID, SD, UT, VT, RI, WY, ND, MS, AR**

---

## Related Research Files

| File | Notes |
|---|---|
| `Docs/State Research/00-MASTER-INDEX.md` | State-by-state access tier reference |
| `Docs/State Research/COVERAGE-ANALYSIS-RESULTS.md` | Full 48-state gap analysis with Clarity status |
| `Docs/State Research/SC-Election_Research.md` | SC: no API, Clarity unconfirmed |
| `Docs/State Research/MI-Election_Research.md` | MI: michiganelections.io API details |
| `Docs/State Research/PA-Election_Research.md` | PA: Socrata/SODA API details |
| `Docs/ADRs/ADR-002-Scheduler-Architecture.md` | Cloud Scheduler → HTTP endpoint pattern |

---

## Session History (fixes deployed before this plan was created)

| Fix | Commit | Status |
|---|---|---|
| `election.results_url` NOT NULL crash | `ea8d4c1` | ✅ Deployed |
| `jurisdiction_level` filter on `/api/v1/races/` | `cddff9c` | ✅ Deployed |
| OpenStates `jurisdiction` bug | prior session | ✅ Deployed |
| Clarity CloudFront User-Agent | prior session | ✅ Deployed |
