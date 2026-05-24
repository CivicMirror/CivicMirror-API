# New Mexico Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | CSV/PDF (Clarity unverified) — no adapter built |

---

**Site:** https://www.sos.state.nm.us/voting-and-elections/election-results/
**Operated by:** New Mexico Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

New Mexico provides election results through the Secretary of State's website with canvass results and election night reporting.

---

## Data Access

### Election Results
- Canvass results by election
- County-level breakdowns
- Downloadable reports (PDF, CSV)

---

## API Access

No public REST API identified.

---

## Notes

- 33 counties
- Results available after canvass certification

---

## Source Coverage Analysis

New Mexico's SOS website provides canvass-level certified results via PDF/CSV downloads, with no public REST API, no ballot measure data, and no candidate profile information. The research file notes "election night reporting" exists but does not identify the platform — this should be investigated for potential **Clarity Elections** (`results.enr.clarityelections.com`) integration. All gaps in candidate data, ballot measures, officials/incumbents, and GeoJSON boundaries should be supplemented using **Google Civic Information API**, **Ballotpedia** (ballot measures, candidate bios, incumbency), **OpenStates** (state legislative data), and **OpenFEC** (federal races). Follow-up research is needed to confirm the election night reporting platform and whether structured live data is accessible.
