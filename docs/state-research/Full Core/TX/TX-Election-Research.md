# Texas GoElect EVR API — Research Notes

**Site:** https://goelect.txelections.civixapps.com  
**Operated by:** Texas Secretary of State  
**Researched:** March 4, 2026  
**Status:** Public, no authentication required

---

## Overview

The Texas GoElect Early Voting Report (EVR) portal is an Angular single-page application that surfaces early voting turnout data for Texas elections. Although the frontend requires JavaScript to render, all data is delivered via a simple, unauthenticated REST API that can be called directly — no browser or scraping required.

The site is a CivixApps product (`ivis-evr-ui` in the URL path). The backend is hosted on AWS (responses reference S3 for file storage).

---

## Discovery Method

The initial `web_fetch` attempts against the rendered UI routes returned either authentication errors (403) or empty SPA shells. The breakthrough came from fetching and analyzing the compiled Angular JavaScript bundle directly:

```
https://goelect.txelections.civixapps.com/ivis-evr-ui/main.77b08a58f1f7c4e1.js
```

Grepping the minified JS for API path patterns surfaced the internal base path `/api-ivis-system/api/` and revealed the service methods by name, e.g.:

```
getNewEarlyVotingTurnout(Oa.EVR_EARLYVOTING, this.electionId, this.dateFilter)
getNewEarlyVotingTurnout(Oa.EVR_STATEWIDE, this.electionId, this.dateFilter)
```

This identified both the endpoint structure and the string constants used for the `type` parameter. The enum `Oa` was defined inline in the bundle:

```
EVR_COUNTYPLACEINFO, EVR_EARLYVOTING, EVR_ELECTION,
EVR_ELECTIONDAYTURNOUT, EVR_STATEWIDE, EVR_STATEWIDE_ELECTIONDAY
```

---

## API Details

### Base URL

```
https://goelect.txelections.civixapps.com/api-ivis-system/api/v1/getFile
```

All requests are HTTP GET. No API key, session cookie, or authentication header is needed. A standard browser `User-Agent` header is sufficient (the server appears to do minimal bot filtering).

### Query Parameters

| Parameter      | Type   | Description                                         |
|----------------|--------|-----------------------------------------------------|
| `type`         | string | One of the `EVR_*` constants (see table below)      |
| `electionId`   | int    | Numeric election ID (obtained from `EVR_ELECTION`)  |
| `electionDate` | string | Date in `MM/DD/YYYY` format, URL-encoded            |

### Type Constants

| Constant                  | Data Returned                                                   | Format          |
|---------------------------|-----------------------------------------------------------------|-----------------|
| `EVR_ELECTION`            | All elections with county lists and EV date schedules           | Base64 → JSON   |
| `EVR_EARLYVOTING`         | County-level turnout for one early voting date                  | Raw JSON        |
| `EVR_STATEWIDE`           | Individual voter list for one early voting date (statewide)     | Base64 → CSV    |
| `EVR_ELECTIONDAYTURNOUT`  | County-level turnout for election day                           | Base64 → JSON   |
| `EVR_STATEWIDE_ELECTIONDAY` | Individual voter list for election day                        | Base64 → ZIP    |
| `EVR_COUNTYPLACEINFO`     | County/place metadata                                           | Base64 → JSON   |

### Response Envelope

Every response wraps data in a single-field JSON object:

```json
{ "upload": "<base64-encoded content>" }
```

The `EVR_EARLYVOTING` endpoint is an exception — it returns a raw JSON object directly (no base64 wrapping). For all other types, the `upload` field must be base64-decoded before parsing.

Decoding in Python:

```python
import base64, json

raw = response.json()["upload"]
decoded_bytes = base64.b64decode(raw)
data = json.loads(decoded_bytes.decode("utf-8"))   # for JSON types
# or just decoded_bytes.decode("utf-8")            # for CSV types
```

---

## Endpoint Reference

### 1. EVR_ELECTION — Election & Metadata Listing

**Request:**
```
GET /api-ivis-system/api/v1/getFile?type=EVR_ELECTION
```
No `electionId` or `electionDate` needed.

