# US State Election Results Data Access — Master Index

**Researched:** March 4, 2026
**Coverage:** 48 states (excludes TX and MA, which were pre-existing)
**Purpose:** Document official election results data access methods (APIs, CSV/Excel downloads, data feeds, web portals) for each state

---

## Coverage Definitions

Coverage terminology follows `docs/design/COVERAGE-CLARIFICATION.md`.

### Full Core Coverage

A state has Full Core Coverage when CivicMirror can reliably:

- Discover federal elections
- Create federal races
- Ingest federal results
- Discover statewide elections
- Create statewide races
- Ingest statewide results
- Create state legislative races
- Ingest state legislative results

Local elections, precinct reporting, historical backfills, candidate biographies, GIS boundaries, and ballot measure enhancements are tracked separately and are not required for Full Core Coverage.

### Enhanced Coverage

Additional capabilities beyond Core Coverage:

- Local elections
- Ballot measures
- Precinct-level reporting
- Historical backfill
- Candidate biography/contact information
- GIS boundaries
- Live election-night reporting

---

## States by Data Access Sophistication

[Existing research sections retained]

---

## Quick Reference: All 48 States

[Existing reference table retained]

---

## CivicMirror Integration Coverage

Tracks Stage 1 (Election Discovery + Race Creation) and Stage 2 (Results Ingestion) implementation status per state.

**Stage 1** covers pre-election seeding: elections discovered, races created, candidates linked. Adapters run on a daily schedule and populate the DB before election night.

**Stage 2** covers results ingestion: a results adapter polls the state source on election night and post-election, writing vote totals to the DB. Stage 2 can exist independently of Stage 1 — for Clarity sweep states, elections and races come from Civic API while the results adapter handles ingestion.

