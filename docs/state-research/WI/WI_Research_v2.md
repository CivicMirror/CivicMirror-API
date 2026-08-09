# Wisconsin Election System — Research Notes

## Coverage Status

| Pipeline stage                 | Status                                                   | Recommended official source                                                                                                               |
| ------------------------------ | -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Election creation and calendar | ⚠️ Partial, document-based                               | Wisconsin Elections Commission election pages, official election notices, and Wisconsin statutes                                          |
| Election-type classification   | ⚠️ Partial                                               | WEC notices and statutes; normalize spring primary, spring election, partisan primary, general, special, recall, and referendum elections |
| Office and district creation   | ✅ Available                                              | WEC candidate materials plus Wisconsin Legislature LTSB GIS Hub                                                                           |
| Candidate and filing ingestion | ⚠️ PDF-based and split by filing officer                 | WEC Candidate Tracking for state-filed offices; county, municipal, and school-district clerks for local offices                           |
| Ballot qualification           | ⚠️ PDF-based                                             | WEC Candidate Tracking and WEC ballot-access decisions                                                                                    |
| Certified results ingestion    | ✅ Batch files; adapter needed                            | WEC certified election-result spreadsheets and reports                                                                                    |
| Election-night results         | ❌ No statewide feed                                      | County and municipal result sites; heterogeneous HTML, Excel, and PDF sources                                                             |
| Ballot measures                | ⚠️ Split source                                          | Wisconsin Legislature joint resolutions, WEC ballots/results, and local clerk notices                                                     |
| Certification and canvass      | ✅ Available                                              | County canvass records, WEC certified results, and Wisconsin statutes                                                                     |
| Recounts and recalls           | ⚠️ Document-based                                        | WEC decisions, orders, recount materials, and resulting certified files                                                                   |
| Campaign finance               | ✅ Structured public search/export for state committees   | Wisconsin Ethics Commission Sunshine                                                                                                      |
| Local campaign finance         | ❌ Decentralized                                          | County, municipal, or school-district filing officer                                                                                      |
| District and ward geography    | ✅ Structured GIS data                                    | Wisconsin Legislature Legislative Technology Services Bureau GIS Hub                                                                      |
| Historical results             | ⚠️ Available but exact statewide completeness unresolved | WEC archive plus official county archives                                                                                                 |

---

**Primary election authority:** Wisconsin Elections Commission
**Primary results page:** `https://elections.wi.gov/elections/election-results`
**Statewide results archive:** `https://elections.wi.gov/elections/election-results/results-all`
**Election and candidate page:** `https://elections.wi.gov/elections`
**Statistics and data:** `https://elections.wi.gov/statistics-data`
**Voter-facing portal:** `https://myvote.wi.gov/`
**Campaign finance:** `https://campaignfinance.wi.gov/`
**District GIS:** `https://gis-ltsb.hub.arcgis.com/`
**Operated by:** Wisconsin Elections Commission, Wisconsin Ethics Commission, Wisconsin Legislature LTSB, and local election officials
**Researched:** March 4, 2026
**Updated:** August 9, 2026 — replaced unofficial pipeline recommendations with official state sources; added candidate filing, Sunshine campaign-finance exports, GIS data, canvass and certification mapping, local-results strategy, and corrections to the two-hour reporting claim
**Access checked:** August 9, 2026
**Status:** Public sources; some WEC and MyVote pages blocked automated retrieval with HTTP 403 during this review

---

## Overview

Wisconsin uses a highly decentralized election-administration model. Municipal election officials conduct voting and produce initial returns, county boards canvass county, state, and federal contests, and the Wisconsin Elections Commission receives certified county statements and produces the final statewide canvass. Wisconsin statutes assign results, canvass, and certification responsibilities across these levels rather than creating a single statewide election-night reporting system.

This distinction is important for CivicMirror:

1. **Certified statewide results** can be treated as a batch-ingestion problem centered on WEC spreadsheets and reports.
2. **Election-night reporting** is a separate, county-by-county collection problem.
3. **Local contests** may require municipal or school-district sources even after the county canvass.
4. **Candidate filing** is split between WEC and local filing officers.
5. **Campaign finance** is split between the Wisconsin Ethics Commission for state committees and local clerks for local committees.

