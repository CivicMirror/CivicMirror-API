# Utah Election Results — Research Notes

## Coverage Status

| Pipeline stage                       |                       Status | Best official source                                                         | Notes                                                                                                                                                                                             |
| ------------------------------------ | ---------------------------: | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Election calendar and cycle creation |                  ✅ Available | Current Election Information; annual election calendar                       | Covers regular primary/general dates, candidate deadlines, canvass periods, and odd-year municipal elections.                                                                                     |
| Election type and jurisdiction       |                  ✅ Available | Current Election Information; historical result index; county canvass pages  | Official sources distinguish regular primary, presidential primary, general, municipal primary/general, special congressional, special district, and some instant-runoff municipal elections.     |
| Offices and contests                 |                  ✅ Available | Notice of Election; candidate filings; certified candidate lists             | The Notice of Election is the best election-cycle office inventory.                                                                                                                               |
| Districts and precinct geography     |          ✅ **Official APIs** | Utah Geospatial Resource Center ArcGIS services                              | Public ArcGIS REST services support JSON, GeoJSON, and spatial queries.                                                                                                                           |
| Candidates and filing status         |                  ✅ Available | Candidate Filings HTML and Excel                                             | Includes office, party, and statuses such as filed, primary, election candidate, withdrew, disqualified, out in convention, and out in primary.                                                   |
| Ballot qualification                 |                  ✅ Available | Certified candidate documents; general-election certification                | Certification PDFs determine which candidates, judges, and statewide measures qualify for the ballot.                                                                                             |
| Election-night results               | ⚠️ Public; adapter not built | Utah Election Night Reporting portal                                         | Public Enhanced Voting portal with locality and precinct views, reports, real-time refresh, and a visible “Media Export” control. Export format and internal request endpoints remain unverified. |
| Certified results                    |                  ✅ Available | Statewide canvass PDFs; county canvass certifications                        | Certification must come from canvass documents rather than election-night reporting status.                                                                                                       |
| Precinct-level results               |              ⚠️ Mixed access | ENR precinct views; free data request                                        | Recent precinct results are available from the Lieutenant Governor’s Office by request with no fee; delivery format is not stated.                                                                |
| Historical results                   |                  ✅ Available | Historical Election Results index                                            | Online coverage reaches 1960–2024, with Excel for several 2016–2020 elections and PDF/HTML for other years.                                                                                       |
| Recounts and audits                  |                  ✅ Available | Election-cycle record pages                                                  | Recount reports, statewide certifications, affidavits, and audit-review documents are published as PDFs.                                                                                          |
| Ballot measures                      |                  ✅ Available | Initiatives and Referenda; ballot proposition numbering; voter pamphlets     | Statewide petition status is centralized. Local measure details remain partly decentralized to counties, cities, and recorders.                                                                   |
| Judicial retention                   |                  ✅ Available | Candidate filings; certification; Judicial Performance Evaluation Commission | Judicial retention candidates appear in the filing and certification sources; evaluations are maintained separately.                                                                              |
| Campaign finance                     |                  ✅ Available | Utah Financial Disclosures portal                                            | Public entity search and year/entity-type bulk download workflow. Municipal reports are stored separately by county.                                                                              |
| Voter registration statistics        |                  ✅ Available | Current Voter Registration Statistics                                        | Current HTML table plus annual Excel files for 2014–2026.                                                                                                                                         |
| Pre-1960 archives                    |           ⚠️ Archival/manual | Utah State Archives, Election Papers Series 364                              | Historical election papers cover 1851–1976, but much of the material requires archival or microfilm review.                                                                                       |

---

**Primary site:** https://vote.utah.gov/election-results-data-historical-information/
**Current results:** https://electionresults.utah.gov/results/public/Utah
**Historical results:** https://vote.utah.gov/historical-election-results/
**Candidate filings:** https://vote.utah.gov/2026-candidate-filings/
**Campaign finance:** https://disclosures.utah.gov/
**Election GIS:** https://gis.utah.gov/products/sgid/political/
**Operated by:** Utah Office of the Lieutenant Governor, with county clerks administering county and many local elections; GIS services are maintained by the Utah Geospatial Resource Center in coordination with the Lieutenant Governor’s Office.
**Researched:** March 4, 2026
**Updated:** August 4, 2026 — verified the Enhanced Voting results portal, candidate filing spreadsheet, campaign-finance bulk download, official GIS APIs, certification archives, and free precinct-results requests; corrected the earlier paid-access and missing-source assessment
**Accessed:** August 4, 2026
**Status:** Most election information is public without authentication. Voter files and ballot-processing reports use paid request workflows. No documented public election-results REST API was verified.

---

## Review of the Existing Research File

The prior file correctly identified the Lieutenant Governor’s Office, the current results portal, the historical-results index, voter-registration statistics, and the paid voter-data request service. It also correctly recorded the original research date of March 4, 2026.

Material corrections and additions:

1. **Results are not primarily behind a paid request barrier.** The public election-night portal provides current results, and the Lieutenant Governor’s Office says recent precinct-level result data can be requested without a fee.
2. **The state does have a live reporting system.** The portal identifies itself as Utah Election Night Reporting, auto-refreshes, reports a last-updated time, supports locality or precinct views, and displays a “Media Export” option.
3. **Candidate information is available from official sources.** The state publishes a current HTML filing table and an Excel workbook with candidate, office, party, and filing status. Candidate names commonly link to filing declarations.
4. **Ballot-measure information is available from official sources.** Utah publishes statewide initiative and referendum status, applications, fiscal-impact documents, signer records, determinations, and local petition records, as well as numbered municipal ballot propositions.
5. **Historical results extend beyond the page’s outdated “1960–2020” heading.** The same page now links 2022, 2023, and 2024 results, making the visible online span 1960–2024.
6. **“No API” requires qualification.** No documented results or candidate API was found, but Utah maintains official ArcGIS REST APIs for congressional, legislative, school-board, judicial, combined-district, and precinct geography.
7. The previous recommendations to rely on commercial or unofficial aggregators have been removed. The pipeline below is based on first-party Utah sources, with unresolved gaps marked for human review.

