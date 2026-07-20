# Alabama Election System — Research Notes

**State:** Alabama (AL)  
**Primary operator:** Alabama Secretary of State  
**Original research:** March 4, 2026  
**Stage 2 HAR analysis and live verification:** July 18, 2026  
**Stage 1 FCPA and district-map HAR analysis:** July 20, 2026  
**Core coverage target:** Federal and state elections, races, candidates, statewide ballot measures, official district geometry, live/unofficial results, and certified results. County and municipal coverage is enhanced coverage.

---

## Coverage Status

| Capability | Status | Recommended official source | Confidence / verified |
|---|---|---|---|
| Stage 1 — Election Creation | ✅ Strong official source | SOS year-specific Election Information pages and election calendars | High — HTML and links captured 2026-07-18 |
| Stage 1 — Provisional Race/Candidate Discovery | ✅ Structured public source confirmed | FCPA Political Race Search JSON + committee-detail records | High — HAR captured 2026-07-20 |
| Stage 1 — Ballot-Qualified Race/Candidate Creation | ⚠️ Official source confirmed; parser pending | Party, amended-party, and state candidate-certification PDFs | Medium-high — document index captured; PDF schemas not fully validated |
| Stage 1 — Sample Ballot Validation / Local Expansion | ⚠️ Source indexes confirmed | SOS county/party sample-ballot pages | Medium — links captured; ballot PDF schemas not reviewed |
| Stage 1 — Statewide Ballot Measures | ⚠️ Partial official path | State certification of statewide/constitutional amendments + sample ballots | Medium — links captured; document schemas not reviewed |
| District Geometry — Congressional | ✅ Public structured source | Alabama ArcGIS FeatureServer layers | High — metadata and query traffic captured 2026-07-20 |
| District Geometry — State Senate | ✅ Public structured source | Alabama ArcGIS FeatureServer layers | High — metadata and query traffic captured 2026-07-20 |
| District Geometry — State House / State Board of Education | ⚠️ Official experiences identified; layer URLs not captured | Alabama Redistricting Plans ArcGIS experiences | Medium |
| Stage 2 — Live/Unofficial Results | ✅ Adapter path confirmed | ENR statewide Excel export | High — HAR replay and live verification 2026-07-18 |
| Stage 2 — Certified Results | ✅ Available as official files | SOS year pages and Election Data archive | High for discovery; format-specific parsers still required |
| Precinct-Level Results | ⚠️ Archive confirmed; schema pending | SOS Election Data ZIP archives | Medium |

---

## Executive Conclusion

Alabama now has a viable official-source path for both Stage 1 and Stage 2, but the data is split across several state systems rather than exposed through one unified election API.

The recommended source stack is:

1. **SOS Election Information pages** create the election record and discover official documents.
2. **FCPA Political Race Search** provides early, structured, provisional race and candidate discovery.
3. **Candidate-certification PDFs** determine ballot qualification and supersede FCPA-only status.
4. **Sample ballots** validate exact ballot names and add county/local contests and ballot measures.
5. **Alabama ArcGIS Feature Services** provide authoritative-source district polygons and plan metadata.
6. **ENR Excel export** provides live statewide election-night results and reporting progress.
7. **SOS certification workbooks and ZIP archives** provide final and precinct-level reconciliation.

The earlier conclusion that Alabama lacked a state-source Stage 1 path is no longer accurate. The corrected implementation decision is:

> **Use FCPA for provisional discovery, official candidate certifications for ballot-qualified race/candidate creation, sample ballots for validation and enhanced local coverage, and ArcGIS Feature Services for district geometry. Do not treat an active FCPA committee as proof that a candidate qualified for a specific ballot.**

Alabama should be classified as **Stage 1 path identified / implementation pending**, not Full Core yet. Full Core can be declared after the certification parser and reconciliation workflow are validated end to end for at least one statewide primary or general election.

---

# 1. Official Source Architecture

Alabama uses at least five relevant official systems.

