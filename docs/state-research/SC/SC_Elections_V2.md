# South Carolina Election System — Research Notes

## Coverage Status

| CivicMirror stage                 | Status                                  | Recommended official source                                                           |
| --------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------- |
| Election calendar and creation    | ✅ Available                             | SEC Upcoming Elections pages and annual election-calendar PDFs                        |
| Election-type classification      | ✅ Available                             | SEC election calendar, result archive, and Title 7                                    |
| Office and district creation      | ✅ Available                             | Candidate Tracking System and Revenue and Fiscal Affairs mapping                      |
| Candidate ingestion               | ✅ Available                             | SEC Candidate Tracking System                                                         |
| Filing status and documents       | ✅ Available                             | Candidate Tracking System and candidate-document downloads                            |
| Ballot qualification              | ✅ Available                             | Candidate status and filed documents in Candidate Tracking                            |
| Party affiliation                 | ✅ Available                             | Candidate Tracking and official results                                               |
| Ballot and referendum definitions | ✅ Available                             | SEC Referendum Tracking and historical election database                              |
| Election-night results            | ✅ Structured downloads                  | SEC ENR portal with CSV, XLS, XML, and legacy TXT reports                             |
| Certified results                 | ✅ Available                             | State Board of Canvassers records and signed certification sheets                     |
| Historical result backfill        | ⚠️ Multiple systems                     | ENR archive, historical election database, biennial reports, and SEC requests         |
| Primary runoffs                   | ✅ Available                             | Separate election, candidate, results, certification, recount, and audit records      |
| Recounts                          | ✅ Available                             | Separate ENR reports, canvass records, and mandatory-recount law                      |
| Special elections                 | ✅ Available                             | Calendar, Candidate Tracking, ENR archive, and special-election archive               |
| Municipal elections               | ⚠️ Incomplete centrally                 | SEC ENR where administered; otherwise municipal or county election authority          |
| Recall elections                  | ⚠️ No general recurring source verified | Research specific enabling law or election order before creating a recall cycle       |
| Campaign finance                  | ✅ Searchable portal                     | South Carolina State Ethics Commission public reporting system                        |
| Election audits                   | ✅ Available                             | SEC hand-count and results-verification audit pages                                   |
| Precinct and district geography   | ✅ Bulk GIS files                        | South Carolina Revenue and Fiscal Affairs Office                                      |
| Public election-results API       | ❌ Not verified                          | Structured downloads are available, but no supported REST API documentation was found |

---

**Primary election authority:** South Carolina State Election Commission
**Current election-results page:** `https://scvotes.gov/elections-statistics/election-results/`
**Election-night reporting host:** `https://www.enr-scvotes.org/`
**Historical election database:** `https://electionhistory.scvotes.gov/`
**Candidate and referendum tracking:** `https://vrems.scvotes.sc.gov/Candidate/SelectElection`
**Upcoming elections:** `https://scvotes.gov/elections-statistics/upcoming-elections/`
**Certification notices:** `https://scvotes.gov/about-the-sec/public-notices/`
**Election audits:** `https://scvotes.gov/elections-statistics/election-audits/`
**Campaign finance:** `https://apps.sc.gov/publicreporting/index.aspx`
**Political GIS:** `https://rfa.sc.gov/programs-services/precinct-demographics/jurisdictional-mapping`
**Operated by:** South Carolina State Election Commission, South Carolina State Ethics Commission, South Carolina Revenue and Fiscal Affairs Office, State Board of Canvassers, county election boards, and municipal election commissions
**Researched:** March 4, 2026
**Updated:** August 9, 2026 — corrected the results URL and agency name; verified structured ENR downloads, historical contest CSVs, candidate and referendum tracking, certification documents, campaign finance, audits, calendars, and GIS files; documented municipal and historical gaps
**Access checked:** August 9, 2026
**Status:** Public access; no user authentication normally required, although the ENR host presented automated-browser verification or blocking during this review

---

## Overview

South Carolina has a substantially stronger official election-data environment than the original repository note described. The State Election Commission maintains several complementary systems:

1. An election-night reporting portal with structured statewide, county, and precinct result downloads.
2. A searchable historical election database with per-contest CSV exports.
3. A candidate and referendum tracking system with stable election, candidate, and referendum identifiers.
4. Annual calendars containing election numbers, dates, jurisdictions, types, and filing periods.
5. State Board of Canvassers notices and signed certification documents.
6. Public post-election audit reports.
7. An official campaign-finance reporting portal.
8. Bulk precinct GIS files and political-district maps.

These systems should be treated as separate but related pipeline layers. Election-night reports are initially unofficial. County boards review provisional ballots and certify results, after which the State Election Commission, acting as the Board of State Canvassers, certifies applicable statewide, federal, legislative, multicounty, constitutional-amendment, and other state-canvassed contests.

South Carolina’s strongest integration feature is its official **Election Number**. The annual SEC calendar identifies the November 3, 2026 Statewide General Election as election number `22596`, and the Candidate Tracking System uses `electionId=22596` for the same election. This provides a verified first-party join between the calendar, candidates, filing records, and referenda.

