# Hawaii Election Results — Research Notes

## Coverage Status

| Pipeline area | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Official sources available | Use Office of Elections proclamations, supplemental vacancy proclamations, the contest schedule, and the historical results index. |
| Stage 1 — Race Creation | ✅ Official sources available | Proclamations identify offices and election types; official preview ballots establish contest wording, party sections, vote-for limits, and ballot-style applicability. |
| Stage 1 — Candidate Creation | ✅ Source available; scraper required | The Office of Elections Candidate Report supplies candidate, contest, party, filing dates, and status. It is a stateful ASP.NET/Telerik HTML portal, not a verified API. |
| Stage 2 — Results Ingestion | ✅ Structured state files available | Statewide summary and precinct-detail text files are the preferred source for most regular elections from 2004 forward. A CivicMirror adapter was not verified. |
| Special and Vacancy Elections | ✅ Available | Current proclamations and historical results include vacancy, first special, second special, and standalone congressional or local special elections. |
| Ballot Measures | ✅ Available | Proclamations and dedicated question pages define measures; official result files and reports contain measure totals. |
| Certification | ✅ Available | The results index explicitly labels certified files. Certification is not exposed as a verified structured Boolean. |
| Recounts | ✅ Available | The Office of Elections publishes separate recount reports linked from the affected election. |
| Election Objections | ✅ Available | The Office of Elections publishes objection eligibility, deadlines, and court-process information. |
| Campaign Finance | ✅ Official API and downloads | The Campaign Spending Commission publishes Socrata/SODA datasets and downloadable files. |
| District and Precinct Geography | ✅ Available | Official precinct, congressional, legislative, and census-block files are linked from the Office of Elections GIS page. |
| Registration and Turnout | ✅ Available | Statewide and county historical tables extend to 1959; recent district-level turnout maps are also available. |
| Historical Results | ✅ Available with format changes | Official coverage begins in 1992. Older elections require HTML or PDF extraction; regular elections from 2004 forward increasingly provide structured text. |
| Candidate Portal HAR | ✅ Captured | HARs verify page-size and page-navigation postbacks. Filtering and the live CSV export path were captured; clean election-cycle switching still needs confirmation. |
| Official Results API | ❌ Not identified | No official public Hawaii election-results REST or JSON API was verified. |
| Official Candidate API | ❌ Not identified | No candidate JSON, Excel export, or documented API was observed; the current report does expose a verified CSV export. |
| Official Clarity Source | ❌ Not verified | Repository references to a “Clarity sweep” are implementation notes, not confirmed Hawaii state-source provenance. |

---

**Primary results source:** `https://elections.hawaii.gov/election-results/`  
**Candidate report landing page:** `https://elections.hawaii.gov/candidates/candidate-reports/`  
**Current candidate portal:** `https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=94`  
**Proclamation archive:** `https://elections.hawaii.gov/proclamations/`  
**Open Data portal:** `https://opendata.hawaii.gov/`  
**GIS source:** `https://elections.hawaii.gov/resources/maps/geographic-information-systems-gis-files/`  
**Campaign finance:** `https://ags.hawaii.gov/campaign/`  
**Operated by:** State of Hawaii Office of Elections  
**Campaign finance operator:** Hawaii Campaign Spending Commission  
**Researched:** March 4, 2026  
**Updated:** August 5, 2026 — verified the native candidate portal and official result-text pipeline; added HAR-backed pagination details; corrected CKAN, special-election, ballot-measure, GIS, and unverified Clarity claims  
**Accessed:** August 5, 2026  
**Status:** Public; no user login required for the election, candidate, result, GIS, turnout, or public campaign-finance sources reviewed

---

## Overview

Hawaii has usable first-party sources for both principal CivicMirror pipeline stages.

For Stage 1, election definitions come from Office of Elections proclamations and supplemental vacancy proclamations. The Candidate Report supplies candidate filings and status, while official preview ballots establish actual ballot appearance, contest wording, vote-for limits, party sections, and ballot-style applicability.

For Stage 2, the Office of Elections results index is the authoritative discovery page. It links certified statewide summaries, county reports, precinct detail, statements of vote, structured text files, and recount reports. The archive covers regular primaries and general elections as well as special and vacancy elections. The official index currently spans 1992 through 2026.

The main integration problem is therefore an **adapter gap**, not a lack of official data:

1. Candidate data requires a stateful HTML scraper.
2. Result data requires a structured-text adapter plus historical HTML/PDF fallbacks.
3. Supplemental proclamations must be monitored because vacancies can add contests after the principal election proclamation.
4. Different result eras use different formats and, in at least one case, different text schemas.

---

## Existing Research Inputs and Corrections

The previous repository file correctly identified the Office of Elections results page, certified PDFs, text files, the Hawaii Open Data portal, and historical coverage beginning in 1992. It described Stage 1 as dependent on Google Civic Information and Stage 2 as an unbuilt CKAN adapter.

Issue #156 correctly identified the native Candidate Report and the need to investigate pagination, changing `elid` values, exports, and browser-network behavior. The issue reported 411 records across 28 pages for the 2026 report.

### Material corrections

- Hawaii has a native official Stage 1 candidate source. Google Civic Information is not required as the primary evidence source.
- The Hawaii Open Data portal is a narrow legacy supplement, concentrated mainly in 2010 and 2012 datasets. It is not the comprehensive current Stage 2 source.
- The results archive includes special elections, vacancy elections, recounts, and ballot measures.
- Geographic boundary data is available from the Office of Elections GIS page.
- Current officeholder and next-election information is available from the Office of Elections Elected Officials page.
- No official Hawaii Clarity Elections endpoint was verified.
- No official evidence was found for the previous claim that election-night results are always published in exactly three scheduled runs. Preserve observed update timestamps instead of assuming a fixed run schedule.
- The candidate portal is an ASP.NET Web Forms application using Telerik controls. Paging and page-size changes are form postbacks to the same HTML endpoint, not calls to a candidate JSON API.