| System | Host | Primary use |
|---|---|---|
| Election information / official documents | `www.sos.alabama.gov` | Election dates, calendars, candidate certifications, sample ballots, certified results |
| Campaign-finance / political-race search | `fcpa.alabamavotes.gov` | Provisional candidates, offices, jurisdictions, parties, committee details |
| Election Night Reporting | `www2.alabamavotes.gov/electionNight/` | Live/unofficial results and reporting statistics |
| Election Data archive | `www.sos.alabama.gov/alabama-votes/voter/election-data` | Precinct ZIPs, registration workbooks, historical files |
| Redistricting GIS | `alabamaredistrictingplans-algeohub.hub.arcgis.com` and `services7.arcgis.com` | Congressional and legislative district geometry |

No single source should be expected to satisfy all CivicMirror fields. The Alabama implementation should use multiple small adapters with explicit provenance and reconciliation rules.

---

# 2. Stage 1 — Election Creation

## 2.1 Year-Specific Election Information Page

Canonical pattern:

```text
https://www.sos.alabama.gov/alabama-votes/voter/election-information/{year}
```

The captured 2026 page is server-rendered Drupal HTML. Election sections are represented by headings and grouped official-document links. The page identified:

- Special General Election, House District 63 — January 13, 2026
- Special General Election, House District 38 — February 3, 2026
- Primary Election — May 19, 2026
- Primary Runoff Election — June 16, 2026
- Special Primary Election, Congressional Districts 1, 2, 6, and 7 — August 11, 2026
- Special Primary Election, State Senate Districts 25 and 26 — August 11, 2026
- General Election — November 3, 2026

The same page links election calendars, candidate filing guides, candidate certifications, sample ballots, amendment certifications, unofficial-result files, and final certification documents.

### Proposed `AL-Elections` behavior

1. Fetch the year page.
2. Parse each election heading into:
   - election name;
   - election date;
   - election type;
   - office/district scope when encoded in the heading;
   - source URL;
   - retrieval timestamp.
3. Associate every document link with the nearest election heading.
4. Preserve the original heading and link label because filenames are inconsistent.
5. Use linked election-calendar PDFs to enrich registration, qualification, runoff, absentee, and certification deadlines where needed.
6. Retain Google Civic Information only as a fallback/cross-check, not the canonical Alabama election-creation source.

### Discovery warning

Static-file paths and filenames are not stable enough to construct directly. Always scrape the year page and retain the discovered URL.

---

# 3. Stage 1 — FCPA Provisional Race and Candidate Discovery

## 3.1 Public Search Page

```text
https://fcpa.alabamavotes.gov/page.request.do?page=page.acfPublicPoliticalRaceSearch
```

The page is public and server-rendered. Its JavaScript performs anonymous JSON requests for search results.

The captured search form contained:

- **161 named election choices** plus a placeholder;
- **45 named office choices** plus a placeholder;
- **250 named jurisdiction choices** plus a placeholder;
- **8 named party choices** plus a placeholder;
- district, place, city, and financial-year filters.

Observed 2026 election options included:

```text
160  2026 ELECTION CYCLE
167  2026 2026 Municipal Election
169  2026 Fort Deposit Special Election
170  2026 Tuscaloosa City Council District 3
171  2026 City of Montgomery City Council District 3 Special Election
172  2026 Stockton Local Referendum
```

These IDs are source-system identifiers and should be stored as strings/integers in source metadata. Do not assume they are stable across a rebuilt FCPA system.

## 3.2 Political Race Search JSON Endpoint

Captured request pattern:

```text
GET https://fcpa.alabamavotes.gov/page.request.do
    ?page=com.acf.common.page.politicalracesearchresults
    &pageNumber=1
    &pageSize=10
    &sortDirection=ASC
    &sortBy=candidate
    &election={ELECTION_ID}
    &office={OFFICE_ID|null}
    &jurisdiction={JURISDICTION_ID|null}
    &party={PARTY_ID|null}
    &place={PLACE_ID|null}
    &district={DISTRICT_ID|null}
    &city={CITY_ID|null}
    &year={FINANCIAL_YEAR_ID|null}
```