The ENR portal uses a different result-site identifier, such as `126718` for the June 23, 2026 runoff. Do not assume that the ENR directory number equals the SEC Election Number. Link those systems by official name, date, type, and jurisdiction until a direct crosswalk is verified.

---

## Changes from the Existing Repository File

### Supported findings retained

The original file correctly stated that:

* South Carolina publishes county- and precinct-level results.
* Historical election results are available.
* Downloadable result files exist.
* No public REST API had been identified.

Those findings remain supported, although the structured download options and historical systems are much more extensive than the original note indicated.

### Corrected result URL

The repository uses:

`https://www.scvotes.gov/election-results`

The current official page is:

`https://scvotes.gov/elections-statistics/election-results/`

The old URL should be treated as stale and replaced.

### Corrected agency name

Use **South Carolina State Election Commission**, abbreviated **SEC**, rather than “South Carolina Election Commission” when recording the formal responsible entity.

### Added sources

The consolidated research adds:

* The current and historical ENR archive.
* The official historical election database.
* Candidate Tracking and filing-document access.
* Referendum Tracking.
* Election Number joins.
* State Board of Canvassers certification records.
* Election audits.
* State Ethics Commission campaign-finance records.
* Revenue and Fiscal Affairs GIS data.
* Biennial election-report PDFs from 1968 through 2008.
* Municipal-election coverage limitations.

### API classification correction

No supported public election-results REST API was verified. The historical system’s URL contains `/api/download_contest/`, but it is an undocumented per-contest CSV download linked by the official database. It must be classified as a **database portal with CSV download**, not as an official API.

---

# Source Inventory

## Rank 1 — SEC Election-Night Reporting Portal

**Responsible entity:** South Carolina State Election Commission
**Official archive page:** `https://scvotes.gov/elections-statistics/election-results/`
**Reporting host:** `https://www.enr-scvotes.org/`

### Scope

The official results page links ENR reports from 2008 through 2026, including:

* Presidential preference primaries
* Statewide partisan primaries
* Primary runoffs
* General elections
* Special primaries
* Special runoffs
* Special general elections
* Recounts
* State and local referenda
* Many municipal elections

The archive contains separate entries for original results, recounts, and runoffs rather than silently replacing one result with another.

### Source type

* Database portal
* Bulk CSV download
* Bulk Excel download
* Bulk XML download
* Legacy delimited-text download
* Interactive HTML reporting pages

### Observed report formats

Official ENR report menus expose or have exposed:

* **Summary CSV:** statewide contest totals
* **Detail XLS:** detailed county or precinct results
* **Detail XML:** structured detailed results
* **Detail TXT:** legacy detailed export on older elections
* Printable and interactive HTML reports

Current indexed report menus show Summary CSV and detailed XLS/XML options; older election pages also expose detailed TXT exports.

### Access

* Public browser access
* No account or API token identified
* Automated requests encountered JavaScript verification or HTTP blocking
* No supported REST API documentation found

### Machine-readability

**High**, provided the downloadable reports can be fetched consistently.

Preferred order:

1. Detail XML
2. Detail XLS
3. Summary CSV
4. Detail TXT
5. HTML pages
6. Printable reports

The best format must be selected after schema testing. XML may offer explicit hierarchy, while XLS may be easier for researchers to inspect and may contain fields absent from the summary CSV.

### Update cadence

* Updated throughout election night as county returns are received.
* Provisional ballots and canvass changes can alter totals after election night.
* Results become official only after certification.

The SEC says election-night results are reported in real time as county boards transmit them. County boards later decide which provisional ballots count, and the SEC subsequently certifies applicable results.

### Extraction approach

For each ENR election:

1. Capture the election landing-page URL and ENR election identifier.
2. Capture all available report links.
3. Download the most detailed structured format.
4. Preserve the summary report for reconciliation.
5. Store each retrieval as a timestamped snapshot.
6. Detect changes using a content hash.
7. Retain the reporting percentage and any unofficial/official label.
8. Replace neither preliminary nor recount versions; connect them as result revisions.
9. Compare the final ENR totals against the signed canvass and certification documents.

### Observable route patterns

Examples include:

```text
https://www.enr-scvotes.org/SC/{enrElectionId}/
https://www.enr-scvotes.org/SC/{enrElectionId}/{siteBuild}/en/reports.html
```

The exact report-file hrefs should be captured in a normal browser. A HAR file could not be produced with the available tools. Before automation, record:

* Report download URLs
* HTTP methods
* Query parameters
* Redirects
* Required cookies
* Request headers
* Cache behavior
* Compression format
* Response content types
* Any automated-access limits

Do not infer hidden endpoints from filename patterns alone.

### Suggested identifiers

* `source_enr_election_id`
* `source_contest_id`, when present
* `source_choice_id`, when present
* County FIPS or normalized county name
* Precinct code plus county
* Election date
* Normalized election type
* Office
* District
* Party
* Candidate or response text

### Known gaps

* The ENR identifier is not verified as the same identifier used by Candidate Tracking.
* Municipal elections do not all appear in one statewide ENR instance.
* Download schemas may differ by election era.
* Automated retrieval may require browser-compatible handling.
* Certification must not be inferred from 100 percent reporting.

---

## Rank 2 — SEC Candidate and Referendum Tracking System