The existing repository file correctly identified the lack of a statewide live-results feed and the use of ward-level spreadsheets, but it treated several unofficial services as core pipeline sources and did not map the state’s candidate, campaign-finance, geography, certification, or local-data systems.

---

## Corrections and Changes from the Existing File

### 1. Remove Google Civic Information API from the official pipeline

The existing file marked election creation as available through Google Civic Information API. That is not a first-party Wisconsin source and should not be the CivicMirror source of record.

Use WEC election notices, calendars, statutes, and local notices instead. An external civic-information service may be retained only as a non-authoritative comparison or alerting source.

### 2. Separate certified results from election-night reporting

The existing file’s “no adapter” status combines two different data products:

* **WEC certified results:** statewide, official, delayed, and generally suitable for batch ingestion.
* **Election-night results:** locally reported, unofficial, and distributed across county and municipal websites.

This should become two pipeline stages rather than one.

### 3. Correct the two-hour posting statement

The repository file states that counties must post unofficial results within two hours of polls closing. The official sources reviewed do not support that formulation.

Wisconsin Statute § 7.15(2) describes the municipal clerk posting election information as soon as possible after the polls close. An official City of Madison closing-polls manual uses two-hour language for getting results to the county clerk, not for county website publication. The updated file should therefore say that election returns must be transmitted promptly through the local reporting chain; it should not claim a statewide two-hour web-posting deadline.

### 4. Do not represent the historical archive as fully inventoried

The existing file says the WEC archive goes back “10+ years.” The archive URL remains valid as a research target, but its exact earliest statewide year and completeness could not be independently enumerated because the WEC pages returned HTTP 403 to automated retrieval during this review.

Official county archives demonstrate deeper local coverage: Brown County publishes election records from 2000, and Dane County’s online archive reaches at least 2004 and includes regular, primary, spring, and recall elections.

### 5. Remove unofficial vendors and aggregators as primary recommendations

Google Civic, Ballotpedia, OpenElections, OpenStates, AP election feeds, and similar services should not appear as recommended primary evidence. They may be used only for discovery or independent comparison, never as the authoritative CivicMirror record.

---

## Election Administration and Data Flow

### Municipal level

Municipal clerks and election inspectors conduct elections, tabulate local returns, and transmit results into the canvass process. Municipalities may publish election-night reports in HTML, PDF, spreadsheet, or vendor-generated formats.

For municipal offices and many local referenda, the municipal canvass or municipal clerk may be the authoritative final source.

### County level

County clerks aggregate municipal returns and county boards of canvassers certify results for federal, state, county, and referendum contests within their responsibility.

Official county pages show that the distinction between official and unofficial results depends on the contest. Dane County labels county-canvassed federal, state, county, and referendum results as “Official Canvass,” while warning that municipal and school-district results shown on the same site may remain unofficial.

Polk County similarly directs researchers to municipal or school-district clerks for the authoritative versions of those local contests.

### State level

Certified county statements are transmitted to the Wisconsin Elections Commission. Wisconsin Statute § 7.70 governs the state canvass, including county transmission deadlines and the Commission chair’s determination and certification. Presidential certification records receive additional treatment under § 7.75.

---

## Source Inventory

### Rank 1 — WEC Certified Election Results

* **Entity:** Wisconsin Elections Commission
* **Official URLs:**

  * `https://elections.wi.gov/elections/election-results`
  * `https://elections.wi.gov/elections/election-results/results-all`
* **Election scope:** Statewide certified contests and statewide compilation of county-certified returns
* **Election types:** General, partisan primary, spring election, spring primary, presidential preference, special, recall, and statewide referendum elections when applicable
* **Cycle coverage:** Multiple historical cycles; exact earliest statewide cycle needs manual inventory
* **Data subjects:** Elections, offices, districts, candidates or choices, party, vote totals, counties, municipalities, wards, referenda, and certification
* **Source type:** Excel, PDF, and HTML landing pages
* **Access:** Direct file download from election-specific pages
* **Authentication:** None indicated
* **Update cadence:** After county canvasses and state certification
* **Machine-readability:** High for consistently structured Excel files; low to medium for PDFs
* **Integration value:** Highest source for final certified results
* **Access note:** The repository baseline describes ward-by-ward XLSX and PDF reports, but the WEC pages returned HTTP 403 to automated requests in this research environment. File links and schemas therefore need a browser-assisted manual capture before adapter implementation.