---

## Overview

Utah’s election information is distributed across four main official systems:

1. **Vote.Utah.gov** — calendars, candidate filings, certified candidate lists, historical results, statewide canvasses, county certifications, recounts, ballot measures, voter pamphlets, registration statistics, and data requests.
2. **Utah Election Night Reporting** — current and recent unofficial results, locality and precinct views, report pages, and a visible media-export function.
3. **Utah Financial Disclosures** — state campaign-finance entity records, reports, transactions, and year/entity-type downloads, with a separate municipal archive.
4. **Utah Geospatial Resource Center** — public ArcGIS REST services and downloadable GIS layers for election districts and precincts.

This division of responsibility means CivicMirror should not treat any single portal as the complete election record. Candidate filings establish who filed and how their status changed; certification documents establish ballot qualification; election-night reporting supplies changing unofficial totals; canvass documents establish official results; and GIS layers establish the geographic meaning and effective dates of districts.

Utah also divides election administration by jurisdiction. The Lieutenant Governor is the election official for statewide elections, while county clerks administer elections within their counties. Odd-numbered years generally contain municipal and most special-district elections; even-numbered years contain federal, state, and county elections.

---

## Ranked Official Source Inventory

### 1. Utah Geospatial Resource Center Political GIS Services

**Responsible entity:** Utah Geospatial Resource Center, with the Lieutenant Governor’s Office listed as co-steward for core political layers
**Source type:** GIS service / ArcGIS REST API / bulk GIS download
**Authentication:** None observed
**Election scope:** Statewide
**Election types:** All types requiring district or precinct geography
**Cycle coverage:** Current layers plus selected prior redistricting vintages
**Update cadence:** Redistricting cycles and periodic precinct or annexation updates
**Machine-readability:** Excellent — JSON, GeoJSON, PBF, ArcGIS query API, and downloadable GIS formats
**Pipeline subjects:** Districts, precincts, ballot areas, contest jurisdiction, address-to-district support

Verified endpoints:

| Geography                                                           | Feature service                                                                                                                   |
| ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| U.S. Congress, elections beginning in 2026                          | `https://services1.arcgis.com/99lidPhWCzftIe9K/ArcGIS/rest/services/political_us_congress_districts_2026_to_2032/FeatureServer/0` |
| U.S. Congress, 2022–2025 election geography                         | `https://services1.arcgis.com/99lidPhWCzftIe9K/ArcGIS/rest/services/political_us_congress_districts_2022_to_2026/FeatureServer/0` |
| Utah Senate, 2022–2032                                              | `https://services1.arcgis.com/99lidPhWCzftIe9K/ArcGIS/rest/services/UtahSenateDistricts2022to2032/FeatureServer/0`                |
| Utah House, 2022–2032                                               | `https://services1.arcgis.com/99lidPhWCzftIe9K/ArcGIS/rest/services/UtahHouseDistricts2022to2032/FeatureServer/0`                 |
| State School Board, 2022–2032                                       | `https://services1.arcgis.com/99lidPhWCzftIe9K/ArcGIS/rest/services/UtahSchoolBoardDistricts2022to2032/FeatureServer/0`           |
| Combined congressional, House, Senate, and school-board areas, 2026 | `https://services1.arcgis.com/99lidPhWCzftIe9K/ArcGIS/rest/services/political_district_combination_areas_2026/FeatureServer/0`    |
| Vista Ballot Areas / precincts                                      | `https://services1.arcgis.com/99lidPhWCzftIe9K/ArcGIS/rest/services/VistaBallotAreas/FeatureServer/0`                             |
| Judicial districts                                                  | `https://services1.arcgis.com/99lidPhWCzftIe9K/ArcGIS/rest/services/JudicialDistricts/FeatureServer/0`                            |

The 2026 congressional layer is especially important. Utah states that it supersedes the congressional boundaries used in 2022–2025 and is used for election purposes beginning January 1, 2026. The layer exposes `DISTRICT` as the district number and supports JSON, GeoJSON, and PBF queries.

The Vista Ballot Areas layer contains voting precincts or subprecincts for all 29 counties. County clerks submit the boundaries, and the state says dissolving geometries on `PRECINCTID` produces precinct polygons without subprecinct divisions. The layer is periodically updated for annexations and municipal-boundary changes.

**Suggested identifiers**

* `district_type`
* `district_number`
* `effective_from`
* `effective_through`
* ArcGIS `OBJECTID` as a source-row identifier only
* `PRECINCTID` for precinct normalization
* Geometry hash for change detection

**Normalization notes**

* Do not join districts by number alone; include district type and effective dates.
* Store the 2022–2025 and 2026 congressional maps as separate versions.
* Treat `OBJECTID` as service-specific and potentially unstable across republishing.
* Use the combined-district layer to validate district intersections, not as a replacement for the authoritative component layers.
* The judicial-district layer was last updated in 2005 and requires legal or court-site review before assuming it reflects every later administrative change.

---

### 2. Current Candidate Filings

