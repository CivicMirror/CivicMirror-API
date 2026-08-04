# Maryland Election Research — CivicMirror Source Inventory and Pipeline Map

## Coverage Status

| Pipeline stage             | Status                               | Recommended official source                                               | Notes                                                                                                          |
| -------------------------- | ------------------------------------ | ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Election creation          | ✅ Strong                             | SBE election calendar; Offices Up for Election                            | Covers regular primary/general dates, deadlines, election scope, and expected office families.                 |
| Race creation              | ✅ Strong                             | Offices Up for Election; candidate-list CSVs                              | Candidate CSVs provide office, district, party, status, and filing information.                                |
| Candidate filings          | ✅ Strong                             | SBE candidate-list CSVs and HTML                                          | Rich candidate data; schema changes between cycles require header-based mapping.                               |
| Ballot qualification       | ✅ Strong                             | Candidate status and filing fields                                        | Preserve withdrawn, disqualified, and other inactive records rather than deleting them.                        |
| Ballot measures            | ✅ Strong for 2026                    | SBE ballot-question HTML; DLS summary PDF                                 | Statewide and local question text is available; petition-based questions may remain provisional during review. |
| Live or unofficial results | ✅ Source identified                  | Static full-ballot HTML; limited dashboard JSON                           | No full-results API verified. HTML is the complete source; JSON covers selected featured contests only.        |
| Certified results          | ✅ Strong                             | Current and archived election-data CSVs; official result pages            | County, precinct, congressional, legislative, and local-district breakdowns.                                   |
| Election certification     | ⚠️ Partial                           | Official result-page status; SBE certification/audit notices              | “Official” page status is confirmed, but certification instruments are not yet indexed systematically.         |
| Recounts and audits        | ⚠️ Partial                           | SBE press releases, board materials, audit notices                        | Requires event-specific discovery.                                                                             |
| Special elections          | ✅ Available                          | SBE special-election archive                                              | Mixed state-hosted and official county-hosted result pages and PDFs.                                           |
| Municipal elections        | ⚠️ Heterogeneous                     | SBE municipal-results manifest                                            | DOCX, PDF, and XLSX files with no common schema.                                                               |
| Campaign finance           | ⚠️ Strong portal; extraction pending | MD CRIS                                                                   | Official database from 1999 forward; automated access and raw-download behavior require focused capture.       |
| Districts and precincts    | ✅ References; GIS follow-up          | Precinct-reference Excel files; SBE district page; Maryland Planning maps | Precinct crosswalks are structured. Machine-readable boundary-layer access remains to be verified.             |
| Cast-vote records          | ⚠️ Cycle-dependent                   | Election-specific SBE result pages                                        | Confirmed for the 2022 gubernatorial primary; not consistently linked for every cycle.                         |
| Historical archive         | ✅ Extensive, mixed formats           | SBE elections archive                                                     | General/primary pages extend to the 1980s; structured detail and vote-mode granularity vary by generation.     |

---

**Primary site:** `https://elections.maryland.gov/`
**Operated by:** Maryland State Board of Elections
**Researched:** March 4, 2026
**Updated:** August 4, 2026 — corrected current 2026 certification and raw-data paths; added ballot-question, campaign-finance, district, cast-vote-record, special-election, municipal, and pipeline coverage.
**Access checked:** August 4, 2026
**Authentication:** None for the core election, candidate, result, and archive sources
**Verified public REST API:** None identified
**Current results architecture:** State-hosted static HTML, downloadable CSV/Excel files, and a limited flat JSON dashboard feed
**Vendor finding:** No evidence that the current statewide result pages use Clarity, Civix, or another separately hosted election-night reporting vendor.

---

## 1. Executive Assessment

Maryland is a high-value state for CivicMirror because its State Board of Elections centrally publishes:

1. election dates and office families;
2. detailed candidate filing lists in CSV and HTML;
3. full-ballot result pages;
4. structured county, precinct, congressional, legislative, and councilmanic or commissioner-district result files;
5. statewide and local ballot-question text;
6. historical regular and special-election archives;
7. an official campaign-finance database;
8. election-specific precinct-reference workbooks; and
9. some cycle-specific cast-vote-record collections.

The official 2026 gubernatorial primary pages now identify the results as **Official**, with a last-refresh timestamp of July 23, 2026. The 2026 `election_data` page is also active and exposes primary result files for statewide and county breakdowns. This supersedes the earlier observation that the active-cycle data directory did not yet exist.

Maryland does not need Google Civic Information API as a primary election-creation or candidate source. Official SBE pages now provide the election dates, office universe, candidate lists, filing status, ballot questions, and result structure needed for the core state pipeline.

---

## 2. Material Changes From the July 21 Research

### Corrected

* The statement that `/elections/2026/election_data/` was unavailable is now stale. The page is active and contains 2026 primary data files.
* The 2026 primary result pages no longer say “Unofficial.” They now say “Official.”
* Ballot-measure text is not an unresolved core gap. SBE publishes statewide and local question text, explanatory language, and FOR/AGAINST descriptions.
* Maryland has an official district-map hub and structured precinct-reference workbooks. The remaining boundary gap is verification of machine-readable GIS downloads, not the absence of an official source.
* Campaign finance is now included as a CivicMirror pipeline source.
* Cast-vote records are confirmed for at least the 2022 gubernatorial primary.
* The municipal lane is confirmed as a mixed-format document pipeline, including DOCX, PDF, and XLSX—not a conventional result-table adapter.

### Preserved as HAR-derived findings

The supplied research records the following observations from the July 21 HAR:

* UTF-8 BOM on `dashboarddata.json`;
* static HTML result delivery rather than a full hidden JSON result service;
* CSV responses served as `application/octet-stream`;
* Cloudflare-related infrastructure;
* response-body “soft 404” behavior;
* ETag or cache-related behavior;
* CRLF and trailing-space irregularities in some CSV rows;
* candidate schema differences between 2025 and 2026.

The currently accessible official pages corroborate the BOM-prefixed JSON, flat static HTML, downloadable files, dotted filenames, and schema variability. Exact HTTP status codes, cache headers, response sizes, and generator details should be replayed from the HAR or tested from the production environment before they are made adapter invariants.

---

## 3. Ranked Official Source Inventory

### Rank 1 — Raw election-result data files

**Entity:** Maryland State Board of Elections
**Current-cycle index:** `https://elections.maryland.gov/elections/2026/election_data/index.html`
**Historical pattern:** `https://elections.maryland.gov/elections/archive/{year}/election_data/index.html`
**Source types:** CSV, Excel
**Access:** Public GET; no authentication
**Election scope:** Primary and general elections
**Data subjects:** Candidates, questions, vote totals, party, winner indicator, write-ins, precincts, counties, congressional districts, legislative districts, councilmanic or commissioner districts
**Machine-readability:** High
**Integration value:** Highest

The 2026 page exposes statewide congressional, legislative, and precinct files, followed by county-level and precinct-level files for Maryland’s jurisdictions. It also links an Excel state precinct reference for the primary.

Maryland’s official documentation says these electronic files implement Election Law §11-402 reporting by precinct, state legislative district or subdistrict, county legislative district, and county. It also confirms that the files are comma-separated and have header rows.

**Historical granularity warning:** For elections before the 2020 general election, precinct-level detail generally covers election-day voting only; early, mail-in, and provisional totals are instead reported at county level. From the 2020 general election forward, those vote modes are available at precinct level.

**Suggested identifiers and joins**

* `election_code` from filename, such as `GP26`
* `county_code`
* `election_district`
* `precinct`
* `office_name`
* `office_district`
* `candidate_name`
* `party`
* question key: `election + county + question_number`
* geographic join: precinct-reference workbook plus county and district fields

Do not use `question_number` alone as a statewide identifier. SBE warns that different counties may use the same question number.

---

