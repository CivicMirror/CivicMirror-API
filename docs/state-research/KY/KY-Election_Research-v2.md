# Kentucky Election Results — Research Notes

**Version:** 2  
**Original research:** March 4, 2026  
**Version 1 updated:** May 31, 2026  
**Version 2 updated:** July 18, 2026  
**Research target:** Kentucky election creation, live/unofficial results ingestion, and certified-result reconciliation  
**Primary official sources:** Kentucky State Board of Elections and Kentucky Secretary of State

---

## Coverage Status

| Stage | Status | Recommended source | Notes |
|---|---:|---|---|
| Stage 1 — Election Creation | ✅ Available | Kentucky `Elections` XML, supplemented by Google Civic Information | The official XML provides election ID, name, type, and date. |
| Stage 1 — Race Creation | ✅ Path identified | Kentucky `Contests`, `Candidates`, `PoliticalParties`, and `GeopoliticalUnits` XML | The official datasets provide stable IDs and jurisdiction relationships. |
| Stage 2 — Live Results Ingestion | ✅ Available with operational caution | Kentucky `/liveresults/Data` XML downloads | Officially documented XML files; current results are refreshed every two minutes, but CivicMirror does not need to poll at that cadence. Do not scrape the rendered HTML pages. |
| Stage 2 — Certified Results | ✅ Available | `elect.ky.gov` certification and recap files | Use as the authoritative final comparison baseline. |
| Historical normalization | ✅ Available, may lag | OpenElections Kentucky | Useful standardized CSVs, but volunteer-maintained and not a guaranteed live source. |

---

## Executive Conclusion

Kentucky exposes **two different interfaces on the `vrsws.sos.ky.gov` host**, and they should not be treated as the same source:

1. **Rendered Election Night Reporting website** — `/liveresults` and `/liveresults?id={gpu_id}`
   - Server-rendered HTML intended for interactive browser use.
   - Protected by Akamai browser/bot controls.
   - County and precinct navigation reloads the complete page.
   - Not suitable as the primary automated ingestion interface.

2. **Documented data-download website** — `/liveresults/Data`
   - Officially advertises downloadable XML datasets.
   - Provides election, party, jurisdiction, contest, candidate, and current-results data.
   - States that the Current Results data file refreshes every two minutes.
   - This is the preferred source for live, unofficial Kentucky results.

The Version 1 conclusion that the entire `vrsws` system was off-limits for ingestion was too broad. The corrected recommendation is:

> **Do not scrape Kentucky's rendered election-results HTML. Use the separately documented XML download interface, follow its published update interval, and reconcile the live unofficial records against certified files from `elect.ky.gov`.**

---

## Source Architecture

Kentucky currently has four relevant result layers.

### 1. Kentucky official XML data downloads

**Landing page:**  
https://vrsws.sos.ky.gov/liveresults/Data

**Documentation:**  
https://vrsws.sos.ky.gov/liveresults/Documentation/Data%20Website%20Guide.pdf

This is the best available source for structured live/unofficial data.

### 2. Kentucky rendered Election Night Reporting website

**Statewide/browser interface:**  
https://vrsws.sos.ky.gov/liveresults

This interface is useful for manual verification, but the attached HAR shows that it returns complete server-rendered HTML documents rather than calling a hidden JSON results API during ordinary statewide, county, and precinct navigation.

### 3. Kentucky certified results and recap files

**Results archive:**  
https://elect.ky.gov/results/

**2026 results page:**  
https://elect.ky.gov/results/2020-2029/Pages/2026.aspx

Use these files after certification as the authoritative final source.

### 4. OpenElections Kentucky

**Normalized result data:**  
https://github.com/openelections/openelections-data-ky

**Original source files:**  
https://github.com/openelections/openelections-sources-ky

OpenElections is valuable for historical normalization, but recent elections may not appear immediately.

---

## Official Kentucky XML Data Interface

The `/liveresults/Data` page identifies the following downloadable datasets for the 2026 primary:

```text
https://vrsws.sos.ky.gov/liveresults/Data/CurrentResults
https://vrsws.sos.ky.gov/liveresults/Data/CurrentResultsExcludeLocal
https://vrsws.sos.ky.gov/liveresults/Data/Elections
https://vrsws.sos.ky.gov/liveresults/Data/PoliticalParties
https://vrsws.sos.ky.gov/liveresults/Data/GeopoliticalUnits
https://vrsws.sos.ky.gov/liveresults/Data/Contests
https://vrsws.sos.ky.gov/liveresults/Data/Candidates
```

