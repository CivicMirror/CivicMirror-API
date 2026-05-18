# Wyoming Election Results — Research Notes

**Site:** https://sos.wyo.gov/elections/electionresults.aspx
**Operated by:** Wyoming Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Wyoming provides election results through the Secretary of State's website. Results are available as downloadable PDF and Excel files with statewide summaries and precinct-by-precinct breakdowns for statewide and legislative contests.

---

## Data Access

### Election Results
- **URL:** https://sos.wyo.gov/elections/electionresults.aspx
- Results organized by election year (primary and general)
- Both PDF and Excel format downloads

### Download Formats
- **PDF:** Complete results including statewide and precinct summaries
- **Excel (XLSX):** Spreadsheet format for data analysis
- Available as zip files containing all result spreadsheets
- Includes write-ins, undervotes, and overvotes for each race

### Precinct-by-Precinct Data
- Available for statewide and legislative contests
- Judicial retentions and ballot issues included
- Local/county results available on individual county websites

---

## API Access

No public REST API identified.

---

## Notes

- 23 counties (fewest in the US tied with Delaware)
- Smallest state population
- Closed primary system (party registration required)
- County websites provide local/county race results
- Precinct-level data limited to statewide/legislative contests at state level
- Office established 1869 (territorial secretary)
---

## Source Coverage Analysis

Wyoming provides PDF and Excel election result downloads including precinct-by-precinct data, write-ins, undervotes, and overvotes, and notably includes judicial retentions and ballot issues within the same download structure — giving it slightly better ballot measure coverage than comparable small states. However, the state source has no REST API, no candidate profiles, no officials/incumbency data, and no district boundary files; local and county-level results require visiting individual county websites. Gaps in candidate data, structured ballot measure type classification, officials/incumbents, and district boundaries should be supplemented using **Google Civic Information API** (elections, candidates, district lookups), **Ballotpedia** (ballot measure type detail, candidate bios, incumbency), **OpenStates** (Wyoming state legislative data), and **OpenFEC** (federal candidate and campaign finance filings). Live election night results are not available from the state source and should be investigated via **Clarity Elections** or covered post-election through **MEDSL**.