### Rank 2 — Candidate filing CSVs

**Index pattern:** `https://elections.maryland.gov/elections/{year}/primary_candidates/index.html`
**2026 statewide list:** `https://elections.maryland.gov/elections/2026/primary_candidates/2026_GP_statewide_candidatelist.html`
**Source types:** CSV and HTML
**Access:** Public GET
**Data subjects:** Office, district, party, candidate name, jurisdiction, status, filing method and date, campaign contact information, committee, social links, and related candidate or running mate
**Machine-readability:** High for CSV
**Update cadence:** Irregular during filing and qualification; page exposes a last-updated timestamp

The statewide page links both a consolidated CSV and per-office CSVs. Candidate entries include status, filing date, jurisdiction, committee, address, phone, website, and related-candidate information.

**Recommended candidate key**

Maryland does not expose a clearly documented stable candidate ID in these files. Use a source-scoped compound key:

```text
election_cycle
+ office_name
+ contest_district
+ party
+ ballot_last_name
+ ballot_first_middle_name
+ related_candidate_flag
```

Retain the original source row and candidate-list retrieval timestamp. Name-based matching across cycles should be treated as probabilistic.

**Normalization rules**

* Map by header name, never column position.
* Preserve `Candidate Status` as source data.
* Do not delete withdrawn or disqualified candidates.
* Keep ballot-name fields separate from display-name and person-identity fields.
* Model Governor/Lt. Governor as a ticket with two people, not one concatenated candidate.
* Preserve committee name as a preliminary campaign-finance join, not a definitive committee identifier.

---

### Rank 3 — Full result HTML pages

**2026 primary index:** `https://elections.maryland.gov/elections/2026/primary_results/index.html`
**Source type:** Static HTML tables
**Access:** Public GET; no client rendering required for the captured pages
**Coverage:** Full state and local ballot
**Machine-readability:** Medium to high
**Use:** Live or unofficial results, manual verification, and official result summaries

The official result tables contain candidate name, party, early voting, election-day voting, mail-in ballot, provisional ballot, total, percentage, winner indicator, and county-breakdown links.

The earlier HAR documented filenames such as:

```text
gen_results_{year}_{group}[_{sequence}].html
gen_detail_results_{year}_{office}_{sequence}_{party}.html
```

District-page sequence values should not be assumed to equal the displayed district. Scrape the result index and retain the page label and URL as the authoritative sequence mapping.

**Certification rule**

Use the result-page title as one certification signal:

```text
Unofficial ... Election Results
Official ... Election Results
```

Do not infer certification solely from 100% reporting, a winner icon, or a `Winner=Y` field. Save the page title, retrieval date, last-refresh value, and raw file snapshot.

---

### Rank 4 — `dashboarddata.json`

**2026 URL:** `https://elections.maryland.gov/elections/2026/primary_results/dashboarddata.json`
**Source type:** JSON file
**Access:** Public GET
**Coverage:** Selected featured contests only
**Machine-readability:** High, but incomplete
**Recommended use:** Refresh heartbeat and limited homepage display—not full result ingestion

The current file is BOM-prefixed, contains a `lastRefreshed` field, and stores votes and percentages as formatted strings. Its 2026 content covers selected congressional contests rather than the whole ballot.

Use it to detect a possible update, then refresh the complete HTML pages. Do not label it a statewide results API.

---

### Rank 5 — Ballot-question page and legislative summaries

**HTML:** `https://elections.maryland.gov/elections/2026/ballot_questions.html`
**PDF:** `https://elections.maryland.gov/elections/2026/2026_Ballot_Question_SBE_Letter.pdf`
**Entities:** Maryland SBE; Maryland General Assembly Department of Legislative Services
**Source types:** HTML and PDF
**Coverage:** Statewide constitutional amendments and local ballot questions
**Machine-readability:** High for HTML; medium for PDF

The 2026 page includes the question title, constitutional or statutory reference, ballot text, and explanatory FOR/AGAINST language. It also warns that some petition-based questions may not qualify until signature verification and certification are complete.

