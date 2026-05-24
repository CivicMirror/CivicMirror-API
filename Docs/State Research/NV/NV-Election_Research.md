# Nevada Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | PDF/Excel downloads — no adapter built |

---

**Site:** https://www.nvsos.gov/sos/elections/election-information/election-results
**Operated by:** Nevada Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Nevada provides election results through the Secretary of State's website with county-level and precinct-level results.

---

## Data Access

### Election Results
- County-level and precinct-level results
- Historical archive
- Downloadable reports

---

## API Access

No public REST API identified.

---

## Notes

- 17 counties (including Carson City as independent city)
- Clark County (Las Vegas) contains majority of voters

---

## Source Coverage Analysis

Nevada's SOS website provides county- and precinct-level historical results via downloadable reports, but offers no API, no structured election-type categorization, no ballot measure data, and no candidate profile information. Clark County (containing the majority of Nevada voters) may have independent reporting infrastructure, but no **Clarity Elections** integration is currently documented. Gaps across candidate data, ballot measures, officials/incumbents, GeoJSON boundaries, and live results should be filled using **Google Civic Information API** (elections, candidates, districts by address), **Ballotpedia** (ballot measures, candidate bios, incumbency), **OpenStates** (state legislative data), and **OpenFEC** (federal campaign finance and candidate filings). Live election night coverage should be investigated via **Clarity Elections** at the county level for Clark and Washoe counties.
