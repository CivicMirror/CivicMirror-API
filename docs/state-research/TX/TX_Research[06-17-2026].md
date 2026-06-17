# Texas GoElect ENR API — Research Notes

**Site:** https://goelect.txelections.civixapps.com/ivis-enr-ui/
**Also visited:** https://www.sos.state.tx.us (note: correct URL is `sos.state.tx.us`, not `sos.texas.gov`)
**Operated by:** Texas Secretary of State
**Vendor:** CivixApps (same platform as EVR — see TX-Election-Research.md)
**Researched:** June 17, 2026
**Status:** Public, no authentication required for API calls

---

## Overview

This document covers the **Election Night Results (ENR)** system — a completely separate CivixApps application from the Early Voting Report (EVR) system documented in `TX-Election-Research.md`. Both apps share the same domain and API gateway (`/api-ivis-system/`) but use entirely different paths, response schemas, and frontend bundles.

| System | UI Path | API Path | Data |
|--------|---------|----------|------|
| EVR (prior research) | `/ivis-evr-ui/` | `/api-ivis-system/api/v1/getFile` | Early voting turnout + individual voter lists |
| **ENR (this doc)** | `/ivis-enr-ui/` | `/api-ivis-system/api/s3/enr/` | Election night race results by candidate + county |

The ENR system is Angular + AWS S3-backed. It uses an AWS Cognito Identity Pool for the frontend's S3 SDK access (unauthenticated guest credentials), but the proxy API endpoints themselves require no credentials and work with standard browser headers.

---

## Cloudflare Status

The ENR site sits behind Cloudflare. HAR shows both `__cf_bm` and `cf_clearance` cookies present on requests, and response headers confirm `server: cloudflare` with `cf-cache-status: DYNAMIC`. However, the challenge appears passive — a normal browser session resolves it automatically. For automated ingestion, standard `requests` with a browser User-Agent succeeded during this session with no active bot challenge observed. Monitor for future tightening.

---

## Election Inventory (as of June 17, 2026)

Obtained from `/api-ivis-system/api/s3/enr/electionConstants`.

### 2026 Elections

| ID | Election Name | Type | Scope | Status |
|----|---------------|------|-------|--------|
| 53813 | 2026 REPUBLICAN PRIMARY ELECTION | P | SW | Certified (135 result versions) |
| 53814 | 2026 DEMOCRATIC PRIMARY ELECTION | P | SW | Certified |
| **58315** | **2026 REPUBLICAN PRIMARY RUNOFF ELECTION** | **RU** | **SW** | **New since March HAR** |
| **58314** | **2026 DEMOCRATIC PRIMARY RUNOFF ELECTION** | **RU** | **SW** | **New since March HAR** |
| 56181 | 2026 SPECIAL ELECTION SENATE DISTRICT 4 | S | PS | Final (May 2, 2026) |
| 54613 | 2026 SPECIAL RUNOFF ELECTION SENATE DISTRICT 9 | SR | PS | Final |
| 54612 | 2026 SPECIAL RUNOFF ELECTION CONGRESSIONAL DISTRICT 18 | SR | PS | Final |

### 2025 Elections (archived)

| ID | Election Name | Type | Scope |
|----|---------------|------|-------|
| 51031 | 2025 NOVEMBER 4TH CONSTITUTIONAL AMENDMENT | S | SW |
| 51830 | 2025 SPECIAL ELECTION SENATE DISTRICT 9 | S | PS |
| 51742 | 2025 SPECIAL ELECTION CONGRESSIONAL DISTRICT 18 | S | PS |

**Election type codes:** `P` = Primary, `RU` = Primary Runoff, `GE` = General, `S` = Special, `SR` = Special Runoff, `GR` = General Runoff  
**Scope codes:** `SW` = Statewide, `PS` = Partial/District

The `O` field in the constants payload indicates whether results are online (`"Y"`) or offline (`"N"`).

---

## API Endpoints

### Base URL

```
https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/
```

All requests are HTTP GET, unauthenticated, standard browser User-Agent.

---

### 1. Election Constants

```
GET /api-ivis-system/api/s3/enr/electionConstants
```

Returns the full election index: all election IDs, names, types, years, and scope codes. No parameters needed. Use this as the discovery endpoint to enumerate available elections.

**Response:** `{"upload": "<base64>"}` → decode to the election constants structure.

```python
import base64, json, requests

resp = requests.get(
    "https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/electionConstants"
)
data = json.loads(base64.b64decode(resp.json()["upload"]))
elections = data["electionInfo"]  # nested by year → type code → election ID
```