**Responsible entity:** South Carolina State Election Commission
**Candidate landing page:** `https://vrems.scvotes.sc.gov/Candidate/SelectElection`
**Date search:** `https://vrems.scvotes.sc.gov/Candidate/SearchElectionDate`

### Scope

Candidate Tracking includes candidates who filed for elections represented in the system. The SEC warns that statewide-primary listings show candidates appearing on the primary ballot and that candidates for some local elections may not be available.

The system supports:

* Election selection
* Candidate search
* Office filters
* County filters
* Candidate status
* Political party
* Filing location
* Candidate detail records
* Filed-document access
* Referendum search
* Exact referendum text and response choices

The SEC states that the public can track filings in real time, view candidate documents, and download filing data.

### Source type

* HTML database portal
* Structured candidate-detail pages
* Downloadable filing data
* PDF or image filing documents
* Structured referendum-detail pages

### Candidate fields observed

A candidate detail page exposes:

* Candidate display name
* Election
* Office
* Name on ballot
* Party
* Candidate status
* Date filed
* Filing location
* Address
* SICPP or filing form
* Filing-fee receipt

### Referendum fields observed

Referendum records expose:

* Referendum identifier
* Election
* Election date
* Responsible county
* District type
* District
* Referendum type
* Exact referendum title and text
* Permitted responses

### Verified join key

The SEC calendar’s `Election Number` maps directly to the Candidate Tracking query parameter `electionId`.

Example:

```text
Election Number: 22596
Election: 2026 Statewide General Election
Candidate URL:
https://vrems.scvotes.sc.gov/Candidate/CandidateSearch?electionId=22596
```

### Observable routes and parameters

```text
/Candidate/SelectElection

/Candidate/SearchElectionDate

/Candidate/CandidateSearch?electionId={electionId}

/Candidate/CandidateDetail/
    ?candidateId={candidateId}
    &electionId={electionId}
    &searchType=Default

/Candidate/ReferendumSearch
    ?electionDate={MM/DD/YYYY}

/Candidate/ReferendumDetail
    ?referendumId={referendumId}
    &searchType=Default

/Candidate/ViewCandidateDocument
    ?candidateId={candidateId}
    &documentTypeSid={documentType}
```

No supported API documentation was found. A HAR capture was not available. Search and export requests should be inspected manually before production automation.

### Filing authority

For the 2026 partisan filing cycle, the SEC identified these filing locations:

* Federal, statewide, and multicounty offices: SEC
* State House: SEC or the candidate’s county election board
* Various county offices: county election board

All nonfederal candidates were directed to file campaign and economic-interest disclosures through the State Ethics Commission.

### Update strategy

* Poll more frequently during active filing periods.
* Preserve each observed status transition.
* Store the SEC Election Number as the external election key.
* Retain `candidateId` as the source candidate key.
* Archive candidate-document URLs and hashes.
* Distinguish filed, active, withdrawn, disqualified, removed, and other source statuses.
* Reconcile final candidates against the official ballot and result files.
* Avoid publishing home-address data unless CivicMirror has a documented operational reason and appropriate policy.

### Known gaps

* Some local candidates are absent.
* The exact filing-data export endpoint was not captured.
* Candidate status vocabulary must be enumerated.
* Filing documents may require PDF or image extraction.
* Candidate and result IDs are not yet directly crosswalked.

---

## Rank 3 — Historical Election Database

**Responsible entity:** South Carolina State Election Commission
**Landing page:** `https://scvotes.gov/elections-statistics/election-database/`
**Database:** `https://electionhistory.scvotes.gov/`

### Scope

The database describes itself as a searchable collection of historical information derived from official source documents. Its inventory includes:

* Contests
* Ballot questions
* Candidates
* Historical candidate participation
* Election dates
* Election types
* Jurisdictions
* Contest results

The SEC says the database was created to consolidate historical contests and ballot questions and that the inventory is ongoing. It should therefore be considered an authoritative state-operated research database, but not assumed complete for every year or jurisdiction.

### Source type

* Historical database portal
* HTML contest pages
* Per-contest CSV downloads
* Candidate-history pages
* Ballot-question records

### CSV access

Contest pages contain a **Results CSV** download. A verified example is the 2022 Democratic primary for governor.

Observed download pattern:

```text
https://sc.elstats.civera.com/api/download_contest/{contestId}_table.csv
    ?split_party=false
```

Although the URL contains `/api/`, no official API documentation, discovery endpoint, service-level commitment, authentication specification, or pagination documentation was found. Classify this as an **undocumented per-contest CSV download**, not as an official public API.

### Suggested identifiers

* Historical database contest ID
* Candidate profile ID
* Election date
* Election type
* Office
* Jurisdiction
* Party
* Candidate name
* Ballot-question text

### Update strategy

* Inventory available elections and contests by year.
* Store the contest-page URL and CSV URL.
* Hash and archive every CSV.
* Compare database totals with the ENR file or historical report from which they were derived.
* Use the historical database for normalized discovery and backfill.
* Use signed canvass records or contemporary official reports when certification status is material.

### Known gaps