**URL:** https://vote.utah.gov/2026-candidate-filings/
**Excel:** https://vote.utah.gov/wp-content/uploads/2026/06/Candidate-Filing-2026.xlsx
**Responsible entity:** Utah Office of the Lieutenant Governor
**Source type:** HTML table + Excel download + linked filing PDFs
**Authentication:** None
**Election scope:** Federal, statewide, state legislative, State Board of Education, and judicial retention offices handled through the state system
**Cycle coverage:** Current 2026 cycle
**Update cadence:** Stated as once daily by 4 p.m.; page last displayed an update of July 20, 2026
**Machine-readability:** High for Excel; moderate for HTML; low for linked declaration PDFs
**Pipeline subjects:** Candidates, office, district, party, filing status, declaration document

The filing page contains candidate, office, party, and status columns. Observed statuses include `Election Candidate`, `Primary`, `Filed`, `Out in Convention`, `Out in Primary`, `Withdrew`, and `Disqualified`.

**Recommended extraction**

1. Download and retain the Excel file on every observed change.
2. Parse the HTML table as a secondary check and to capture declaration links.
3. Store the source status exactly as published.
4. Map source statuses into separate CivicMirror fields:

   * `filed`
   * `advanced_to_primary`
   * `advanced_to_general`
   * `eliminated_at_convention`
   * `eliminated_in_primary`
   * `withdrawn`
   * `disqualified`
5. Do not infer ballot qualification solely from `Election Candidate`; reconcile with the formal certified-candidate document.

**Suggested candidate key**

`UT:{cycle}:{office_type}:{district}:{normalized_candidate_name}:{party}`

No universal candidate identifier was visible in the public table. Preserve declaration-document URLs as source identifiers and retain the unmodified display name.

**Known gap**

Municipal candidates generally file with local officials. The state candidate workbook should not be assumed to contain every city, town, or local special-district candidate.

---

### 3. Utah Financial Disclosures

**Public search:** https://disclosures.utah.gov/Search/PublicSearch
**Advanced search:** https://disclosures.utah.gov/Search/AdvancedSearch
**Municipal archive:** https://disclosures.utah.gov/municipal
**Responsible entity:** Utah Office of the Lieutenant Governor
**Source type:** Database portal / HTML search / bulk download / document archive
**Authentication:** Public search requires no login; filing requires an account
**Election scope:** State candidates and officeholders, PACs, political-issues committees, parties, corporations, electioneers, labor organizations, and independent expenditures
**Cycle coverage:** Multiple report years selectable in the portal
**Update cadence:** Filing-driven; portal displayed an August 4, 2026 update and version 4.4.0
**Machine-readability:** Potentially high through “Download Data by Year”; exact downloaded format was not verified during this review

The public search provides filed disclosure reports and statements of organization for multiple entity types. The advanced-search instructions state that users can select an entity type and report year and then use “Download Data by Year” to obtain all report data for that combination.

Municipal campaign-finance reports are stored separately in a county-folder hierarchy rather than being fully integrated into the statewide entity search.

**Pipeline use**

* Campaign-finance entities
* Candidate-to-finance-entity matching
* Contributions
* Expenditures
* Filing reports
* Entity status
* Statements of organization

**Suggested identifiers**

* Portal entity identifier from the entity URL or downloaded file, once inspected
* Report year
* Report type
* Filing date
* Transaction identifier, when provided
* Source document URL

**Normalization notes**

* Match candidates using name, office, district, and election cycle.
* Maintain a human-review queue for name changes, punctuation differences, joint fundraising entities, and candidates with multiple committees.
* Do not merge municipal folder documents with state portal entities solely by name.
* Federal candidate finance records are outside this state system; the state portal explicitly directs users elsewhere for federal filings. CivicMirror should record this as a scope boundary rather than treating the state source as incomplete.

**Unresolved item**

The bulk-download file type and schema should be manually captured before an adapter is designed.

---

### 4. Historical Structured Results

**URL:** https://vote.utah.gov/historical-election-results/
**Responsible entity:** Utah Office of the Lieutenant Governor
**Source type:** Excel, PDF, HTML pages
**Authentication:** None
**Election scope:** Federal, statewide, legislative, school-board, judicial, and ballot-question results where included in the statewide canvass
**Election types:** General, regular primary, presidential primary, special primary, and special general
**Visible cycle coverage:** 1960–2024
**Machine-readability:** Varies by year

The index currently links:

* 2024 general, primary, and presidential primary PDFs
* 2023 special congressional general certification
* 2022 general and primary PDFs
* 2020 general, regular primary, and presidential primary in PDF and Excel
* 2018 general and primary in PDF and Excel
* 2017 special general in PDF and Excel
* 2017 special primary in PDF
* 2016 general in PDF and Excel
* Earlier primary and general results through 1960, mostly through HTML or document links

Representative Excel files:

* `https://vote.utah.gov/wp-content/uploads/2023/09/2018-Primary-Election-State-Canvass.xlsx`
* `https://vote.utah.gov/wp-content/uploads/2023/09/2018-General-Election-Canvass.xlsx`

**Recommended extraction priority**

1. Excel files
2. Stable HTML result tables
3. Text-bearing PDFs
4. Image or poorly structured PDFs requiring manual review

**Historical limitations**

* Recent statewide canvass PDFs generally aggregate by county rather than precinct.
* Single-county contests may be presented only for information or deferred to the relevant county clerk.
* Older files vary substantially in layout, contest naming, party abbreviations, district notation, and write-in treatment.
* The historical page’s introductory text remains stale because it says “1960–2020” even though the page now includes 2022–2024 files. Use the actual link inventory rather than the heading.