**Recommended identifiers**

* `election_key`: election date + normalized election type
* `contest_key`: election key + office + district or jurisdiction
* `result_key`: contest key + candidate/choice + reporting geography
* Preserve the source’s ward, municipality, county, district, and office labels exactly in raw staging tables.

**Update strategy**

* Poll the WEC election page after the canvass deadline.
* Record file URL, filename, retrieval timestamp, file hash, and stated certification status.
* Re-ingest when the file hash changes.
* Never overwrite unofficial records without retaining provenance and version history.

---

### Rank 2 — Wisconsin Ethics Commission Sunshine

* **Entity:** Wisconsin Ethics Commission
* **Official URLs:**

  * `https://campaignfinance.wi.gov/`
  * `https://campaignfinance.wi.gov/browse-data`
  * `https://campaignfinance.wi.gov/browse-data/transactions`
  * `https://campaignfinance.wi.gov/browse-data/reports`
  * `https://campaignfinance.wi.gov/browse-data/registrants`
  * `https://ethics.wi.gov/Pages/CampaignFinance/ViewReports.aspx`
* **Scope:** State candidate committees, state recall committees, legislative campaign committees, political parties, PACs, independent-expenditure committees, statewide referendum committees, and conduits
* **Historical coverage:** Activity from July 1, 2008 to present
* **Data subjects:** Registrants, candidates, committees, contributors, payees, transactions, reports, offices, reporting periods, receipts, and disbursements
* **Source type:** HTML/JavaScript database portal, spreadsheet export, and PDF reports
* **Access:** Public search and export
* **Authentication:** None for public browsing
* **Update cadence:** Reports are publicly available immediately after filing
* **Machine-readability:** High for exported transaction spreadsheets; medium for searchable registrant records; low for PDF reports
* **Integration value:** Best official source for state campaign-finance data

The Ethics Commission states that Sunshine was introduced in 2025, contains records covering activity since July 1, 2008, provides transaction-level spreadsheet export, and makes reports public immediately after filing.

**Observed public routes and parameters**

Public URLs expose routes for transactions, reports, and registrants. Search-engine-visible examples show parameters including `specificCommittee`, `office`, `searchField`, and `searchTerm`. These are browser routes, not verified API endpoints.

**API status**

No official Sunshine API documentation or supported public API endpoint was verified. Classify Sunshine as a **database portal with spreadsheet export**, not as an API.

A HAR capture was not available with the research tools used. Before automating the portal, record the browser’s network calls, request parameters, pagination, export request, response format, and any rate limiting. Do not rely on undocumented endpoints until their behavior and stability have been tested.

**Suggested joins**

* Prefer official registrant or committee IDs from Sunshine.
* Join candidate committees to election candidates using candidate name, office, district, cycle, and committee ID.
* Do not assume the Candidate Tracking “receipt number” is the same as a Sunshine committee identifier.

**Important gap**

The Ethics Commission does not maintain campaign-finance records for local candidates, local recall committees, or local referendum committees. Those records remain with the appropriate county, municipal, or school-district clerk.

---

### Rank 3 — Wisconsin Legislature LTSB GIS Hub

* **Entity:** Wisconsin Legislature, Legislative Technology Services Bureau GIS Team
* **Official URLs:**

  * `https://gis-ltsb.hub.arcgis.com/`
  * `https://gis-ltsb.hub.arcgis.com/pages/download-data`
* **Scope:** Congressional districts, state Senate districts, Assembly districts, wards, and other political geography
* **Data subjects:** District identifiers, ward identifiers, geometries, population attributes, municipalities, counties, and redistricting vintages
* **Source type:** ArcGIS Hub, GIS services, and bulk geospatial downloads
* **Access:** Public
* **Authentication:** Generally none for public layers and downloads
* **Machine-readability:** High
* **Integration value:** Primary source for district and ward geometry

