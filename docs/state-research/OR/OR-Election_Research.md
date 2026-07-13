# Oregon Election System — Research Notes

**State:** Oregon (OR)
**Primary operator:** Oregon Secretary of State, Elections Division
**Research updated:** July 13, 2026
**CivicDeNovo/CivicMirror coverage target:** Federal and state offices are core coverage. Local offices, local measures, precinct reporting, and historical backfill are enhanced coverage.

---

## Coverage Status

| Stage | Status | Recommended source | Notes |
|---|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Oregon SOS Upcoming Elections + election dates | The official site identifies the current statewide election and key dates. Google Civic can remain a secondary source. |
| Stage 1 — Race Creation | ✅ Implemented for core skeleton/candidates | Open Offices PDF + ORESTAR Candidate Filing Search | The adapter parses open offices and ORESTAR candidate filings. Real-source validation is still required before declaring production completeness. |
| Stage 1 — Ballot Measures | ⚠️ Local measures implemented; statewide incomplete | ORESTAR Local Measures Search | Local measures ingest is implemented. Statewide initiative/referral pages should be researched separately. |
| Stage 2 — Certified Results | ⚠️ Partially implemented | Oregon SOS SharePoint History index + Oregon Records archive | SharePoint/history discovery and CSV/TSV/TXT/ZIP/XLSX parsing are implemented. PDF and legacy XLS parsing remain unsupported. |
| Stage 2 — Live/Unofficial Results | ❌ Statewide feed not available | County election sites only | Oregon counties publish unofficial election-night results in batches, but no persistent, public, centralized SOS live-results dashboard, REST API, or structured statewide feed has been identified. |
| Turnout / Ballot Returns | ✅ Available, supplemental | Oregon Open Data Socrata dataset `rxzj-n3di` | Daily ballot-return statistics; useful for turnout tracking, but it is not contest-result data. |

---

## Executive Finding

Oregon is more automatable than the original notes suggested, but its useful sources are split across several systems:

1. **Oregon SOS SharePoint** provides an anonymous, structured election-history index through SOAP.
2. **ORESTAR** exposes searchable candidate filings and local measures through server-rendered web forms.
3. **Oregon Records Management** stores certified result documents and precinct files.
4. **Oregon Open Data / Socrata** provides a public ballot-return dataset with JSON and CSV downloads.
5. **Oregon Legislature OData** provides current legislator and legislative-session data, useful for incumbent enrichment but not election results.

A practical Oregon implementation should use multiple small adapters rather than one scraper.

### Live validation notes

Read-only validation on July 13, 2026 found:

- The current-election page splits `General Election` and `November 3, 2026` across separate lines and uses non-breaking spaces; the parser now handles this and ignores non-election deadline dates.
- The open-offices PDF uses office section headings followed by district rows; the parser now extracts 83 core federal/state races from the live 2026 general PDF.
- ORESTAR CSRF now requires loading `/orestar/JavaScriptServlet` with `GET`, then fetching the token via `POST` with `FETCH-CSRF-TOKEN: 1`; candidate and local-measure searches parse live pages.
- ORESTAR candidate pagination currently returns 165 rows with a one-row page overlap; the task de-duplicates filing identities across pages.
- ORESTAR local-measure pagination currently returns 99 rows across two pages after using `searchButtonName=next`.
- Socrata ballot-return JSON remains accessible and parseable.
- Anonymous SharePoint SOAP calls to the SOS history list currently return `401 Unauthorized`; the result adapter now returns a no-data adapter result instead of failing the whole poll when the history index is unavailable. Direct `or_results_url` metadata remains the reliable path for structured result files.

---

# 1. Election Calendar and Election Creation

## Official current-election page

- https://sos.oregon.gov/elections/Pages/current-election.aspx
- https://sos.oregon.gov/elections/Pages/election-dates.aspx

The current page identifies the **November 3, 2026 General Election**. The supplied capture also contained primary-election registration, mailing, election-day, and certification dates beneath the general-election heading, so the adapter should not assume every date block belongs to the heading immediately above it.

### Recommended Stage 1 behavior

