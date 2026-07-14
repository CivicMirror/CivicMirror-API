# Tennessee Election System — Research Notes

**State:** Tennessee (TN)  
**Primary operator:** Tennessee Secretary of State, Division of Elections  
**Research updated:** July 14, 2026  
**Core coverage target:** Federal and state elections, races, candidates, statewide ballot measures, unofficial/live results when technically available, and certified results. Local elections and local measures are enhanced coverage.

---

## Coverage Status

| Stage | Status | Recommended source | Notes |
|---|---|---|---|
| Stage 1 — Election Creation | ✅ Strong | Tennessee SOS Elections Calendar | Statewide elections, deadlines, and a 327-row local-election schedule are directly present in HTML tables. |
| Stage 1 — Race Creation | ✅ Strong for federal/state | Tennessee SOS Candidate Lists, Excel downloads | Qualified 2026 candidate workbooks are published by office group. Local candidates are not included. |
| Stage 1 — Ballot Measures | ⚠️ Partial | Tennessee SOS Proposed Constitutional Amendments | A dedicated statewide-amendments page exists. Local referendum coverage still appears decentralized. |
| Stage 2 — Live/Unofficial Results | ⚠️ Dashboard confirmed; feed unknown | `www.elections.tn.gov` | A genuine statewide election-night dashboard exists, but the supplied offseason HAR contains no result-data request. |
| Stage 2 — Certified Results | ✅ Strong | Tennessee SOS Historical Election Results | Recent elections include precinct XLSX files plus office, county, and precinct PDFs. |
| Turnout / Registration | ✅ Supplemental | Tennessee SOS Election Statistics | Useful context and quality checks, but not contest-result data. |

---

## Executive Finding

Tennessee is one of the stronger states reviewed so far.

The state publishes:

1. a structured statewide and local election calendar;
2. qualified federal and state candidate lists in Excel;
3. a state-hosted election-night reporting dashboard;
4. certified results at office, county, and precinct levels;
5. precinct-level result spreadsheets for many recent elections;
6. text-based PDFs that are suitable as a fallback parser source.

The main unresolved issue is not whether Tennessee offers live results. It does. The unresolved issue is **how the active dashboard obtains its data**.

The July 14, 2026 capture occurred while no election was active. The dashboard returned an offseason placeholder and made no contest-data request. A second HAR must be captured while test or live results are loaded.

---

# 1. Official Sources

## Elections landing page

```text
https://sos.tn.gov/elections
```

Provides links to:

- the 2026 elections calendar;
- qualified candidate lists;
- proposed constitutional amendments;
- county election commissions;
- election statistics;
- historical election results;
- GoVoteTN voter services.

## Elections calendar

```text
https://sos.tn.gov/elections/calendar
```

## Candidate lists

```text
https://sos.tn.gov/elections/2026-candidate-lists
```

## Certified and historical results

```text
https://sos.tn.gov/elections/results
```

## Election-night reporting

```text
https://www.elections.tn.gov/
```

## Election statistics

```text
https://sos.tn.gov/elections/statistics
```

## Proposed constitutional amendments

```text
https://sos.tn.gov/elections/announcements/2026-proposed-constitutional-amendments
```

---

# 2. Election Creation — Strong Official Source

The 2026 elections calendar is not merely prose. The supplied HAR shows three HTML tables:

1. August election deadlines;
2. November election deadlines;
3. the 2026 local-election schedule.

The local table contains **327 election rows**, excluding its header.

## August 6, 2026 election

The page describes:

- primary elections for Governor;
- U.S. Senate;
- U.S. House;
- Tennessee Senate odd-numbered districts;
- Tennessee House;
- Republican State Executive Committee;
- Democratic State Executive Committee;
- general elections for vacant state judicial offices;
- applicable county offices.

Published deadlines include:

| Deadline | Date |
|---|---|
| Voter-registration deadline | July 7, 2026 |
| Early voting | July 17–August 1, 2026 |
| Absentee-ballot request deadline | July 27, 2026 |

## November 3, 2026 election

The page identifies the state and federal general election and explains that federal and state candidates qualify through the August-election process. Municipal races held with the November election follow the separate dates shown on the page.

Published deadlines include:

| Deadline | Date |
|---|---|
| First day to pick up petitions | June 22, 2026 |
| Qualifying deadline | August 20, 2026 at noon |
| Withdrawal deadline | August 27, 2026 at noon |
| Voter-registration deadline | October 5, 2026 |
| Early voting | October 14–29, 2026 |
| Absentee-ballot request deadline | October 24, 2026 |

## Local-election schedule

The local table uses consistent columns:

```text
County
Jurisdiction
Date
```