The browser serializes unselected optional filters as the literal string `null`. An adapter should initially mirror the captured browser behavior.

Captured response shape:

```json
{
  "data": {
    "totalRecords": 848,
    "list": [
      {
        "COMMITTEEID": 4834,
        "CANDIDATE": "ABBETT, JIMMY ",
        "CANDIDATESTATUS": "Active",
        "BEGINNINGFUNDS": 623.00,
        "MONETARYCONTRIB": 0.00,
        "MONETARYEXP": 0.00,
        "NONMONETARYCONTRIB": 0.00,
        "OTHERSOURCES": 0.00,
        "ENDINGFUNDS": 623.00,
        "YEAR": 2026
      }
    ]
  },
  "success": true
}
```

The unrestricted `2026 ELECTION CYCLE` request returned **848 records**. Pagination was captured through page 85.

### Important interpretation

The result row is a campaign-finance summary. It does **not** include office, district, party, or jurisdiction. `CANDIDATESTATUS` describes the committee/candidate record in FCPA and must not be interpreted as ballot qualification.

## 3.3 Office Metadata Endpoint

Captured request:

```text
GET /page.request.do?page=com.acf.committee.page.getofficedata&officeId={OFFICE_ID}
```

Example response for Governor (`officeId=23`):

```json
{
  "code": "code.governor",
  "districts": [],
  "showCity": false,
  "showJurisdiction": false,
  "places": [],
  "name": "Governor",
  "showParty": true,
  "showDistrict": false,
  "id": 23,
  "showPlace": false,
  "jurisdictions": [],
  "trackingId": 23
}
```

This endpoint provides UI/schema behavior for each office and can guide normalization of district, jurisdiction, city, and place fields.

Core office options observed include:

- Attorney General
- Commissioner of Agriculture & Industries
- Governor
- Lieutenant Governor
- President / member of the Public Service Commission
- Secretary of State
- State Auditor
- State Board of Education
- State Representative
- State Senator
- State Treasurer
- Supreme Court and appellate-court offices
- district, county, and municipal offices

## 3.4 Candidate / Committee Detail Page

Search rows link to:

```text
/page.request.do?page=page.acfPublicCommitteeDetails
    &type={base64("pcc")}
    &id={base64(COMMITTEEID)}
```

Each captured principal-campaign-committee page embeds:

```javascript
const committeeDetailsObj = { ... };
```

Observed fields include:

```text
id
trackingId
committeeId
committeeType
committeeStatus
registeredDate
dissolutionDate
dissolved

candidateFirstName
candidateMiddleName
candidateLastName
suffix

office
jurisdiction
district
party
place
officeCity

committeeAddressLine1
city
committeeState
zipCode
phone
email
members[]
```

The object supplies the office, jurisdiction, district, and party that are absent from the search-result JSON. It also provides campaign contact data that may be useful as enrichment, subject to CivicMirror privacy and display rules.

### Identifier distinction

The captured objects expose multiple identifiers:

- `id` / `trackingId` matched the `COMMITTEEID` used by the public detail URL.
- `committeeId` was a different string-valued internal/registration identifier.

Preserve all three in raw source metadata until identity behavior is validated across older and newly registered committees.

## 3.5 Export Endpoint

The search page offers CSV, Excel, PDF, and HTML/Print exports and states:

```text
Exports are limited to 20,000 results.
```

The JavaScript constructs:

```text
GET /page.request.do
    ?page=reportRunner
    &reportKey=report.michael.onjack.searchPoliticalRace
    &{same search parameters}
    &format={csv|xlsx|pdf|html}
```

The URL construction is confirmed by the HAR. An actual export response was not captured, so the output schema, MIME types, and whether exports include office/district fields remain unverified.

## 3.6 FCPA Limitations

FCPA is an excellent early-discovery source, but it is not a ballot roster.

Reasons:

- the generic election cycle can include hundreds of committee records;
- some active committees were registered years before the target election;
- dissolved committees remain searchable;
- committee status is not ballot status;
- a person may register or maintain a committee without qualifying for the selected ballot;
- withdrawals, party disqualification, petition failure, or replacement may occur after registration.