**Decoded top-level structure:**

```json
{
  "electionInfo": {
    "2026": {
      "P":  { "53813": {...}, "53814": {...} },
      "RU": { "58315": {...}, "58314": {...} },
      "S":  { "56181": {...} },
      "SR": { "54613": {...}, "54612": {...} }
    },
    "2025": { ... }
  },
  "electionType": { "GE": "GENERAL ELECTION", "P": "PRIMARY", ... },
  "currentelectionInfo": { ... }
}
```

---

### 2. Election Results

```
GET /api-ivis-system/api/s3/enr/election/{electionId}
```

Returns the full election-night results payload for one election. No query parameters — just the integer election ID in the path.

**Response:** Direct JSON (no `upload` wrapper). Each value field is independently base64-encoded JSON:

```json
{
  "Version": "enr/56181/21/",
  "Home": "<base64>",
  "Lookups": "<base64>",
  "Race": "<base64>",
  "OfficeSummary": "<base64>",
  "Federal": "<base64>",
  "StateWide": "<base64>",
  "StateWideQ": "<base64>",
  "Districted": "<base64>",
  "ReportList": "<base64>"
}
```

Each sub-field must be decoded independently:

```python
def decode_field(data, field):
    return json.loads(base64.b64decode(data[field]).decode("utf-8"))
```

**Sub-field reference:**

| Field | Description | Null When |
|-------|-------------|-----------|
| `Version` | S3 path version string: `enr/{id}/{n}/` — `n` increments each update | Never |
| `Home` | Election summary: date, counties reporting, precincts reporting, last update | Never |
| `Lookups` | Master tables: candidates, office types, offices, counties (with FIPS codes) | Never |
| `Race` | Office type → race index (IDs + names only, no vote totals) | Never |
| `OfficeSummary` | Per-office candidate totals sorted by placement | Never |
| `Federal` | Full federal race results with candidate vote data | District elections |
| `StateWide` | Full statewide office race results | District elections |
| `StateWideQ` | Statewide ballot propositions | No propositions |
| `Districted` | District-level race results | Statewide elections |
| `ReportList` | Available downloadable canvass/turnout report metadata | Never |

**`Home` decoded:**

```json
{
  "ElecDate": "05022026",
  "CountiesReporting": { "CR": 5, "CT": 5 },
  "LastUpdatedTime": "May 15, 2026 17:21:41",
  "RefreshTime": 5,
  "PrecinctsReporting": { "PR": 45, "PT": 122 },
  "PollingReporting": { "PLR": 112, "PLT": 112 }
}
```

Fields: `CR` = counties reporting, `CT` = counties total, `PR` = precincts reporting, `PT` = precincts total, `PLR` = polling places reporting, `PLT` = polling places total.

**`Lookups` decoded (county subfield — note FIPS codes via `MID`):**

```json
{
  "County": [
    { "ID": 1, "CN": "ANDERSON", "MID": 48001 },
    { "ID": 84, "CN": "GALVESTON", "MID": 48167 },
    { "ID": 101, "CN": "HARRIS", "MID": 48201 },
    ...
  ],
  "Candidates": [ { "ID": 36388, "BN": "BRETT W. LIGON" }, ... ],
  "Office": [ { "ID": 5031, "ON": "STATE SENATOR, DISTRICT 4 - UNEXPIRED TERM", "OT": 1442, "SO": 50, "SSO": 4 } ],
  "OfficeType": [ { "ID": 510, "OT": "FEDERAL OFFICES" }, ... ]
}
```

`MID` is the 5-digit FIPS county code (48001, 48167, etc.) — directly usable for FIPS joins. `SO` in Office is the sort order; `SSO` is the district number.

**Candidate fields (within race results):**

| Field | Meaning |
|-------|---------|
| `ID` | Candidate ID |
| `N` | Full name |
| `LN` / `FN` | Last / first name |
| `P` | Party code (`DEM`, `REP`) |
| `V` | Total votes |
| `EV` | Early votes (subset of total) |
| `PE` | Percentage of total |
| `C` | Hex color for UI display |
| `O` | Sort/display order |

**`Version` field significance:** The integer `n` in `enr/{id}/{n}/` increments each time the results file is updated in S3. Stale polling can be detected by caching this field. The Republican Primary (53813) shows version 135 after certification; the May 2 special election (56181) shows version 21.

---

### 3. County-Level Results

```
GET /api-ivis-system/api/s3/enr/election/countyInfo/{electionId}
```