The official GIS Hub identifies the Legislature’s GIS team as the provider of legislative geographic data and supplies a download-data section. The State Cartographer’s Office also identifies LTSB as the maintainer of Wisconsin political-district spatial datasets and notes that municipal ward data incorporates locally produced submissions.

**Normalization requirements**

* Store `map_vintage` and legal effective dates.
* Never join results to a district number without checking the district plan used for that election.
* Preserve source ward identifiers and municipality names.
* Maintain a ward-to-district crosswalk by election date.
* Retain geometry source item ID, layer ID, download URL, retrieval date, and checksum.

**Open issue**

Capture the exact ArcGIS item and REST service URL for each current layer before implementation. Do not use a Department of Natural Resources copy of a legislative boundary layer when the corresponding LTSB item is available.

---

### Rank 4 — WEC Candidate Tracking

* **Entity:** Wisconsin Elections Commission
* **Official landing URL:** `https://elections.wi.gov/elections#tracker`
* **Scope:** Offices for which candidates file with WEC
* **Election types:** Spring, partisan, general, and special elections as applicable
* **Data subjects:** Office, district, candidate, party, incumbent, filing documents, signatures, and staff review
* **Source type:** PDF report linked from an HTML page
* **Access:** Public
* **Authentication:** None indicated
* **Update cadence:** WEC states that the tracker is updated at the end of each business day
* **Machine-readability:** Low to medium; table extraction from PDF required
* **Integration value:** Primary state source for candidate filing and ballot-qualification workflow

WEC’s official public communication says the candidate tracker is updated at the end of each business day.

The Ethics Commission confirms that state-filed offices include governor, lieutenant governor, attorney general, secretary of state, state treasurer, state Senate, Assembly, district attorney, Supreme Court, Court of Appeals, circuit court, and state superintendent. All other candidates generally file with the appropriate local filing officer.

**Extraction approach**

* Download and archive every tracker revision during active filing periods.
* Extract tables by page and office.
* Preserve the printed timestamp from the PDF.
* Treat “pending,” “approved,” challenged, withdrawn, and rejected states as separate values.
* Store filing-document dates independently rather than reducing them to one filing date.
* Use visible office and district text as the primary contest link.
* Flag duplicate names and changes in ballot-name formatting for manual review.

**Unresolved access issue**

The current official PDF asset URL was not captured because the WEC landing page blocked automated retrieval. The exact official PDF URL must be captured manually before production use. A media-hosted copy of a WEC-branded report was visible during research, but it should not be used as the authoritative ingestion URL.

---

### Rank 5 — Official County Election Results

* **Entities:** Wisconsin’s 72 county clerks and county boards of canvassers
* **Scope:** Election-night returns and county-certified federal, state, county, and referendum results
* **Source types:** HTML tables, Excel, PDF, database portals, and vendor-generated reports
* **Access:** Usually public, no authentication
* **Update cadence:** Election night through county canvass
* **Machine-readability:** Highly variable
* **Integration value:** Essential for election-night reporting and county-level historical gaps

Examples of official access patterns include:

* Dane County: structured HTML result pages and an archive reaching at least 2004.
* Polk County: Excel-format unofficial results plus official canvass records.
* Oneida County: Excel and PDF election records with election notices and sample ballots.
* Wood County: structured HTML contest pages with election and contest identifiers visible in query parameters.
* Brown County: official historical records reaching 2000.

**County adapter strategy**

Create a county source registry with:

* County name and FIPS code
* Official clerk/result URL
* Result technology or format
* Election list or archive URL
* Whether results are unofficial, county-canvassed, or mixed
* Contest types included
* Local-contest limitations
* Stable election and contest identifiers, where available
* Pagination or file naming behavior
* Last successful retrieval
* Manual-review notes

Do not assume one vendor or schema across all counties.

---

### Rank 6 — Wisconsin Legislature Proposal and Joint-Resolution Records

