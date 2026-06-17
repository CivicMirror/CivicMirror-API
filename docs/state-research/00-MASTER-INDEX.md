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

Tracks Stage 1 (Election + Race Creation) and Stage 2 (Results Ingestion) implementation status per state.

| Code | State | Stage 1 — Election Creation | Stage 1 — Race Creation | Stage 2 — Results Ingestion |
|------|-------|----------------------------|-------------------------|-----------------------------|
| **WV** | West Virginia | ✅ Complete | ✅ Complete | ✅ Complete |
| **CO** | Colorado | ✅ Complete | ✅ Complete | ✅ Complete |
| **SC** | South Carolina | ✅ Complete | ✅ Complete | ✅ Complete |
| **VA** | Virginia | ✅ Complete | ✅ Complete | ✅ Complete |
| **AZ** | Arizona | ✅ Complete | ✅ Complete | ✅ Complete |
| **MA** | Massachusetts | ✅ Complete | ✅ Complete | ✅ Complete |
| **IA** | Iowa | ✅ Complete | ✅ Complete | ⚠️ Adapter built, needs production wiring |
| **AR** | Arkansas | ✅ Available | ⚠️ Untested | ✅ Complete |
| **CT** | Connecticut | ✅ Available | ⚠️ Untested | ✅ Complete |
| **AK, DE, HI, ID, IN, KS, LA, ME, MS, MT, ND, NE, NH, NV, OK, RI, SD, VT, WI, WY** | Clarity sweep states | ✅ Available | ⚠️ Untested | ✅ Adapter available |
| All others | — | ✅ Available (Civic API) | ⚠️ Untested | ❌ No adapter |

---

## Core Coverage Status

### Full Core Coverage

States that currently satisfy the CivicMirror Federal + State coverage goal:

- Arizona (AZ)
- Colorado (CO)
- Massachusetts (MA)
- South Carolina (SC)
- Virginia (VA)
- West Virginia (WV)

These states currently provide:

- Election discovery
- Race creation
- Results ingestion

for Federal and State contests.

### Near Core Coverage

- Iowa (IA) — adapter exists but production integration remains incomplete.

### Results Coverage Only

- Arkansas (AR)
- Connecticut (CT)
- Tier A Clarity states

### Blocked

- Pennsylvania (PA)
- Michigan (MI)

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