The July 29 DLS letter identifies three statewide constitutional amendments, their enacted chapters or bills, and approved summaries.

**Measure key**

```text
election_date
+ jurisdiction
+ question_label
+ enacted_chapter_or_bill, when present
```

Preserve:

* official title;
* complete question text;
* summary;
* FOR text;
* AGAINST text;
* constitutional article or statute;
* chapter and bill;
* jurisdiction;
* qualification status;
* source version and retrieval date.

Because the page was still handling comment deadlines and petition qualification, the pre-election adapter should version question text rather than overwrite it.

---

### Rank 6 — Election calendar and office universe

**Calendar PDF:** `https://elections.maryland.gov/elections/2026/2026_Election_Calendar.pdf`
**Offices page:** `https://elections.maryland.gov/candidacy/ballot.html`
**Source types:** PDF and HTML
**Coverage:** Election dates, deadlines, filing, withdrawals, petitions, canvass activities, state/federal/local office families
**Machine-readability:** Medium for PDF; high for HTML

The 2026 calendar identifies the June 23 primary and November 3 general election and provides statutory deadlines beginning before the election year. The offices page identifies statewide executive offices, General Assembly seats, circuit courts, appellate retention elections, congressional seats, local offices, boards of education, and party offices.

Use the offices page to create an expected contest skeleton. Candidate CSVs should then instantiate the actual party and district contests.

---

### Rank 7 — Historical and special-election archives

**Archive:** `https://elections.maryland.gov/elections/archive/index.html`
**Special-election archive:** `https://elections.maryland.gov/elections/archive/special_elections_past.html`
**Source types:** HTML indexes, CSV, Excel, PDF, and linked official county pages
**Access:** Public
**Historical scope:** General/primary election pages back to the 1980s, plus special elections and a 1948–2012 presidential candidate summary

The archive lists regular cycles from 2024 back through 1983, including Baltimore City off-cycle elections, and separately links special elections, municipal results, and historical presidential totals.

The special-election archive includes elections from 2024, 2022, 2020, 2011, 2009, 2008, and older entries. Some older records redirect to official county sources or rely on PDFs rather than state CSVs.

Create an archive manifest before parsing results:

```text
election date
displayed election name
election type
jurisdiction
index URL
result URL
download URL
format
official/unofficial label
retrieval date
```

Do not assume one filename or schema generation across the entire archive.

---

### Rank 8 — Municipal result manifest

**URL:** `https://elections.maryland.gov/elections/municipal_results.html`
**Source types:** DOCX, PDF, XLSX
**Coverage:** Municipal elections submitted to SBE
**Machine-readability:** Low and inconsistent

The current page links municipality-specific files in all three formats. Individual documents may be letters, simple vote lists, spreadsheets, or formal result reports.

**Recommended lane**

1. Parse the HTML page as a clean file manifest.
2. Save municipality, displayed election date, file type, URL, retrieval date, and checksum.
3. Route XLSX files to spreadsheet extraction.
4. Route DOCX and text-based PDFs to document extraction.
5. Route image-only PDFs to human review or OCR as a last resort.
6. Preserve the source document with every normalized result.
7. Require manual review where office, vote-for limit, candidate status, or certification language is unclear.

Municipal data should not block the core statewide pipeline.

---

### Rank 9 — Campaign finance

**SBE page:** `https://elections.maryland.gov/campaign_finance/campaign_finance_database.html`
**Portal:** MD CRIS at `campaignfinancemd.us`
**Source type:** Official database portal
**Coverage:** Candidate committees, slates, PACs, party committees, ballot-issue committees, and legislative caucus committees
**Authentication:** Public search; automated access behavior not fully verified
**Historical coverage:** Active database from 2007 forward; archived search for 1999–2006

SBE states that MD CRIS contains contributions and expenditures as filed by campaign committees. It includes all committees filing reports with SBE; electronically filed reports are posted, while some low-activity accounts are manually entered by staff.