Create an election from:

- election name/type;
- election date;
- registration deadline;
- first ballot-mail date;
- certification date;
- source URL and retrieval timestamp.

Google Civic may remain a fallback or cross-check, but the Oregon SOS source should be treated as authoritative for Oregon-specific dates.

---

# 2. Race and Candidate Discovery

## Open offices PDF

- https://sos.oregon.gov/elections/Documents/open-offices-general-election.pdf

The PDF was revised July 2, 2026 and lists offices for the November 3, 2026 General Election. Core federal/state coverage includes:

- U.S. Senator;
- U.S. Representative, Districts 1–6;
- Governor;
- the state senate districts on the 2026 cycle;
- State Representative, Districts 1–60;
- specified nonpartisan judicial and district-attorney vacancies.

This PDF is a strong **race skeleton** source: it can create expected contests before the final candidate list is complete.

## ORESTAR Candidate Filing Search

- https://secure.sos.state.or.us/orestar/CFSearchPage.do

The public search currently exposes filters for:

- candidate name;
- election year and election;
- office;
- district, position, county, or city;
- party affiliation;
- filing method;
- filing-date range;
- withdrawal-date range;
- disqualified candidates.

The 2026 form includes federal offices, statewide offices, state representative, state senator, courts, district attorneys, and other state-level offices.

### Proposed adapter: `OR-Candidates`

1. Load the candidate-search form and preserve cookies and hidden fields.
2. Submit one election-wide search, or search by office if the result set is limited.
3. Parse candidate filing rows and detail links.
4. Normalize:
   - office;
   - district/position;
   - candidate name;
   - party;
   - filing method;
   - filing date;
   - withdrawal date;
   - qualification/disqualification status.
5. Reconcile candidates against races created from the open-offices PDF.
6. Store the official filing URL and retrieval timestamp.

**Status:** source confirmed; form submission and result-page structure still require a focused HAR capture.

---

# 3. Ballot Measures

## ORESTAR Local Measures Search

- https://secure.sos.state.or.us/orestar/gotoLocalMeasSearch.do
- https://sos.oregon.gov/elections/Pages/Candidate-Filings-Local-Measures.aspx

The public search supports:

- year, including 2026;
- election;
- county, covering all 36 Oregon counties.

### Proposed adapter: `OR-Measures`

Use this as an enhanced-coverage source for local measures. For core coverage, separately inspect Oregon's initiative, referendum, referral, and voters' pamphlet sources for statewide measures.

**Status:** search page confirmed; result fields and submission parameters still need a HAR capture.

---

# 4. Election History Index — Anonymous SharePoint SOAP

The supplied HAR reveals that the Oregon SOS historical-data page is backed by a public SharePoint list.

## Page

- https://sos.oregon.gov/elections/Pages/historical-data.aspx

## SOAP endpoint

```text
POST https://sos.oregon.gov/elections/_vti_bin/Lists.asmx
Content-Type: text/xml; charset=utf-8
```

## List and view

- List name: `History`
- Public view GUID: `{B5E14970-1EE5-4BCB-8D5E-D2089E612F1C}`
- Sort: `Election Date` descending
- Row limit: 300

## View fields

```text
Election_x0020_Date
Results
Voter_x0020_Registration_x0020_a
Pamphlets
Election_x0020_Type
```

## Anonymous request

```xml
<soap:Envelope
  xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <GetListItems xmlns="http://schemas.microsoft.com/sharepoint/soap/">
      <listName>History</listName>
      <viewName>{B5E14970-1EE5-4BCB-8D5E-D2089E612F1C}</viewName>
      <queryOptions>
        <QueryOptions>
          <IncludeAttachmentUrls>TRUE</IncludeAttachmentUrls>
        </QueryOptions>
      </queryOptions>
    </GetListItems>
  </soap:Body>
</soap:Envelope>
```

## HAR observations

The response returned **133 election rows**, spanning June 2, 1902 through May 19, 2026:

- 53 General elections;
- 51 Primary elections;
- 29 Special elections.

Each row includes an election date/type and rich-HTML fields containing links to:

