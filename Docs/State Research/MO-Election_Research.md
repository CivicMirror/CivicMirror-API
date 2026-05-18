# Missouri Election Results — Research Notes

**Site:** https://www.sos.mo.gov/elections/resultsandstats
**Operated by:** Missouri Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Missouri provides election results through the Secretary of State's website with historical results and downloadable data.

---

## Data Access

### Election Results & Statistics
- **URL:** https://www.sos.mo.gov/elections/resultsandstats
- Historical election results
- Voter turnout statistics
- Results by county

### Download Formats
- PDF reports
- CSV/Excel files for some datasets

---

## API Access

No public REST API identified.

---

## Notes

- 114 counties + City of St. Louis (independent city)
- Results organized by election year and type

---

## Source Coverage Analysis

Missouri's SOS source covers only historical election results (voter turnout statistics, county-level results by year/type) and provides no structured API, live results feed, ballot measure data, or candidate metadata. Missouri's prolific ballot initiative culture makes the ballot measure gap especially significant. All candidate metadata, incumbent/official data, and district boundary information must be sourced externally: use **Ballotpedia** for ballot measures and candidate bios, **Google Civic Information API** for candidate/district/election type data, **OpenStates** for state legislative incumbents, **OpenFEC** for federal candidates, and **MEDSL** for normalized historical results.