* **Entity:** Wisconsin Legislature
* **Official base:** `https://docs.legis.wisconsin.gov/`
* **Scope:** Proposed constitutional amendments, advisory referenda, ballot language, legislative history, and legal authority
* **Source type:** HTML, PDF, and legislative database records
* **Data subjects:** Joint-resolution number, session, proposal text, ballot question, legislative actions, and constitutional section
* **Machine-readability:** Medium
* **Integration value:** Primary source for statewide ballot-measure definitions

Legislative joint resolutions can contain the exact question to be stated on the ballot. For example, the official record for SJR 71 includes ballot-language instructions.

**Ballot-measure workflow**

1. Detect enrolled or twice-approved constitutional-amendment resolutions.
2. Capture the exact ballot question and affected constitutional provisions.
3. Join the measure to the WEC election using election date and ballot-question text.
4. Ingest certified yes/no results from WEC.
5. Preserve the legislative proposal identifier as the primary provenance key.
6. Treat local referenda separately through county, municipal, or school-district notices.

---

### Rank 7 — Wisconsin Statutes and Certification Records

* **Entity:** Wisconsin Legislature
* **Official base:** `https://docs.legis.wisconsin.gov/statutes/`
* **Scope:** Election definitions, filing responsibilities, reporting, canvass, certification, recounts, recalls, wards, and election timing
* **Source type:** HTML and PDF legal documents
* **Machine-readability:** Medium
* **Integration value:** Authoritative source for rules and pipeline state transitions

Priority provisions for the source registry include:

* Chapter 5 — election definitions, districts, and wards
* Chapter 6 — electors and registration
* Chapter 7 — election officials, returns, canvass, and certification
* Chapter 8 — nominations and primaries
* Chapter 9 — recounts
* Chapter 10 — election notices
* Chapter 11 — campaign finance, read together with Ethics Commission materials
* Chapter 12 — prohibited election practices

Legal rules should control pipeline status labels such as `unofficial`, `county_canvassed`, `state_certified`, `recount_pending`, and `recount_completed`.

---

### Rank 8 — MyVote Wisconsin

* **Entity:** Wisconsin Elections Commission
* **Official URL:** `https://myvote.wi.gov/`
* **Scope:** Voter-specific registration, polling place, sample ballot, absentee, and election information
* **Source type:** Interactive HTML application
* **Access:** Public interface; some functions require voter-identifying inputs
* **API status:** No official public API verified
* **Integration value:** Human verification and ballot preview, not primary bulk ingestion

The repository file identified a MyVote election-results page, but automated access returned HTTP 403. No supported bulk interface or public API was verified.

Do not scrape voter-specific workflows or submit personal data. Use MyVote only for human review unless WEC publishes a documented bulk or API service.

---

## Election Types and Cycle Coverage

CivicMirror should normalize at least the following Wisconsin election types:

| Normalized type         | Typical scope                                                                   | Primary source path                                           |
| ----------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| Spring primary          | Nonpartisan contests requiring a primary                                        | WEC calendar, candidate tracker, WEC results, local results   |
| Spring election         | Judicial, education, municipal, school, and referendum contests                 | WEC results plus local clerks                                 |
| Presidential preference | Presidential party preference, generally associated with the spring cycle       | WEC candidate/ballot materials and results                    |
| Partisan primary        | Federal, state, legislative, district-attorney, and county partisan nominations | WEC candidate tracker and results                             |
| General election        | Federal, state, legislative, county, and referenda                              | WEC certified results and county reports                      |
| Special primary         | Vacancy election where a primary is required                                    | Governor’s order, WEC notices, candidate tracker, results     |
| Special election        | Vacancy or exceptional election                                                 | Governor’s order, WEC notices, results                        |
| Recall primary          | Recall nomination stage when required                                           | WEC recall records, candidate materials, and results          |
| Recall election         | Recall question and successor contest                                           | WEC decisions and results                                     |
| Statewide referendum    | Constitutional amendment or advisory question                                   | Legislature proposal, WEC ballot/results                      |
| Local referendum        | County, municipal, school, or special-district question                         | Local notices, ballots, canvass, and campaign-finance officer |

Official Dane County historical records demonstrate spring, partisan primary, general, recall primary, and recall election records within one county archive.