Examples include municipalities, school-board primaries, judicial elections, annexation questions, and special school districts.

### Proposed adapter: `TN-Elections`

1. Download the calendar HTML.
2. Parse the statewide election headings and descriptive text.
3. Parse deadline tables separately from election records.
4. Parse each local-election row into:
   - county or counties;
   - jurisdiction;
   - election date;
   - inferred election subtype;
   - official source URL.
5. Reconcile statewide elections against Google Civic as a secondary check.
6. Store page-retrieval time and source hash.

### Assessment

Stage 1 election creation should no longer depend primarily on Google Civic. The Tennessee SOS calendar is the better authoritative source.

---

# 3. Race and Candidate Creation — Official Excel Files

The candidate-list page publishes direct PDF and Excel downloads for qualified candidates.

## 2026 Excel sources

```text
Governor_2026.xlsx
USSenate_2026.xlsx
USHouseCandidates_2026.xlsx
TNSenate_2026.xlsx
TNHouse_2026.xlsx
TNGOPSEC_Filed_2026-03-24.xlsx
TNDPSEC_Filed_2026-03-24.xlsx
```

The files are hosted under:

```text
https://sos-prod.tnsosgovfiles.com/s3fs-public/document/
```

The page explicitly says its lists exclude candidates who:

- did not file;
- timely withdrew;
- lacked enough valid signatures;
- were determined not bona fide by a political party;
- otherwise failed to qualify.

That makes the page a strong source of ballot-qualified candidates rather than an unfiltered filing log.

## Coverage

Strong core coverage:

- Governor;
- U.S. Senate;
- U.S. House;
- Tennessee Senate;
- Tennessee House.

Additional coverage:

- Republican State Executive Committee;
- Democratic State Executive Committee.

Not covered by these workbooks:

- most county and municipal candidates;
- local school-board candidates;
- local judicial candidates unless separately published;
- candidate biographies and campaign contacts.

## Proposed adapter: `TN-Candidates`

1. Scrape the candidate-list page for the current workbook URLs.
2. Prefer Excel over PDF.
3. Preserve the workbook filename, retrieval time, checksum, and page source.
4. Normalize candidate records into:
   - office;
   - district;
   - candidate name;
   - party;
   - ballot status;
   - source workbook.
5. Create races from the unique office/district combinations.
6. Reconcile workbook races against the statewide election description.
7. Flag an expected race when no qualified candidate is listed rather than silently dropping it.

## Remaining validation

The candidate workbooks were linked but not opened in the supplied HAR. A focused capture should download each workbook so that column names, merged cells, sheet names, and update behavior can be documented.

### Assessment

Stage 1 federal and state race creation can be moved from “untested” to **strong official source available**.

---

# 4. Statewide Ballot Measures

The SOS elections site prominently links to a dedicated page for:

```text
2026 Proposed Constitutional Amendments
```

This is a better starting point for Tennessee statewide measures than relying exclusively on Ballotpedia.

## Proposed adapter: `TN-Measures`

1. Parse the official amendments page.
2. Capture:
   - amendment number or resolution identifier;
   - official title;
   - full ballot question;
   - explanatory summary;
   - constitutional article/section;
   - election date;
   - qualification status.
3. Reconcile the amendment with the Tennessee General Assembly resolution.
4. Treat local referenda as enhanced coverage unless a centralized source is identified.

## Limitation

The supplied HAR did not open the amendments page, so its current field structure and whether it links to PDFs or legislative resolutions remain to be captured.

---

# 5. Certified and Historical Results

The historical-results page is a large static index of official files.

## Coverage observed

The page contains election sections from **1996 through 2026** and includes regular, primary, judicial, and special elections.

The captured page contained:

- **558 downloadable result-document links**;
- **530 PDF links**;
- **27 XLSX links**;
- **1 legacy XLS link**.

## Recent structured spreadsheets

Examples include:

```text
20251202AllbyPrecinct.xlsx
20251007AllbyPrecinct.xlsx
20241105AllbyPrecinct.xlsx
20240801AllbyPrecinct.xlsx
20240305AllbyPrecinct.xlsx
20221108AllbyPrecinct.xlsx
20220804ResultsbyPrecinct.xlsx
Nov2020PrecinctDetail.xlsx
Aug2020PrecinctDetail.xlsx
March2020Results.xlsx
```

This confirms that Tennessee has a repeatable machine-readable certified-results path for many recent statewide elections.

## Recent result groupings

### May 5, 2026 State Judicial Primary

- Republican by county PDF;
- Republican by precinct PDF;
- Democratic by county PDF;
- Democratic by precinct PDF.

No spreadsheet was linked for this election in the captured page.

