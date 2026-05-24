# Florida Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | Structured downloads only — no adapter built |

---

**Site:** https://dos.fl.gov/elections/data-statistics/elections-data/
**Election Watch:** https://floridaelectionwatch.gov/
**Results Extract:** https://results.elections.myflorida.com/
**Operated by:** Florida Division of Elections, Department of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Florida provides one of the most comprehensive election data systems in the country with multiple data access points: a data download utility, precinct-level results archive, election watch site with file downloads, early voting/vote-by-mail reports, and historical results going back to 1978.

---

## Data Access

### Florida Election Watch Downloads
- **URL:** https://floridaelectionwatch.gov/Downloads
- Download formats: Excel, Tab-delimited Text, Pipe-delimited
- File layout documentation provided
- Includes informational file and votes file

### Election Results Data Extract Utility
- **URL:** https://results.elections.myflorida.com/downloadresults.asp
- Parameterized downloads by election date and type

### Precinct-Level Results
- **URL:** https://dos.fl.gov/elections/data-statistics/elections-data/precinct-level-election-results/
- ZIP file downloads containing precinct-level data
- Coverage: 2012 to present
- County-submitted data compiled statewide

### Election Results Archive
- **URL:** https://dos.fl.gov/elections/data-statistics/elections-data/election-results-archive/
- Historical data from 1978 to present
- Includes General, Primary, Presidential Preference Primary, and Special Elections

### Early Voting & Vote-by-Mail Reports
- County-uploaded reports during early voting and VBM periods

### Turnout Data
- Statewide turnout data going back to 1954

### General Election Surveys (EAVS)
- Federal survey data in CSV, Excel, SPSS, and Stata formats

### Voter Extract
- Publicly available voter extract file from Florida Voter Registration System
- Contact: DivElections@dos.myflorida.com

---

## API Access

No dedicated REST API identified, but multiple structured download endpoints:
1. Election Watch download utility with multiple format options
2. Results data extract utility with parameterized queries
3. Precinct-level ZIP file downloads
4. Historical archive downloads

---

## Notes

- Florida's data infrastructure is exceptionally well-organized
- Multiple download formats support various analysis workflows
- Precinct-level data available from 2012; county-level from 1978
- 67 county Supervisors of Elections submit data to state
- Turnout data extends back to 1954
- Public records law means email addresses to DOS are public records

---

## Source Coverage Analysis

Florida's election data infrastructure is among the most comprehensive in the country, with explicitly typed election archives (General, Primary, Presidential Preference Primary, Special) from 1978, precinct-level data from 2012, and multiple structured download formats. Gaps remain in candidate biographical and contact data, incumbent metadata, district GeoJSON, and confirmation of ballot measure as a distinct structured data category — ballot measure data should be confirmed by reviewing the Election Watch file layout documentation. **Google Civic API** fills district, official, and candidate contact gaps; **Ballotpedia** provides candidate profiles and confirmed ballot measure text; **OpenStates** supplements state legislative data; **OpenFEC** adds federal campaign finance; and **EAVS/EAC** data (already referenced in the research notes) provides election administration statistics.