---

### 5. Utah Election Night Reporting

**State portal:** https://electionresults.utah.gov/results/public/Utah
**2026 primary example:** https://electionresults.utah.gov/results/public/Utah/elections/Primary06232026
**Reports example:** https://electionresults.utah.gov/results/public/Utah/elections/Primary06232026/reports
**2024 general example:** https://electionresults.utah.gov/results/public/utah/elections/general11052024
**Responsible entity:** Utah election officials; portal branding states “powered by enhanced voting”
**Source type:** Interactive HTML portal / potential HTML scraping / visible media export
**Authentication:** None observed
**Election scope:** Statewide and participating county or municipal reporting jurisdictions
**Election types observed:** Primary, general, municipal primary, and municipal general
**Cycle coverage observed:** At least 2023–2026 through indexed public routes
**Update cadence:** Real-time or periodic during reporting; pages display a last-updated timestamp
**Machine-readability:** Unresolved

The portal exposes election pages, jurisdiction pages, report pages, contest-detail pages, locality views, and precinct views. Publicly indexed pages show:

* An `UNOFFICIAL RESULTS` label
* Last-updated timestamps
* Localities or precincts reporting
* Party filters for primary elections
* “View results by locality”
* “View results by precinct”
* A “Media Export” control
* Auto-refresh or real-time update language

Observed route patterns:

```text
/results/public/{jurisdiction}/elections/{election-slug}
/results/public/{jurisdiction}/elections/{election-slug}/reports
/results/public/{jurisdiction}/elections/{election-slug}/ballot-items/{contest-guid}
```

Observed query parameters include:

```text
party
sm
st
sv
fr
```

Examples show contest GUIDs in `ballot-items` routes and in the `sv` parameter. These are promising external contest identifiers but should not be treated as permanent until tested across portal updates.

#### API and network status

No official API documentation or confirmed public results endpoint was located. The portal likely performs browser network requests, but hidden endpoints, parameters, headers, and response formats were not observable with the available browser tools.

A HAR capture was not available. No network behavior has been invented.

Before building an adapter:

1. Manually activate **Media Export** and record the downloaded format, fields, and URL.
2. Capture browser network traffic during:

   * election-page load,
   * contest selection,
   * locality selection,
   * precinct view,
   * report download,
   * media export.
3. Record request method, URL, parameters, pagination, response content type, and whether authentication tokens are present.
4. Prefer the media export if it is a stable structured file.
5. Use HTML extraction only if no reusable official export exists.

#### Certification warning

The portal’s reporting percentage and `UNOFFICIAL RESULTS` label are operational status fields, not certification. CivicMirror should mark results official only after reconciling them with statewide or county canvass documents.

---

### 6. Recent Precinct-Level Results by Request

**URL:** https://vote.utah.gov/obtain-voter-registration-or-election-data/
**Responsible entity:** Utah Office of the Lieutenant Governor
**Source type:** Request-based data delivery
**Authentication:** Request submission required
**Fee:** None for recent precinct-level election results
**Format:** Not stated
**Historical coverage:** Described only as “recent elections”
**Pipeline subjects:** Precinct totals, contest results, candidate or option totals

The state expressly states that recent precinct-level election results can be requested and that there is no fee.

**Recommended request record**

For every request, retain:

* Request date
* Election name and date
* Requested geography
* Requested granularity
* State response
* Delivery date
* File name
* File hash
* Field list
* Any data dictionary
* State contact information
* Restrictions or caveats

**Known gaps**

* Delivery format is not published.
* “Recent” is undefined.
* Turnaround time is not stated.
* It is unclear whether requests include every county-administered municipal contest.
* This source is unsuitable for unattended polling but may be the best official route for certified precinct backfills.

---

### 7. Election Calendar and Notice of Election

**Current information:** https://vote.utah.gov/current-election-information/
**2026 calendar:** https://vote.utah.gov/wp-content/uploads/2026/01/2026-Utah-Election-Calendar.pdf
**2026 Notice of Election:** https://vote.utah.gov/wp-content/uploads/2025/11/2026-Notice-of-Election.pdf
**Responsible entity:** Utah Office of the Lieutenant Governor
**Source type:** HTML + PDF
**Authentication:** None
**Update cadence:** Each cycle and as amended
**Pipeline subjects:** Election definitions, election dates, filing windows, offices, districts, canvass deadlines, registration deadlines

The current election page identifies the 2026 regular primary as June 23 and links the official certified-candidate list and primary certification. It also explains the division between odd-year municipal elections and even-year federal, state, and county elections.

The annual calendar includes filing, voter-registration, ballot-mailing, early-voting, election-day, candidate-profile, and canvass events. It warns that dates are subject to legislative change and that Utah Code controls.

The amended Notice of Election identifies the November 3, 2026 regular general election, filing periods, offices to be filled, district descriptions, and filing fees.

**Recommended election key**

`UT:{YYYY-MM-DD}:{normalized_election_type}:{jurisdiction}`

Examples:

```text
UT:2026-06-23:regular_primary:statewide
UT:2026-11-03:regular_general:statewide
UT:2025-08-12:municipal_primary:{jurisdiction}
UT:2025-11-04:municipal_general:{jurisdiction}
```

Store source terminology separately from CivicMirror’s normalized election type.

---

### 8. Certification, County Canvasses, Recounts, and Audits