Repository and issue content should remain working research context. Official state sources remain the evidence for election facts and source behavior.

---

## Source Inventory

Sources are ranked primarily by machine-readability and then by practical integration value.

| Rank | Source | Responsible entity | Scope and subjects | Election types / cycles | Source type and access | Cadence | Machine-readability / authentication | CivicMirror value and provenance |
|---:|---|---|---|---|---|---|---|---|
| 1 | Campaign Spending Commission searchable datasets — `https://ags.hawaii.gov/campaign/cc/view-searchable-data/` | Hawaii Campaign Spending Commission | Contributions, expenditures, loans, other receipts, unpaid expenditures, committee filings | Candidate committees; searchable coverage described as 2015–2025, encompassing 2016–2024 elections, plus some amended earlier transactions | **API — Socrata/SODA; CSV, Excel, PDF; database portal** | Updated as reports and amendments are loaded | Public read/download access; an account is needed only to save custom views | Best verified official API, but it covers campaign finance rather than election administration. |
| 2 | Election result text files — discovered at `https://elections.hawaii.gov/election-results/` | Office of Elections | Contest totals, choices, parties, registration, reporting status, voting-method totals, precinct and split information | Most regular primary/general elections from 2004 forward; coverage varies by year | **Structured text / bulk download** | Multiple updates during tabulation; certified files later linked or relabeled | Public, no login; schema varies by era | Preferred Stage 2 source. Discover URLs from the index rather than constructing them. |
| 3 | Hawaii Open Data election datasets — `https://opendata.hawaii.gov/dataset/?organization=office-of-elections` | Office of Elections / Hawaii Open Data | Selected summary and precinct results | Confirmed mainly for 2010 and 2012 | **Database portal; CSV, JSON, XML, RDF** | Legacy datasets; not a current-cycle feed | Public structured downloads | Useful for selected historical validation, not the main results pipeline. The organization search returned five datasets. |
| 4 | Candidate Report — `https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=94` | Office of Elections | Contest, party, ballot name, legal name, contact fields, issued date, filed date, candidate status | Confirmed 2022, 2024, and 2026 reports | **HTML page / HTML scraping; ASP.NET Web Forms; Telerik RadGrid** | Updated during filing and after elections | Public, no login; session cookies and fresh page state required; CSV export verified on the current report | Preferred candidate and filing-status source. |
| 5 | Proclamation archive — `https://elections.hawaii.gov/proclamations/` | Office of Elections and county clerks | Election dates, offices, districts, vacancy contests, voter-service details, measure categories | Current archive visibly includes 2020–2026 regular proclamations and selected vacancy/amendment notices | **HTML page plus PDF** | Event-driven; amended and supplemental proclamations may appear during the cycle | Public; HTML is readable, PDFs require document extraction | Preferred election-definition and amendment-monitoring source. |
| 6 | Contest Schedule — `https://elections.hawaii.gov/voting/contest-schedule/` | Office of Elections | Offices, seats, jurisdictions, districts, and terms by scheduled cycle | Current schedule includes 2026 and 2028 | **HTML table** | Infrequent; updated when schedules or vacancies change | Public and scrapeable | Baseline office-cycle source; proclamations control for the actual election. |
| 7 | Official GIS files — `https://elections.hawaii.gov/resources/maps/geographic-information-systems-gis-files/` | Office of Elections / Hawaii State GIS Program | Election precincts, congressional districts, state Senate and House districts, census-block assignments | 2022 precincts, 2021 reapportionment, 2018 precincts, and linked boundary products | **GIS service / geoportal / bulk download** | Reapportionment and election-boundary cycles | Public; formats depend on linked layer or download | Preferred geography source. Record boundary vintage before joining to results. |
| 8 | Registration and Turnout Statistics — `https://elections.hawaii.gov/resources/registration-voter-turnout-statistics/` | Office of Elections | Registered voters, voters casting ballots, turnout percentages; recent district maps | Primary/general historical series beginning in 1959; recent maps through 2024 | **HTML tables; ArcGIS maps** | Updated following elections | Public; HTML tables are machine-readable with cleanup | Strong reconciliation source; not a substitute for contest results. |
| 9 | Elected Officials — `https://elections.hawaii.gov/resources/elected-officials/` | Office of Elections | Current officeholders, terms, vacancies, and next scheduled elections | Current snapshot | **HTML page** | Updated when offices or appointments change | Public and scrapeable | Useful for incumbent and vacancy validation; retain access date because it changes over time. |
| 10 | Preview ballots — e.g. `https://elections.hawaii.gov/wp-content/uploads/2026-Primary-Ballots.pdf` | Office of Elections | Ballot styles, precinct codes, contest names, candidates, party sections, vote-for limits | Current-cycle primary/general ballots when published | **PDF** | Published before election; may be replaced if corrected | Public but large and repetitive | Strong race and ballot-qualification validation source; expensive for routine extraction. |
| 11 | Certified result PDFs and recount PDFs — discovered from results index | Office of Elections | Human-readable summaries, county reports, precinct detail, statement of vote, recounts | 1992 forward; format and granularity vary | **PDF** | Published during and after certification/recount | Public; older scans are machine-unfriendly | Human validation and historical fallback. PDFs are lowest-priority extraction inputs. |
| 12 | Certified historical HTML | Office of Elections | Statewide, county, and precinct results | Confirmed for 1996, 1998, and 2000, including the 1996 special election | **HTML page / HTML scraping** | Static archive | Public and easier to extract than paired PDFs | Preferred over PDF for those historical years. |

