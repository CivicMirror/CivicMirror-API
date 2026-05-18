# Oregon Election Results — Research Notes

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