### Required status model

```text
FCPA record
  -> provisional_candidate

Party certification
  -> party_certified

State candidate certification
  -> ballot_certified

Sample ballot appearance
  -> ballot_validated
```

Never promote `FCPA Active` directly to `ballot_certified`.

## 3.7 Proposed `AL-FCPA` Adapter

### Discovery

1. Fetch the Political Race Search page.
2. Parse election, office, jurisdiction, party, district, city, place, and financial-year option IDs.
3. Snapshot labels and IDs with retrieval timestamps.
4. Detect newly added elections.

### Search

1. Query by election.
2. Prefer federal/state office filters for Core coverage.
3. Paginate using `totalRecords`.
4. Preserve the raw JSON response and query parameters.
5. Deduplicate using FCPA `COMMITTEEID`.

### Detail enrichment

1. Fetch each principal-campaign-committee detail page.
2. Parse `committeeDetailsObj`.
3. Normalize:
   - candidate name;
   - office;
   - jurisdiction;
   - district/place/city;
   - party;
   - committee status;
   - registered and dissolution dates.
4. Create provisional races from unique office + geography + party combinations.
5. Store contact fields as source data; apply application-level privacy/display policy separately.

### Reconciliation

Match FCPA records to certification records using:

```text
normalized candidate name
office
district / jurisdiction / place / city
party
election cycle
```

Retain unmatched FCPA records as provisional history. Do not silently delete them.

---

# 4. Ballot-Qualified Candidates — SOS Certifications

The year-specific SOS page publishes multiple certification layers:

- party certification of candidates;
- amended party certification;
- state certification of candidates;
- state certification of statewide amendments;
- certification of runoff nominees;
- certification of general-election candidates;
- certification of election results.

The captured 2026 page linked candidate certifications for:

- the May 19 primary;
- the June 16 primary runoff;
- August 11 congressional special primaries;
- August 11 State Senate special primaries;
- the November 3 general election;
- House District 38 and 63 special elections.

## 4.1 Recommended Authority Order

For candidate ballot status:

```text
1. Latest state candidate certification
2. Latest amended party certification, when no later state certification is published
3. Original party certification
4. FCPA provisional record
```

For exact ballot presentation:

```text
Latest official sample ballot
  -> validates ballot name, contest title, party ballot, ordering, and local additions
```

Every document version should be retained. An amendment should supersede, not erase, the earlier certification.

## 4.2 Proposed Certification Parser

1. Scrape the year page and group documents under their election heading.
2. Classify documents by link label:
   - party candidate certification;
   - amended candidate certification;
   - state candidate certification;
   - amendment certification;
   - result certification.
3. Download and checksum each file.
4. Parse office headings, district/jurisdiction, candidate ballot names, party, and certification date.
5. Create or promote provisional FCPA candidates to `ballot_certified`.
6. Mark missing previously certified candidates as superseded/withdrawn only when supported by a newer official document.
7. Preserve original PDF and parser output for audit.

## 4.3 Current Validation Gap

The candidate-certification PDFs were linked in the SOS HAR but were not opened in the supplied capture. Before production implementation, download representative files and document:

- whether the PDFs are text-based or scanned;
- office-heading and district formatting;
- multi-column behavior;
- candidate-name punctuation;
- write-in and unopposed markers;
- amended-certification conventions;
- whether statewide and district offices share one consistent schema.

---

# 5. Sample Ballots and Ballot Measures

The 2026 Election Information page links official sample-ballot indexes for:

- the May 19 primary;
- the June 16 primary runoff;
- the August 11 special primaries.

Sample ballots should be used for:

- exact ballot candidate names;
- contest wording and ordering;
- party-specific primary contest identity;
- county participation in district contests;
- local offices and referenda;
- statewide and local ballot-question text;
- validation of late certification changes.

The same year page also links:

- State Certification of Statewide Amendments;
- State Certification of Constitutional Amendments.