The portal returned an access denial from the current research environment, so no API, export endpoint, query parameters, or bulk-download workflow should be claimed yet.

**Focused follow-up needed**

Capture a normal browser session that performs:

* committee search;
* candidate committee lookup;
* report selection;
* contribution search;
* expenditure search;
* raw-data or export action.

Document observable requests, parameters, pagination, download formats, and access restrictions. Do not reverse-engineer or invent hidden endpoints.

**Likely CivicMirror joins**

* exact committee name from candidate CSV;
* candidate name;
* office;
* election cycle;
* committee registration identifier, once exposed by MD CRIS.

Committee-name matching alone is insufficient for production identity resolution.

---

### Rank 10 — Precinct references and district maps

**Precinct references:** Linked from each cycle’s `election_data` page
**SBE district page:** `https://elections.maryland.gov/elections/districts.html`
**Source types:** Excel, HTML, official map portal
**Coverage:** Precinct identifiers, polling-place references, congressional and legislative district context
**Machine-readability:** High for Excel; GIS format not yet verified

The SBE district page links Maryland Department of Planning redistricting maps and detailed redistricting information.

**Follow-up**

Verify whether Maryland Planning publishes:

* downloadable shapefiles;
* GeoJSON;
* ArcGIS REST layers;
* authoritative district effective dates;
* precinct polygons or only congressional and legislative boundaries.

Until verified, classify the Planning source as an official map portal—not a confirmed GIS API.

---

### Rank 11 — Cast-vote records

The official 2022 gubernatorial primary results page links downloadable cast-vote records for each local board of elections through an SBE SharePoint location.

**Classification:** Bulk download / election-specific archive
**Confirmed coverage:** 2022 gubernatorial primary
**Current gap:** No consistent statewide index has been verified for all cycles or election types.

CVRs should be treated as optional transparency and audit data, not as the primary certified-result source. Before ingestion, document format, ballot anonymity controls, jurisdiction coverage, contest identifiers, and whether records are original or transformed exports.

---

## 4. Result Data Model Notes

### Candidate result fields

Modern Maryland result files commonly include:

```text
County
County Name
Election District - Precinct
Congressional
Legislative
Office Name
Office District
Candidate Name
Party
Winner
Write-In?
vote-mode columns
```

Vote modes can include:

```text
Early Voting
Election Day
Mail-In Ballot 1
Provisional
Mail-In Ballot 2
```

The official documentation also describes older schema generations using “Election Night,” “Absentee,” “Provisional,” and “2nd Absentee” terminology. Build schema adapters by detected header set, not by year alone.

### Questions and retention contests

“For” and “Against” columns are required for ballot questions and appellate judicial retention contests. Ordinary candidate rows may leave “Against” columns empty. SBE’s documentation explicitly describes vote type 1 as For and vote type 2 as Against for appellate judges and question files.

### County codes

SBE documents a stable lookup beginning with:

```text
00 = State level
01 = Allegany County
02 = Anne Arundel County
03 = Baltimore City
...
```

Store both code and official county name. Do not derive Maryland’s county ordering alphabetically.

---

## 5. CivicMirror Pipeline Map