Returns per-county breakdowns for all races in the election. Keyed by CivixApps county ID (same as `Lookups.County[].ID` — **not** FIPS; join via `MID` for FIPS).

**Response:** `{"upload": "<base64>"}` wrapper — same decode pattern as `electionConstants`.

**Decoded structure:**

```json
{
  "101": {
    "N": "HARRIS",
    "TV": 7881,
    "C": "#19b90f",
    "Races": {
      "5031": {
        "OID": 5031,
        "N": "STATE SENATOR, DISTRICT 4 - UNEXPIRED TERM",
        "T": 7881,
        "C": {
          "36388": { "id": 36388, "N": "BRETT W. LIGON", "P": "REP", "V": 5757, "PE": 73.05, "EV": 4394, "O": 2 },
          "36422": { "id": 36422, "N": "RON C. ANGELETTI", "P": "DEM",  "V": 2124, "PE": 26.95, "EV": 1472, "O": 1 }
        },
        "OT": "SR",
        "PR": 75,
        "TP": 75,
        "OTRV": 221764
      }
    },
    "Summary": {
      "PRR": 75.0, "PRP": 75.0, "P": 100.0,
      "RV": 221764.0, "VC": 7883.0, "VT": 3.55,
      "NPL": 28.0, "PLR": 28.0, "PLP": 100.0
    }
  },
  ...
}
```

**Summary field reference:**

| Field | Meaning |
|-------|---------|
| `PRR` | Precincts reporting (count) |
| `PRP` | Precincts total (count) |
| `P` | Precincts reporting (percentage) |
| `RV` | Registered voters |
| `VC` | Votes cast |
| `VT` | Voter turnout percentage |
| `NPL` | Number of polling locations |
| `PLR` | Polling locations reporting |
| `PLP` | Polling locations reporting (percentage) |

**Race field reference (within county races):**

| Field | Meaning |
|-------|---------|
| `OID` | Office ID (joins to `Lookups.Office`) |
| `T` | Total votes for this race in this county |
| `OT` | Office type code |
| `O` | Sort order |
| `SO` | District/sub-order |
| `PR` | Precincts reporting |
| `TP` | Precincts total |
| `OTRV` | Total registered voters in this office's district |
| `TV` | Provisional/uncounted votes (usually 0 until canvass) |
| `TPR` | Total precincts (duplicate of TP in observed data) |

**File size observed:** countyInfo/53813 (statewide Republican Primary) is approximately 5.3 MB, making it the largest single pull. District/special elections are ~800 bytes to ~4 KB.

---

## Cognito Identity Pool (Frontend Only — Not Required for API)

The ENR Angular app calls AWS Cognito to obtain temporary S3 SDK credentials for frontend S3 access:

```
POST https://cognito-identity.us-east-1.amazonaws.com/
X-Amz-Target: AWSCognitoIdentityService.GetCredentialsForIdentity

{"IdentityId": "us-east-1:2e250654-3097-c1f6-6d4a-4be07a808478"}
```

The response contains `AccessKeyId`, `SecretKey`, and `SessionToken`. These are used by the `aws-sdk-2.903.0.min.js` embedded in the frontend to talk to S3 directly.

**These credentials are not needed for CivicMirror ingestion.** The `/api-ivis-system/api/s3/enr/` proxy endpoints are fully public. The Cognito flow is purely a frontend concern — the Angular app uses it to serve rich S3 paths not exposed by the proxy, but all result data needed for election ingestion flows through the documented proxy endpoints.

---

## Comparison with EVR System

| | EVR (Early Voting Reports) | ENR (Election Night Results) |
|---|---|---|
| UI bundle | `ivis-evr-ui` | `ivis-enr-ui` |
| API base | `/api-ivis-system/api/v1/getFile` | `/api-ivis-system/api/s3/enr/` |
| Auth | None | None (Cognito is frontend-only) |
| Query style | Query params (`?type=&electionId=&electionDate=`) | Path-based (`/enr/election/{id}`) |
| Response wrapper | `{"upload": "<base64>"}` for most | Mixed: direct JSON with b64 sub-fields, or `upload` wrapper |
| Data scope | Turnout by date + individual voter lists | Race results: candidates, vote totals, county breakdown |
| Data cadence | New file per EV date | Live updates during election night (RefreshTime: 5s) |
| Statewide voter list | Yes (EVR_STATEWIDE CSV, ~7 MB) | No |
| Election-day voter list | Yes (EVR_STATEWIDE_ELECTIONDAY ZIP) | No |
| County granularity | County totals by EV date | County totals + precinct reporting rates |

