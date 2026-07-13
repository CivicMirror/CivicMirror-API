# Oregon Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | File downloads (own system) — no adapter built |

---

**Site:** https://sos.oregon.gov/elections/Pages/electionhistory.aspx
**Operated by:** Oregon Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Oregon provides election results through the Secretary of State's website. Oregon is notable as the first state to implement universal vote-by-mail (since 2000).

---

## Data Access

### Election History
- **URL:** https://sos.oregon.gov/elections/Pages/electionhistory.aspx
- Historical results searchable by year and office
- County-level breakdowns

### Download Formats
- Downloadable results files
- PDF abstract of votes

---

## API Access

No public REST API identified.

---

## Notes

- 36 counties
- 100% vote-by-mail since 2000
- All elections conducted by mail
---

## Source Coverage Analysis

Oregon is a 100% vote-by-mail state that provides statewide results downloads, but ballot measure data is critically absent — Oregon is historically one of the nation's most active ballot initiative states, making this gap especially significant for CivicMirror. The state source also lacks candidate biographical data, official/incumbent records, district GeoJSON, and a real-time results feed. **Ballotpedia** is the highest-priority supplementary source for Oregon ballot measures; **Google Civic Information API** fills candidate, district, and official gaps; **OpenStates** covers Oregon legislative incumbents; **OpenFEC** adds federal candidates; and **MEDSL** and **OpenElections** provide normalized historical CSV data. Oregon's ballot measure calendar should be tracked proactively via Ballotpedia ahead of each election cycle.

## Additional researched added: 06/13/206
https://sos.oregon.gov/elections/Pages/current-election.aspx  - General election and registration dates
https://sos.oregon.gov/elections/Pages/historical-data.aspx  - Historical Election data.
https://sos.oregon.gov/elections/Pages/Candidate-Filings-Local-Measures.aspx - Candidate Filings and Local Measures
https://sos.oregon.gov/elections/Documents/open-offices-general-election.pdf - Open Positions
https://sos.oregon.gov/elections/campaign-finance/Pages/default.aspx - Campaign Finance
https://sos.oregon.gov/elections/Pages/county-officials.aspx - County Officials
https://geo.maps.arcgis.com/apps/instant/lookup/index.html?appid=fd070b56c975456ea2a25f7e3f4289d1  - GIS find your legislator
https://catalog.data.gov/dataset/ballot-count-history - Ballot Count  (API access?)  
     Related(possible source for other cities and states?):
       https://catalog.data.gov/organization
       https://catalog.data.gov/?keyword=elections
       https://data.oregon.gov/Administrative/Ballot-Count-History/rxzj-n3di/about_data
https://www.oregonlegislature.gov/citizen_engagement/Pages/data.aspx - Legislative Information Portal,  Mostly legislative data.  but also contains Legislator information(candidate info?)

    