| Pipeline stage       | Primary source                         | Suggested key                                 | Extraction and update strategy                                              | Known gap                                       |
| -------------------- | -------------------------------------- | --------------------------------------------- | --------------------------------------------------------------------------- | ----------------------------------------------- |
| Election calendar    | Calendar PDF; offices page             | election date + type                          | Check annually and after legislative revisions; retain PDF version          | Off-cycle municipal events are separate         |
| Election definition  | Offices page; result/candidate indexes | year + primary/general/special + jurisdiction | Create expected election records, then reconcile to published pages         | No documented universal election ID             |
| Offices              | Offices Up for Election                | office name + jurisdiction + district type    | Normalize official labels; retain raw label                                 | Local office naming varies                      |
| Contests             | Candidate CSV; result index            | election + office + district + party          | Create from active and inactive filings; reconcile after ballot publication | No stable contest ID exposed                    |
| Candidates           | Candidate CSV                          | source-scoped compound key                    | Poll by timestamp/checksum; preserve status history                         | No stable person ID                             |
| Filing status        | Candidate CSV                          | candidate source row                          | Store status and filing date as events                                      | Reason codes may be incomplete                  |
| Tickets              | Related-candidate fields               | election + office + ticket members            | Model Governor/Lt. Governor relationship explicitly                         | Ticket changes need history                     |
| Ballot measures      | Ballot-question HTML; DLS PDF          | election + jurisdiction + question + chapter  | Version during public-comment and petition review                           | Qualification can remain provisional            |
| Live results         | Static HTML                            | page URL + contest label                      | Discover pages from index; poll conservatively; snapshot raw HTML           | No full live JSON API                           |
| Refresh detection    | `dashboarddata.json`                   | `lastRefreshed` + source hash                 | Use as trigger, not results authority                                       | Covers featured contests only                   |
| Certified results    | CSV data page; official HTML           | election code + geography + contest + choice  | Download complete package and checksum; reconcile to official status        | Separate certification instrument index pending |
| Precinct geography   | Precinct-reference Excel               | county + ED + precinct                        | Load before result rows; version by election                                | Boundary polygons not yet verified              |
| Historical results   | Archive indexes                        | election date + official index URL            | Build format-aware manifest, then parse by generation                       | Older files may lack vote-mode detail           |
| Special elections    | Special archive                        | date + office + jurisdiction                  | Crawl state and official linked county sources                              | Formats vary                                    |
| Municipal results    | Municipal manifest                     | municipality + date + file URL                | Document extraction with manual review                                      | No common schema                                |
| Campaign finance     | MD CRIS                                | committee ID when discovered                  | Focused browser/HAR research; snapshot reports and transactions             | Automated access currently unresolved           |
| CVRs                 | Election-specific SharePoint links     | election + local board + source file          | Optional bulk lane; retain source files                                     | Availability varies by cycle                    |
| Certification/audits | Result titles; SBE notices             | election + event date                         | Record official/unofficial transitions and audit events                     | No consolidated certification feed              |

---

## 6. Adapter Gotchas

1. **Current versus archive paths change over the cycle.**
   During an active election, data appears under `/elections/{year}/`. After archival, historical pages use `/elections/archive/{year}/`. Discover links from official indexes rather than constructing only one pattern.

2. **Page-not-found bodies must be detected.**
   The supplied HAR reported soft 404 behavior. Regardless of status code, verify expected title, table, or file signature before accepting a response.

3. **One current placeholder is defective.**
   The 2026 result-data page exposes a general-election precinct-reference link before a valid general-election file has been published. Treat unreplaced template links and page-not-found responses as unavailable, not empty datasets.

4. **JSON begins with a BOM.**
   Decode `dashboarddata.json` with UTF-8 BOM support.

5. **Numbers are display strings in live sources.**
   Remove commas, percent signs, whitespace, and `NR` markers before numeric conversion.

6. **CSV media type may be generic.**
   Validate CSV bytes and headers instead of relying on `Content-Type`.

7. **Filenames contain multiple periods.**
   Determine the file extension from the final suffix only.

8. **Candidate-list columns drift.**
   Use normalized header names and preserve unknown columns.

9. **Result schemas have generations.**
   The documentation’s legacy filenames and terminology differ from modern abbreviated filenames such as `GP26_...`. Detect columns and election metadata rather than assuming one universal naming rule.

10. **District sequence numbers in HTML may be positional.**
    Build the sequence-to-label map from the index page each election.

11. **Question numbers are not globally unique.**
    Always include jurisdiction and election.

12. **Official status is separate from reporting completeness.**
    “100% precincts reported” does not itself mean certified.

---

## 7. Recommended Implementation Order