---

## Two-Stage Ingestion Plan for CivicMirror

### Stage 1 — Pre-election seeding (from ENR `electionConstants`)

Pull `/enr/electionConstants` to discover new election IDs and metadata. For each new election, pull `/enr/election/{id}` and extract from `Lookups`:
- Candidate list with IDs, names, parties
- Office list with names, types, district numbers
- County list with internal IDs and FIPS codes via `MID`
- Race list from `Race.OfficeTypes[]`

Seed `Race`, `Candidate`, and `Office` records before election night.

### Stage 2 — Results ingestion (on/after election night)

Poll `/enr/election/{id}` and `/enr/election/countyInfo/{id}` periodically. Check the `Version` field — if the integer `n` in `enr/{id}/{n}/` is unchanged since last poll, skip reprocessing.

Parse `Home` for top-level reporting status. Parse `OfficeSummary` for race-level totals. Parse `countyInfo` for per-county breakdowns by race and candidate.

**Recommended polling cadence:**
- During election night: every 5 minutes (matches `RefreshTime` hint)
- Post-night certification period: once per hour
- After `Home.CountiesReporting.CR == CT` and precincts fully reported: switch to daily until certified

---

## SOS.state.tx.us Links of Interest

The SOS homepage (`www.sos.state.tx.us`, not `sos.texas.gov`) links to these election sections:

| Path | Content |
|------|---------|
| `/elections/index.shtml` | Elections division landing page |
| `/elections/voter/current.shtml` | Current election results (links to ENR + EVR) |
| `/elections/historical/index.shtml` | Historical election results |
| `/elections/candidates/index.shtml` | Candidate filing information |
| `/elections/laws/votingsystems.shtml` | Voting systems certifications |
| `/elections/conducting/index.shtml` | County election administration resources |

The SOS site itself is not the data source — it links out to `goelect.txelections.civixapps.com`. All machine-readable data flows through the CivixApps endpoints above.

---

## Known Election IDs Quick Reference

| ID | Name | Election Date | Notes |
|----|------|---------------|-------|
| 53813 | 2026 Republican Primary | 03/03/2026 | Statewide; version 135 |
| 53814 | 2026 Democratic Primary | 03/03/2026 | Statewide |
| 54612 | 2026 Special Runoff — CD18 | 01/31/2026 | Harris Co. only; Menefee 68.9% |
| 54613 | 2026 Special Runoff — SD9 | 01/31/2026 | District-only |
| 56181 | 2026 Special Election — SD4 | 05/02/2026 | 5 counties; Ligon 73% in Harris |
| 58314 | 2026 Democratic Primary Runoff | TBD | New — no results yet |
| 58315 | 2026 Republican Primary Runoff | TBD | New — no results yet |
| 51031 | 2025 November Constitutional Amendment | 11/04/2025 | Statewide |
| 51830 | 2025 Special Election — SD9 | 11/04/2025 | District-only |
| 51742 | 2025 Special Election — CD18 | 11/04/2025 | District-only |

---

## Python Client Sketch

```python
import base64, json, requests

BASE = "https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def b64d(s):
    return json.loads(base64.b64decode(s).decode("utf-8"))

def get_elections():
    r = requests.get(f"{BASE}/electionConstants", headers=HEADERS)
    return b64d(r.json()["upload"])["electionInfo"]

def get_election_results(election_id):
    r = requests.get(f"{BASE}/election/{election_id}", headers=HEADERS)
    data = r.json()
    return {
        "version": data["Version"],
        "home": b64d(data["Home"]),
        "lookups": b64d(data["Lookups"]),
        "race": b64d(data["Race"]),
        "office_summary": b64d(data["OfficeSummary"]),
        "federal": b64d(data["Federal"]),
        "statewide": b64d(data["StateWide"]),
        "statewide_q": b64d(data["StateWideQ"]),
        "districted": b64d(data["Districted"]),
        "report_list": b64d(data["ReportList"]),
    }

def get_county_results(election_id):
    r = requests.get(f"{BASE}/election/countyInfo/{election_id}", headers=HEADERS)
    return b64d(r.json()["upload"])

def get_version_number(election_id):
    """Returns the integer update counter from the Version string."""
    r = requests.get(f"{BASE}/election/{election_id}", headers=HEADERS)
    version_str = r.json()["Version"]          # e.g. "enr/53813/135/"
    return int(version_str.split("/")[2])
```