* The database states that inventory work is ongoing.
* Exact earliest coverage and completeness are not documented.
* Bulk whole-database download was not found.
* Per-contest downloads require contest discovery first.
* The vendor download host may change independently of the official landing domain.

---

## Rank 4 — Annual Election Calendar and Upcoming Elections

**Responsible entity:** South Carolina State Election Commission
**Upcoming elections:** `https://scvotes.gov/elections-statistics/upcoming-elections/`
**General-election calendars:** `https://scvotes.gov/elections-statistics/general-election-calendars/`

### Annual schedule fields

The annual election-calendar PDF contains:

* Election date
* Election Number
* County
* Election name
* Election type
* Multicounty indicator
* Filing period

The February 17, 2026 calendar contains five pages and includes regular, special, primary, general, and referendum elections.

### Source type

* Current HTML event calendar
* Annual PDF schedule
* Election-specific HTML event pages

### Update cadence

The annual calendar is a dated snapshot. The current Upcoming Elections page can contain elections added after the PDF was generated. For example, the August 2026 HTML calendar includes a U.S. Senate special Republican primary and other local elections not necessarily present in the February PDF.

### Extraction strategy

1. Use the annual PDF to seed the year’s election table.
2. Preserve its publication or revision date.
3. Poll Upcoming Elections for additions and changes.
4. Match events by SEC Election Number where available.
5. Flag records found only in the HTML calendar.
6. Verify filing dates against election-specific notices.
7. Treat applicable law and formal election orders as controlling when a calendar conflict exists.

### Suggested election key

Use:

```text
sc_sec_election_number
```

as the preferred source identifier.

Also store:

* Date
* Official name
* County or `ALL`
* Election type
* Multicounty flag
* Filing-period start
* Filing-period end
* Calendar revision date

---

## Rank 5 — State Board of Canvassers and Certification Records

**Responsible entities:** State Election Commission acting as the Board of State Canvassers; Secretary of State
**Public notices:** `https://scvotes.gov/about-the-sec/public-notices/`

### Scope

The Public Notices page publishes:

* Board meeting dates
* Certification agendas
* Signed canvass sheets
* Signed certification documents
* Special-election certifications
* Primary and runoff certifications

The 2026 primary and runoff entries link signed canvass sheets directly from the corresponding certification meetings.

### Current examples

```text
https://scvotes.gov/wp-content/uploads/2026/07/
SBC-Signed-Cavass-Sheets-June-2026-Primary.pdf
```

Document title: Certified Statement of All Votes Cast for the 2026 Primary
Election date: June 9, 2026
Certification date shown: June 12, 2026
Pages: 2
Extraction difficulty: Low for metadata; signature verification remains manual

```text
https://scvotes.gov/wp-content/uploads/2026/06/
SBC-Signed-Certification-Documents-2026-Primary-Runoffs.pdf
```

Document title: Certified Statements for the 2026 Primary Runoffs
Election date: June 23, 2026
Certification date shown: June 26, 2026
Pages: 20
Extraction difficulty: Medium because multiple contest certifications are combined

### Legal role

The State Election Commission constitutes the Board of State Canvassers. The Board canvasses statewide and other qualifying elections, prepares certified statements, declares the persons elected, and records constitutional-amendment and question totals. The certified determination is delivered to the Secretary of State.

### Source type

* HTML public-notice page
* Meeting agenda
* Signed PDF canvass sheet
* Signed PDF certification package
* Meeting minutes

### Integration use

Use these records to determine:

* Certification date
* Certifying body
* Official status
* Recount or protest context
* Contests covered by the certification
* Whether a later certification supersedes an earlier document

Do not use 100 percent precinct reporting as a substitute for certification.

### Suggested certification key

```text
election_id
certifying_body
certification_date
document_url
document_hash
certification_version
```

---

## Rank 6 — Revenue and Fiscal Affairs Political GIS

**Responsible entity:** South Carolina Revenue and Fiscal Affairs Office
**Mapping page:** `https://rfa.sc.gov/programs-services/precinct-demographics/jurisdictional-mapping`
**GIS downloads:** `https://rfa.sc.gov/programs-services/precinct-demographics/jurisdictional-mapping/political-gis-data`

### Scope

Official mapping products include:

* State House districts
* State Senate districts
* Congressional districts
* Voting precincts
* County council districts
* School-board districts
* Historical district-map series
* Shapefiles
* KML/KMZ files
* PDF maps on request

The office states that precinct maps are updated as legislation is enacted and provides shapefile and KML downloads.

### Current structured files

```text
Statewide precinct shapefile:
https://rfa.sc.gov/media/10668

Statewide precinct KML/KMZ:
https://rfa.sc.gov/media/10669

2020 county council district shapefile:
https://rfa.sc.gov/media/8135

2020 county council district KMZ:
https://rfa.sc.gov/media/8136
```

The statewide precinct shapefile and KMZ are labeled effective January 1, 2025.

### Source type

* Bulk GIS download
* Shapefile
* KML/KMZ
* HTML map index
* PDF district maps

### Machine-readability

**High** for shapefiles and KML/KMZ.

### Update strategy

