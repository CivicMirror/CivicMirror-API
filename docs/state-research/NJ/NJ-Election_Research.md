# New Jersey Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Active | Google Civic API (election id 1776 in DB) |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | 🔧 Tier B planned | County-level Clarity confirmed; no state-level aggregator — custom multi-county adapter required |

---

**Site:** https://nj.gov/state/elections/election-information-results.shtml
**Election Night Results:** https://nj.gov/state/elections/election-night-results.shtml
**2026 Info:** https://www.nj.gov/state/elections/election-information-2026.shtml
**Operated by:** New Jersey Division of Elections
**Researched:** March 4, 2026 / **Updated:** 2026-05-31 (Clarity probe)
**Status:** Public, no authentication required

---

## Overview

New Jersey provides election results through the Division of Elections website. Each of NJ's 21 counties manages elections locally via the county clerk. The state does not have a single Clarity aggregator — instead, individual counties host their own Clarity ENR instances. The state's election-night-results page lists each county's Clarity URL.

---

## Clarity Architecture — KEY FINDING (2026-05-31)

**NJ uses Clarity at the county level, not at the state level.**

- `results.enr.clarityelections.com/NJ/` returns 403 — no state-level Clarity instance
- Each county that uses Clarity has its own URL: `results.enr.clarityelections.com/NJ/{CountyName}/{electionId}/`
- All 5 probed county instances returned valid `current_ver.txt` version strings on 2026-05-31

**This means:** A standard 2-line `ClarityAdapter` thin wrapper will NOT work for NJ. A custom multi-county adapter is required that:
1. Knows the county-level Clarity election IDs per election (published on NJ's election-night-results page before each election)
2. Fetches `current_ver.txt` from each county in parallel
3. Aggregates vote totals across counties for statewide races

**June 3, 2026 Primary — Confirmed County Clarity Election IDs:**

| County | Election ID | `current_ver.txt` (probed 2026-05-31) |
|---|---|---|
| Atlantic | 125304 | `367866` ✅ |
| Burlington | 125216 | `366774` ✅ |
| Cape May | 125225 | live ✅ |
| Cumberland | 125167 | live ✅ |
| Essex | 126073 | `369948` ✅ |
| Gloucester | 124692 | live ✅ |
| Hudson | 125139 | live ✅ |
| Mercer | 125161 | `366767` ✅ |
| Middlesex | 125223 | `366844` ✅ |
| Monmouth | 125221 | live ✅ |
| Morris | 126193 | live ✅ |
| Ocean | 125152 | live ✅ |
| Union | 125153 | live ✅ |
| Passaic | (ID not yet posted) | ⏳ |
| Somerset | (ID not yet posted) | ⏳ |
| Camden | camdencounty.com — no Clarity | ❌ |
| Bergen, Hunterdon, Salem, Sussex, Warren | Not listed on state page | ❓ |

**Statewide candidates source:** State publishes PDF candidate lists per race.
- US Senate primary candidates: `https://www.nj.gov/state/elections/assets/pdf/election-results/2026/2026-official-primary-candidates-us-senate.pdf`
- Post-election certified results also published as per-county PDFs.

---

## Data Access

### Election Results
- County-level Clarity ENR instances (live on election night) — see table above
- Post-election: per-county certified result PDFs published at `nj.gov/state/elections/`
- Historical results archive (PDF/Excel)

### Candidate Data
- Pre-election PDF candidate lists published at `nj.gov/state/elections/`
- No machine-readable API for candidates

---

## API Access

No public REST API for election data or results.

---

## Notes

- 21 counties; county clerk offices manage elections locally
- 13+ counties confirmed on Clarity; Camden uses own system; 5 counties unverified
- County Clarity URLs are published on the state's election-night-results page before each election
- Phase 3 tier: **Tier B** — multi-county Clarity adapter (November 2026 general target)