---

## 1. Election Calendar, Definitions, and Election Types

### Primary official sources

- `https://elections.hawaii.gov/proclamations/`
- `https://elections.hawaii.gov/2026-proclamation/`
- `https://elections.hawaii.gov/state-senate-district-18-proclamation/`
- `https://elections.hawaii.gov/voting/contest-schedule/`
- `https://elections.hawaii.gov/resources/elected-officials/`

The May 12, 2026 proclamation establishes the August 8 primary and November 3 general election and lists the federal, state, OHA, and county offices to be elected. It also reserves the general election for constitutional amendments and county charter, ordinance, or initiative questions when present.

The proclamation archive must be monitored throughout the cycle. It contains a December 2025 State Senate District 19 vacancy proclamation and a July 1, 2026 State Senate District 18 proclamation in addition to the principal 2026 proclamation.

The Senate District 18 vacancy election will occur with the November 3, 2026 general election. Party and nonpartisan nomination papers are due September 4, 2026, meaning the candidate source can change well after the regular June filing deadline.

### Election-type normalization

Preserve Hawaii’s official terminology in source-facing fields.

| Official Hawaii term | Suggested normalized type | Treatment |
|---|---|---|
| Primary Election | `primary` | Partisan preference sections plus applicable nonpartisan contests |
| General Election | `general` | Federal, state, OHA, county, vacancy, and measure contests may coexist |
| First Special Election | `special_first` | County nonpartisan election held with the primary |
| Second Special Election | `special_second` | Later county contest held with the general when the applicable threshold is not met |
| Vacancy Election | `vacancy_special` | May be added by a supplemental proclamation and conducted with a regular election |
| Special Election | `special` | Standalone or separately identified historical election |
| Constitutional amendment | `ballot_measure_state_constitutional` | Statewide general-election question |
| Charter, ordinance, or initiative question | `ballot_measure_local` | County-specific question |
| Mandatory recount | `recount_event` | Post-election event linked to the affected contest, not a new election |

Do not silently rename Hawaii’s “Second Special Election” as a conventional runoff. A normalized `runoff_like` flag may be added while preserving the state’s official name.

### Election-definition update strategy

1. Poll the proclamation archive before and throughout each cycle.
2. Store every proclamation, amendment, and vacancy proclamation as a versioned source record.
3. Treat a supplemental proclamation as an additive change unless the state explicitly supersedes an earlier document.
4. Compare election dates, offices, districts, terms, filing deadlines, and measure categories.
5. Cross-check scheduled offices against the Contest Schedule.
6. Use the Elected Officials page only as a dated incumbent and vacancy snapshot.
7. Cross-check historical election dates against the results index.

---

## 2. Candidate Filing and Candidate Status

### Official sources

- Landing page: `https://elections.hawaii.gov/candidates/candidate-reports/`
- 2026: `https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=94`
- 2024: `https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=92`
- 2022: `https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=87`
- Filing guidance: `https://elections.hawaii.gov/candidates/candidate-filing/`

The official landing page states that regular 2026 candidate filing closed June 2, 2026, while Senate District 18 vacancy filing remains open through September 4. It also states that the Candidate Report will be updated for status, contact, issuing, and filing changes.

### Confirmed portal coverage

| Cycle | `elid` | Records and pages observed | Status examples |
|---|---:|---:|---|
| 2022 | 87 | 509 items / 34 pages | `Issued`, `In Primary`, `In General` |
| 2024 | 92 | 395 items / 27 pages | `Issued`, `In Primary`, `In General`, `Elected` |
| 2026 | 94 | 411 items / 28 pages | `Issued`, `In Primary` as of August 5 |

The portal exposes page-size options of 10, 15, 20, and 50. The 2026 page reports 411 items in 28 pages; the 2024 and 2022 URLs return 395 and 509 items respectively.

### Fields

The report contains:

- Contest
- Party
- Ballot Name
- Legal Name
- Mailing Address
- Phone
- Email
- Website
- Issued date
- Filed date
- Status

Contact information is public in the state source, but CivicMirror should ingest only fields needed for its public product and provenance requirements.

### Status interpretation

| Status | Recommended interpretation |
|---|---|
| `Issued` | Nomination materials were issued. This alone does not establish ballot qualification. |
| `In Primary` | Candidate appears in the primary election. |
| `In General` | Candidate appears in the general election. |
| `Elected` | Post-election portal status. Do not use it in place of certified result ingestion. |
| Unknown future value | Preserve verbatim and queue for researcher review. |

The portal states that statuses are updated after the filing deadline and after elections to reflect the election in which the candidate appears or whether the candidate was elected.

### Candidate identifiers

No stable public candidate ID was verified in the page or HAR.

Use a source-scoped provisional key:

HI|cycle|contest_raw|party_raw|legal_name|filed_date


Also store:
• source elid 
• exact ballot name 
• exact legal name 
• exact raw party 
• exact raw contest 
• issued date 
• filed date 
• status and status-observed timestamp 
• source URL 
• retrieval timestamp 
• normalized row hash 
Do not join candidates solely by ballot name. Preserve legal and ballot names separately.
Discovering the current elid
Do not permanently hardcode elid=94.
1. Fetch the official Candidate Reports landing page. 
2. Follow its Candidate Report link. 
3. Record the resolved URL and elid. 
4. Store confirmed historical URLs for backfill. 
5. Start a clean browser or HTTP session when changing election cycles because the portal also maintains election state in a cookie. 