The official Data Website Guide identifies these files as XML. The landing page and guide state that the Current Results file is refreshed every two minutes.

### Dataset summary

| Dataset | Important fields | Project use |
|---|---|---|
| `Elections` | `ElectionId`, `ElectionName`, `ElectionType`, `ElectionDate` | Create or identify an election. |
| `PoliticalParties` | `PartyId`, `PartyName`, `Abbreviation` | Normalize candidate and contest party records. |
| `GeopoliticalUnits` | `UnitId`, `UnitName`, `UnitType`, `ParentId` | Build the state/county/precinct/district hierarchy. |
| `Contests` | Election, contest, jurisdiction-scope, party, display, and contest-status fields | Create races and associate them with the correct district or jurisdiction. |
| `Candidates` | Election, contest, candidate, ballot name, party, incumbent, write-in, and withdrawn fields | Create candidate records and ballot associations. |
| `CurrentResults` | Candidate vote totals plus geopolitical-unit reporting records | Import live, unofficial vote totals and reporting status. |
| `CurrentResultsExcludeLocal` | Reduced current-results feed excluding local contests | Efficient import for federal, statewide, congressional, and legislative coverage. |

### Current-results candidate records

The guide documents candidate result records ordered by:

```text
gpu_id
contest_id
candidate_id
```

Candidate result fields include:

```text
gpu_id
contest_id
candidate_id
total_votes
election_day_votes
```

The guide states that absentee votes are calculated as:

```text
absentee_votes = total_votes - election_day_votes
```

This feed does not document separate early-voting, provisional, or other detailed method columns. Do not invent those categories unless they appear in a later schema revision.

### Reporting records

`CurrentResults` also contains `ReportData` records for geopolitical units such as the state, counties, and precincts:

```text
gpu_id
status
precinct_participating
precinct_reporting
ballots_cast
registered_voters
```

The guide uses three reporting states:

| Status | Meaning |
|---|---|
| `NotReporting` | `ballots_cast` is zero. |
| `PartialReporting` | Results have been uploaded, but the county has not indicated that all data is complete. |
| `FinalReporting` | The county clerk's office has indicated that uploading is complete. |

### Critical reporting-status rule

Do **not** determine finality only from:

```text
precinct_reporting == precinct_participating
```

The official guide warns that a precinct counted as “reporting” may only mean that the county has supplied some data for it. The `ReportData.status` attribute is the correct source for determining whether a county or precinct has reached `FinalReporting`.

`FinalReporting` is set by the county clerk's office and becomes effective simultaneously for a county and its precincts.

---

## XML Relationships and Suggested Joins

The datasets are designed to join through stable IDs.

```text
CurrentResults.contest_id
    -> Contests.ContestId

CurrentResults.candidate_id
    -> Candidates.CandidateId

CurrentResults.gpu_id
    -> GeopoliticalUnits.UnitId

Candidates.ContestId
    -> Contests.ContestId

Candidates.PoliticalPartyId
    -> PoliticalParties.PartyId

Contests.ElectionId
    -> Elections.ElectionId

Contests.*ScopeUnitId
    -> GeopoliticalUnits.UnitId
```

Candidate IDs should be treated as contest-scoped unless testing demonstrates that they are globally unique. A safe natural key is:

```text
ElectionId + ContestId + CandidateId
```

A safe live-result key is:

```text
ElectionId + gpu_id + contest_id + candidate_id
```

The current-results file does not directly list `ElectionId` in each candidate result record according to the guide, so the importer should associate the current feed with the active election identified from the accompanying metadata and ingestion configuration.

---

## Geopolitical Unit Hierarchy

Kentucky represents jurisdictions through `UnitId`, `UnitType`, and `ParentId`.

Example hierarchy from the official guide:

```text
United States  UnitId 1     UnitType 10
└── Kentucky   UnitId 2     UnitType 11
    └── Adair  UnitId 3     UnitType 12
        └── A102 UnitId 1617 UnitType 17
```

Important unit types include:

