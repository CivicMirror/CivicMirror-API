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

> **Reconciled against the live `/api/coverage/sync-status/` endpoint on 2026-08-10.** CT moved to Full Core after the multi-ID adapter fix (#170) was live-verified against production. NC, NY, and VT were already Full Core per this table but the live coverage page's `_FULL_CORE_STATES` set hadn't been updated to include them — fixed in the same pass. WV was the opposite case: this table already corrected WV back to Results Coverage Only on 2026-07-24 (no dedicated Stage 1 integration), but the live page's `_FULL_CORE_STATES` set still had it — that stale entry was removed in this pass too, so the live page and this table now agree on WV.
>
> **Known open mismatch:** AL's live coverage page still reports Full Core, but this table's Stage 1 — Race Creation shows `⚠️ Untested` and the row is labeled "Results Adapter." Not resolved in this pass — needs the same live-verification treatment CT just got (or the same correction WV just got) before either the doc or the live page can be trusted for AL. See issue #178 for the parallel AK/WY gap.

| Code | State | Stage 1 — Election Discovery | Stage 1 — Race Creation | Stage 2 — Results Ingestion | Core Coverage |
|------|-------|------------------------------|-------------------------|-----------------------------|---------------|
| **CO** | Colorado | ✅ Complete | ✅ Complete | ✅ Complete (CO SOS) | Full Core |
| **SC** | South Carolina | ✅ Complete | ✅ Complete | ✅ Complete (SC VREMS + Clarity) | Full Core |
| **VA** | Virginia | ✅ Complete | ✅ Complete | ✅ Complete (VA ELECT ENR) | Full Core |
| **AZ** | Arizona | ✅ Complete | ✅ Complete | ✅ Complete (AZ SOS XML) | Full Core |
| **MA** | Massachusetts | ✅ Complete | ✅ Complete | ✅ Complete (MA SOS) | Full Core |
| **WA** | Washington | ✅ Complete | ✅ Complete | ✅ Complete (VoteWA ENR) | Full Core |
| **FL** | Florida | ✅ Complete | ✅ Complete | ✅ Complete (FL Election Watch) | Full Core |
| **TX** | Texas | ✅ Complete | ✅ Complete | ✅ Complete (GoElect ENR) | Full Core |
| **IL** | Illinois | ✅ Complete | ✅ Complete | ✅ Complete (IL SBE CSV) | Full Core |
| **NC** | North Carolina | ✅ Complete (`sync_nc_elections`, S3 ENRS/ folder listing) | ✅ Complete (`sync_nc_candidates`, Candidate Filing CSV; federal + state legislative + state executive scope) | ✅ Complete (NCSBE S3) | Full Core |
| **NY** | New York | ✅ Complete (`ny_boe`, `sync_ny_elections`) | ✅ Complete (`ny_boe`, `sync_ny_races`; 433 races/1285 candidates verified) | ✅ Complete (Flateau DB, multi-county) | Full Core |
| **CA** | California | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (CA SOS) | Near Core |
| **NJ** | New Jersey | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (multi-county Clarity, ~16/21 counties) | Near Core (partial) |
| **MN** | Minnesota | ⚠️ POC election upsert | ✅ Complete for federal/state result-file scope | ✅ Complete (MN SOS flat files) | Near Core (partial) |
| **OR** | Oregon | ✅ Complete for current statewide election | ✅ Complete for core skeleton/candidates | ⚠️ Partial (structured certified files; no live statewide feed) | Near Core (partial) |
| **GA** | Georgia | ✅ Complete | ✅ Complete | ✅ Complete (Enhanced Voting API) | Full Core |
| **MI** | Michigan | ✅ Complete | ✅ Complete | ✅ Complete (MVIC) | Full Core |
| **PA** | Pennsylvania | ✅ Complete | ✅ Complete | ✅ Complete (electionreturns.pa.gov) | Full Core |
| **KY** | Kentucky | ✅ Complete | ✅ Complete | ⚠️ Built + tested (`ky.py`, XML feed), blocked by Akamai bot-protection 403 pending KY SBE IP allowlisting (issue #44) | Near Core (blocked) |
| **IA** | Iowa | ✅ Calendar live (8 elections) | ✅ Results bootstrap verified (272 races / 555 candidates) | ✅ Clarity live (555 `OfficialResult` rows) | Near Core (CF allowlist pending) |
| **AL** | Alabama | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (AL SOS ENR Excel export) | Results Adapter |
| **AR** | Arkansas | ✅ Available (Civic API) | ⚠️ Untested | ✅ Complete (TotalVote ENR) | Results Coverage Only |
| **CT** | Connecticut | ✅ Available (Civic API) | ✅ Verified (`ct.py` multi-ID adapter, one EMS election per party; `_bootstrap_races_from_results` confirmed live against 111/112 — 17 races, real candidates, 2026-08-10) | ✅ Complete (PCC EMS, dual-ID Democratic + Republican merge) | Full Core |
| **WV** | West Virginia | ✅ Available (Civic API) | ⚠️ Untested — no dedicated Stage 1 integration; race creation is Civic-API-driven like every other Clarity sweep state (see note below, corrected 2026-07-24) | ✅ Complete (Clarity) | Results Coverage Only |
| **AK, DE, HI, ID, IN, KS, LA, ME, MS, MT, ND, NE, NH, NV, OK, RI, SD, WI, WY** | Clarity sweep (19 states) | ✅ Available (Civic API) | ⚠️ Untested | ✅ Adapter available (Clarity) | Results Coverage Only |
| **OH** | Ohio | ✅ Available (Civic API) | ⚠️ Untested | ⚠️ Pending CF solver deploy (Clarity ENR) | Near Core (adapter built, CF solver required) |
| **TN** | Tennessee | ✅ Complete | ✅ Complete | ⚠️ Certified XLSX adapter; live dashboard pending active-election transport capture | Near Core (partial) |
| **VT** | Vermont | ✅ Complete (vt_sos) | ✅ Complete (vt_sos, incl. contest_variant primary disambiguation) | ✅ Complete (VT static JSON feed, statewide/district totals) | Full Core |
| **MD** | Maryland | ✅ Complete (`md_sbe`, `sync_md_elections`) | ✅ Complete (`md_sbe`, `sync_md_races`; party-split primaries) | ✅ Complete (live cycle, full office scope incl. district matching) | Near Core (pending production verification) |
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
- North Carolina (NC) — `nc_sbe`: `sync_nc_elections` (S3 ENRS/ folder listing) + `sync_nc_candidates` (Candidate Filing CSV, `Elections/{YEAR}/Candidate Filing/`); federal + state legislative + state executive scope, judicial/county/local out of scope. Built, tested, merged (PR #98) and live in production 2026-07-22.
- Vermont (VT) — vt_sos (static JSON feed; statewide-only scope, local elections deferred)
- Virginia (VA) — VA ELECT ENR
- Washington (WA) — VoteWA ENR
- New York (NY) — `ny_boe`: `sync_ny_elections` + `sync_ny_races` (Stage 1, shipped PR #100 + #123) alongside the existing Flateau results adapter (Stage 2). Promoted 2026-08-04 after 9 consecutive clean unattended daily cron runs (2026-07-26 through 2026-08-04, `ops_synclog` all `status=completed`/`error_count=0`, steady 433 races/day) with zero recurrences of the #40 `no_election_name` bug and zero candidate-match warnings; 25 `OfficialResult` rows confirmed attached to Stage-1-created races.
- Connecticut (CT) — `ct.py`: multi-ID results adapter fetches Connecticut's per-party EMS elections (e.g. 111 Democratic / 112 Republican for the 2026-08-11 primary) and merges them into one logical election, tagging rows with `party_code`/`contest_code` so `_bootstrap_races_from_results` keeps Democratic and Republican contests distinct. Previously blocked entirely — CT's election had zero races because it wasn't discovered via Civic API and the prior single-ID adapter couldn't ingest a split-party primary at all. Fixed and live-verified against production 2026-08-10: `ingest_official_results('CT', 1864)` bootstrapped 17 real races (Governor, US House, State Senate, State House, Probate) with real candidates from both party feeds. Promoted directly to Full Core — no separate Near Core interim step, since Stage 1 (race creation) and Stage 2 (results) both come from the same adapter fix.

### Near Core Coverage

Stage 2 results adapter is complete and active. Stage 1 race creation relies on Civic API (untested for all state offices) or has a production wiring gap.

- California (CA) — results adapter built; race creation depends on Civic API
- Maryland (MD) — native Stage 1 (`md_sbe`: `sync_md_elections` + `sync_md_races`, PR #152, merged 2026-08-04) and a widened Stage 2 (live cycle, full office scope, party-split primaries, district-aware result matching) both merged, but **not yet promoted to Full Core** — same bar NY cleared before its own promotion: crontab wiring in production plus several consecutive days of clean unattended `ops_synclog` runs (`sync_md_elections`/`sync_md_races`, `status=completed`/`error_count=0`) and confirmed `OfficialResult` attachment. Known follow-up, not blocking: the results adapter's archived-vs-current-cycle URL path doesn't yet flip correctly once MD archives the 2026 election post-certification.
- Iowa (IA) — 2026 primary verification created 272 races, 555 candidates, and 555 `OfficialResult` rows from Clarity. The SOS candidate PDF parser returned zero rows, and unattended results-URL discovery remains blocked until `electionresults.iowa.gov` is added to the CF proxy allowlist.
- Minnesota (MN) — results adapter built for SOS semicolon-delimited flat files; `sync_mn_races` seeds the scoped federal/state race/candidate set from the same official files. Election discovery is still a POC/upsert path, not a full election-manifest adapter.
- New Jersey (NJ) — results adapter built (multi-county Clarity sweep, ~16 of 21 counties); 5 off-platform counties (Bergen, Camden, Sussex, Warren, Hunterdon) deferred. Includes office/candidate name normalization to handle cross-county inconsistency. See `docs/state-research/NJ/NJ-Election_Research.md`.
- Oregon (OR) — Stage 1 current-election/race/candidate/local-measure sync built from Oregon SOS + ORESTAR sources; Stage 2 parses structured certified result documents when discoverable or when `or_results_url` is present. PDF/legacy XLS and statewide live results remain out of scope.

### Results Coverage Only

Stage 2 results adapter available. No dedicated Stage 1 adapter — elections and races come from Civic API, which may be incomplete for state primaries.

- Arkansas (AR) — TotalVote ENR
- Alabama (AL) — Stage 2 ENR Excel export adapter; Stage 1 still Google Civic/manual until state candidate/race source is implemented. Requires `source_metadata["al_ecode"]` until ecode discovery is built.
- Missouri (MO) — Grand Totals PDF (pdfplumber), statewide top-of-ticket, 2024 general only (PR #83)
- New Mexico (NM) — BPro TotalVote election-wide CSV, hyper-local municipal election data (PR #85); Civera ElectionStats deferred, issue #84
- Utah (UT) — EnhancedVotingAdapter subclass (same platform as GA/VA/WA), statewide `ballotItems` only (PR #86)
- Clarity sweep states (AK, DE, HI, ID, IN, KS, LA, ME, MS, MT, ND, NE, NH, NV, OK, RI, SD, WI, WV, WY) — requires `results_url` set per election in Django admin. **WV corrected here 2026-07-24** — previously miscategorized as Full Core; it has no dedicated Stage 1 integration (no `integrations/wv_sos/`, no `WV_SOS` in `Race.Source`, no scheduled Stage 1 task), only the Stage 2 `results/adapters/wv.py` Clarity subclass. Election/race creation is Civic-API-driven like every other Clarity sweep state.

**Current focus (issue #87):** migrate CA (results adapter already built, closest to Full Core) and then MO/NM/UT up to Full Core by building native Stage 1 adapters, replacing Civic API's role in election/race creation — not by adding more Results-Coverage-Only states. Vermont (VT) completed this migration 2026-07-22; North Carolina (NC) completed it 2026-07-22 (PR #98, merged; scheduler reloaded); New York (NY) completed it 2026-08-04 (Stage 1 shipped PR #100/#123, promoted after a clean week of unattended cron runs); Connecticut (CT) completed it 2026-08-10 via the multi-ID adapter fix (#170), live-verified against production the same day — all four have moved to Full Core above. Maryland (MD) shipped Stage 1 + widened Stage 2 2026-08-04 (PR #152, merged) but is awaiting the same production-verification bar before promotion — see its Near Core entry above. CA remains blocked on upstream CA SOS ENR API 500s (issue #88).

### Research/Build Scaffold

Research or parser/client scaffolding exists, but a scheduled Stage 1 ingestion task and/or Stage 2 results adapter is not yet implemented.

- (none currently — Tennessee moved to Near Core (partial) above once its certified-XLSX results adapter and Stage 1 sync tasks shipped, PR #43 2026-07-15; live dashboard polling still deferred until an active-election HAR capture)

### Pending External Deploy / Access

Adapter(s) built and code-complete (Full Core-ready), blocked only on infrastructure/deploy or third-party access rather than a missing data source or unbuilt code:

- **Ohio (OH)** — Stage 1 adapter built (`integrations/oh_sos/`) using CFDISCLOSURE `ACT_CAN_LIST.CSV` (765 candidates, daily). Stage 2 uses Clarity ENR (`liveresults.boe.ohio.gov`, added to `CLARITY_PROXY_HOSTS`). Both sources require the CF solver microservice (`cloudflare/cf-solver/`) deployed as a Cloud Run service with `CF_SOLVER_URL` + `CF_SOLVER_SECRET` set. CF bypass confirmed working (nodriver+xvfb, 2026-06-28). Task: `sync-oh-sos`. Federal races via Civic API (15-address config). See `docs/state-research/OH/OH-Election_Research.md`.
- **Kentucky (KY)** — Stage 1 (`integrations/ky_sos/`, `sync_ky_sos`, scheduled) and Stage 2 (`results/adapters/ky.py`, `KentuckyAdapter` — federal + state-legislative XML feed) are both fully built and tested against fixture data. Blocked at the network layer: Kentucky's `vrsws.sos.ky.gov/liveresults/Data` endpoint returns a 403 Acceptable Use Policy page to every IP tested (sandbox and the `civicmirror-proxy` Cloudflare Worker edge alike) — diagnosed as Akamai bot-management (TLS/behavioral fingerprinting), not IP-reputation, so the CF-proxy trick that unblocked OH/MN doesn't apply here. Path forward is Kentucky SBE allowlisting CivicMirror's production egress IP; **user emailed the KY SOS elections office and is still awaiting a response as of 2026-07-22.** Tracked in issue #44. Fallback if allowlisting is refused: an OH-style `cf-solver` browser-automation bypass.

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