## Proposed `AL-Ballots` / `AL-Measures` behavior

1. Crawl each official sample-ballot index.
2. Classify links by county and party.
3. Download and checksum PDFs.
4. Parse contest headings and selectable options.
5. Reconcile federal/state candidates against the latest certification.
6. Add county/local contests only when geography can be determined reliably.
7. Extract measure identifiers and exact ballot text.
8. Reconcile statewide measures against the state amendment-certification document.
9. Preserve the source ballot as evidence.

Local coverage remains enhanced coverage; federal and state races are the Core priority.

---

# 6. Official District Geometry — Alabama ArcGIS

## 6.1 Hub and Experience Items

Hub:

```text
https://alabamaredistrictingplans-algeohub.hub.arcgis.com/
```

Public experience items observed:

| Item | ArcGIS item ID |
|---|---|
| 2023 Court Ordered Congressional Plan Web Experience | `6abefcf297c94ac38aa9d42c0b94cdc3` |
| 2021 Alabama Senate Plan Web Experience | `a13eaebf605c486586ea1cebfba7de23` |
| 2021 Alabama House Plan Web Experience | `908e680a9f1e4622ab53fb1f175caa5f` |
| 2021 Alabama State Board of Education Redistricting Map Web Experience | `2c39b237e3f74bbd9728271c2742aa3d` |

The supplied HAR fully loaded the congressional and Senate web maps. House and State Board of Education experience pages were identified, but their underlying web-map and FeatureServer URLs were not captured.

## 6.2 Captured Congressional Layers

Web map item:

```text
039241aaf1d841bda73e7e49376af60f
```

Operational layers:

| Layer | Feature service item | Service |
|---|---|---|
| 2023 Court Ordered Congressional Plan | `c0eea295ae7e4238903330d5b2c901be` | `2023_Court_Ordered_Congressional_Plan/FeatureServer/0` |
| 2023 Congressional Plan | `cf6612d18f4f4a97b8f2b1392c70654a` | `2023_CONG_LEGISLATIVE_PLAN/FeatureServer/0` |
| Alabama County Lines | `a5bb500edc8a44e4a9be7e922fc55c65` | `Alabama_County_Lines/FeatureServer/0` |

Base host:

```text
https://services7.arcgis.com/jF2q3LPxL7PETdYk/arcgis/rest/services/
```

The web-map presentation had the 2023 Congressional Plan visible and the Court Ordered layer hidden at capture time. This is a UI state only and must not be treated as proof of which plan is legally effective for a particular election.

## 6.3 Captured Senate Layers

Web map item:

```text
637a2764572b44caae046fc6fcd230d2
```

Operational layers:

| Layer | Feature service item | Service |
|---|---|---|
| 2021 Alabama Senate Plan | `1246748e715f4d84a740e9e60d5782b4` | `2021_Alabama_Senate_Plan/FeatureServer/0` |
| 2025 Remedial Senate Plan | `99f920fd47fb4d5bbc077ac41245fae2` | `BEF_Remedial_Senate_Plan_3/FeatureServer/0` |
| Alabama County Lines | `a5bb500edc8a44e4a9be7e922fc55c65` | `Alabama_County_Lines/FeatureServer/0` |

The web-map presentation had the 2021 plan visible and the 2025 remedial layer hidden at capture time. Again, visibility is not legal-status metadata.

## 6.4 FeatureServer Capabilities

Layer metadata confirmed:

```text
capabilities: Query
geometryType: esriGeometryPolygon
maxRecordCount: 2000
supportedQueryFormats: JSON, geoJSON, PBF
```

Generic GeoJSON query:

```text
GET {FEATURESERVER_LAYER}/query
    ?where=1%3D1
    &outFields=*
    &returnGeometry=true
    &outSR=4326
    &f=geojson
```

The map itself used JSON statistics requests and PBF feature requests. Layer metadata explicitly advertises GeoJSON support; a direct `f=geojson` response was not captured and should be replay-tested before implementation is marked complete.

Common fields include:

```text
FID
ID
DISTRICT
DISTRICT_L
DISTRICT_N
NAME
AREA
POPULATION
Shape__Area
Shape__Length
```

The 2021 Senate layer additionally contains:

```text
LONGNAME
SHORTNAME
DISTRICTNUMBER
COUNTY
SENATOR
PARTY
EMAIL
PHOTO
```

Incumbent/person fields are useful enrichment but may become stale. Treat the geometry as the primary authoritative asset and timestamp any representative metadata separately.

## 6.5 Plan Versioning Requirement

Multiple alternative, enacted, remedial, or court-ordered plans may coexist in one web map. Store each plan as a versioned source object:

```text
plan_name
office_type
source_item_id
feature_service_url
legal_status
effective_from
effective_through
legal_authority
retrieved_at
checksum
```

Suggested `legal_status` values:

```text
proposed
enacted
court_ordered
remedial
effective
superseded
uncertain
```

Do not infer `effective` from web-map visibility. Associate each election with the specific plan version supported by the official election/legal record.

## 6.6 Proposed `AL-Districts` Adapter

1. Fetch ArcGIS item metadata and web-map data.
2. Enumerate operational FeatureServer layers.
3. Import polygon features with `outSR=4326`.
4. Normalize district numbers and office type.
5. Store source item ID, service URL, modified timestamp, and checksum.
6. Preserve all plan versions.
7. Link election races to the correct geometry version.
8. Separately research the House and State Board of Education experience items to capture their Web Map and FeatureServer IDs.

---

# 7. Stage 2 — ENR System

**Host:** `https://www2.alabamavotes.gov/electionNight/`

Alabama's election-night system is a custom SOS-built ASP.NET WebForms 4.0 application (`x-aspnet-version: 4.0.30319`), Cloudflare-fronted. No Clarity/Scytl, ES&S, KNOWiNK, or other vendor fingerprint was identified.

Export filename:

```text
sosEnrExport.xlsx
```

## 7.1 URL Structure

| Page | URL |
|---|---|
| Statewide results | `statewideResultsByContest.aspx?ecode={ECODE}` |
| County picker | `chooseCounty.aspx?ecode={ECODE}` |
| County results | `countyResultsByContest.aspx?cid={CID}&ecode={ECODE}` |

## 7.2 Election Codes

- Seven-digit code.
- `1001295` = 2026 Primary Runoff Election, June 16, 2026.
- Only the active election was populated during testing.
- Probing `1001250–1001296` found every code except `1001295` returned an empty results shell.
- No election index was found at `chooseElection.aspx`, `electionList.aspx`, or `default.aspx`.
- Treat `ecode` as per-election source metadata and discover it from the official link or a controlled capture.

## 7.3 County ID Scheme

The ENR uses 67 county IDs with non-obvious ordering:

```text
01 Jefferson
02 Mobile
03 Montgomery
04 Autauga
05 Baldwin
06 Barbour
...
```

The `cid` parameter and workbook `County Code` values use the same scheme.

## 7.4 Excel Export

The Export Data link is a WebForms postback:

1. `GET statewideResultsByContest.aspx?ecode={ECODE}`
2. Scrape:
   - `__VIEWSTATE`
   - `__VIEWSTATEGENERATOR`
   - `__EVENTVALIDATION`
3. `POST` the same URL with:
   - `__EVENTTARGET=hlnkExportData`
   - `__EVENTARGUMENT=` (empty)
   - hidden fields
4. Receive `sosEnrExport.xlsx`.

Key findings:

- The export is always statewide.
- A county-page export and statewide-page export were byte-identical.
- One workbook contained all 67 counties, 50 contests, and 924 result rows.
- Fresh GET → POST succeeded without login or session warmup.
- Display pagination is irrelevant to the workbook export.

## 7.5 Workbook Schema

### `AllResults`

| Column | Example |
|---|---|
| Election Code | `1001295` |
| Election Title | `2026 PRIMARY RUNOFF ELECTION` |
| County Code | `01` |
| County Name | `Jefferson` |
| Contest Code | `00100892` |
| Contest Title | `LIEUTENANT GOVERNOR (REP)` |
| Candidate Number | `001` |
| Candidate Name | `Wes Allen` |
| Votes | `13036` |
| Party Code | `REP` |