| Value | Type |
|---:|---|
| 10 | Country |
| 11 | State |
| 12 | County |
| 13 | City |
| 14 | County School District |
| 16 | Other Governmental Jurisdictions |
| 17 | Precinct |
| 18 | Split Precinct |
| 19 | Polling Place |
| 20 | Vote Center |
| 21 | Other Administrative Divisions |
| 22 | Congressional District |
| 23 | State House District |
| 24 | State Senate District |
| 25 | Supreme Court District |
| 26 | Circuit Court District |
| 27 | District Court District |
| 28 | Ward |
| 29 | Magisterial District |
| 30 | Other Political Districts |
| 31 | Division |
| 111 | School Board |

The hierarchy allows an importer to represent both geographic navigation and contest scope without parsing jurisdiction names from race titles.

---

## Contest Data

The official guide documents the following `Contest` fields:

```text
ElectionId
ContestId
ContestName
GovernmentScopeUnitId
FilingScopeUnitId
OfficeScopeUnitId
ContestScopeUnitId
IsPartisan
IsUnexpiredTerm
IsUncontested
SelectableOption
DisplayOrder
PoliticalPartyId
```

These fields provide a better race-creation source than attempting to parse the rendered contest heading.

Suggested mapping:

| Kentucky field | CivicMirror use |
|---|---|
| `ElectionId` | Parent election |
| `ContestId` | External race identifier |
| `ContestName` | Race title |
| `ContestScopeUnitId` or appropriate scope ID | District/jurisdiction association |
| `IsPartisan` | Race partisan flag |
| `IsUnexpiredTerm` | Special/unexpired-term indicator |
| `IsUncontested` | Uncontested flag |
| `SelectableOption` | Number of selections allowed, where applicable |
| `DisplayOrder` | Source ordering |
| `PoliticalPartyId` | Primary-party association where applicable |

The multiple scope fields should be preserved in raw metadata until their behavior has been tested across statewide, legislative, judicial, county, city, and school contests.

---

## Candidate Data

The official guide documents:

```text
ElectionId
ContestId
CandidateId
BallotName
IsIncumbent
IsWriteIn
IsWithdrawn
PoliticalPartyId
```

Recommended mapping:

| Kentucky field | CivicMirror use |
|---|---|
| `CandidateId` | Source candidate identifier within the election/contest |
| `BallotName` | Display name exactly as shown on the ballot |
| `PoliticalPartyId` | Join to normalized party |
| `IsIncumbent` | Incumbency flag |
| `IsWriteIn` | Write-in flag |
| `IsWithdrawn` | Withdrawn flag |

The guide notes that candidates in nonpartisan contests may still have a `PoliticalPartyId` value other than zero. The importer should rely on the contest's `IsPartisan` value rather than assuming that a populated candidate party makes the contest partisan.

---

## Attached HAR Analysis

**HAR file:** `vrsws.sos.ky.gov_Archive [26-07-18 15-15-30].har`  
**Capture date:** July 18, 2026  
**Entries:** 103

### Primary navigation requests captured

The HAR contains six complete result-page navigations:

| Request | Interpretation | HTTP status |
|---|---|---:|
| `/liveresults` | Statewide | 200 |
| `/liveresults?id=3` | Adair County | 200 |
| `/liveresults?id=1621` | Adair County Precinct B104 — Ozark | 200 |
| `/liveresults?id=38` | Floyd County | 200 |
| `/liveresults?id=2597` | Floyd County Precinct A116 — Cliff | 200 |
| `/liveresults?id=2` | Kentucky statewide geopolitical unit | 200 |

The IDs used in the browser URL are consistent with the `GeopoliticalUnits.UnitId` model documented in the XML guide.

### No hidden JSON results API observed

Ordinary page navigation in the HAR does not call a separate results JSON endpoint. No requests were captured to paths resembling:

```text
/api/results
results.json
CurrentResults
Contests
Candidates
```

Instead, every statewide, county, and precinct selection returns a large, complete HTML response containing the result tables. The JavaScript captured in the HAR primarily handles:

- Client-side filtering of already-rendered contests.
- County and precinct navigation.
- Candidate-row expansion and collapse.
- Optional full-page refresh.
- Display behavior and Akamai browser telemetry.

This corrects the Version 1 inference that the rendered page's timer necessarily implied a hidden JSON feed.

### HTML refresh interval