| Code | State | Stage 1 — Election Discovery | Stage 1 — Race Creation | Stage 2 — Results Ingestion | Core Coverage |
|------|-------|------------------------------|-------------------------|-----------------------------|---------------|
| **WV** | West Virginia | ✅ Complete | ✅ Complete | ✅ Complete (Clarity) | Full Core |
| **CO** | Colorado | ✅ Complete | ✅ Complete | ✅ Complete (CO SOS) | Full Core |
| **SC** | South Carolina | ✅ Complete | ✅ Complete | ✅ Complete (SC VREMS + Clarity) | Full Core |
| **VA** | Virginia | ✅ Complete | ✅ Complete | ✅ Complete (VA ELECT ENR) | Full Core |
| **AZ** | Arizona | ✅ Complete | ✅ Complete | ✅ Complete (AZ SOS XML) | Full Core |
| **MA** | Massachusetts | ✅ Complete | ✅ Complete | ✅ Complete (MA SOS) | Full Core |
| **WA** | Washington | ✅ Complete | ✅ Complete | ✅ Complete (VoteWA ENR) | Full Core |
| **FL** | Florida | ✅ Complete | ✅ Complete | ✅ Complete (FL Election Watch) | Full Core |
| **TX** | Texas | ✅ Complete | ✅ Complete | ✅ Complete (GoElect ENR) | Full Core |
| **IL** | Illinois | ✅ Complete | ✅ Complete | ✅ Complete (IL SBE CSV) | Full Core |
| **NC** | North Carolina | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (NCSBE S3) | Near Core |
| **NY** | New York | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (Flateau DB) | Near Core |
| **CA** | California | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (CA SOS) | Near Core |
| **NJ** | New Jersey | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (multi-county Clarity, ~16/21 counties) | Near Core (partial) |
| **MN** | Minnesota | ⚠️ POC election upsert | ✅ Complete for federal/state result-file scope | ✅ Complete (MN SOS flat files) | Near Core (partial) |
| **OR** | Oregon | ✅ Complete for current statewide election | ✅ Complete for core skeleton/candidates | ⚠️ Partial (structured certified files; no live statewide feed) | Near Core (partial) |
| **GA** | Georgia | ✅ Complete | ✅ Complete | ✅ Complete (Enhanced Voting API) | Full Core |
| **MI** | Michigan | ✅ Complete | ✅ Complete | ✅ Complete (MVIC) | Full Core |
| **PA** | Pennsylvania | ✅ Complete | ✅ Complete | ✅ Complete (electionreturns.pa.gov) | Full Core |
| **KY** | Kentucky | ✅ Complete | ✅ Complete | ❌ Not implemented | Stage 1 Coverage |
| **IA** | Iowa | ✅ Complete | ✅ Complete | ⚠️ Adapter built, needs production wiring | Near Core |
| **AL** | Alabama | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (AL SOS ENR Excel export) | Results Adapter |
| **AR** | Arkansas | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (TotalVote ENR) | Results Coverage Only |
| **CT** | Connecticut | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (PCC EMS) | Results Coverage Only |
| **AK, DE, HI, ID, IN, KS, LA, ME, MS, MT, ND, NE, NH, NV, OK, RI, SD, WI, WY** | Clarity sweep (19 states) | ✅ Available (Civic API) | ⚠️ Untested | ✅ Adapter available (Clarity) | Results Coverage Only |
| **OH** | Ohio | ✅ Available (Civic API) | ⚠️ Untested | ⚠️ Pending CF solver deploy (Clarity ENR) | Near Core (adapter built, CF solver required) |
| **TN** | Tennessee | ✅ Complete | ✅ Complete | ⚠️ Certified XLSX adapter; live dashboard pending active-election transport capture | Near Core (partial) |
| **VT** | Vermont | ✅ Complete (vt_sos) | ✅ Complete (vt_sos, incl. contest_variant primary disambiguation) | ✅ Complete (VT static JSON feed, statewide/district totals) | Full Core |
| **MD** | Maryland | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (county CSVs, statewide offices; 2024 general historical snapshot only) | Results Coverage Only |
| **MO** | Missouri | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (Grand Totals PDF via pdfplumber, statewide top-of-ticket; 2024 general only) | Results Coverage Only |
| **NM** | New Mexico | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (BPro TotalVote election-wide CSV, hyper-local municipal election data; Civera ElectionStats deferred, issue #84) | Results Coverage Only |
| **UT** | Utah | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (EnhancedVotingAdapter subclass, same platform as GA/VA/WA; statewide `ballotItems` only) | Results Coverage Only |
| All others | — | ✅ Available (Civic API) | ⚠️ Untested | ❌ No adapter | Federal Only |

---

## Core Coverage Status

Coverage terminology follows `docs/design/COVERAGE-CLARIFICATION.md` and `docs/adr/ADR-005-COVERAGE-DEFINITION.md`.

### Full Core Coverage

Stage 1 and Stage 2 complete for Federal and State offices. Election discovery, race creation, and results ingestion all wired and active in production.

- Arizona (AZ) — AZ SOS XML feed
- Colorado (CO) — CO SOS adapter
- Florida (FL) — FL Election Watch
- Georgia (GA) — Enhanced Voting API
- Illinois (IL) — IL SBE CSV adapter
- Massachusetts (MA) — MA SOS adapter
- Michigan (MI) — MVIC + BOE candidate listings
- Pennsylvania (PA) — PA SOS candidate lists + electionreturns.pa.gov
- South Carolina (SC) — SC VREMS + Clarity
- Texas (TX) — GoElect ENR
- Vermont (VT) — vt_sos (static JSON feed; statewide-only scope, local elections deferred)
- Virginia (VA) — VA ELECT ENR
- Washington (WA) — VoteWA ENR
- West Virginia (WV) — Clarity

### Near Core Coverage

Stage 2 results adapter is complete and active. Stage 1 race creation relies on Civic API (untested for all state offices) or has a production wiring gap.

- California (CA) — results adapter built; race creation depends on Civic API
- Iowa (IA) — Stage 1 complete; Stage 2 adapter built but production wiring incomplete
- Kentucky (KY) — Stage 1 SOS election/race/candidate ingestion complete; results ingestion remains open
- Minnesota (MN) — results adapter built for SOS semicolon-delimited flat files; `sync_mn_races` seeds the scoped federal/state race/candidate set from the same official files. Election discovery is still a POC/upsert path, not a full election-manifest adapter.
- New Jersey (NJ) — results adapter built (multi-county Clarity sweep, ~16 of 21 counties); 5 off-platform counties (Bergen, Camden, Sussex, Warren, Hunterdon) deferred. Includes office/candidate name normalization to handle cross-county inconsistency. See `docs/state-research/NJ/NJ-Election_Research.md`.
- New York (NY) — results adapter built (Flateau DB); race creation depends on Civic API
- North Carolina (NC) — results adapter built (NCSBE S3); race creation depends on Civic API
- Oregon (OR) — Stage 1 current-election/race/candidate/local-measure sync built from Oregon SOS + ORESTAR sources; Stage 2 parses structured certified result documents when discoverable or when `or_results_url` is present. PDF/legacy XLS and statewide live results remain out of scope.

### Results Coverage Only

Stage 2 results adapter available. No dedicated Stage 1 adapter — elections and races come from Civic API, which may be incomplete for state primaries.

- Arkansas (AR) — TotalVote ENR
- Alabama (AL) — Stage 2 ENR Excel export adapter; Stage 1 still Google Civic/manual until state candidate/race source is implemented. Requires `source_metadata["al_ecode"]` until ecode discovery is built.
- Connecticut (CT) — PCC EMS
- Maryland (MD) — county CSVs, statewide offices, 2024 general historical snapshot only (PR #82)
- Missouri (MO) — Grand Totals PDF (pdfplumber), statewide top-of-ticket, 2024 general only (PR #83)
- New Mexico (NM) — BPro TotalVote election-wide CSV, hyper-local municipal election data (PR #85); Civera ElectionStats deferred, issue #84
- Utah (UT) — EnhancedVotingAdapter subclass (same platform as GA/VA/WA), statewide `ballotItems` only (PR #86)
- Clarity sweep states (AK, DE, HI, ID, IN, KS, LA, ME, MS, MT, ND, NE, NH, NV, OK, RI, SD, WI, WY) — requires `results_url` set per election in Django admin

**Current focus (issue #87):** migrate CA, NC, NY (results adapters already built, closest to Full Core) and then MD/MO/NM/UT up to Full Core by building native Stage 1 adapters, replacing Civic API's role in election/race creation — not by adding more Results-Coverage-Only states. Vermont (VT) completed this migration 2026-07-22 and has moved to Full Core above.

### Research/Build Scaffold

Research or parser/client scaffolding exists, but a scheduled Stage 1 ingestion task and/or Stage 2 results adapter is not yet implemented.

- (none currently — Tennessee moved to Near Core (partial) above once its certified-XLSX results adapter and Stage 1 sync tasks shipped, PR #43 2026-07-15; live dashboard polling still deferred until an active-election HAR capture)

### Pending External Deploy

Adapter(s) built and code-complete, blocked only on infrastructure/deploy rather than a missing data source:

- **Ohio (OH)** — Stage 1 adapter built (`integrations/oh_sos/`) using CFDISCLOSURE `ACT_CAN_LIST.CSV` (765 candidates, daily). Stage 2 uses Clarity ENR (`liveresults.boe.ohio.gov`, added to `CLARITY_PROXY_HOSTS`). Both sources require the CF solver microservice (`cloudflare/cf-solver/`) deployed as a Cloud Run service with `CF_SOLVER_URL` + `CF_SOLVER_SECRET` set. CF bypass confirmed working (nodriver+xvfb, 2026-06-28). Task: `sync-oh-sos`. Federal races via Civic API (15-address config). See `docs/state-research/OH/OH-Election_Research.md`.

### Federal Only (no adapter)

Elections available via Civic API for federal contests; no state-level adapter built. All remaining states fall here until a dedicated adapter is shipped.

---

## Enhanced Coverage Tracking

The following capabilities are tracked independently from Core Coverage:

- Local elections
- Ballot measures
- Precinct reporting
- Historical backfill
- Candidate biography/contact information
- GIS boundaries
- Live reporting enhancements

A state may have Full Core Coverage while still having gaps in Enhanced Coverage areas.

---

## Key Findings

1. Only California has a full official REST API for election results.
2. Michigan has a community-built REST API.
3. Connecticut and Pennsylvania offer Socrata/SODA APIs.
4. Virginia provides highly structured JSON election data.
5. North Carolina has one of the strongest public results data systems.
6. Most states still rely on downloadable files rather than public APIs.
7. Federal and State office coverage remain the primary CivicMirror objective.
8. Local election coverage should be considered an enhancement rather than a requirement for state completion.