### December 2, 2025 Congressional District 7 Special General Election

- results by office PDF;
- results by county PDF;
- results by precinct PDF;
- precinct spreadsheet.

### November 5, 2024 General Election

- results by office PDF;
- results by county PDF;
- results by precinct PDF;
- precinct spreadsheet.

### August 1, 2024

- precinct spreadsheet;
- Republican primary by county and precinct;
- Democratic primary by county and precinct;
- state general by county and precinct;
- judicial retention by county and precinct.

### March 5, 2024

- precinct spreadsheet;
- presidential preference results at statewide, county, and precinct levels;
- judicial results at office, county, and precinct levels.

---

# 6. PDF Result Format and Parseability

Three captured official PDFs were extracted and inspected:

```text
20260506_RepublicanPrimarybyCounty.pdf
20260506_RepublicanPrimarybyPrecinct.pdf
20251202GeneralbyOffice.pdf
```

They are text-based PDFs, not image scans.

## Common structure

The files consistently contain:

- state name;
- election date;
- election type;
- contest title;
- numbered candidate list;
- party where applicable;
- county or precinct rows;
- district/county/total-vote rows;
- document-generation date;
- page number.

The text layer extracts cleanly with layout preservation.

## Example logical structure

```text
Contest
  Candidate 1
  Candidate 2

County or precinct       Candidate 1 votes   Candidate 2 votes
...
DISTRICT TOTALS          total               total
```

## Parser implications

A PDF parser is viable as a fallback when an XLSX file is not published. It should not rely only on fixed horizontal coordinates because:

- one-candidate and multi-candidate contests use different column layouts;
- long contest names wrap;
- some reports group multiple counties;
- precinct pages continue the same contest across page boundaries;
- “No Candidate Qualified” can appear as a candidate-like row.

### Recommended strategy

1. Prefer spreadsheet.
2. Use text extraction with layout preservation for PDF fallback.
3. Identify report header and election metadata.
4. Identify contest boundaries by large title lines and candidate-number blocks.
5. infer candidate columns from the numbered candidate list.
6. parse county/precinct rows until a total marker or new contest.
7. validate:
   - county totals against precinct sums;
   - district totals against county sums;
   - office totals against lower-level files.
8. retain the original source document and parser version.

---

# 7. Election-Night Reporting Dashboard

## Confirmed site

```text
https://www.elections.tn.gov/
```

The supplied HAR confirms:

- page title: `Election Night Reporting Dashboard`;
- heading: `Tennessee Unofficial Election Results`;
- official past results link back to the SOS historical page;
- public access without authentication;
- state-hosted domain.

## Current offseason behavior

The July 14, 2026 capture contained only **38 requests**.

It loaded:

- one server-rendered HTML page;
- one custom stylesheet;
- jQuery;
- Bootstrap;
- images;
- analytics;
- Dynatrace monitoring.

It did **not** load:

- contest JSON;
- county-result JSON;
- a result API call;
- a custom election-dashboard JavaScript bundle;
- an iframe from an election vendor;
- periodic polling requests.

The page displayed an empty-results placeholder because no live election was active.

## Platform observations

Response headers identify:

```text
Apache 2.4
PHP 8.1
Amazon CloudFront
No-store / no-cache response policy
```

No outside election-night vendor was identifiable from this capture.

## Evidence of active dashboard capabilities

Although the inactive page had no data calls, its stylesheet contains classes and IDs for:

- county reporting status;
- final-unofficial status;
- county-status tables;
- county result banners;
- statewide office charts;
- a Tennessee county map;
- selected-county highlighting;
- precinct headings;
- county breakdown links;
- result filtering and sorting;
- office search;
- favorite contests;
- updated timestamp;
- testing alerts;
- manual refresh;
- grid and column views.

This strongly indicates that the active site is a substantial statewide reporting application rather than a simple redirect page.

## Important conclusion

Tennessee **does offer statewide live/unofficial results**.

However, the current research has not yet established whether the live system uses:

- a public JSON API;
- server-rendered refreshes;
- form POSTs returning HTML;
- static JSON files;
- database-backed PHP endpoints;
- another transport activated only during election periods.

Therefore:

```text
Live results availability: CONFIRMED
Public structured feed: NOT YET CONFIRMED
Adapter readiness: BLOCKED ON ACTIVE-ELECTION HAR
```

---

# 8. Required Active-Election Capture

The next major statewide reporting opportunity is **August 6, 2026**.

## Begin checking before election day

Because the CSS includes a testing-alert design, the state may expose test results before election day.

Recommended checks:

- July 27, 2026;
- July 31, 2026;
- August 3–5, 2026;
- August 6, 2026 before polls close;
- August 6, 2026 after results begin posting.