3. Candidate Portal HAR and Network Behavior
Two Firefox HAR exports were reviewed:
• olvr.hawaii.gov_Archive [26-08-05 16-40-14].json 
• olvr.hawaii.gov_Archive [26-08-05 16-57-03].json 
These captures are research evidence and should not be committed without sanitization.
Confirmed application behavior
The portal is an ASP.NET Web Forms application using Telerik RadGrid controls.
• Initial access is a GET to the CandidateFiling page. 
• Candidate records are returned in the full HTML response. 
• Grid actions are POST requests to the same URL. 
• Request content type is application/x-www-form-urlencoded. 
• Postbacks include fresh __VIEWSTATE and related ASP.NET state. 
• No separate candidate JSON or XHR data endpoint was observed. The export is a form postback to the same page. 
• Responses to captured grid actions were HTML. 
The form action and hidden ASP.NET state are present in the captured HTML. 
Page-size change
Changing the page size from 15 to 20 produced:
POST https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=94

__EVENTTARGET=ctl00$cphFooter$rdgSearch
__EVENTARGUMENT=FireCommand:ctl00$cphFooter$rdgSearch$ctl00;PageSize;20
ctl00$cphFooter$ddlElection=94
ctl00$cphFooter$rdgSearch$ctl00$ctl03$ctl01$PageSizeComboBox=20
The request also included __VIEWSTATE, filter fields, and Telerik client-state fields. The returned HTML initialized the page-size control with 20 selected. 
Numbered pagination
The second HAR captured numbered-page postbacks:
Page 2:
__EVENTTARGET=ctl00$cphFooter$rdgSearch$ctl00$ctl03$ctl01$ctl07

Page 3:
__EVENTTARGET=ctl00$cphFooter$rdgSearch$ctl00$ctl03$ctl01$ctl09
The page HTML exposed these visible mappings:
Page 1 → ...$ctl05
Page 2 → ...$ctl07
Page 3 → ...$ctl09
Page 4 → ...$ctl11
Page 5 → ...$ctl13
Page 6 → ...$ctl15
Page 7 → ...$ctl17
Page 8 → ...$ctl19
Page 9 → ...$ctl21
Page 10 → ...$ctl23
The control suffix currently increases by two, but an extractor should parse each response’s actual javascript:__doPostBack(...) links rather than generate control names from this pattern. 
Form fields observed
Captured postbacks included:
__EVENTTARGET
__EVENTARGUMENT
__LASTFOCUS
__VIEWSTATE
ctl00$cphFooter$ddlElection
ctl00$cphFooter$rdgSearch$ctl00$ctl02$ctl03$Contests
ctl00$cphFooter$rdgSearch$ctl00$ctl02$ctl03$Party
ctl00$cphFooter$rdgSearch$ctl00$ctl02$ctl03$Name
ctl00$cphFooter$rdgSearch$ctl00$ctl02$ctl03$LegalName
ctl00$cphFooter$rdgSearch$ctl00$ctl03$ctl01$PageSizeComboBox
Telerik client-state fields
The presence of empty filter fields confirms filter controls exist, but the HAR did not capture an applied filter. Their precise postback command remains unresolved. 
Session-pinned election behavior
The second capture’s page metadata referenced elid=87, but its actual CandidateFiling requests, form value, and election-state cookie remained on election 94. The session therefore continued to serve the 2026 report.
For reliable cycle switching:
1. clear olvr.hawaii.gov cookies or begin a private session; 
2. load the desired direct URL; 
3. verify the returned heading and ddlElection value; 
4. do not trust only the browser tab title or intended URL. 
Recommended extraction method
Preferred operational choices:
1. Browser automation that clicks the visible pager and verifies row changes; or 
2. An HTTP client that: 
    ◦ maintains session cookies; 
    ◦ parses fresh hidden fields on every response; 
    ◦ parses the actual page-specific __doPostBack targets; 
    ◦ submits the complete current form state; 
    ◦ verifies the returned current-page marker and first/last row. 
A simple sequence of independent GET requests is not sufficient for deterministic paging.
HAR security and retention
The raw captures include:
• ASP.NET session identifiers 
• Cloudflare cookies and clearance information 
• analytics cookies 
• the portal’s election-state cookie 
• request and response cookie arrays 
Do not commit the raw HARs. Before retaining a reproducible record, remove:
• all Cookie request headers; 
• all Set-Cookie response headers; 
• request and response cookie arrays; 
• unrelated analytics and browser-service requests; 
• full __VIEWSTATE values unless needed for a temporary local replay. 
Preserve request URL, method, parameter names, sanitized parameter structure, response status, response MIME type, and timing metadata.
Remaining HAR gaps
Not yet captured:
• an applied contest, party, ballot-name, or legal-name filter; 
• an election-cycle switch in a clean session; 
• column sorting; 
• an export action; 
• any hidden endpoint associated with such an action. 
The current 2026 candidate report exposes a verified CSV export; future work should preserve the postback mechanics rather than assuming a hidden API.

4. Race Creation and Ballot Qualification
Official sources
• Proclamations define the offices and broad election structure. 
• Candidate Reports supply candidate filings and status. 
• Preview ballots confirm ballot appearance and detailed contest structure. 
• Contest Schedule supplies expected offices, seats, jurisdictions, and terms. 
• GIS and proclamation precinct tables supply geographic applicability. 
The 2026 preview-ballot PDF contains precinct-coded ballot styles, political-preference sections, contest labels, candidates, and “Vote For Not More Than” limits. 
Recommended reconciliation process
1. Create the election from the proclamation. 
2. Create preliminary office and contest definitions from the proclamation and Contest Schedule. 
3. Import candidate filings and statuses from the Candidate Report. 
4. Treat In Primary and In General as candidate-election placement evidence. 
5. Validate candidate appearance, contest label, party section, vote-for limit, and precinct applicability against the preview ballot. 
6. Record discrepancies for manual review rather than silently dropping a candidate. 
7. Repeat after supplemental vacancy filing deadlines and ballot revisions. 
Suggested contest key
Before official results publish a contest ID:
election_key|jurisdiction|office_family|district_type|district_id|party_section
After result publication, attach the official election-scoped result contest_id.
Ballot-style key
election_key|precinct_code|split_code|ballot_style
Retain leading zeros and punctuation in precinct identifiers.