The embedded page script uses:

```javascript
(function countdown(remaining) {
    if (remaining == 0)
        location.reload(true);
    document.getElementById('countdown').innerHTML = remaining;
    setTimeout(function () { countdown(remaining - 1); }, 1000);
})(180);
```

Therefore:

| Interface | Refresh behavior |
|---|---|
| Rendered HTML with `autorefresh=true` | Reloads the complete page every 180 seconds. |
| Official `CurrentResults` XML | Kentucky states that the data file refreshes every 120 seconds. |

These are separate refresh mechanisms and should not be conflated.

### County PDF endpoints discovered

County and precinct views expose human-readable result files with predictable county-based paths:

```text
/liveresults/CumulativePdf/{county_gpu_id}
/liveresults/PrecinctPdf/{county_gpu_id}
```

Examples captured:

```text
/liveresults/CumulativePdf/3
/liveresults/PrecinctPdf/3
/liveresults/CumulativePdf/38
/liveresults/PrecinctPdf/38
```

When viewing an individual precinct, the PDF URLs still use the parent county's geopolitical-unit ID.

These files can be retained as audit/reference attachments, but XML is preferable for normalized ingestion.

### Akamai evidence in the HAR

The browser capture contains clear Akamai protection indicators, including:

```text
akamai-grn
x-akamai-transformed
bm_sz cookies
_abck / ak_bmsc-style browser-validation behavior
obfuscated Akamai JavaScript
telemetry POST requests returning HTTP 202
```

This supports the Version 1 observation that plain datacenter requests may be blocked or challenged.

However, the attached HAR itself contains:

- Successful HTTP 200 result-page responses.
- No captured HTTP 403 result page.
- No captured Kentucky Acceptable Use Policy warning page.

The HAR therefore proves that the browser session passed Akamai validation. It does not, by itself, prove that every programmatic request to every path on the host is prohibited.

### Correct policy interpretation

The prior research observed a 403 Acceptable Use Policy response when accessing the rendered results interface programmatically. That remains an important operational warning.

The existence of a separately documented XML download page changes the implementation decision. The project should:

- Avoid automating the rendered HTML interface.
- Use the documented XML download paths.
- Treat the published two-minute update rate as the source's maximum useful refresh cadence, not CivicMirror's default polling schedule.
- Poll once every 24 hours during off-season periods, aligned with the other nightly state syncs, so special or off-cycle elections are still detected.
- During active election windows, increase polling to hourly unless project needs later justify a faster cadence.
- Identify itself honestly where a user agent is accepted.
- Apply conditional requests and backoff where supported.
- Contact the Kentucky State Board of Elections for clarification or allowlisting if the production host receives a policy block.
- Never attempt to defeat Akamai challenges or impersonate browser telemetry.

---

## Current 2026 Result Context

The rendered site and official result pages identify the active election as the **May 19, 2026 Primary Election**.

The statewide values observed in the HAR were:

```text
Registered voters:          3,365,369
Ballots cast:                 864,365
Voter turnout:                  25.68%
Counties participating:            120
Counties finished reporting:       120
Precincts participating:         3,189
Precincts reporting:             3,189
```

The displayed results are labeled **unofficial**. Completion of election-night reporting is not equivalent to certification.

Observed contest categories include:

- United States Senator.
- United States Representative in Congress, districts 1–6.
- State Senate districts.
- State House districts.
- Judicial contests.
- County and local contests.

---

## Data-Page Presentation Caveat

The `/liveresults/Data` page contains stale presentation text, including a 2022 last-updated label and a reference to the 2022 general election, while the same page identifies its downloadable section as **2026 Primary Election Data**.

Therefore:

- Do not identify the election solely from decorative page headings.
- Use the `Elections` XML fields as the authoritative machine-readable election identity.
- Store the source URL, retrieval timestamp, file hash, and election metadata with each ingestion batch.

---

## Clarity Elections System

**Host:**  
https://results.enr.clarityelections.com/KY/

**Manifest convention:**  
https://results.enr.clarityelections.com/KY/elections.json

Historically, Clarity election sites commonly expose paths such as:

```text
/KY/{EID}/{subpage}/en/summary.html
/KY/{EID}/web.{VERSION}/#/summary
/KY/{EID}/{subpage}/reports/detailxml.zip
```