* Store source filename, media ID, effective date, hash, and retrieval date.
* Preserve every historical vintage.
* Build a county-plus-precinct-code key.
* Normalize district numbers without dropping leading zeros.
* Match result precincts to geography only after confirming the election’s applicable precinct plan.
* Retain unmatched and split precincts for manual review.
* Do not apply the January 2025 precinct file automatically to earlier elections.

### Known gaps

* A single current bulk download for every district type was not identified.
* Some district products are map pages rather than shapefiles.
* Local district boundaries can change independently.
* Precinct names in result exports may not exactly match GIS labels.

---

## Rank 7 — State Ethics Commission Campaign-Finance System

**Responsible entity:** South Carolina State Ethics Commission
**Guidance:** `https://ethics.sc.gov/campaigns`
**Public reporting:** `https://apps.sc.gov/publicreporting/index.aspx`

### Scope

The Public Disclosure and Accountability Reporting System is the state’s electronic campaign-disclosure system. Candidate reports include contributions, expenditures, initial filings, pre-election reports, quarterly reports, and final reports. The Ethics Commission also defines election activity to include general, special, primary, runoff, convention, caucus, and ballot-measure activity.

The SEC states that all nonfederal candidates must file a Statement of Economic Interests and Campaign Disclosure online through the State Ethics Commission.

### Source type

* HTML database portal
* Search forms
* Individual campaign reports
* Contribution records
* Expenditure records
* Committee and candidate records
* Filing guidance

### Access

* Public reporting interface
* No public API documentation found
* Automated access produced redirect or retrieval failures during this review
* No bulk CSV export was verified

### Suggested fields

* Candidate or committee name
* Candidate office
* Election year
* Report type
* Reporting period
* Filing date
* Contributor
* Contribution amount and date
* Expenditure payee
* Expenditure amount and date
* Balance
* Committee type
* Ballot-measure association

### Join strategy

Use:

* Candidate name
* Office
* District
* Election year
* Committee or filer identifier, when exposed

Do not assume an Ethics Commission filer ID equals an SEC Candidate Tracking `candidateId`.

### Update strategy

* Capture pre-election reports before each election.
* Refresh after filing deadlines.
* Preserve amendments as separate versions.
* Archive report-level metadata before transaction extraction.
* Reconcile candidate committees against Candidate Tracking.
* Keep federal campaign finance outside this state system.

### Known gaps

* No supported API verified.
* No bulk-download path verified.
* Historical start date and completeness need a portal inventory.
* Search requests and pagination need browser-network inspection.
* Committee-to-candidate joins may require manual review.

---

## Rank 8 — Election Audit Records

**Responsible entity:** South Carolina State Election Commission Audit Division
**Official page:** `https://scvotes.gov/elections-statistics/election-audits/`

### Audit types

South Carolina publishes two result-audit categories:

1. **Hand-count audits**, comparing selected ballots and contests with tabulator totals.
2. **Results-verification audits**, independently retabulating an election from ballot images.

Hand-count audits are required for federal- and state-level elections. Selected early-voting centers, precincts, and contests are chosen by the SEC Audit Division. The audits occur before certification, are open to the public, and their results are published by the SEC.

### Source type

* HTML annual archive
* PDF audit reports
* Excel workbooks
* Contest-comparison reports
* County-breakout reports
* Public audit notices

### Coverage

The audit archive contains regular, primary, runoff, special, presidential-preference, and general-election reports. The page includes records for 2022 through 2026 and may include additional earlier material farther down the archive.

### Pipeline use

Audit records should not replace certified results. Use them to record:

* Audit type
* Election
* Selected county
* Precinct or early-voting center
* Audited contest
* Machine total
* Audit total
* Difference
* Reconciliation explanation
* Audit completion date
* Report URL
* Whether the audit occurred before certification

### Known gaps

* No common machine-readable schema was verified across audit years.
* Some reports are PDF-only.
* The results-verification vendor’s internal service is not a public results API.
* Audit files may require separate parsers by report type.

---

## Rank 9 — South Carolina Election Law

**Responsible entity:** South Carolina General Assembly
**Title 7:** `https://www.scstatehouse.gov/code/title7.php`
**Canvass chapter:** `https://www.scstatehouse.gov/code/t07c017.php`

### Pipeline uses

Election law provides the authoritative basis for:

* Election definitions
* Filing and nomination
* Primary and runoff requirements
* County canvassing
* State canvassing
* Certification
* Protests
* Recounts
* Election records
* Special-election timing
* Referendum treatment

### Mandatory recount

A recount is required when the relevant margin is no more than one percent of the total vote for the office. The rule also applies to the threshold for entering a runoff and to constitutional amendments, questions, and other issues.

### Certification flow

County boards organize and canvass after the election. The State Board canvasses applicable contests, certifies the statements, declares persons elected, and delivers its determination to the Secretary of State for recording.

### Recall status

No generally operative statewide recall-election workflow was identified in the current Title 7 canvass and election sources reviewed. Search results primarily produced proposed recall legislation rather than verified enacted statewide recall authority. Certain local offices may be subject to special local laws.

CivicMirror should therefore:

* Not create recurring South Carolina recall cycles automatically.
* Require an enacted law, official election order, SEC calendar entry, or local election notice.
* Record the specific legal authority for any recall election discovered.

---

# Historical Coverage