- official results;
- ballot-return or voter-registration material;
- voters' pamphlets.

The newest result row points to the Oregon Records system and identifies a document titled **“2026 May Primary Election Official Results.PDF.”**

### Value to the project

This endpoint is a reliable, machine-readable **document index** and election-discovery source. It is not itself a contest-results API.

Because historical backfill is not required for core completion, the initial implementation can use the list to discover current/future certified documents and save new results going forward.

### Stability risk

SharePoint list names are usually stable, but view GUIDs can change. The adapter should:

1. call `Views.asmx/GetViewCollection` for the `History` list;
2. locate the view named `public`;
3. use the returned GUID;
4. fall back to the known GUID only when discovery fails.

---

# 5. Certified Results and Precinct Data

Most `Results` links in the SharePoint list point to:

```text
https://records.sos.state.or.us/
```

Recent examples use either:

```text
/ORSOSWebDrawer/Recordhtml/<record-id>
```

or:

```text
/ORSOSCMSearch/Search/RecordViewer.aspx?uri=<record-id>
```

The 2026 result viewer exposes a PDF document, not a structured contest JSON response.

The historical-data page also links to:

- a 2024 General Election precinct-level-results record search;
- historical precinct data;
- county election offices for data not held centrally.

## Proposed `OR-Results` v1

Use a **certified-results document adapter**, not a live-results scraper:

1. Poll the SharePoint `History` list for the target election.
2. Detect a new or modified official-results record.
3. Follow the Records-system link.
4. Resolve and download the underlying PDF, spreadsheet, ZIP, or other attachment.
5. Prefer machine-readable precinct files when available.
6. Parse contest/candidate totals and map them to existing races.
7. mark results certified only when the source document is explicitly official/final.
8. retain the original file, source URL, retrieval time, checksum, and parser version.

## Stage 2 limitation

No live or semi-live structured statewide results endpoint was observed. Oregon counties publish unofficial results in batches beginning on election night, and statewide live displays from AP/news organizations appear to aggregate county reports. For CivicMirror's Oregon core path, live results should be treated as out of scope for now. Future enhanced coverage could investigate county-level unofficial result pages individually, but the primary Oregon adapter should focus on SOS certified results and historical documents.

---

# 6. Ballot Count History — Public Socrata API

## Dataset

- Landing page: https://data.oregon.gov/Administrative/Ballot-Count-History/rxzj-n3di
- Dataset ID: `rxzj-n3di`
- Publisher: Oregon Secretary of State, Elections Division

The catalog describes it as daily ballot returns in the two weeks leading up to an election. It is useful for turnout and ballot-return monitoring, not candidate or measure results.

## Public downloads

```text
JSON:
https://data.oregon.gov/api/views/rxzj-n3di/rows.json?accessType=DOWNLOAD

CSV:
https://data.oregon.gov/api/views/rxzj-n3di/rows.csv?accessType=DOWNLOAD

Column metadata:
https://data.oregon.gov/api/views/rxzj-n3di/columns.json
```

Metadata observed July 13, 2026:

- 406 rows;
- 32 elections represented;
- coverage through the November 5, 2024 General Election;
- dataset last updated May 29, 2025.

Important fields include:

- `election`;
- `date`;
- `number_of_ballots_returned`;
- daily-return percentages;
- cumulative ballot-return totals and percentages.

### Proposed adapter: `OR-Turnout`

Optional enhanced adapter for turnout visualizations and election-status context. Do not map these rows to candidate results.

---

# 7. County Elections Officials — Structured Directory

The HAR also revealed a second anonymous SharePoint list:

- List: `County Officials`
- Public view: `{A9774A92-B879-4219-B62B-BE69E2FDEC56}`
- Item count: 36

Fields include:

- county;
- elections website;
- contact;
- address;
- mailing address;
- phone;
- fax;
- email.

This is useful for source discovery and county-level fallback ingestion, but county/local coverage remains enhanced rather than core.

---

# 8. Oregon Legislature Open Data