The `elections.json` path currently encounters Akamai/JavaScript bot verification from non-browser clients. Even when individual Clarity report ZIP URLs can be identified, discovery and county-subpage navigation may be fragile.

### Clarity verdict

Clarity should not be the primary Kentucky integration because:

- Election discovery is bot-challenged.
- URL structures can differ by election and subpage.
- County subpages may require redirects or browser discovery.
- Kentucky now exposes an official, documented XML download area on its own ENR system.

Clarity can remain a research fallback or cross-check source, not a production dependency.

Tools historically associated with Clarity parsing include:

- `clarify` from the OpenElections ecosystem.
- `washingtonpost/elex-clarity`.
- `courierjournal/clarity-elections-finder`.

Any use should remain compliant with the source's access controls and terms.

---

## Certified Results

**Primary certified source:**  
https://elect.ky.gov/results/

The Kentucky State Board of Elections publishes official certification documents and county recap files. The 2026 page currently includes:

- 2026 Primary Results — Official Certification.
- 2026 Primary Recap Sheets.
- Unofficial statewide and county result links.

### Certified-result role

CivicMirror's final comparison baseline should continue to use certified results, even when live XML is ingested on election night.

Recommended lifecycle:

```text
Live XML
    -> store as unofficial snapshots
    -> display/update election-night totals
    -> wait for official certification
    -> import certified files
    -> reconcile and mark final
```

The system should never silently replace an unofficial history. Preserve both the live snapshots and certified final records with distinct `result_type` values.

---

## OpenElections

OpenElections remains useful for standardized historical data.

Typical normalized columns include:

```text
county
precinct
office
district
party
candidate
votes
```

Some files may include vote-method columns, but availability varies by year and source.

### Strengths

- Open GitHub access.
- Standardized CSV format.
- Easier historical backfills.
- Useful for cross-state normalization.

### Limitations

- Volunteer maintained.
- New elections may lag official publication.
- Coverage and detail vary by election and county.
- It should not replace Kentucky's official source for live or certified 2026 data.

---

## Recommended CivicMirror Ingestion Design

### Phase A — Election metadata initialization

At the beginning of an election cycle or ingestion run:

1. Download `Elections`.
2. Select the intended election by ID, date, and type.
3. Download `PoliticalParties`.
4. Download `GeopoliticalUnits`.
5. Download `Contests`.
6. Download `Candidates`.
7. Store each raw XML file and its hash before normalization.
8. Upsert elections, parties, jurisdictions, races, and candidates using Kentucky IDs.

### Phase B — Live result polling

During election-night reporting:

1. Poll once every 24 hours during off-season periods, aligned with the other nightly state syncs, so special or off-cycle elections are still detected.
2. During active election windows, poll hourly. The official XML refreshes every two minutes, but that cadence is not necessary for CivicMirror unless future needs demand it.
3. Poll `CurrentResultsExcludeLocal` when only federal, statewide, congressional, and legislative contests are required.
4. Poll `CurrentResults` when county, city, judicial, school, or other local contests are required.
5. Do not poll both full feeds unless there is a specific need.
6. Save the original XML response with retrieval time and checksum.
7. Skip processing when the response hash has not changed.
8. Join result records using `gpu_id`, `contest_id`, and `candidate_id`.
9. Update reporting status from `ReportData.status`.
10. Label all records `unofficial` until certification.

### Phase C — Failure handling

- Use exponential backoff after errors.
- Honor `Retry-After`, `ETag`, and `Last-Modified` when supplied.
- Stop or sharply reduce polling after all relevant units become `FinalReporting`.
- Do not attempt to bypass a Kentucky/Akamai policy block.
- Retain the last successful snapshot and mark the feed stale if polling fails.

### Phase D — Certification reconciliation

1. Monitor the official `elect.ky.gov` election page for certification and recap files.
2. Import certified statewide and county files.
3. Match certified records to the existing election, race, candidate, and jurisdiction IDs where possible.
4. Record discrepancies rather than overwriting the unofficial audit history.
5. Mark the certified dataset as the final comparison baseline.

---

## Suggested Internal Source Records