**2024 election records:** https://vote.utah.gov/2024-election-information/
**Historical county canvasses:** https://vote.utah.gov/county-canvass-certifications-and-results/
**Historical records:** https://vote.utah.gov/historical-election-records-and-documents/
**Responsible entities:** Lieutenant Governor, county boards of canvassers, and county clerks
**Source type:** HTML indexes + PDF certifications and reports
**Authentication:** None
**Pipeline subjects:** Certification, official results, recounts, audit findings, write-in qualification, ballot order

The 2024 election page links the statewide canvass, county canvasses, primary certification, presidential-primary canvass, congressional recount, official general-election certification, write-in certification, constitutional-amendment notice, audit review, and candidate filings.

The county-canvass index includes 2024 primary and general, 2025 municipal primary and general, and 2026 primary materials.

Municipal coverage is decentralized. For the 2025 municipal general election, the state index says it contains countywide materials where county clerks administered elections, while individual city canvass materials must be obtained from the city. The 2025 primary page similarly identifies municipalities whose results are hosted on city sites.

The 2024 Congressional District 2 recount report is a useful model: it identifies the contest, counties, revised totals, original-versus-recount changes, certification date, and statutory basis.

**Certification strategy**

* `unofficial`: election-night portal
* `county_certified`: county canvass document
* `state_certified`: statewide canvass or certification
* `recount_certified`: recount report and subsequent canvass
* `amended`: later amended or corrected canvass

Store the certification document URL, document date, signatory, scope, and file hash.

---

### 9. Ballot Measures, Initiatives, and Referenda

**Current and historical petition records:** https://vote.utah.gov/initiatives-and-referenda/
**Current proposition numbers:** https://vote.utah.gov/current-ballot-proposition-names-and-numbers/
**Historical voter pamphlets:** https://vote.utah.gov/historical-voter-information-pamphlets-2/
**Responsible entity:** Utah Office of the Lieutenant Governor; local clerks or recorders for local measures
**Source type:** HTML, PDF, linked data files, audio, and petition-signer records
**Authentication:** None for public records
**Pipeline subjects:** Measure application, jurisdiction, title, status, filing date, fiscal impact, petition sufficiency, qualification, ballot number, results

The initiatives page distinguishes statewide and local initiatives and referenda and records statuses such as sufficient, insufficient, withdrawn, inactive, and bill repealed. It links applications, proposed laws, fiscal-impact statements, signer records, hearing materials, and final determinations.

The ballot-proposition numbering page provides official numbers and names for municipal propositions but directs users to city recorders for further information.

Historical Voter Information Pamphlets are indexed from 1976 through 2024, with gaps in odd years except where a pamphlet was issued. These pamphlets are valuable for official ballot titles, arguments, judicial information, and candidate profiles but are PDF-oriented and require document extraction.

The 2018 election-record page demonstrates how the state archives constitutional amendments, a nonbinding question, propositions, certification documents, candidate filings, and initiative materials together by cycle.

**Suggested measure key**

`UT:{jurisdiction}:{election_date}:{measure_type}:{official_number}`

Fallback when no number has been assigned:

`UT:{jurisdiction}:{filed_date}:{normalized_title}`

**Normalization notes**

Keep separate fields for:

* Petition/application title
* Official ballot title
* Proposition or amendment number
* Measure type
* Jurisdiction
* Sponsor or applicant
* Filing date
* Qualification status
* Ballot appearance status
* Election result
* Certification status

A petition that was once sufficient may later be withdrawn, superseded, invalidated, or made moot by legislation. Preserve status history rather than overwriting it.

---

### 10. Voter Registration and Aggregate Election Statistics

**Current statistics:** https://vote.utah.gov/current-voter-registration-statistics/
**Data landing page:** https://vote.utah.gov/election-results-data-historical-information/
**Responsible entity:** Utah Office of the Lieutenant Governor
**Source type:** HTML table + Excel downloads
**Authentication:** None
**Cycle coverage:** Annual Excel files for 2014–2026
**Update cadence:** Periodic; current page displayed July 27, 2026
**Pipeline subjects:** Active and inactive registration by party, county, and year; election context and denominator data

The current page provides active, inactive, and total registration by party and links annual Excel workbooks for 2014 through 2026.

The main data landing page also links aggregated canvass statistics, NVRA data, list-maintenance data, historical results, county canvasses, and campaign-finance records.

Observed aggregate workbook:

`https://vote.utah.gov/wp-content/uploads/2025/12/Master-Aggregated-Numbers-2023-2025.xlsx`

**Pipeline use**

These are supporting statistics rather than contest results. Keep registration snapshots keyed by:

* Snapshot date
* County
* Party
* Active/inactive status

Do not use a later registration snapshot as the denominator for an earlier election unless the source explicitly identifies it as the election’s registration total.

---

### 11. Paid Voter and Ballot-Processing Data

**URL:** https://vote.utah.gov/obtain-voter-registration-or-election-data/
**Responsible entity:** Utah Office of the Lieutenant Governor
**Source type:** Paid request / tab-delimited bulk file
**Authentication:** Request and payment
**Machine-readability:** High, but access-controlled by fee and request workflow

#### Statewide voter file

* Fee: $1,050 for a one-time purchase
* Format: Tab-delimited
* Approximate size: 150 MB
* Delivery: Email download link
* Includes voter ID, name, age range, address, county, precinct, multiple districts, party, status, last update, and participation history
* Excludes protected at-risk records from public delivery
* County or district-only lists must be requested from the relevant county clerk

#### Who Has Voted report

* Fee: $35 per election
* Regular even-year primary and general elections only
* Tab-delimited
* Delivered daily beginning 21 days before Election Day through the day before the election
* Includes voter ID, voter identity fields, county, precinct, congressional district, voting method, processing date, and party