**Response (after base64 decode):**
```json
{
  "date_updated": "03/04/2026",
  "elections": [
    {
      "id": 53813,
      "type": "EV",
      "election_date": "03/03/2026",
      "election_name": "2026 REPUBLICAN PRIMARY ELECTION",
      "certified": false,
      "early_voting_dates": [
        { "date": "02/17/2026", "date_turnout_id": 1 },
        { "date": "02/18/2026", "date_turnout_id": 2 },
        ...
      ],
      "counties": [
        { "county_id": 1, "name": "ANDERSON" },
        ...
        { "county_id": 254, "name": "ZAVALA" }
      ]
    },
    ...
  ],
  "elections_local": []
}
```

As of March 4, 2026, the following elections were returned:

| ID    | Election Name                                         | Date       |
|-------|-------------------------------------------------------|------------|
| 53813 | 2026 REPUBLICAN PRIMARY ELECTION                      | 03/03/2026 |
| 53814 | 2026 DEMOCRATIC PRIMARY ELECTION                      | 03/03/2026 |
| 54612 | 2026 SPECIAL RUNOFF ELECTION CONGRESSIONAL DISTRICT 18| 01/31/2026 |
| 54613 | 2026 SPECIAL RUNOFF ELECTION SENATE DISTRICT 9        | 01/31/2026 |
| 51830 | 2025 SPECIAL ELECTION SENATE DISTRICT 9               | 11/04/2025 |
| 51031 | 2025 NOVEMBER 4TH CONSTITUTIONAL AMENDMENT            | 11/04/2025 |
| 51742 | 2025 SPECIAL ELECTION CONGRESSIONAL DISTRICT 18       | 11/04/2025 |

The 2026 Primary elections have 11 early voting dates each (02/17/2026 through 02/27/2026). All 254 Texas counties are listed for statewide elections; district-specific elections only list relevant counties.

---

### 2. EVR_EARLYVOTING — County-Level EV Turnout

**Request:**
```
GET /api-ivis-system/api/v1/getFile
    ?type=EVR_EARLYVOTING
    &electionId=53813
    &electionDate=02%2F17%2F2026
```

**Response (raw JSON, no base64):**
```json
{
  "date_updated": "2026-03-02",
  "election_id": 53813,
  "election_type": "P",
  "early_voting_date": "2026-02-17",
  "early_voting_date_id": 925,
  "turnout_by_county": [
    {
      "name": "ANDERSON",
      "id": 1,
      "registered_voters": 30678,
      "in_person_votes_on_date": 397,
      "total_in_person_votes_for_election": 397,
      "total_mail_votes_for_election": 1,
      "voter_details_report": " "
    },
    ...
  ]
}
```

**Field notes:**
- `in_person_votes_on_date` — votes cast specifically on the requested date
- `total_in_person_votes_for_election` — cumulative in-person votes since the first EV day
- `total_mail_votes_for_election` — cumulative mail-in ballots received
- Some counties report `null` for total fields when no votes have been cast yet
- `voter_details_report` is typically a blank string (placeholder for a PDF link in some counties)

**Statewide totals observed for 2026 Republican Primary, Feb 17, 2026 (first EV day):**

| Metric                        | Value      |
|-------------------------------|------------|
| Registered voters (statewide) | 18,657,918 |
| In-person votes on Feb 17     | 100,384    |
| Cumulative in-person          | 100,443    |
| Cumulative mail-in            | 6,945      |
| Total cumulative votes        | 107,388    |
| Turnout %                     | 0.58%      |

---

### 3. EVR_STATEWIDE — Individual Voter List (EV)

**Request:**
```
GET /api-ivis-system/api/v1/getFile
    ?type=EVR_STATEWIDE
    &electionId=53813
    &electionDate=02%2F17%2F2026
```

**Response:** Base64-encoded CSV. Decoded size is approximately **7 MB** for a statewide election on a typical early voting day.

**CSV columns:**
```
tx_county_name, voter_name, id_voter, voting_method, tx_precinct_code
```

**Sample rows:**
```
"ANDERSON","ADAMS, PAULA DIANE","1155229927","IN-PERSON","S 19.4"
"ANDERSON","ADAMS, RODNEY","1041687625","IN-PERSON","S 10.2"
"ANDERSON","BAKER, JEFFERY","2192687456","MAIL-IN","18"
```