5. Official Election Results
Results index
https://elections.hawaii.gov/election-results/
The index is the authoritative discovery layer. It lists election years from 1992 through 2026 and links available result artifacts. As of August 5, the 2026 primary section existed before the August 8 election and its result files should be treated as pre-election placeholders until actual data is published. 
Current result-file examples
Certified 2024 General Election:
Statewide summary text:
https://files.hawaii.gov/elections/files/results/2024/General/summary.txt

Statewide precinct-detail text:
https://files.hawaii.gov/elections/files/results/2024/General/media.txt
The official index labels these as certified text files and separately links certified PDFs and the State House District 39 recount report. 
The research browser encountered a Unicode-decoding error when opening the two 2024 text files. This is a client-decoding limitation and does not establish that the files are invalid. Fetch raw bytes, retain the original file, inspect encoding, and parse without forcing UTF-8. 
Documented text schemas
The official 2010 layout documents a 16-column precinct/media report:
1. Precinct Name 
2. Split Name 
3. Precinct-Split ID 
4. Registered Voter count 
5. Ballots cast 
6. Precinct Reporting 
7. Contest ID 
8. Contest Title 
9. Contest Party 
10. Choice ID 
11. Candidate Name 
12. Choice Party 
13. Candidate Type 
14. Absentee Mail votes 
15. Early or absentee walk-in votes 
16. Election Day votes 
The corresponding summary layout documents 22 columns, including contest identifiers, sequence, type, party, blank and overvote totals by voting method, registered voters, total and counted precincts, candidate identifiers and sequence, candidate party, voting-method totals, and total votes. 
A separate 2006 layout documents fixed-position ASCII records for registered voters, ballots cast, and contest lines. This shows that result schemas changed over time. Parsers must be selected by election/report era rather than assuming one layout applies to the entire archive. 
Result identifiers and joins
Recommended keys:
Election:
HI|election_date|official_election_type|jurisdiction

Contest:
election_key|official_contest_id

Choice:
election_key|official_contest_id|official_choice_id

Precinct result:
election_key|official_contest_id|official_choice_id|precinct_split_id

Report version:
source_url|retrieved_at|content_hash
Treat contest and choice IDs as election-scoped unless cross-election stability is separately demonstrated.
Extraction procedure
1. Fetch the results index. 
2. Discover links and labels from the page instead of constructing filenames. 
3. Capture election date, report title, file type, certification label, recount label, and page Last Updated value. 
4. Download raw bytes. 
5. Store the file, checksum, retrieval time, and source URL. 
6. Select the parser associated with that report era. 
7. Validate row counts, contest totals, precinct totals, blanks, and overvotes. 
8. Compare statewide totals with the certified PDF. 
9. Version every changed file. 
10. Mark certified only from explicit official evidence. 
Update cadence
The Office of Elections page publishes update timestamps, but no fixed number or schedule of election-night releases was verified.
Recommended polling:
• before voting closes: infrequent discovery checks; 
• election night: frequent index and file checks; 
• following days: reduced frequency until certification; 
• after certification: daily checks for recount or replacement reports; 
• archive stage: stop routine polling after a stable retention period. 
Use content hashes and official timestamps rather than assumptions about numbered result “runs.”

6. Historical Results Coverage
Coverage by era
Era
Formats observed
Recommended extraction path
2026
Pre-election result links present as of August 5
Begin ingestion only after files contain actual results
2006–2024 regular primary/general
Certified summary and precinct text plus PDFs; statements of vote in many cycles
Structured text first; PDF validation
2004 General
Summary and precinct text plus PDFs
Structured text first
2004 Primary
Summary text plus PDFs; no precinct text listed
Summary text plus precinct PDF
2010 congressional special
PDF summary and precinct detail
PDF extraction and human validation
2002–2003 congressional specials
PDF summary, county reports, and precinct detail
PDF extraction and human validation
2002 regular primary/general
PDF only
PDF extraction
1996–2000 regular elections
Certified HTML plus PDFs
HTML first; PDF validation
1996 Special Election
Certified HTML and PDFs
HTML first; PDF validation
1992–1994 primary/general
Statewide summary PDFs only
PDF extraction; lower granularity
The archive therefore covers more than regular primary and general elections. It includes a 1996 special election and congressional special elections in November 2002, January 2003, and May 2010. 
Confirmed PDF-only special-election files
May 22, 2010 — U.S. Representative, District I Special Vacancy Election
• Statewide summary:
https://files.hawaii.gov/elections/files/results/2010/special/special2010-summary.pdf 
• Statewide precinct detail:
https://files.hawaii.gov/elections/files/results/2010/special/special2010-precinct.pdf 
The summary is one page. The precinct file is 197 pages and includes precinct, absentee-walk, turnout, candidate, blank, and overvote sections. Extraction difficulty is high because of the large repeated report structure. 
January 4, 2003 — U.S. Representative, District II Special Election
• Statewide summary:
https://files.hawaii.gov/elections/files/results/2003/special/histatewide.pdf 
• Statewide precinct detail:
https://files.hawaii.gov/elections/files/results/2003/special/precinct.pdf 
The summary is one page; the precinct report is 100 pages. Use the results index for the county-specific summary links. 
November 30, 2002 — U.S. Representative, District II Special Election
• Statewide summary:
https://files.hawaii.gov/elections/files/results/2002/special/histatewide.pdf 
• Statewide precinct detail:
https://files.hawaii.gov/elections/files/results/2002/special/precinct.pdf 
The summary is one page; the precinct report is 99 pages. Use the results index for county summaries. 
Earliest statewide summaries
• 1994 General:
https://files.hawaii.gov/elections/files/results/1994/general/histatewide.pdf 
• 1994 Primary:
https://files.hawaii.gov/elections/files/results/1994/primary/histatewide.pdf 
• 1992 General:
https://files.hawaii.gov/elections/files/results/1992/general/histatewide.pdf 
• 1992 Primary:
https://files.hawaii.gov/elections/files/results/1992/primary/histatewide.pdf 
These are scanned or scan-like fixed report pages. They are readable but substantially more difficult to normalize than structured text or HTML and may require human review after extraction. 
1996 special-election note
The results index labels the special election as September 23, 1996, while the linked statewide PDF prints September 21, 1996. Preserve both source observations and flag the date discrepancy for human resolution rather than silently selecting one. 
Historical backfill order
1. Structured result text. 
2. Certified HTML. 
3. Statewide and precinct PDFs. 
4. County-specific PDFs when statewide material lacks needed detail. 
5. Manual reconciliation against source totals. 
6. Store every artifact’s title, election date, report date, certification label, URL, retrieval time, parser version, and checksum. 