```text
source_id: ky_sbe_live_xml
source_type: official_unofficial_results
base_url: https://vrsws.sos.ky.gov/liveresults/Data
format: xml
source_refresh_interval_seconds: 120
off_season_poll_interval_seconds: 86400
active_election_poll_interval_seconds: 3600
result_type: unofficial

source_id: ky_sbe_certified
source_type: official_certified_results
base_url: https://elect.ky.gov/results/
format: pdf/xls/xlsx/html
result_type: certified

source_id: openelections_ky
source_type: normalized_historical_results
base_url: https://github.com/openelections/openelections-data-ky
format: csv
result_type: varies
```

---

## Recommended Source Priority

### Live election night

```text
1. Kentucky official CurrentResults XML
2. Kentucky official CurrentResultsExcludeLocal XML, when appropriate
3. Rendered Kentucky HTML for manual verification only
4. County cumulative/precinct PDFs for audit reference
5. Clarity only as a nonessential cross-check
```

### Certified final results

```text
1. Kentucky official certification and recap files
2. OpenElections after it publishes normalized files
3. Other reputable archives as verification sources
```

---

## Changes from Version 1

Version 2 makes the following corrections and additions:

1. **Adds the official `/liveresults/Data` XML interface** as the preferred live results source.
2. **Replaces the blanket prohibition on the entire `vrsws` host** with a specific warning against scraping the rendered HTML interface.
3. **Corrects the hidden-feed inference:** the HAR shows server-rendered HTML and no separate JSON results request during navigation.
4. **Documents the two distinct update intervals:** 180-second HTML page reload and 120-second XML refresh.
5. **Documents all seven XML download paths.**
6. **Adds dataset fields, joins, and geopolitical-unit types** from Kentucky's official guide.
7. **Adds the reporting-status rule** requiring `ReportData.status` rather than precinct-count equality.
8. **Adds predictable county cumulative and precinct PDF routes** discovered in the HAR.
9. **Qualifies the Akamai conclusion:** the HAR confirms browser-validation infrastructure but does not contain a 403 or Acceptable Use Policy page.
10. **Keeps certified Kentucky files as the final authority** and OpenElections as the historical/normalized secondary source.
11. **Adds an implementation workflow** for metadata loading, nightly off-season polling, hourly active-election polling, backoff, raw snapshot retention, and certification reconciliation.

---

## Final Assessment

Kentucky has a viable official integration path.

The rendered ENR website should be treated as a browser-facing verification layer, not scraped as an API. The attached HAR confirms that it serves complete HTML pages, uses geopolitical-unit IDs for navigation, reloads at three-minute intervals when auto-refresh is enabled, exposes county PDF downloads, and operates behind Akamai browser validation.

The official `/liveresults/Data` page is the appropriate machine-readable layer. Its documented XML files supply the metadata and vote totals necessary to create elections, races, jurisdictions, candidates, and live result records. The files refresh every two minutes, but CivicMirror should poll nightly during off-season periods and hourly during active election windows, then stop or back off once reporting is final.

Certified results from `elect.ky.gov` remain the authoritative final baseline. OpenElections remains a useful standardized historical supplement but should not be relied on for immediate election-night coverage.

---

## Sources Reviewed

### Kentucky official sources

- Kentucky Election Night Reporting — statewide interface  
  https://vrsws.sos.ky.gov/liveresults

- Kentucky Election Night Reporting — data downloads  
  https://vrsws.sos.ky.gov/liveresults/Data

- Kentucky Election Night Reporting — Data Website Guide, Version 4  
  https://vrsws.sos.ky.gov/liveresults/Documentation/Data%20Website%20Guide.pdf

- Kentucky State Board of Elections — result archive  
  https://elect.ky.gov/results/

- Kentucky State Board of Elections — 2026 results  
  https://elect.ky.gov/results/2020-2029/Pages/2026.aspx

### Other result sources

- Clarity Elections Kentucky  
  https://results.enr.clarityelections.com/KY/

- Clarity election manifest convention  
  https://results.enr.clarityelections.com/KY/elections.json

- OpenElections Kentucky data  
  https://github.com/openelections/openelections-data-ky

- OpenElections Kentucky source files  
  https://github.com/openelections/openelections-sources-ky

### Attached research artifacts

- `KY-Election_Research(2).md` — Version 1 research document.
- `vrsws.sos.ky.gov_Archive [26-07-18 15-15-30].har` — browser network capture used to analyze the rendered ENR interface.
