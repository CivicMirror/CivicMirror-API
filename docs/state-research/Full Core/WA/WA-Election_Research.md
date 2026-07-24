# Washington Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API plus SOS calendar/archive |
| Stage 1 — Race Creation | ✅ Strong candidate sources | VoteWA candidate lists, SOS offices-open pages, PDC candidate dataset |
| Stage 2 — Results Ingestion | ⚠️ Feasible, no adapter | SOS downloads and GIS-ready files are strongest near-term path; VoteWA app needs API capture |
| Local Election Coverage | ✅ Strong | PDC includes state and local candidacies; SOS archive links local election data pages |
| Geography / Districts | ✅ Strong | SOS precinct shapefiles, splits, district maps, district-precinct association files |

---

**Primary SOS Archive:** https://www.sos.wa.gov/elections/data-research/election-data-and-maps/election-results-and-voters-pamphlets  
**Reports / Statistics:** https://www.sos.wa.gov/elections/data-research/election-data-and-maps/reports-data-and-statistics  
**Precinct Shapefiles:** https://www.sos.wa.gov/elections/data-research/election-data-and-maps/reports-data-and-statistics/precinct-shapefiles  
**PDC Candidates:** https://www.pdc.wa.gov/political-disclosure-reporting-data/browse-search-data/candidates  
**Operated by:** Washington Secretary of State, VoteWA, Washington Public Disclosure Commission  
**Researched:** June 12, 2026  
**Status:** Public pages and downloads available without authentication; voter registration extract requires approval

---

## Overview

Washington is one of the stronger states for election research because state-level sources expose election archives, official downloads, calendar deadlines, precinct geography, ballot-return data, and candidate-disclosure data. The best CivicMirror path is not one single API: combine SOS archive/download pages for election results and geography, VoteWA/SOS candidate-list pages for election-specific candidate filing, and PDC Socrata data for local candidate discovery and campaign-finance enrichment.

Washington is a vote-by-mail state with 39 counties and VoteWA as the centralized voter registration/election platform. Statewide and local elections follow a predictable cycle: ballots and accessible voting units are available during an 18-day voting period, online/mail registration closes 8 days before Election Day, and in-person registration continues through 8 p.m. on Election Day.

---

## Source Inventory

### SOS Election Results and Voters' Pamphlets

- **URL:** https://www.sos.wa.gov/elections/data-research/election-data-and-maps/election-results-and-voters-pamphlets
- Organized by election year and election type.
- Provides links to results, voters' guides, election-specific data pages, offices open, and candidates who filed.
- Current examples include 2026 February and April Special Elections, 2025 Primary/General, and 2024 Primary/General.
- Historical archive includes older ZIP data files and legacy candidate-list links.

### Election-Specific Data Pages

Election data pages are the best starting point for a results adapter because they expose structured files without needing to reverse-engineer the VoteWA results app.

Example: the 2024 General Election data page includes:
- Reconciliation XLSX.
- Certification of candidates PDF.
- Congressional district results XLSX/PDF.
- Legislative district results XLSX/PDF.
- Districts with precinct associations XLSX.
- Precinct results GIS-ready ZIP.

Recommended ingestion priority:
1. Election-specific XLSX/ZIP downloads.
2. District and precinct association files.
3. VoteWA results app API capture only where downloads are missing or insufficient.

### VoteWA Results

- **Current format:** Angular/static web app under `results.votewa.gov` / `results.vote.wa.gov`.
- **Observed behavior:** HTML shell loads JavaScript bundles and connects to Enhanced Voting endpoints.
- **Adapter implication:** Do not treat the page as simple scrapeable HTML. Future adapter work should capture network requests in browser dev tools or Playwright and identify the underlying results JSON endpoints.
- **Useful pattern:** Public results URLs include election dates, for example `https://results.votewa.gov/results/public/washington/elections/20260428` and older `https://results.vote.wa.gov/results/20241105/`.

### SOS Reports, Data, and Statistics

- **URL:** https://www.sos.wa.gov/elections/data-research/election-data-and-maps/reports-data-and-statistics
- Current-election reports:
  - Daily ballot return statistics.
  - Daily ballot status reports, also called matchback reports.