**Note (2026-08-04):** Stage 2 (certified-results CSV ingestion, `results/adapters/md.py`/`md_aggregate.py`) already shipped in PR #82. The gap CivicMirror actually needs closed next is Stage 1 (election discovery + race/candidate creation), so the candidate-list loader is promoted to item 1 below — it is MD's Stage 1 source, not a follow-on to the results loader. The original ordering (results indexer/loader before candidate loader) made sense for a state starting from zero but is stale now that Stage 2 is live.

1. **Build the candidate-list loader (Stage 1).**
   Load consolidated and per-office CSVs, preserve statuses, and model related candidates. This is the piece that unblocks native race/candidate creation and replaces Civic API reliance — the actual current gap.

2. **Build the current and archived election-data indexer.**
   Enumerate all linked CSV and Excel files, classify them by election, geography, party, contest/question content, and file generation. Reuse where Stage 2 already indexes these paths.

3. **Reconcile against the certified-results CSV loader.**
   Stage 2 already ingests results; confirm Stage-1-created races/candidates attach cleanly to existing `OfficialResult` rows before promoting MD to Full Core.

4. **Build the ballot-question adapter.**
   Parse the official HTML and retain DLS PDFs as provenance attachments. *(Deferred — not required for Full Core at this time; see Section 9 scope note.)*

5. **Build the live HTML adapter.**
   Discover all pages from the result index. Use `dashboarddata.json` only as a heartbeat.

6. **Add precinct-reference workbooks.**
   Use them for precinct identity and geographic quality checks.

7. **Index historical and special elections.**
   Separate discovery from format-specific extraction.

8. **Add the municipal document lane.**
   Prioritize XLSX, then structured DOCX/PDF, with manual review for freeform documents. *(Deferred — not required for Full Core at this time; see Section 9 scope note.)*

9. **Capture MD CRIS network behavior.**
   Do not begin a campaign-finance adapter until the official search and export flows are documented.

10. **Verify official GIS downloads.**
    Record exact layer ownership, effective dates, coordinate system, and file or service type.

11. **Index certification, recount, and audit notices.**
    Use these to supplement result-page status and preserve post-election changes.

---

## 8. Supporting Research Artifacts

| Artifact                                                 | Role                                                                                    |
| -------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `MD-Election_Research.md`                                | Original March/July research used as the baseline                                       |
| `elections.maryland.gov_Archive [26-07-21 12-25-03].har` | July 21 browser capture supporting live-result transport and file-behavior observations |

The HAR should be preserved with the project. Before implementation, replay its important requests or capture a fresh election-period session so status codes, cache headers, request sequences, and response formats can be documented independently.

---

**Scope note (2026-08-04):** Full Core promotion for MD is scoped to federal + state legislative + state executive race creation (same convention as NC/KY/VT). Ballot measures and municipal results are confirmed sources per Rank 5/8 above and remain nice-to-have, not required for this wave — do not let them block the Stage 1 candidate-list loader.

## 9. Final Assessment

Maryland should be classified as **near-full core coverage** for CivicMirror.

```text
Election creation:             READY
Federal/state race creation:   READY
Local race creation:           READY for SBE-administered ballot; municipal enhanced
Candidate filings:             READY
Ballot measures:               READY, with qualification/version tracking
Live results:                  READY through HTML scraping
Certified results:             READY through structured CSV
Historical backfill:           STRONG, format-aware work required
Special elections:             READY for source indexing
Municipal results:             ENHANCED / document extraction
Campaign finance:              SOURCE CONFIRMED / transport research pending
District and precinct joins:   READY for references / GIS validation pending
Cast-vote records:             OPTIONAL / cycle-dependent
Certification and audits:      PARTIAL / event index pending
```

The recommended first production adapter is the structured election-data CSV loader. Candidate CSVs and ballot-question HTML should follow. The live HTML adapter is practical but should remain separate from certified-result reconciliation. Municipal documents, campaign finance, GIS boundaries, and CVRs are valuable enhanced lanes and should not delay core statewide ingestion.