#### Who Has Been Sent an Absentee Ballot report

* Fee: $35 per election
* Regular even-year primary and general elections only
* Tab-delimited
* Daily pre-election delivery
* Includes voter and ballot-order or processing fields subject to privacy restrictions

These sources are useful for turnout and ballot-processing research but are not required to create elections, contests, candidates, or certified results.

---

### 12. Utah State Archives

**Series search:** https://axaemarchives.utah.gov/solr/axaem/Series?fq=recordType%3ASeries&fq=seriesNo%3A364
**Responsible entity:** Utah Division of Archives and Records Service
**Source type:** Archival catalog, physical records, microfilm, limited catalog CSV
**Authentication:** Public catalog; record access may require an archival request or visit
**Coverage:** 1851–1976 for Election Papers Series 364
**Pipeline subjects:** Early election returns, candidates, referenda, initiatives, constitutional amendments, bond questions, party affiliation, apportionment, and campaign-finance history

Series 364 contains 33.9 cubic feet and 65 microfilm reels of election papers and covers territorial and state election duties, results, initiatives, referenda, constitutional amendments, and related subjects from 1851–1976.

**Machine-readability**

The catalog result can be exported as CSV, but this exports descriptive inventory metadata, not normalized election results. Most underlying records require manual archival review.

**Recommended archival identifiers**

* Series number
* Container or reel
* Folder
* Record title
* Date range
* Creating agency
* Digital-object URL, where available

---

## Election-Type Coverage

| Election type                      | Official evidence and source                                                                              | Pipeline treatment                                                                        |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Regular primary                    | Current election page, ENR, statewide canvass, historical index                                           | Full election, contest, candidate, results, and certification pipeline                    |
| Presidential primary               | Historical index and canvass PDFs                                                                         | Preserve as separate election type                                                        |
| Regular general                    | Notice of Election, ENR, statewide canvass                                                                | Full pipeline                                                                             |
| Municipal primary                  | County canvass index and municipal election pages                                                         | State index plus county/city source discovery                                             |
| Municipal general                  | ENR and county canvass index                                                                              | State, county, and city sources may all be needed                                         |
| Special congressional              | 2017 special primary/general and 2023 CD2 records                                                         | Preserve vacancy reason and special-election sequence                                     |
| Special-district elections         | Current election information says most occur in odd years                                                 | Usually county or local administration; state coverage may be incomplete                  |
| Judicial retention                 | Candidate filings, certification, voter pamphlet, judicial evaluation site                                | Model as yes/no retention contest, not a candidate-vs-candidate race                      |
| Constitutional amendments          | Certification, Class A notices, voter pamphlets, results                                                  | Measure pipeline                                                                          |
| Initiatives and referenda          | Initiatives portal, petition records, certification, results                                              | Preserve petition lifecycle and ballot lifecycle separately                               |
| Local propositions and bonds       | Proposition numbering, county/city records, ENR                                                           | Jurisdiction-specific discovery required                                                  |
| Instant-runoff municipal elections | Utah law and an older state pilot page confirm the election method                                        | Current participating-jurisdiction list was not verified centrally; flag for local review |
| Recounts                           | Election-cycle pages and recount PDFs                                                                     | Create a recount event linked to the original contest and certification                   |
| Recall elections                   | No centralized recall-election source or recent recall cycle was identified in the reviewed state indexes | Unresolved; research county and municipal sources if a recall is announced                |
| Traditional runoff election        | No statewide recurring runoff series was identified                                                       | Do not create by assumption; distinguish from instant-runoff voting and recounts          |

Utah’s current recount statute separately addresses ordinary races, ballot propositions, and instant-runoff races, reinforcing the need to model recounts independently from runoff elections.

---

## CivicMirror Pipeline Map