## 2008–2026 ENR archive

The SEC results page provides election-specific ENR links from 2008 through 2026. Coverage includes statewide primaries, runoffs, general elections, presidential primaries, recounts, special elections, and selected municipal elections.

### Historical ingestion priority

1. Detailed XML or XLS files
2. Summary CSV
3. Legacy detailed TXT
4. Historical database CSV
5. HTML reports
6. PDF reports

## 1996–2006 gap

The results page includes some 2006 primary and runoff reports, including statewide, congressional, legislative, solicitor, county, precinct, and turnout reports.

However, the SEC page says that consolidated 1996–2006 statewide, multicounty, and county-level result files are still to be made available and directs researchers to contact the SEC in the meantime.

Record this period as:

```text
Coverage: Partial
Access: Some online reports plus records request
Human review: Required
```

## Biennial Election Reports, 1968–2008

The SEC publishes a PDF archive of biennial reports. The series was discontinued after the 2008 report.

### PDF inventory

| Coverage  | Official PDF URL                                                               |
| --------- | ------------------------------------------------------------------------------ |
| 2007–2008 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_2008.pdf`      |
| 2005–2006 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_2006.pdf`      |
| 2003–2004 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_2004.pdf`      |
| 2001–2002 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_2002.pdf`      |
| 1999–2000 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_2000.pdf`      |
| 1997–1998 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1997-1998.pdf` |
| 1995–1996 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1995-1996.pdf` |
| 1994–1995 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1994-1995.pdf` |
| 1992–1993 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1992-1993.pdf` |
| 1990–1991 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1990-1991.pdf` |
| 1988–1989 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1988-1989.pdf` |
| 1986–1987 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1986-1987.pdf` |
| 1984–1985 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1984-1985.pdf` |
| 1982–1983 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1982-1983.pdf` |
| 1980–1981 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1980-1981.pdf` |
| 1978–1979 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1978-1979.pdf` |
| 1976–1977 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1976-1977.pdf` |
| 1974–1975 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1974-1975.pdf` |
| 1969–1973 | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1969-1973.pdf` |
| 1968      | `https://scvotes.gov/wp-content/uploads/2022/08/Election_Report_1968.pdf`      |

The files are large, often hundreds of pages, and combine election results with turnout, registration, officeholder, procedural, or administrative material. The 2008 report is a 238-page digitally readable PDF, while early reports such as 1968 are scanned historical documents.

### Extraction difficulty

* **Recent reports:** Medium
* **Older scanned reports:** High
* **Tables spanning pages:** High
* **Changing office and district terminology:** High
* **OCR reliability for old typefaces:** Low to medium
* **Manual validation:** Required

Preserve each original PDF even after table extraction.

---

# Municipal Election Coverage

Municipal coverage is the largest completeness issue.

The SEC results archive includes many municipal elections, but the page also links separate reporting systems for particular municipalities and jurisdictions. Some municipal election commissions administer and publish results independently. The official state archive therefore cannot be assumed to contain every municipal contest.

For every municipality, CivicMirror should record:

* Municipality
* County or counties
* Election authority
* Whether SEC administers the election
* Candidate source
* Election-night result source
* Canvass source
* Certification source
* Referendum source
* Historical archive
* Result format
* Source authority level

### Recommended authority order

1. SEC, when it administers or publishes the election
2. County Board of Voter Registration and Elections
3. Municipal election commission
4. Municipal clerk or official municipal website
5. Official canvass or council record

Do not substitute a media report or commercial election feed for missing municipal records.

---

# Election Types

CivicMirror should normalize at least these South Carolina types:

| Normalized type                 | Official examples and treatment                                                                                    |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Presidential preference primary | Separate Democratic or Republican election and result record                                                       |
| Partisan primary                | Party nomination election                                                                                          |
| Primary runoff                  | Separate election approximately two weeks after a qualifying primary                                               |
| General election                | Federal, state, legislative, county, local, and ballot questions                                                   |
| Special primary                 | Nomination stage for a vacancy                                                                                     |
| Special primary runoff          | Runoff resulting from a special primary                                                                            |
| Special election                | Vacancy-filling or other specially ordered election                                                                |
| Municipal general               | Regular city or town election                                                                                      |
| Municipal runoff                | Separate local runoff                                                                                              |
| Referendum election             | Local or statewide ballot question                                                                                 |
| Constitutional amendment        | State-canvassed ballot question with legislative provenance                                                        |
| Recount                         | Revised tabulation associated with the original contest, not a new election unless the source treats it separately |
| Recall                          | Create only when an official legal authority and election record are verified                                      |

The annual calendar and result archive show that off-cycle special, municipal, school, county, and referendum elections occur throughout the year rather than only on statewide primary and general dates.

---

# CivicMirror Pipeline Map