**Notes:**
- `voting_method` values observed: `IN-PERSON`, `MAIL-IN`
- `id_voter` appears to be a stable numeric voter ID (10 digits)
- `tx_precinct_code` format varies by county — some use alphanumeric codes like `S 19.4`, others use simple integers
- This file represents all votes cast **on that specific date only**, not cumulative

---

### 4. EVR_ELECTIONDAYTURNOUT — Election Day County Turnout

**Request:**
```
GET /api-ivis-system/api/v1/getFile
    ?type=EVR_ELECTIONDAYTURNOUT
    &electionId=53813
    &electionDate=03%2F03%2F2026
```

Same county-level structure as `EVR_EARLYVOTING`. Data only populated after election day.

---

### 5. EVR_STATEWIDE_ELECTIONDAY — Election Day Individual Voter List

**Request:**
```
GET /api-ivis-system/api/v1/getFile
    ?type=EVR_STATEWIDE_ELECTIONDAY
    &electionId=53813
    &electionDate=03%2F03%2F2026
```

Returns a base64-encoded **ZIP file** (not CSV). The Angular frontend downloads and presents it as a ZIP download to the user.

---

## Error Handling

When required parameters are missing or malformed, the API returns an error envelope:

```json
{
  "type": "EXCEPTION",
  "errorModels": [{
    "code": null,
    "detail": "software.amazon.awssdk.core.exception.SdkClientException: Unable to marshall request to JSON: Parameter 'Key' must not be null",
    "message": "...",
    "params": null
  }]
}
```

This error means a required query parameter was missing or the resulting S3 object key could not be constructed (e.g., `electionDate` omitted). Always supply all three parameters for data requests.

When an early voting date has no data yet (date hasn't occurred or county hasn't reported), `EVR_EARLYVOTING` returns an empty response body or a JSON object with empty `turnout_by_county`. The `EVR_STATEWIDE` endpoint returns an `upload` field that decodes to an empty string.

---

## Additional Endpoint

A separate lookup endpoint was also found in the bundle:

```
GET /api-ivis-system/api/lookup?txName=<name>
```

This returned an empty array `[]` for the values tested (`election`, `county`) and may require specific `txName` values that are only used internally by the UI. It does not appear necessary for data extraction.

---

## Implementation Notes

### Date Format

The `electionDate` parameter must be `MM/DD/YYYY` and URL-encoded (`/` → `%2F`). The ISO format `YYYY-MM-DD` was tested and returns an S3 key error. The response metadata uses ISO format internally (`"early_voting_date": "2026-02-17"`) but the request parameter must use the slash format.

### Polling / Rate Limiting

No rate limiting was observed during testing. The data is served via S3 (likely CloudFront CDN in front), so repeated identical requests are probably cached. For production use, polling once per hour per date is a reasonable cadence during early voting periods.

### File Sizes

| Data Type              | Approx. Size |
|------------------------|--------------|
| EVR_ELECTION (metadata)| ~120 KB      |
| EVR_EARLYVOTING        | ~50 KB       |
| EVR_STATEWIDE (CSV)    | ~7 MB        |
| EVR_STATEWIDE_ELECTIONDAY (ZIP) | Unknown (not tested) |

---

## Provided Module

`tx_goelect.py` — A self-contained Python client implementing all of the above. Works with the standard library only (`urllib`) but will use `requests` if installed. Key methods:

| Method | Description |
|--------|-------------|
| `get_elections()` | List all elections and their metadata |
| `get_election_by_id(id)` | Look up a single election dict |
| `get_ev_dates(election_id)` | List available EV dates for an election |
| `get_ev_turnout(election_id, date)` | County-level turnout for one EV date |
| `get_all_ev_turnout(election_id)` | Turnout for all EV dates (full sweep) |
| `get_statewide_voter_list(election_id, date)` | Individual voter CSV |
| `get_electionday_turnout(election_id, date)` | Election-day county turnout |
| `get_statewide_totals(election_id, date)` | Aggregated statewide summary dict |
| `print_turnout_summary(election_id, date)` | Pretty-printed console summary |