No separate recurring Wisconsin runoff-election source was identified. Do not generate runoff cycles automatically; create them only from a specific official order, notice, statute, or certified election record.

---

## CivicMirror Pipeline Map

| Pipeline subject       | Primary source                                | Suggested key                                                              | Extraction and update strategy                                         | Known gap                                                 |
| ---------------------- | --------------------------------------------- | -------------------------------------------------------------------------- | ---------------------------------------------------------------------- | --------------------------------------------------------- |
| Election calendar      | WEC election page, official notices, statutes | Date + normalized type + jurisdiction                                      | Refresh during each cycle; archive notices                             | No verified calendar API                                  |
| Election definition    | Statutes and WEC notices                      | Statute citation + election key                                            | Store legal and display names separately                               | Terminology varies by notice                              |
| Offices                | Candidate tracker, statutes, GIS              | Office type + district + term                                              | Extract tracker offices; normalize against statutory office list       | Local offices decentralized                               |
| Districts              | LTSB GIS Hub                                  | Geography type + district number + map vintage                             | Bulk GIS ingestion with vintage tracking                               | Ward changes require historical versions                  |
| Contests               | Candidate tracker, ballots, results files     | Election + office + district/jurisdiction                                  | Build preliminary contest from filings; confirm from certified results | Local contest universe incomplete centrally               |
| Candidates             | Candidate tracker and local filing officers   | Source candidate/receipt ID where present; otherwise name + office + cycle | Version filing status throughout nomination period                     | No single statewide local-candidate file                  |
| Filing status          | Candidate tracker                             | Candidate + document type + filing date                                    | Preserve each document and review status                               | PDF extraction                                            |
| Ballot qualification   | Candidate tracker and WEC decisions           | Candidate + election + office                                              | Use final approved status; retain earlier states                       | Challenges may be separate documents                      |
| Party affiliation      | Candidate tracker and certified results       | Candidate + election                                                       | Preserve source party label and normalized party                       | Nonpartisan contests need null/not-applicable distinction |
| Ballot measures        | Legislature proposal + WEC/local ballot       | Proposal ID or jurisdiction + exact question text                          | Match by exact and normalized question text                            | Local measures fragmented                                 |
| Election-night results | County and municipal pages                    | County source election ID or date/type                                     | County-specific polling; timestamp each snapshot                       | No statewide feed                                         |
| County canvass         | County clerk                                  | County + election + contest                                                | Replace or supersede election-night records while preserving versions  | Local contest authority varies                            |
| State certification    | WEC certified results                         | WEC election/file + contest                                                | File-hash monitoring; mark state-certified only from WEC               | Direct page currently bot-protected                       |
| Recount                | WEC order and recount files                   | Election + contest + petition/order ID                                     | Create recount event; ingest revised certification separately          | Documents may be PDF-only                                 |
| Recall                 | WEC recall filings and decisions              | Officeholder + office + recall cycle                                       | Model petition, sufficiency decision, primary, and election separately | Failed petitions may not reach results archive            |
| Campaign finance       | Sunshine                                      | Registrant/committee ID                                                    | Scheduled transaction exports and report snapshots                     | Local committees excluded                                 |
| Historical archives    | WEC and county archives                       | Source-specific election ID/date                                           | Inventory from newest backward; store missing-format flags             | Exact statewide earliest year unresolved                  |

---

## Recommended Implementation Order

### Phase 1 — Certified statewide results

1. Manually capture all election links from the WEC results and archive pages.
2. Build an inventory containing election date, election type, filename, format, certification status, and coverage.
3. Implement Excel ingestion before PDF extraction.
4. Test multiple election eras because workbook layouts may change.
5. Preserve original workbooks and raw cell values.

### Phase 2 — Candidate and contest creation

1. Archive each WEC Candidate Tracking revision.
2. Extract offices, districts, candidates, parties, filing documents, and staff-review status.
3. Create preliminary contests from approved candidates.
4. Reconcile the candidate list against the final ballot or certified results.
5. Add a local-filing-officer workflow for county, municipal, school, and special-district contests.