7. Hawaii Open Data Portal
Official source
• Organization dataset search:
https://opendata.hawaii.gov/dataset/?organization=office-of-elections 
• General Election 2012 Summary:
https://opendata.hawaii.gov/dataset/general-election-2012-summary-results 
The Office of Elections organization search returned five datasets. Confirmed formats across the election datasets include CSV, RDF, JSON, and XML. Identified datasets include 2010 General Election results and 2012 primary/general summary or precinct results. 
Classification
• Source type: database portal and structured bulk download 
• Authentication: none indicated for downloads 
• Coverage: narrow legacy coverage, principally 2010 and 2012 
• Use: historical validation and selected backfill 
• Do not use as: the current comprehensive election-results feed 
The previous claim that CKAN provides broad 1992–present results coverage is unsupported.
A general CKAN-style registry or dataset interface should not be labeled a dedicated election API. Only confirmed election dataset resources and documented endpoints should receive an API classification.

8. Ballot Measures
Official sources
• https://elections.hawaii.gov/proclamations/ 
• https://elections.hawaii.gov/voting/2024-proposed-amendments-to-the-hawaii-state-constitution/ 
• https://elections.hawaii.gov/election-results/ 
The 2026 proclamation states that the general election may include constitutional amendments and county charter, ordinance, or initiative questions. Historical result pages also link measure-specific material, including a County of Hawaii Charter Questions report in 2006. 
Recommended measure fields
• election key 
• state or county jurisdiction 
• official short title 
• full official question text 
• measure category 
• originating act, resolution, proclamation, charter, or ordinance reference 
• choice labels 
• result contest ID 
• total votes by choice 
• blanks 
• overvotes 
• certification status 
• definition source URL 
• result source URL 
• retrieval timestamps 
Suggested measure join key
election_key|jurisdiction|normalized_title|question_text_hash
Result-file titles may abbreviate the full question. Use jurisdiction and full-text hash for reconciliation rather than title alone.

9. Districts, Precincts, and GIS
Official sources
• https://elections.hawaii.gov/resources/maps/geographic-information-systems-gis-files/ 
• https://elections.hawaii.gov/resources/maps/ 
• https://elections.hawaii.gov/resources/districts-and-precincts/ 
• https://elections.hawaii.gov/about-us/boards-and-commissions/reapportionment/ 
The GIS page links 2022 election precincts, 2021 reapportionment congressional districts, county-specific state Senate and House districts, census-block assignments, and 2018 election precincts. 
Suggested geography keys
• precinct code 
• split code 
• precinct-split ID 
• county 
• congressional district 
• state Senate district 
• state House district 
• county council district 
• boundary vintage 
• effective election cycle 
• official GIS item or layer identifier 
Normalization cautions
• Keep precinct codes as strings. 
• Preserve leading zeros and punctuation. 
• Do not attach historical results to the newest district geometry without validating the applicable reapportionment plan. 
• Treat precinct-split result identifiers and GIS precinct identifiers as separate fields until a crosswalk is verified. 
• Store geometry source and vintage with every geographic association. 
Remaining GIS research
The public landing page is verified, but the underlying ArcGIS REST service URLs, layer IDs, field dictionaries, and download-format inventory were not fully captured. A GIS-focused follow-up should record these before implementation.

10. Certification, Recounts, and Election Objections
Certification
The results index labels files as certified and publishes certified PDFs and text files. Certification should be derived only from:
• an explicit Certified label on the Office of Elections page; 
• an official final or certification report; 
• another explicit first-party certification notice. 
Do not infer certification from 100% reporting.
Suggested normalized statuses:
reporting_unofficial
final_unofficial
recount_pending
recount_completed
certified
contested
certification_delayed
superseded
Always preserve the state’s exact label alongside the normalized value.
Recounts
The results archive separately links recount reports, including reports for 2020, 2022, and 2024 contests. Store a recount as a separate event linked to the original contest and result version. Do not overwrite the earlier result without retaining its provenance. 
Election objections
Official source:
https://elections.hawaii.gov/resources/election-objections/
A candidate, qualified political party, or 30 voters of an election district may file an objection presenting reasons that could change the result. The Office of Elections publishes separate 2026 primary and general objection deadlines and explains the Hawaii Supreme Court process. 
Suggested objection fields:
• election key 
• affected contest 
• complainant type 
• filing date 
• objection deadline 
• court case identifier 
• source document 
• disposition 
• judgment date 
• ordered remedy 
• result version affected 
Court records may require separate manual research after an objection is filed.