- Historical/statistical data:
  - Annual election reports.
  - Voter demographics by age, county, gender, congressional district, legislative district, and city/town.
  - Monthly voter registration transactions back to March 2007.
  - Voter participation data since 1952.
  - Voter participation XLSX by county, gender, and age range.
  - Turnout by election and general election turnout tables.
  - Reconciliation XLSX data submitted by counties since 2005.
  - Ballot drop box usage by year since 2012.
  - Same-day registration totals since 2019.

### PDC Candidate Data

- **URL:** https://www.pdc.wa.gov/political-disclosure-reporting-data/browse-search-data/candidates
- **Structured endpoint:** `https://data.wa.gov/api/v3/views/3h9x-7bvm/query.json`
- **Direct CSV export:** `https://www.pdc.wa.gov/political-disclosure-reporting-data/browse-search-data/download?dsid=3h9x-7bvm&fname=candidates-table...`
- **Dataset ID:** `3h9x-7bvm`
- **Fixed filter used by public table:** `filer_type = "CA"`
- **Key fields:** `filer_name`, `election_year`, `jurisdiction`, `office`, `position`, `party`, `jurisdiction_type`, `candidacy_id`, `jurisdiction_code`.
- **Coverage:** state and local candidates, including cities, school districts, fire districts, mayoral offices, council seats, and other local offices.
- **Local snapshot reviewed:** `candidates-table.csv` contains 36,790 rows with elections ranging primarily from 2009 through 2026, plus a small number of future-cycle records through 2029.
- **Coverage mix in snapshot:** 30,957 local candidacies, 3,223 legislative, 2,207 judicial, and 338 statewide records.

Sample query shape:

```sql
SELECT filer_name, election_year, jurisdiction, office, position, party,
       jurisdiction_type, candidacy_id, jurisdiction_code
WHERE filer_type = "CA"
ORDER BY election_year DESC, filer_name ASC
LIMIT 100
```

Do not commit exported candidate rows or public app tokens. Use this endpoint as a discoverable public data source for implementation research and future adapter design.

The CSV export is highly useful for statewide candidate and local-office discovery, but it is not a complete election-results feed. It does not replace SOS election-specific results downloads or VoteWA results data. Treat PDC as candidate/campaign-finance enrichment keyed by `candidacy_id`, `jurisdiction_code`, `office`, `position`, and `election_year`.

---

## Calendar and Election Lifecycle

### 2026 Dates and Deadlines

- **Dates page:** https://www.sos.wa.gov/elections/elections-calendar/dates-and-deadlines
- February Special Election:
  - January 23: 18-day voting period begins.
  - February 2: online/mail registration deadline.
  - February 10: Election Day and in-person registration deadline.
- April Special Election:
  - April 10: 18-day voting period begins.
  - April 20: online/mail registration deadline.
  - April 28: Election Day and in-person registration deadline.
- Candidate filing:
  - May 4-8: declaration of candidacy filing week.
  - May 11: withdrawal deadline.
  - May 19: voters' pamphlet profile deadline.
- Primary:
  - July 17: 18-day voting period begins.
  - August 4: Primary Election Day.
- General:
  - October 16: 18-day voting period begins.
  - November 3: General Election Day.

The full elections calendar adds administrative milestones such as resolution filing deadlines, random ballot audit notices, equipment checks, canvassing board certification, state certification, and initiative/referendum petition deadlines.

---

## Geography and District Mapping

### 2024 Court-Designated District Maps

- **URL:** https://www.sos.wa.gov/elections/data-research/election-data-and-maps/2024-court-designated-legislativecongressional-maps
- Provides statewide legislative/congressional map PDFs and district-by-district legislative map PDFs in letter and wall sizes.
- Useful for voter-facing district context, but not the preferred machine-readable boundary source.

### Precinct Shapefiles

- **URL:** https://www.sos.wa.gov/elections/data-research/election-data-and-maps/reports-data-and-statistics/precinct-shapefiles
- Public ZIP files are available from 2004 through 2025.
- Recent files include statewide precincts, statewide splits, and consolidated precincts.
- 2025 examples:
  - `Statewide_Splits_2025General.zip`
  - `Statewide_Precincts_2025General.zip`
- 2024 examples:
  - `Statewide_Splits_2024General.zip`
  - `Statewide_Precincts_2024General_1.zip`
  - `Statewide_Precincts_2024General_Consol.zip`