| Pipeline subject            | Primary official source                    | Suggested identifiers                   | Extraction and update strategy                                | Known gap                                      |
| --------------------------- | ------------------------------------------ | --------------------------------------- | ------------------------------------------------------------- | ---------------------------------------------- |
| Election calendar           | SEC annual calendar and Upcoming Elections | `election_number`                       | Seed from PDF; poll HTML for changes                          | PDF is a dated snapshot                        |
| Election definition         | Calendar, election notice, Title 7         | Election Number + official name         | Preserve official and normalized types                        | Local naming varies                            |
| Election type               | Calendar and result archive                | Election Number + type                  | Map source labels to controlled values                        | Runoff/recount distinctions need care          |
| Offices                     | Candidate Tracking                         | Election ID + office label              | Enumerate office filters and candidates                       | Some local offices missing                     |
| Districts                   | Candidate Tracking and RFA maps            | Office type + district + map vintage    | Normalize only after preserving source label                  | Local district geometries fragmented           |
| Contests                    | Candidate Tracking, ENR, historical DB     | Election ID + office + district + party | Create preliminary contest from filings; confirm with results | Direct candidate-to-result ID join unverified  |
| Candidates                  | Candidate Tracking                         | `candidateId`                           | Poll during filing; preserve status history                   | Some local candidates unavailable              |
| Filing status               | Candidate Tracking                         | Candidate ID + filing event             | Snapshot status and documents                                 | Status vocabulary not inventoried              |
| Ballot qualification        | Candidate status and final ballot          | Candidate ID + election                 | Mark qualified only from final official status or ballot      | Challenges may require separate records        |
| Party affiliation           | Candidate Tracking and results             | Candidate ID + election                 | Preserve exact source party label                             | Convention nominees need separate handling     |
| Referenda                   | SEC Referendum Tracking                    | `referendumId`                          | Capture exact text and response options                       | Some local measures may be absent              |
| Ballot-measure legal origin | General Assembly and local authority       | Bill/resolution/ordinance ID            | Link legal text to SEC referendum                             | Local documents fragmented                     |
| Election-night results      | ENR structured downloads                   | ENR election ID + contest/choice IDs    | Poll and retain every changed snapshot                        | Automated access controls                      |
| Precinct results            | ENR Detail XML/XLS/TXT                     | County + precinct source code           | Preserve raw labels; normalize later                          | Schema varies by era                           |
| County canvass              | County board                               | Election + county + canvass date        | Archive county certification                                  | County publication practices vary              |
| State certification         | Board of State Canvassers                  | Election + certification date           | Parse public notice and signed PDF                            | Combined PDFs may need manual splitting        |
| Recounts                    | ENR recount page and §7-17-280             | Election + contest + recount version    | Store as a new result version                                 | Waiver and recount context may be PDF-only     |
| Runoffs                     | Calendar, candidates, ENR                  | Separate Election Number                | Create separate election linked to originating primary        | Candidate qualification logic must be retained |
| Campaign finance            | State Ethics public reporting              | Filer or committee ID                   | Refresh at filing deadlines; retain amendments                | No bulk API/export verified                    |
| Audits                      | SEC audit archive                          | Election + audit type + geography       | Parse reports and comparison workbooks                        | Multiple report schemas                        |
| Precinct geography          | RFA shapefile                              | County + precinct + effective date      | Load by map vintage                                           | Current file not valid for all history         |
| Historical archive          | Historical DB, ENR, reports                | Source-specific IDs                     | Backfill newest structured data first                         | 1996–2006 incomplete online                    |
| Municipal elections         | SEC, county, or municipality               | Local election ID + jurisdiction        | Maintain local source registry                                | No complete central source                     |

---

# Recommended Implementation Order

## Phase 1 — Election and candidate definitions

1. Ingest annual SEC election calendars.
2. Store the SEC Election Number as the primary external election key.
3. Poll Upcoming Elections for additions.
4. Use Candidate Tracking to ingest offices, candidates, parties, statuses, filing locations, and documents.
5. Use Referendum Tracking for exact ballot-question text.
6. Reconcile candidates and referenda with the final ballot.

## Phase 2 — Election-night result adapter

1. Capture ENR download URLs in a normal browser.
2. Compare Detail XML and Detail XLS schemas.
3. Select the most complete stable format.
4. Add Summary CSV as a reconciliation source.
5. Preserve every election-night revision.
6. Label all pre-certification data as unofficial.
7. Maintain a separate adapter profile for older TXT-era elections.

## Phase 3 — Certification

1. Monitor the SEC Public Notices page.
2. Capture Board of State Canvassers meeting dates.
3. Download signed canvass sheets.
4. Record certification date and contests covered.
5. Compare certified totals with the final ENR snapshot.
6. Create a new version when a recount or later certification changes the result.

## Phase 4 — Historical backfill

1. Ingest per-contest historical database CSVs.
2. Backfill ENR elections from 2008 forward.
3. Inventory partial 2006 files.
4. Request unavailable 1996–2006 files from SEC.
5. Extract biennial PDFs from 1968 through 2008.
6. Track source conflicts and unresolved missing contests.

## Phase 5 — Geography

1. Load the current RFA precinct shapefile.
2. Store its January 1, 2025 effective date.
3. Inventory prior precinct and district vintages.
4. Create election-date-aware district crosswalks.
5. Reconcile ENR precinct labels against GIS precinct identifiers.

## Phase 6 — Campaign finance and audits

1. Inventory State Ethics search fields and report types.
2. Capture browser-network behavior and pagination.
3. Connect filers to SEC candidates.
4. Ingest audit selections and result comparisons.
5. Flag discrepancies or reconciliation explanations for human review.