- https://www.oregonlegislature.gov/citizen_engagement/Pages/data.aspx
- Base API: https://api.oregonlegislature.gov/odata
- Metadata: https://api.oregonlegislature.gov/odata/$metadata

The legislature publishes current measure, committee, session, and legislator data through OData.

### Recommended use

Use this source for:

- current state legislative incumbents;
- chamber and district enrichment;
- legislator identity matching;
- legislative history.

Do not treat legislative “measures” as election ballot measures without explicit type filtering and reconciliation.

---

# 9. Recommended Oregon Adapter Layout

```text
OR-Elections
  Official current-election and election-date pages

OR-RaceSkeleton
  Open Offices PDF

OR-Candidates
  ORESTAR Candidate Filing Search

OR-Measures
  ORESTAR Local Measures Search
  Statewide initiative/referral sources to be added

OR-Results
  SharePoint History index
  Oregon Records certified-result documents
  Precinct spreadsheets/ZIP files when available

OR-Turnout
  Socrata Ballot Count History dataset

OR-Incumbents
  Oregon Legislature OData
```

---

# 10. Recommended Implementation Order

1. **Build `OR-Elections` and `OR-RaceSkeleton`.**
   This should provide dependable election and federal/state race creation.

2. **Capture and automate ORESTAR candidate searches.**
   This is the key remaining Stage 1 task.

3. **Capture ORESTAR local-measure result pages.**
   Treat local coverage as enhanced.

4. **Build the SharePoint history-index client.**
   Use it for official-document discovery rather than historical backfill.

5. **Resolve one recent Oregon Records attachment end to end.**
   Prefer the 2024 precinct data or 2026 primary official result.

6. **Write a certified-result parser against actual downloaded files.**

7. **Perform an election-night HAR capture.**
   Determine whether Oregon exposes a separate live reporting vendor or endpoint before certifying Stage 2 live coverage.

---

# 11. Required Follow-up Capture

For the next HAR, perform these actions before saving:

1. In ORESTAR Candidate Filing Search:
   - select 2026;
   - select the General Election;
   - run an all-office search;
   - open one candidate detail record.

2. In ORESTAR Local Measures:
   - select 2026;
   - select an election;
   - run an all-county search;
   - open one measure detail.

3. In Election Results & History:
   - open the 2026 May Primary official result;
   - download the PDF;
   - open the 2024 precinct-data search;
   - download every available CSV/XLSX/ZIP attachment.

4. Preserve response bodies and do not clear cookies before exporting the HAR.

---

# 12. Local Scheduling

The production deployment is local-only and should not rely on GCP or Cloud Scheduler for Oregon ingestion. Run the Oregon sync through the local Django management command from `backend/`:

```bash
python manage.py trigger_internal_task sync_or_sos
```

This command enqueues the same Celery task as the internal HTTP endpoint and uses the shared Redis idempotency lock `sync_or_sos`, so it is safe to invoke from cron/systemd on the normal daily cadence. The task fans out from election discovery to the supported Oregon child syncs when the election metadata includes a known ORESTAR election ID.

Example cron entry:

```cron
15 3 * * * cd /path/to/CivicMirror-API/backend && /path/to/venv/bin/python manage.py trigger_internal_task sync_or_sos
```

---

# 13. Current Assessment

| Capability | Assessment |
|---|---|
| Election creation | Strong |
| Federal/state race skeleton | Strong; implemented, needs live validation |
| Candidate discovery | Implemented via ORESTAR, needs live validation |
| Statewide ballot measures | Incomplete |
| Local measures | Implemented via ORESTAR, needs live validation |
| Certified statewide results | Implemented for structured files; PDF parser still required |
| Live results | No statewide public feed identified; county-level only, future enhanced coverage |
| Precinct results | Available historically; download path needs capture |
| Turnout data | Strong supplemental API |
| Incumbent enrichment | Strong OData source |

**Recommended status:** Oregon should move from “no adapter / unknown” to **adapter implemented, pending live-source validation and remaining PDF/statewide-measure work**. Full core coverage should not be declared until ORESTAR candidate ingestion and at least one official result file are successfully parsed end to end against live Oregon sources.
