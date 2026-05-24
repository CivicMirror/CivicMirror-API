# Utah Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | Portal + paid requests barrier — no adapter built |

---

**Site:** https://vote.utah.gov/election-results-data-historical-information/
**Results:** https://electionresults.utah.gov/
**Historical:** https://vote.utah.gov/historical-election-results/
**Operated by:** Utah Lieutenant Governor's Office
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Utah provides election results through the Lieutenant Governor's Office at vote.utah.gov. The state offers an election results website, historical results from 1960-present, and data request services for voter registration and election data.

---

## Data Access

### Election Results Website
- **URL:** https://electionresults.utah.gov/
- Current and recent election results
- County-level breakdowns

### Historical Election Results
- **URL:** https://vote.utah.gov/historical-election-results/
- Results from 1960 to 2020
- For pre-1960 results, contact Utah State Archives (archives.utah.gov)

### Aggregated Canvass Statistics
- Available from 2023-present
- NVRA data
- Voter list maintenance data

### Voter Registration Statistics
- Current statistics available online
- Historical data downloadable as Excel files (2014-2026)
- Active/inactive voter breakdowns

### Data Request Services
- **URL:** https://vote.utah.gov/obtain-voter-registration-or-election-data/
- Statewide voter registration list: $1,050 (tab-delimited)
- County/district voter lists available from county clerks
- Early voting report: $35 per election (tab-delimited, daily updates)
- Absentee ballot request report available
- Election results available upon request

---

## API Access

No public REST API identified. Data available through formal request process.

---

## Notes

- 29 counties
- Lieutenant Governor is chief elections officer
- Primarily vote-by-mail state
- Large data files (~150MB for statewide voter registration)
- Some data classified as "private" under Utah law
- Voter date-of-birth restrictions (day/month not provided)
---

## Source Coverage Analysis

Utah's election data is primarily accessible via the Lt. Governor's election portal in Excel/CSV format, but the state requires paid data requests for many detailed datasets, creating a cost barrier for comprehensive ingestion. The state is also a primarily vote-by-mail jurisdiction with early reporting patterns. No API, live feed, ballot measure data, or candidate profile information is documented for free public access. Supplement with **Google Civic Information API** (candidates, districts, election types), **Ballotpedia** (ballot measures, candidate bios, incumbency), **OpenStates** (UT state legislative data), and **OpenFEC** (federal candidates). For result data, **MEDSL** provides a cost-free alternative to UT's paid downloads for historical election result normalization.