### `Statistics`

One row per county:

```text
Election Code
Election Title
County Code
Ballots Cast
Total Precincts
Precincts Reported
Last Updated
```

Use `Precincts Reported == Total Precincts` as the per-county completion signal.

## 7.6 Reference Fetch

```python
import re
import requests


def fetch_al_enr_export(ecode: str) -> bytes:
    url = (
        "https://www2.alabamavotes.gov/electionNight/"
        f"statewideResultsByContest.aspx?ecode={ecode}"
    )

    session = requests.Session()
    session.headers["User-Agent"] = "CivicMirror election-results importer"

    html = session.get(url, timeout=30).text
    fields = {
        key: re.search(rf'id="{key}" value="([^"]+)"', html).group(1)
        for key in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")
    }

    response = session.post(
        url,
        data={
            "__EVENTTARGET": "hlnkExportData",
            "__EVENTARGUMENT": "",
            **fields,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.content
```

Use a descriptive User-Agent and a conservative polling interval. Suggested minimum: 60 seconds unless Alabama publishes a different update interval.

---

# 8. Certified and Historical Results

## 8.1 Election Data Archive

```text
https://www.sos.alabama.gov/alabama-votes/voter/election-data
```

The page links approximately 128 files, including:

- precinct-result ZIPs back to at least 2012;
- ALVR registration workbooks;
- turnout and demographic summaries.

Static file pattern:

```text
/sites/default/files/election-data/{UPLOAD_YEAR-MONTH}/{human filename}
```

The upload month is not necessarily the election month. Filenames contain inconsistent spaces, punctuation, and duplicate suffixes. Discover files from the HTML page rather than constructing URLs.

### Remaining validation

The ZIP internal schemas were not verified. Download recent primary, runoff, general, and special-election examples before selecting a deterministic parser.

## 8.2 Per-Year Result and Certification Files

The year page links official XLSX and PDF files. Observed result formats include:

1. ENR-style statewide workbook schema.
2. Simpler workbook with one sheet per county and columns:

```text
PARTY
CONTEST
CANDIDATE
TOTALVOTES
```

In the second format, county is derived from the sheet name.

Use certified files as the authoritative final comparison baseline. Preserve election-night snapshots rather than overwriting them.

---

# 9. Recommended Alabama Adapter Layout

```text
AL-Elections
  Year-specific Election Information page
  Election headings and dates
  Election-calendar document discovery

AL-FCPA
  Lookup-option discovery
  Political Race Search JSON
  Committee-detail parser
  Provisional race/candidate records

AL-Certifications
  Party certifications
  Amended certifications
  State candidate certifications
  Supersession and ballot-status reconciliation

AL-Ballots
  County/party sample-ballot index
  Exact ballot candidate/contest validation
  Enhanced local race discovery

AL-Measures
  State amendment certifications
  Sample-ballot question text
  State/local classification

AL-Districts
  ArcGIS web-map discovery
  FeatureServer metadata
  GeoJSON polygon import
  Plan versioning

AL-ResultsLive
  ENR Excel postback
  AllResults + Statistics ingestion

AL-ResultsCertified
  Year-page XLSX/PDF discovery
  Certification workbooks
  Precinct ZIP archive
```

---

# 10. Recommended Implementation Order

1. **Build `AL-Elections`.**
   Parse the year page and create official election records from headings/dates.

2. **Build `AL-FCPA` discovery and detail ingestion.**
   Limit initial Core coverage to federal and state offices. Store records as provisional.

3. **Validate and build `AL-Certifications`.**
   Start with one primary state certification, one amended certification, and one general-election certification.

4. **Implement FCPA → certification reconciliation.**
   Promote matched candidates to ballot-certified and retain unmatched provisional records.

5. **Build congressional and Senate `AL-Districts`.**
   Import every captured plan version and require an explicit effective-plan association.