| Pipeline stage         | Primary source                                           | Suggested identifiers and joins                       | Update strategy                                          | Extraction and normalization notes                                         |
| ---------------------- | -------------------------------------------------------- | ----------------------------------------------------- | -------------------------------------------------------- | -------------------------------------------------------------------------- |
| Election calendar      | Current Election Information; annual PDF calendar        | Election date + official name + jurisdiction          | Check monthly in-cycle and after legislative sessions    | Utah Code supersedes calendar dates; retain document version               |
| Election definition    | Notice of Election; historical index                     | `UT:{date}:{type}:{jurisdiction}`                     | Once when announced; revise on amendment                 | Preserve “regular,” “municipal,” “special,” and “presidential” terminology |
| Election type          | Same as above                                            | Normalized type + official type                       | On source change                                         | Do not collapse municipal, special, and presidential primaries             |
| Offices                | Notice of Election                                       | Office type + district + term + cycle                 | At notice publication and amendment                      | Office list is more reliable than inferring from ENR                       |
| Districts              | UGRC FeatureServers                                      | District type + number + effective date               | Poll metadata monthly; snapshot before each cycle        | Version 2026 congressional geography separately                            |
| Precincts              | Vista Ballot Areas                                       | `PRECINCTID` + county + effective date                | Snapshot near registration close and Election Day        | Dissolve subprecincts only when precinct-level analysis requires it        |
| Candidates             | Candidate Filing workbook                                | Cycle + office + district + name + party              | Daily during filing and qualification periods            | Preserve source status history                                             |
| Filing documents       | Candidate-name declaration links                         | Declaration URL + candidate key                       | Capture on discovery                                     | PDF/manual extraction may be needed                                        |
| Ballot qualification   | Certified candidate PDF                                  | Candidate key + certification date                    | On each amended certification                            | Certification overrides preliminary filing status                          |
| Party affiliation      | Candidate filing workbook and certification              | Candidate key + source party label                    | On filing/certification changes                          | Preserve official party label and normalized party separately              |
| Contests               | Notice + certification + ENR                             | Office/district/party/election; ENR GUID when present | Create from certified ballot; reconcile when ENR appears | Do not create solely from free-text result headings without jurisdiction   |
| Election-night results | ENR                                                      | Election slug + contest GUID + jurisdiction           | Poll during reporting; stop after certification          | Mark unofficial regardless of 100% reporting                               |
| Precinct results       | ENR precinct view or free state request                  | Election + contest + county + `PRECINCTID`            | Request after certification                              | Retain raw precinct label for reconciliation                               |
| Certified results      | Statewide and county canvass                             | Election + contest + candidate/option + jurisdiction  | Ingest after signed canvass; monitor amendments          | Signed canvass is authoritative                                            |
| Recounts               | Recount report                                           | Original contest + recount date                       | Event-driven                                             | Store original and recounted totals; never overwrite without provenance    |
| Ballot measures        | Initiatives portal, proposition numbering, certification | Jurisdiction + election + number/title                | Monitor petition stages; freeze certified ballot version | Petition status and ballot status are separate                             |
| Judicial retention     | Filing workbook, certification, voter pamphlet           | Judge + court + district + election                   | On filing/certification                                  | Normalize choice labels to retain/not retain while preserving source text  |
| Campaign finance       | Disclosure portal                                        | Portal entity ID + candidate join                     | Daily or weekly in-cycle                                 | Bulk year download preferred once schema is verified                       |
| Voter registration     | Registration-statistics Excel                            | Snapshot date + county + party + status               | Monthly and pre-election                                 | Supporting context, not result totals                                      |
| Historical archive     | Historical results + State Archives                      | Election date/type; archive series/container          | One-time backfill with QA                                | Prefer Excel; queue PDF and archival records for manual review             |

---

## Source Relationships and Recommended Ingestion Order

### Current-cycle election setup

1. Use the annual calendar and Notice of Election to create the election, dates, offices, and districts.
2. Load current UGRC geography using the correct effective period.
3. Load candidate filings daily and retain status history.
4. Reconcile candidates against certified-candidate documents.
5. Use ballot-measure certification and proposition numbering to create measures.
6. Create contests from the certified ballot structure.
7. Add ENR election slugs and contest GUIDs when the portal publishes the election.

### Election-night operation

1. Poll the official ENR.
2. Retain every source timestamp and extraction timestamp.
3. Treat all portal totals as unofficial.
4. Use locality and precinct views only where the portal clearly identifies the geography.
5. Do not use reporting percentage as a certification signal.

### Certification

1. Acquire county canvasses for single-county and local races.
2. Acquire the statewide canvass for statewide and multi-county races.
3. Link recount or amended canvass documents where applicable.
4. Set official status only from the appropriate signed certification.

### Historical backfill

1. Ingest all available Excel workbooks.
2. Extract recent text-bearing PDFs.
3. Process stable HTML tables.
4. Queue difficult PDFs for manual review.
5. Request recent precinct files from the Lieutenant Governor’s Office.
6. Contact county clerks for single-county and municipal detail.
7. Use State Archives Series 364 for pre-1960 and other missing early records.

---

## High-Value Official PDF Registry

| Document                                       | Official URL                                                                                                    | Coverage                                                                       | Extraction difficulty                                     |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | --------------------------------------------------------- |
| 2026 Utah Election Calendar                    | `https://vote.utah.gov/wp-content/uploads/2026/01/2026-Utah-Election-Calendar.pdf`                              | Filing, voting, election, and canvass dates                                    | Medium; visual calendar layout                            |
| 2026 Amended Notice of Election                | `https://vote.utah.gov/wp-content/uploads/2025/11/2026-Notice-of-Election.pdf`                                  | Offices, districts, terms, fees, filing windows                                | Medium; text extractable but nested lists need validation |
| 2024 General Election Statewide Canvass        | `https://vote.utah.gov/wp-content/uploads/2025/02/2024-General-Election-Statewide-Canvass-2.pdf`                | County-level certified totals and selected single-county informational results | High; wide tables and repeated headers                    |
| 2024 Primary Statewide Canvass                 | `https://vote.utah.gov/wp-content/uploads/2024/07/2024-Primary-Election-State-Canvass-Final-Signed.pdf`         | Federal, statewide, multicounty legislative, and school-board results          | High; spreadsheet rendered as PDF                         |
| 2024 Presidential Primary Canvass              | `https://vote.utah.gov/wp-content/uploads/2024/03/2024-Presidential-Primary-Election-State-Canvass-Signed.pdf`  | Presidential-primary totals                                                    | Medium                                                    |
| 2023 CD2 Special Election Certification        | `https://vote.utah.gov/wp-content/uploads/2023/12/Signed-Certification-of-2023-CD2-Election.pdf`                | Special congressional general election                                         | Medium                                                    |
| 2022 General State Canvass                     | `https://vote.utah.gov/wp-content/uploads/2022/12/Signed-2022-General-Election-State-Canvass-Certification.pdf` | 2022 general results                                                           | High; 30 pages                                            |
| 2022 Primary Statewide Canvass                 | `https://vote.utah.gov/wp-content/uploads/2022/07/2022-Signed-Primary-Election-Statewide-Canvass.pdf`           | 2022 primary                                                                   | Medium                                                    |
| 2020 General Canvass                           | `https://vote.utah.gov/wp-content/uploads/2020/12/2020-General-Election-Canvass.pdf`                            | 2020 general                                                                   | High; use linked Excel instead                            |
| 2020 Regular Primary Canvass                   | `https://vote.utah.gov/wp-content/uploads/2020/07/2020-Primary-Election-Canvass.pdf`                            | 2020 primary                                                                   | Medium; use linked Excel instead                          |
| 2020 Presidential Primary Canvass              | `https://vote.utah.gov/wp-content/uploads/2021/03/2020-Presidential-Primary-Election-State-Canvass.pdf`         | 2020 presidential primary                                                      | Medium; use linked Excel instead                          |
| 2024 Congressional District 2 Recount          | `https://vote.utah.gov/wp-content/uploads/2024/08/CD2-Recount-Signed.pdf`                                       | Final recount totals and changes                                               | Low; one-page table                                       |
| 2024 General Election Certification            | `https://vote.utah.gov/wp-content/uploads/2024/09/2024-Official-General-Election-Certification.pdf`             | Qualified candidates, judges, parties, and statewide amendments                | High; 37 pages                                            |
| 2024 Proposed Constitutional Amendments Notice | `https://vote.utah.gov/wp-content/uploads/2024/09/Const.-Amend.-Class-A-Notice-1.pdf`                           | Official amendment titles and legal text                                       | High; long legal text                                     |