## Browser capture procedure

1. Open Developer Tools before loading the dashboard.
2. Select Network.
3. Enable **Preserve log**.
4. Disable browser cache.
5. Load `https://www.elections.tn.gov/`.
6. Wait at least two minutes.
7. Record any automatic refresh cycle.
8. Use every available function:
   - statewide results;
   - office filter;
   - sort control;
   - county-status report;
   - county map;
   - one selected county;
   - precinct breakdown;
   - contest search;
   - favorite contest;
   - grid/column view;
   - manual refresh.
9. Wait through two result updates if possible.
10. Export **HAR with content**.
11. Save the full page source.
12. Save every custom JavaScript file separately.
13. Note the displayed “last updated” timestamps.

## What to inspect in the next HAR

Search for:

```text
.json
.php
/api/
results
county
precinct
office
contest
status
refresh
timestamp
ajax
fetch
xhr
```

For each candidate endpoint, document:

- method;
- request parameters;
- cookies;
- required headers;
- response type;
- election identifier;
- county/office identifiers;
- cache behavior;
- refresh interval;
- test/live/final status field;
- whether old election identifiers remain accessible.

---

# 9. Proposed Tennessee Adapter Layout

```text
TN-Elections
  SOS statewide election calendar
  SOS local-election HTML table

TN-Candidates
  Official qualified-candidate XLSX files

TN-Measures
  Official proposed constitutional amendments
  Tennessee General Assembly reconciliation

TN-ResultsLive
  elections.tn.gov
  Endpoint pending active-election capture

TN-ResultsCertified
  Historical-results index
  Precinct XLSX preferred
  Office/county/precinct PDF fallback

TN-Statistics
  Registration, turnout, and early-voting reports
```

---

# 10. Recommended Implementation Order

1. **Build `TN-Elections`.**
   The calendar is already structured and should be straightforward.

2. **Download and inspect all seven 2026 candidate workbooks.**
   Define the workbook schema and create the core federal/state races.

3. **Build `TN-Candidates`.**
   Poll the candidate page and ingest changed workbooks by checksum.

4. **Build the historical-results document indexer.**
   Discover elections and their available office/county/precinct files.

5. **Implement certified XLSX ingestion.**
   Start with the November 5, 2024 or December 2, 2025 spreadsheet.

6. **Implement the PDF fallback parser.**
   Use the May 5, 2026 judicial-primary PDFs as the initial test case.

7. **Capture the live dashboard during testing or on August 6, 2026.**

8. **Build `TN-ResultsLive` only after identifying the active transport.**

9. **Add statewide constitutional amendments.**

10. **Treat county and municipal candidate/measure coverage as enhanced work.**

---

# 11. Risks and Caveats

## Live endpoint only appears during active reporting

The largest risk is that the useful scripts and data routes are absent outside an election window. The current HAR cannot prove the active endpoint design.

## Candidate workbook replacement

The candidate page may replace files in place while retaining the same URL. Polling must use content checksums or object metadata rather than URL changes alone.

## Spreadsheet schema drift

Recent election spreadsheets may not share identical columns with 2008–2020 files. Build schema adapters by format generation rather than assuming one universal workbook.

## PDF-only elections

Special and judicial elections may publish PDFs without spreadsheets. Core ingestion needs a PDF fallback.

## Local coverage fragmentation

The statewide calendar lists local elections, but candidate and measure details may remain with the 95 county election commissions.

## Duplicate result representations

One election may have office, county, precinct, party-primary, general, judicial, and amendment files. The indexer must map these to one election without double-counting votes.

---

# 12. Final Assessment

| Capability | Assessment |
|---|---|
| Election creation | Strong official HTML source |
| Federal/state race creation | Strong official Excel source |
| Qualified federal/state candidates | Strong |
| Local candidates | Incomplete / decentralized |
| Statewide ballot measures | Official page exists; parser pending |
| Local measures | Incomplete / decentralized |
| Statewide live-results UI | Confirmed |
| Public live API/feed | Unknown until active capture |
| Certified office results | Strong |
| Certified county results | Strong |
| Certified precinct results | Strong, with many XLSX files |
| Historical backfill | Extensive, but mixed formats |
| Turnout/registration | Strong supplemental source |

**Recommended status:** Tennessee should move from “no adapter” to **high-priority implementation candidate**.

Stage 1 federal/state coverage is already practical from official sources. Certified Stage 2 ingestion is also practical because recent precinct spreadsheets are published and the PDF fallback is parseable. Live Stage 2 should remain marked **research pending** until the August 2026 dashboard capture reveals its active data transport.