### Phase 3 — Campaign finance

1. Export registrants and transactions from Sunshine.
2. Identify stable committee and candidate identifiers.
3. Connect committees to WEC candidates using official identifiers where possible.
4. Retain PDF reports as legal source documents.
5. Create a separate local campaign-finance acquisition queue.

### Phase 4 — Geography

1. Capture current LTSB ArcGIS items and bulk-download URLs.
2. Load congressional, Senate, Assembly, county, municipality, and ward geography.
3. Build election-date-aware geography crosswalks.
4. Preserve every district-plan vintage used by historical elections.

### Phase 5 — Election-night county registry

1. Inventory all 72 official county result sites.
2. Classify each as structured HTML, Excel, PDF, database portal, or vendor application.
3. Prioritize structured HTML and downloadable spreadsheets.
4. Add municipal sources only where the county does not cover the required contest.
5. Clearly label all election-night records as unofficial.

---

## PDF and Manual-Review Queue

### Candidate Tracking PDFs

* **Landing page:** `https://elections.wi.gov/elections#tracker`
* **Document:** Candidate Tracking by Office
* **Coverage:** Election-specific state-filed candidates
* **Update frequency:** End of each business day during active filing
* **Difficulty:** Medium; repeated headers, page breaks, multi-line candidate and address fields
* **Action:** Capture the exact official PDF asset and archive every revision

### Recount Procedures

* **Official state-document URL:** `https://www.wistatedocuments.org/digital/api/collection/p267601coll4/id/18589/download`
* **Document:** Election Recount Procedures
* **Date:** April 2018
* **Coverage:** Recount petition, eligibility, fee, and filing procedures
* **Difficulty:** Low to medium
* **Caution:** Historical procedural document; verify against current statutes and current WEC guidance before operational use.

### GIS Documentation

* **Official URL:** `https://legis.wisconsin.gov/ltsb/gisdocs/wise_decade/documentation/wiselr_documentation.pdf`
* **Document:** Wisconsin Shape Editor for Local Redistricting documentation
* **Coverage:** Local redistricting and geography workflow
* **Difficulty:** Medium; procedural rather than direct election data.

---

## Access and Provenance Notes

* The WEC results, archive, statistics, and MyVote pages returned HTTP 403 to the automated retrieval environment used on August 9, 2026. This may be bot protection rather than a public-access restriction. Human browser validation is required.
* No WEC election-results API was verified.
* No Sunshine API was verified; spreadsheet export is the supported structured access method identified.
* No statewide election-night feed was identified.
* County result sources vary substantially in schema and authority.
* Local campaign-finance, candidate, referendum, and final-result records may reside with different filing officers.
* Historical files must retain their original district-plan vintage.
* Certified status should never be inferred from 100% precinct reporting.
* Store a file hash, retrieval time, source URL, publication label, and certification level for every downloaded result.
* Keep PDFs even when their tables are converted into structured data.

---

## Source Coverage Analysis

Wisconsin is suitable for a reliable CivicMirror pipeline, but not through one statewide system.

The strongest official integration path is:

1. **WEC certified Excel files** for final statewide results.
2. **Sunshine spreadsheet exports** for state campaign finance.
3. **LTSB GIS downloads** for districts and wards.
4. **WEC Candidate Tracking PDFs** for state-filed candidates and qualification status.
5. **Official county result sites** for election-night data and historical supplementation.
6. **Wisconsin Legislature records** for ballot-measure definitions and statutory provenance.

The central unresolved issue is live reporting. Wisconsin does not provide a single official statewide election-night data feed. CivicMirror must either defer Wisconsin ingestion until certified WEC files are posted or maintain a registry of county and, when necessary, municipal result sources.

The historical statewide archive also needs a complete manual inventory. Exact cycle coverage, file formats, workbook schemas, and missing election types should be recorded before claiming a statewide start year.

The prior recommendation to fill official-source gaps with Google Civic, Ballotpedia, OpenElections, OpenStates, OpenFEC, or an AP feed has been removed. These sources may help researchers detect discrepancies, but they should not determine CivicMirror’s official election, candidate, ballot-measure, or certification records.