## Phase 7 — Municipal source registry

1. Inventory every municipality and municipal election authority.
2. Record whether SEC administers its elections.
3. Capture official candidate, result, canvass, and referendum URLs.
4. Prioritize downloadable structured data.
5. Treat local-only results as an explicit coverage queue.

---

# Authentication and Access Summary

| Source                  | Authentication         | Automated-access notes                               |
| ----------------------- | ---------------------- | ---------------------------------------------------- |
| SC Votes website        | None                   | Normal public HTML                                   |
| ENR result portal       | None identified        | Automated requests encountered verification/blocking |
| Candidate Tracking      | None                   | Public HTML; no official API                         |
| Historical database     | None                   | Public pages and contest CSV                         |
| Board certification     | None                   | Public HTML and PDFs                                 |
| RFA GIS                 | None                   | Direct bulk downloads                                |
| Ethics public reporting | None for public search | Automated retrieval produced redirects/errors        |
| Audit archive           | None                   | Public HTML, Excel, and PDF files                    |
| State statutes          | None                   | Public HTML                                          |

---

# API Assessment

## Confirmed APIs

No officially documented public election, candidate, result, campaign-finance, audit, or geography REST API was verified.

## Structured non-API access

South Carolina nevertheless offers strong machine-readable access through:

* ENR CSV
* ENR Excel
* ENR XML
* Legacy ENR TXT
* Historical contest CSV
* Candidate filing-data download
* GIS shapefiles
* KML/KMZ
* Audit Excel workbooks
* Structured HTML candidate and referendum pages

Do not label the ENR portal, Candidate Tracking, Ethics portal, or historical CSV endpoint as an API unless the state publishes official API documentation.

---

# Provenance and Reliability Rules

For every acquired file or page, store:

* Responsible entity
* Source URL
* Landing-page URL
* Retrieval timestamp
* Election Number
* ENR election ID, when applicable
* Historical contest ID, when applicable
* Candidate ID or referendum ID
* File format
* File hash
* Publication label
* Unofficial or certified status
* Certification date
* Reporting geography
* Map vintage
* Parser version
* Human-review notes

Additional rules:

* Never treat 100 percent reporting as certification.
* Never overwrite an election-night snapshot.
* Preserve recount and runoff records separately.
* Preserve exact ballot-question text.
* Retain original PDFs after extraction.
* Record when an election is missing from the SEC central system.
* Prefer official county or municipal sources when local results are not centrally published.
* Do not use external aggregators as primary evidence.

---

# Known Gaps and Human-Review Queue

1. Capture and test the current ENR report-download URLs without relying on search indexing.
2. Compare current XML, XLS, and CSV schemas.
3. Determine whether ENR exposes stable contest and choice IDs.
4. Inventory all Candidate Tracking status values.
5. Capture the candidate filing-data export request.
6. Determine whether Candidate Tracking includes every county-filed candidate.
7. Inventory the historical database’s earliest year and completeness.
8. Request missing 1996–2006 result files from SEC.
9. Build a complete municipal election-authority registry.
10. Inspect the Ethics portal’s requests, pagination, and report identifiers.
11. Inventory historical precinct GIS vintages.
12. Determine whether signed canvass packages consistently contain contest totals or only certification statements.
13. Document any enacted local recall provisions before classifying a contest as a recall.
14. Verify how election protests and amended certifications are published.
15. Match ENR elections to SEC Election Numbers without assuming the numeric IDs are interchangeable.

---

# Source Coverage Analysis

South Carolina is a strong candidate for an official-source-only CivicMirror pipeline.

The recommended architecture is:

1. **SEC Election Number** for election identity.
2. **Candidate Tracking** for candidates, parties, filing status, and documents.
3. **Referendum Tracking** for ballot-question definitions.
4. **ENR structured downloads** for election-night and detailed results.
5. **State Board of Canvassers documents** for certification.
6. **Historical database CSVs** for normalized backfill.
7. **RFA GIS files** for precinct and district geography.
8. **State Ethics records** for campaign finance.
9. **SEC audit reports** for post-election verification.
10. **Official local authorities** for municipal gaps.

The largest technical risk is not a lack of structured data. It is reliable automated access to the ENR host and the need to reconcile several identifier systems. The SEC Election Number provides a verified join between the calendar and Candidate Tracking, but the corresponding ENR identifier must still be mapped.

The largest coverage risk is municipal elections. SEC publishes many local results, but its archive visibly directs users to multiple separate municipal reporting systems. A complete South Carolina pipeline therefore requires an official local-source registry in addition to the statewide systems.

The largest historical gap is 1996–2006. Structured ENR coverage begins in 2008, historical PDFs extend to 1968, and the newer historical database is still being populated. CivicMirror should record completeness by election and contest rather than representing the state as uniformly covered from one start year.

The earlier conclusion that South Carolina merely offers county and precinct downloads with “no API” understated the state’s integration value. There is still no verified public API, but the combination of official XML, Excel, CSV, filing downloads, stable election IDs, signed certifications, audit files, and bulk GIS data supports a reliable state-administered pipeline without relying on commercial feeds or unofficial aggregators.
