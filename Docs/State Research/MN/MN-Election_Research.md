# Minnesota Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | GIS + real-time portal (own system) — no adapter built |

---

**Site:** https://www.sos.state.mn.us/election-administration-campaigns/data-maps/
**Results:** https://electionresults.sos.state.mn.us/
**Operated by:** Minnesota Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Minnesota provides election results through the Secretary of State's website with an election results portal and downloadable data files. The state offers CSV/Excel downloads and maintains a comprehensive data and maps section.

---

## Data Access

### Election Results Portal
- **URL:** https://electionresults.sos.state.mn.us/
- Real-time results on election night
- Historical results archive

### Data & Maps
- **URL:** https://www.sos.state.mn.us/election-administration-campaigns/data-maps/
- Downloadable data files
- GIS shapefiles for districts
- Voter registration statistics

### Download Formats
- CSV files for election results
- Excel files
- PDF reports

---

## API Access

No public REST API identified. Data access is through:
1. CSV/Excel downloads
2. Election results web portal
3. GIS data downloads

---

## Notes

- 87 counties
- Election Day voter registration available
- Strong tradition of high voter turnout

---

## Source Coverage Analysis

Minnesota is one of the stronger state sources in this group: GIS district shapefiles are directly available, real-time election night results are served via a dedicated portal, and historical CSV/Excel data is well-organized. The primary gaps are candidate metadata (contact information, party affiliation, platform statements) and ballot measure data, neither of which is covered by the SOS results portal. These gaps should be filled using **Google Civic Information API** (candidate data, election type metadata), **Ballotpedia** (ballot measures, candidate bios), **OpenStates** (state legislative incumbents and bills), and **OpenFEC** for federal candidate finance and contact data.