For CivicMirror, these files are valuable for precinct-to-district reconciliation and local jurisdiction mapping. Election-specific `Districts with Precinct Associations` XLSX files should be preferred when mapping election results to districts.

---

## Election Technology and Audit Context

### Voting Systems by County

- **URL:** https://www.sos.wa.gov/elections/data-research/election-technology/voting-systems-county
- Lists county voting system type, AVU type, vendor, software version, accessible voting unit, and voting location.
- All listed counties use digital scan plus touchscreen accessible voting units.
- Vendors include Clear Ballot, Hart InterCivic, Dominion Voting Systems, and Election Systems and Software.
- SOS notes that software version numbers reflect the system used in the November 2025 General Election.

This source is not a results feed, but it is useful for audit metadata, county context, and diagnosing county-specific result file quirks.

---

## Voter Registration and Ballot Status Data

### Voter Registration Database Extract

- **URL:** https://www.sos.wa.gov/washington-voter-registration-database-extract
- The statewide extract requires an approval/request process.
- Treat it as restricted operational data, not a public anonymous API.
- Do not use it for CivicMirror ingestion unless there is a clear legal basis, approved access, and a privacy review.

### Ballot Return and Matchback Reports

- Daily ballot return statistics and ballot status reports are public current-election resources.
- These are useful for turnout/status dashboards, not candidate/race creation.
- Ballot status/matchback data may contain public voter information; handle conservatively and avoid committing raw extracts.

---

## API and Scraping Feasibility

| Source | Access Pattern | CivicMirror Use |
|---|---|---|
| SOS archive pages | HTML links to results, data pages, PDFs, ZIPs, XLSX | Election source discovery |
| SOS election data pages | Direct XLSX, ZIP, PDF links | Results ingestion, reconciliation, district/precinct mapping |
| VoteWA results | JavaScript app, likely backend JSON endpoints | Future live/certified results adapter after network capture |
| PDC candidates | Socrata `api/v3/views/3h9x-7bvm/query.json` plus CSV export | Candidate and local-office discovery |
| Precinct shapefiles | Direct ZIP downloads | Geography and precinct reconciliation |
| Voter registration extract | Approval-based request | Out of scope unless approved and privacy-reviewed |

Washington should be considered a high-value future adapter candidate. The best first adapter path is the SOS election-specific download pages, especially recent General/Primary pages with XLSX results and GIS-ready precinct ZIPs. PDC should be a parallel enrichment path for local candidate discovery.

---

## Gaps and Risks

- VoteWA results app requires API reverse engineering before reliable live-results ingestion.
- Ballot-measure metadata may still require supplemental sources for explanatory text, measure arguments, and civic summaries.
- Voters' guides are often PDF/HTML and may require document parsing for candidate statements.
- Local jurisdiction naming must be normalized across PDC, SOS, VoteWA, and precinct/district files.
- Public ballot status and voter-registration data can include personally identifying voter information; avoid raw ingestion unless explicitly scoped and reviewed.

---

## Recommended CivicMirror Roadmap

1. Build a WA source inventory scraper for SOS archive pages that records election date, election type, results URL, data page URL, voters' guide URL, candidate-list URL, and offices-open URL.
2. Add parsers for election-specific XLSX/ZIP files, starting with 2024 General Election district and precinct result downloads.
3. Add a PDC candidate discovery adapter using either the Socrata endpoint or direct CSV export with the `filer_type = "CA"` filter.
4. Normalize local jurisdiction names and codes using PDC `jurisdiction_code`, SOS district-precinct association files, and precinct shapefiles.
5. Reverse-engineer VoteWA network calls only after downloadable historical data is parsed successfully.
6. Supplement ballot-measure metadata with SOS initiatives/referenda pages and Ballotpedia where SOS data is insufficient.

---

## Source Coverage Analysis

Washington has unusually strong public election infrastructure for CivicMirror: official election archive pages, recurring election data downloads, public precinct shapefiles, detailed calendars, voting-system metadata, and a structured PDC candidate dataset that covers local offices. The main weakness is that no single official REST API covers elections, races, candidates, results, and ballot measures end to end. Implementation should therefore use a layered approach: SOS archive/downloads for elections and results, PDC for candidate/local-office discovery, VoteWA API capture for live/current result gaps, and supplemental ballot-measure sources for voter-facing measure explanations.