11. Campaign Finance
Official sources
• https://ags.hawaii.gov/campaign/ 
• https://ags.hawaii.gov/campaign/cc/view-searchable-data/ 
• https://ags.hawaii.gov/campaign/socrata-help/ 
• Candidate Filing System public site linked from the Commission 
The Commission’s searchable data page identifies data from reports filed by Hawaii state and county candidate committees. It describes searchable coverage from January 1, 2015 through December 31, 2025, encompassing the 2016–2024 elections, and notes that amended reports may add older transactions. 
The Commission documents programmatic access through the Socrata Open Data API and downloads in CSV, Excel, PDF, and other formats. Public data is read-only; an account is needed only for saving custom views. 
Data subjects
Confirmed or described datasets include:
• contributions received 
• expenditures made 
• other receipts 
• loans received 
• unpaid expenditures 
• candidate committee reports 
• disclosure summaries and schedules 
Candidate-to-committee reconciliation
No direct stable crosswalk from the Office of Elections Candidate Report to the campaign-finance system was verified.
Use:
• legal candidate name 
• ballot name 
• office 
• district 
• cycle 
• committee name 
• committee registration identifier, when present 
Store match confidence and require review for ambiguous identities.

12. Registration and Turnout
Official source:
https://elections.hawaii.gov/resources/registration-voter-turnout-statistics/
The Office of Elections publishes statewide and county registration and turnout history beginning in 1959, with recent data through 2024. It also links recent district-level turnout maps. 
CivicMirror uses
• election-level turnout reconciliation 
• county reconciliation 
• registered-voter denominator checks 
• long-term historical context 
• comparison with result-file ballots-cast totals 
These tables do not contain contest-level vote results and should not be used to reconstruct contests.

13. CivicMirror Pipeline Map
Pipeline stage
Primary official source
Suggested identifiers and joins
Extraction and update strategy
Known gaps
Election calendar
Proclamation archive; current proclamation; results index
State, election date, official type, jurisdiction
Poll and version proclamations; cross-check result archive
No single normalized historical calendar download
Election definitions
Proclamation HTML/PDF
Proclamation date, election date, jurisdiction, office
Parse official terms and retain source version
Supplemental vacancies may arrive after the main proclamation
Election type
Proclamation language
Official type plus normalized type
Preserve exact Hawaii terminology
Second special elections require careful normalization
Offices and terms
Proclamation; Contest Schedule
Office family, seat, district, jurisdiction, term
Use schedule as baseline and proclamation as cycle authority
Schedule page may lag supplemental vacancies
Incumbents
Elected Officials page
Office, district, incumbent, access date
Snapshot and version
Current-state source, not historical officeholder database
Districts
Proclamation and GIS
District type/number, boundary vintage
Load geometry independently and attach applicable vintage
ArcGIS service metadata not fully captured
Precincts
GIS and result files
Precinct code, split code, precinct-split ID
Reconcile identifiers before geometry join
Crosswalk is not documented in one file
Contests
Proclamation, Candidate Report, preview ballots
Election, office, district, jurisdiction, party section
Create preliminary contest; validate against ballot
No confirmed pre-result stable contest ID
Candidates
Candidate Report
Source composite key and row hash
Poll through filing and vacancy deadlines
No stable candidate ID or export
Filing status
Candidate Report
Candidate source key plus observation time
Store as event history
Full future status vocabulary not documented
Ballot qualification
Candidate status and preview ballot
Candidate-to-contest and ballot-style relation
Require qualifying status and verify ballot appearance
Large PDF and possible revisions
Party affiliation
Candidate Report and ballot
Exact raw party plus normalized party ID
Preserve source spelling and abbreviations
Party labels vary by cycle/source
Ballot measures
Proclamations, question pages, results
Election, jurisdiction, text hash, result contest ID
Load definition first; attach result later
Result titles may be abbreviated
Results
Summary and precinct text
Election + contest ID + choice ID + precinct-split ID
Poll, hash, version, parse by schema era
Encoding and schema variation
Certification
Results index and certified reports
Result version plus certification evidence
Promote only from explicit official evidence
No structured certification Boolean verified
Recounts
Results index recount links
Election, contest, recount report
Store separate event and later result version
Reports are generally PDF
Election objections
Objection page and court records
Election, contest, case ID
Activate when filed; monitor disposition
Court linkage is partly manual
Campaign finance
SODA datasets and filing system
Committee ID, candidate, office, district, cycle
API/download polling around deadlines
No direct candidate crosswalk
Turnout
Turnout tables and result files
Election, county, precinct or district
Reconciliation and validation
Historical tables are aggregated
Historical archive
Results index
Election date/type, artifact URL
Backfill by format era
Early years and specials are PDF-heavy

14. Normalization Notes
Names
• Preserve punctuation, capitalization, diacritics, apostrophes, and Hawaiian ʻokina in raw fields. 
• Keep legal and ballot names separate. 
• Generate normalized comparison fields only for matching. 
• Do not replace the state’s display form with a normalized form. 
• Parenthetical nicknames should remain in the ballot-name field. 
Parties
• Preserve exact official party labels. 
• Maintain a separate normalized party identifier. 
• Do not assume the same abbreviation or party roster across cycles. 
• A candidate may appear in portal records associated with more than one party or status; do not deduplicate solely by legal name. 
Offices
Separate:
• office family 
• jurisdiction 
• district type 
• district number or name 
• at-large status 
• residency-seat requirement 
• term length 
• party section 
• vote-for limit 
Examples requiring structured normalization include OHA resident-trustee seats, county council residency areas, and district-numbered federal and legislative offices.
Precincts
• Store codes as strings. 
• Preserve leading zeros. 
• Keep punctuation. 
• Store split separately when available. 
• Store boundary vintage. 
• Validate result precinct codes against the applicable GIS release. 
Result versions
Store:
• results-index URL 
• direct file URL 
• report title 
• report type 
• election date 
• retrieval timestamp 
• state Last Updated value 
• certification label 
• file checksum 
• parser version 
• superseding report reference 

