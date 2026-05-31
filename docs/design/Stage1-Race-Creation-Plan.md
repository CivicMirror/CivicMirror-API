# Stage 1 Race Creation — Research & Build Plan

**Created:** 2026-05-23  
**Status:** P1 ✅ P2 ✅ P4-IA ✅ — P3 (PA) blocked on data, P4-MI blocked on 503  
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
| `backend/results/tasks.py` | `ingest_official_results` — now auto-bootstraps races when 0 exist |
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
| **Clarity Elections** | ✅ Self-bootstrapping | bootstrap added to `ingest_official_results` (P2 ✅) |
| **SC Clarity** | ✅ Confirmed | HTTP 200 on ENR infrastructure; adapter built |
| **IA Clarity** | ✅ Confirmed | HTTP 200, live 2025/2026 data; adapter built (P4-IA ✅) |
| **NM, MT, CT, MD, NJ, NE** | ❌ 404 | All return 404 — not on Clarity infrastructure |
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

### 🔴 Priority 1 — SC Clarity ✅ CONFIRMED & ADAPTER BUILT (2026-05-24)
- `https://results.enr.clarityelections.com/SC/` returns HTTP 200; `elections.json` returns `[]` (normal pre-election state — data typically appears on or near election night)
- `backend/results/adapters/sc.py` — `SouthCarolinaAdapter` added (5-line Clarity subclass)
- `backend/results/apps.py` — `sc` added to `ResultsConfig.ready()` imports
- **Admin action required:** Set `results_url` on the SC election in Django admin once SC publishes their Clarity link (watch `https://scvotes.gov` on/before Jun 9)

### 🟠 Priority 2 — Clarity self-bootstrap ✅ BUILT (2026-05-24)
- `backend/results/tasks.py` — `ingest_official_results` now calls `_bootstrap_races_from_results()` when no races exist
- `_bootstrap_races_from_results()`: groups result rows by `office_title`, detects race type via title keywords (amendment/measure/proposition/etc.), creates `Race`/`Candidate`/`MeasureOption` rows inside `transaction.atomic()` with `select_for_update()` serialisation
- Stale version cache fix: if no races exist, the task clears any cached Clarity version before calling `fetch_results()` to prevent the `unchanged=True` short-circuit from blocking bootstrap
- Version cache now only written after at least one race was processed
- `Race.Source.RESULTS_ADAPTER` added; migration `0005` generated
- Benefits WV, CO, SC, IA immediately (retroactive fill when `results_url` is set)
- 11 new tests added to `backend/results/tests/test_tasks.py`

### 🟡 Priority 3 — PA Socrata adapter
- Source: `https://data.pa.gov/` Socrata SODA API
- **BLOCKED**: 2026 primary data (May 19) not yet published; historical dataset IDs (`9ej9-wkqp`, etc.) return 404 via SODA API
- Dataset ID for election results changes per cycle — must look up on data.pa.gov when 2026 data drops
- Build `backend/integrations/pa/` as combined Stage 1+2 adapter when data is available (~2-4 weeks post-election)

### 🟢 Priority 4 — Michigan adapter
- Wait for `michiganelections.io` to come back online (503 as of 2026-05-24)
- API endpoints:
  - `GET /api/elections/` — list elections
  - `GET /api/positions/?election_id=X` — race/office entries with candidates
  - `GET /api/proposals/?election_id=X` — ballot measures
- Build `backend/integrations/mi/` — genuine Stage 1 (pre-election capable)
- Accept header required: `Accept: application/json; version=2.0`

### 🔵 Priority 5 — Iowa Clarity adapter ✅ BUILT (2026-05-24)
- `https://results.enr.clarityelections.com/IA/` confirmed HTTP 200; live 2025/2026 election data
- `backend/results/adapters/ia.py` — `IowaAdapter` added (5-line Clarity subclass)
- `backend/results/apps.py` — `ia` added to imports
- **Verified not on Clarity:** NM, MT, CT, MD, NJ, NE — all return 404

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