The historical-results index remains the authoritative link registry for the other 1960–2024 files. A production archive job should enumerate and snapshot every linked document because WordPress upload URLs and older HTML pages may change independently.

---

## Known Gaps and Human-Review Items

1. **ENR media export:** The control is visible, but its file type, URL, schema, and stability were not verified.
2. **ENR network requests:** No HAR capture was possible. No internal API should be claimed until requests are observed and reproduced.
3. **Local municipal completeness:** Some municipal canvasses reside only with cities, even when countywide materials are indexed by the state.
4. **Current instant-runoff participation:** Utah has used a municipal alternative-voting pilot, but the central page found during research was stale or unavailable. Verify participating municipalities from current county and city sources.
5. **Recall elections:** No centralized state recall-election archive was identified.
6. **Candidate history:** The current filing workbook is excellent for 2026 but is not a unified historical candidate database.
7. **Candidate identifiers:** No durable statewide candidate ID was visible.
8. **Precinct-result request format:** The state offers recent files for free but does not publish a schema or historical cutoff.
9. **Campaign-finance download schema:** The portal documents a year/entity-type download but not its public file specification.
10. **Older results:** Many pre-2016 elections are HTML or PDF only, and some files require manual table interpretation.
11. **Pre-1960 records:** State Archives holdings are not a normalized digital dataset.
12. **Judicial geography:** The UGRC judicial-district layer is old and should be checked against current court administration before use.
13. **Effective district dates:** The 2026 congressional map differs from the 2022–2025 map; a district-number-only join will produce incorrect history.
14. **Certification scope:** Statewide canvasses may list single-county races only for information and direct users to county clerks for final local results.
15. **PDF amendments:** Certification and canvass files can be amended after initial publication. Retain file hashes, observed dates, and supersession links.

---

## Recommended CivicMirror Implementation Priority

### Priority 1 — Structured, stable sources

1. UGRC ArcGIS district and precinct services
2. Current candidate filing Excel workbook
3. Historical election-result Excel workbooks
4. Current and historical voter-registration Excel workbooks
5. Campaign-finance “Download Data by Year,” after manual schema verification

### Priority 2 — Public operational sources

6. ENR media export, if verified as structured and stable
7. ENR HTML extraction as fallback
8. Current election and Notice of Election parsing
9. Initiatives and referenda HTML extraction

### Priority 3 — Document and request workflows

10. Statewide canvass PDFs
11. County certification PDFs
12. Recount and audit reports
13. Free precinct-result requests
14. Municipal and city-specific canvass collection
15. State Archives research

---

## Source Coverage Analysis

Utah has substantially better official election-data coverage than the prior research file indicated. It does not provide one comprehensive election API, but it does provide:

* Public real-time election-night reporting
* A visible media-export workflow
* Current candidate filings in Excel and HTML
* Formal candidate and ballot certifications
* Free recent precinct-result requests
* Historical election results from 1960 through 2024
* Structured Excel results for several modern cycles
* Statewide and county canvass archives
* Recount and audit documents
* Current and historical ballot-measure records
* Campaign-finance search and year/entity-type downloads
* True public ArcGIS REST APIs for election geography
* Voter-registration statistics in HTML and annual Excel files

The principal integration risk is fragmentation rather than absence. Election definitions, filings, unofficial results, certified results, local contests, campaign finance, and geography are maintained in different systems. Municipal data is especially decentralized.

For CivicMirror, the strongest path is:

1. Build election and office definitions from the calendar and Notice of Election.
2. Build candidates from the state filing workbook and certified lists.
3. Build geography from versioned UGRC APIs.
4. Use ENR for unofficial reporting after the media-export behavior is verified.
5. Replace unofficial totals with signed state or county canvasses.
6. Backfill recent structured workbooks first.
7. Use free precinct requests, county clerks, PDFs, and archives for remaining historical detail.

**Overall assessment:** Utah is feasible for a reliable official-source pipeline. Stage 1 can be built without Google Civic or another aggregator. Stage 2 has a public official source and is no longer properly classified as blocked by a paid-results barrier, but the best automated extraction method remains unresolved until the ENR media export or browser requests are manually captured.
