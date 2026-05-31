# Colorado Election Results — Research Notes

> **Last Updated:** May 25, 2026 at 11:45 AM EDT

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Complete | co_sos integration (`integrations/co_sos/`) |
| Stage 1 — Race Creation | ✅ Complete | CO SOS HTML candidate list, parsed via BeautifulSoup |
| Stage 1 — Candidate Creation | ✅ Complete | `primaryCandidates.html` (HTML table, 250+ candidates for 2026) |
| Stage 2 — Results Ingestion | ✅ Complete | Clarity Elections adapter live (`results/adapters/co.py`) |

---

**Site:** https://www.sos.state.co.us/pubs/elections/resultsData.html
**Historical Database:** https://historicalelectiondata.coloradosos.gov/
**Operated by:** Colorado Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Colorado provides election results through multiple channels: a searchable historical database (dating back to 1902), downloadable XLSX/PDF files, and a Clarity Elections reporting platform for recent elections.

---

## Data Access

### Historical Elections Database
- **URL:** https://historicalelectiondata.coloradosos.gov/
- Searchable database covering 1902 to present
- Search categories: Contests, Questions, Candidates, Voters, Documents
- Created in 2021 to consolidate all electoral history
- Data sourced from official Abstract of Votes Cast documents
- Coverage: Federal (President, Senate, House), State Executive, State Legislative, Judicial, Ballot Questions
- Contact: elections@coloradosos.gov

### Election Results Archives
- **URL:** https://www.sos.state.co.us/pubs/elections/Results/Archives.html
- XLSX downloads: Precinct-level results, ballot measure results
- PDF downloads: Abstract of Votes Cast
- Example: "2024 General Election precinct level results (XLSX)"

### Candidate Lists (New — May 2026)
- **Primary candidate list:** https://www.coloradosos.gov/pubs/elections/vote/primaryCandidates.html
  - HTML table: columns Candidate name | Office | District | Party | Write in?
  - Withdrawn candidates marked with `<span style="text-decoration: line-through;">`
  - XLSX version: `/vote/files/{year}/{year}PrimaryCandidateListOfficial.xlsx`
  - "Last updated" timestamp shown on page (e.g. "Last updated May 5, 2026, 4:44 PM")
  - **Status:** Parsed by `integrations/co_sos/` using BeautifulSoup; 250+ candidates for 2026
- **General petition candidates:** https://www.coloradosos.gov/pubs/elections/vote/generalPetitionCandidates.html
  - ⚠️ Incomplete — petition candidates only, not the full general election ballot
  - Different table schema (Format approved | Filed | Petition withdrawn | Insufficient | Sufficient)
  - **Status:** Deferred — not suitable as a complete general election candidate source
- **Candidate home page:** https://www.coloradosos.gov/pubs/elections/Candidates/CandidateHome.html

### CO SOS Integration Notes
- **Election dates (statutory):** Primary = last Tuesday of June in even years; General = first Tuesday after first Monday of November
- **Change detection:** MD5 hash of HTML response body (site does not return ETag headers reliably)
- **Race grouping (primary):** `(office, district, party)` — separate races per party per primary
- **Trigger:** `POST /internal/tasks/sync-co-sos/` → `sync_co_elections` → `sync_co_candidates`
- **Cloud Scheduler:** `sync-co-sos` job, daily 03:00 UTC

- Recent elections use Clarity Elections platform (results.enr.clarityelections.com/CO/)
- Interactive results with downloadable reports

### Data Request Form
- Formal data request process via PDF form
- Subscription provides electronic download access to voter data extracts
- Includes Master Voter History, UOCAVA Voter List, Voting Center Locations, Ballot tracking lists

---

## API Access

No public REST API identified. Data access is through:
1. Historical database search interface
2. XLSX/PDF downloads from archives
3. Clarity Elections platform for recent elections
4. Formal data request form for voter file data

---

## Notes

- Historical database has excellent depth (1902–present) but some gaps in older primary elections (1902–1910)
- 1938 data is missing across all office types
- Precinct-level data available as XLSX for recent elections
- TRACER system available for campaign finance data

---

## Source Coverage Analysis

Colorado's combination of the Clarity Elections platform (live results) and the `historicalelectiondata.coloradosos.gov` database (1902–present) provides excellent election result and ballot question coverage, making it one of the stronger state sources for raw results data. However, candidate contact information, biographical data, platform statements, incumbent status, term dates, and district boundary GeoJSON are entirely absent from state-provided sources. **Google Civic API** should fill district, incumbent, and candidate contact gaps; **Ballotpedia** provides candidate profiles and platform content; **OpenStates** covers state legislative officials; and **EAVS/EAC** supplements election administration statistics. The Clarity feed (`results.enr.clarityelections.com/CO/`) enables structured real-time XML/JSON ingestion during election night without additional engineering.