15. Known Gaps and Human-Review Items
1. Candidate filtering was not captured. The form fields are known, but the exact filter postback command remains unresolved. 
2. Clean election switching was not captured. The second HAR remained pinned to elid=94 despite an intended elid=87 navigation. 
3. The CSV export path was verified on the live 2026 report. No public JSON, Excel, or documented API was found. 
4. Pre-2022 candidate reports were not confirmed. 
5. No stable candidate identifier was found. 
6. No official Hawaii Clarity endpoint was verified. 
7. No official public result REST or JSON API was identified. 
8. The 2026 primary result files were not yet populated with election results on the August 5 research date. 
9. Senate District 18 candidate data can change through September 4, 2026. 
10. Result schemas vary by era. A 2006 fixed-position layout and a different 2010 column layout are both official. 
11. Current result-file encoding needs raw-byte testing. 
12. The certification signal is page/report labeling rather than a verified structured field. 
13. ArcGIS item IDs, REST layer URLs, schemas, and downloadable formats need a focused capture. 
14. Campaign-finance candidate crosswalks require fuzzy matching and review. 
15. 1992–1994 results are low-granularity PDF-only sources. 
16. The 1996 special election has a date discrepancy between the index and linked report that requires human resolution. 
17. Historical county and precinct PDF inventories are large. The official index should be retained as the discovery manifest. 
18. Recall elections were not identified in the statewide results archive. County charter sources should be researched when a recall is initiated rather than assuming statewide administration. 

16. Recommended Implementation Order
Priority 1 — Native Stage 1 candidate and contest creation
1. Fetch the official Candidate Reports landing page. 
2. Discover the active Candidate Report URL and elid. 
3. Start a clean session for the selected cycle. 
4. Extract all pages using parsed postback targets and fresh ASP.NET state. 
5. Store candidate status history. 
6. Build elections and office definitions from proclamations. 
7. Validate ballot-qualified candidates and contests against preview ballots. 
8. Continue polling through supplemental vacancy deadlines. 
Priority 2 — Official Stage 2 result ingestion
1. Scrape the results index. 
2. Discover summary and precinct text links. 
3. Download raw bytes and retain checksums. 
4. Identify the applicable schema era. 
5. Load election-scoped contests and choices. 
6. Load statewide and precinct totals. 
7. Reconcile blanks, overvotes, ballots cast, registration, and reporting totals. 
8. Version changed files. 
9. apply certification only from explicit state evidence. 
10. attach recount reports as separate events. 
Priority 3 — Historical backfill
1. Structured text for regular elections from 2004 forward. 
2. Certified HTML for 1996–2000. 
3. PDF-only congressional special elections. 
4. PDF-only 2002 regular elections. 
5. 1992–1994 statewide summary PDFs. 
6. Validate selected 2010/2012 output against Hawaii Open Data datasets. 
Priority 4 — Enrichment
1. GIS boundaries and precinct crosswalks. 
2. Registration and turnout history. 
3. Current incumbent and vacancy snapshots. 
4. Campaign-finance SODA data. 
5. Ballot-measure definitions. 
6. Election-objection and court-event monitoring when applicable. 

17. Source Coverage Analysis
Hawaii should no longer be classified as a Google-Civic-only Stage 1 state. The Office of Elections provides a native candidate source with contest, party, ballot and legal names, filing dates, and status. The source is machine-accessible through HTML scraping, though it requires stateful ASP.NET postbacks and careful session handling.
The HAR captures resolve the principal pagination question from issue #156. Page-size and numbered-page navigation are form postbacks to the same CandidateFiling URL. The requests carry fresh page state and return full HTML. No hidden candidate JSON API was observed.
The Stage 1 source chain is distributed but complementary:
• proclamations define elections, dates, offices, vacancy contests, and measure categories; 
• the Contest Schedule supplies expected office cycles and terms; 
• the Candidate Report supplies candidate and filing-state information; 
• preview ballots establish actual ballot placement and detailed contest structure; 
• GIS files establish district and precinct geography; 
• the Elected Officials page supplies a dated incumbent and vacancy snapshot. 
For Stage 2, the Office of Elections result-text files are the highest-value source. They provide substantially more integration value than PDFs and more complete cycle coverage than the Hawaii Open Data portal. The state publishes official text-layout documentation, but the archive demonstrates that the layout changed over time, so parsers must be versioned by era.
The Hawaii Open Data portal remains useful for selected 2010 and 2012 validation. It should not be described as a comprehensive current results API.
The historical archive is broader than the original file indicated. It includes standalone congressional special elections, a 1996 special election, ballot questions, certified HTML, recounts, and PDF-only early results. The appropriate backfill strategy is therefore structured text first, certified HTML second, and PDFs last.
No official Hawaii Clarity Elections source was confirmed. CivicMirror’s existing internal “Clarity sweep” designation should be treated as an implementation assumption until an official Hawaii-owned URL or observed official network path establishes the source.
The remaining core work is implementation rather than source discovery: a candidate HTML adapter, an era-aware result-text adapter, and historical HTML/PDF fallback procedures can provide a substantially first-party Hawaii election pipeline.