6. **Capture House and State Board of Education FeatureServer IDs.**
   Add those geometries before claiming complete state-office district coverage.

7. **Index sample ballots.**
   Validate federal/state ballot names first; add county/local contests as enhanced coverage.

8. **Build the existing ENR results adapter.**
   Use the statewide workbook and per-county Statistics rows.

9. **Build certified-result reconciliation.**
   Preserve unofficial history and compare against final state files.

10. **Inspect precinct ZIP schemas.**
    Add precinct-level ingestion only after format families are documented.

---

# 11. Risks and Open Questions

## Stage 1

- Candidate-certification PDF schemas still need representative downloads and parser tests.
- FCPA export formats are advertised but were not downloaded in the HAR.
- Determine whether a larger FCPA `pageSize` is accepted or whether normal pagination is required.
- Determine whether FCPA election IDs remain stable and whether election-cycle membership is ever revised retroactively.
- FCPA may contain contact information that should not automatically be published.
- Sample-ballot indexes and PDFs need a focused capture.
- Confirm the authoritative precedence between amended party certification and later state certification for each election type.

## Districts

- Direct `f=geojson` output should be replay-tested.
- Capture the House and State Board of Education web-map and FeatureServer IDs.
- Determine the legally effective district plan per election; do not rely on ArcGIS visibility.
- Check ArcGIS item `modified` timestamps and retain historical plan versions before updates overwrite presentation metadata.

## Stage 2

- No ENR AUP/terms were found; review before production-scale polling.
- `ecode` discovery remains election-specific.
- Mid-count behavior was not captured; the tested election was fully reported.
- Precinct ZIP internal schemas remain unverified.

---

# 12. HAR Inventory

| HAR | Captured | Primary findings |
|---|---|---|
| `www.sos.alabama.gov_Archive [26-07-18 10-38-22].har` | 2026-07-18 | 2026 election headings, candidate-certification links, sample-ballot links, result/certification documents |
| `www2.alabamavotes.gov_Archive [26-07-18 10-43-13].har` | 2026-07-18 | ENR WebForms structure, statewide Excel export, election/county IDs |
| `fcpa.alabamavotes.gov_Archive [26-07-20 12-42-17].har` | 2026-07-20 | Political Race Search JSON, lookup IDs, committee details, report-export route |
| `alabamaredistrictingplans-algeohub.hub.arcgis.com_Archive [26-07-20 13-05-20].har` | 2026-07-20 | Public ArcGIS items, congressional/Senate FeatureServers, query metadata |

---

# 13. Implementation Decision

Alabama's official sources are sufficient to support a state-source Stage 1 and Stage 2 architecture.

Use this authority chain:

```text
Election Information page
  -> creates election and discovers documents

FCPA
  -> discovers provisional candidates and race skeletons

Latest official candidate certification
  -> establishes ballot-qualified candidates

Latest sample ballot
  -> validates exact ballot presentation and adds enhanced local coverage

ArcGIS FeatureServer
  -> supplies versioned district geometry

ENR workbook
  -> supplies live/unofficial results

Certified state files
  -> establish final results
```

Google Civic, Ballotpedia, OpenStates, and other third-party sources may still enrich biographies, incumbency, campaign websites, and cross-state normalization, but they are no longer required as the primary source for Alabama election, race, candidate, district, or result creation.

## Current Coverage Tier

**Full Core Coverage (shipped 2026-07-20).** `sync_al_elections` ingests elections from the SOS year page; `sync_al_fcpa_candidates` ingests state/statewide-office races and candidates from FCPA (Governor down through State Senator/Representative — FCPA has no federal-office data) for any Election manually tagged with `source_metadata["al_fcpa_election_id"]`; `results/adapters/al.py` ingests live/unofficial results from the ENR export (shipped earlier).

Deferred to future work (see §4-§6 above): candidate-certification PDF parsing and the FCPA-provisional -> certified-ballot-qualified promotion path, sample-ballot validation, statewide ballot measures, and ArcGIS district-geometry ingestion.
