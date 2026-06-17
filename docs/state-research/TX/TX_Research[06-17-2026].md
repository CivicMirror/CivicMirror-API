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
| 58315 | 2026 REPUBLICAN PRIMARY RUNOFF ELECTION | RU | SW | Certified (May 26, 2026; 70 versions; 254/254 counties) |
| 58314 | 2026 DEMOCRATIC PRIMARY RUNOFF ELECTION | RU | SW | Certified (May 26, 2026; 74 versions; 254/254 counties) |
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

**November 2026 General Election:** Not yet present in `electionConstants` as of June 17, 2026. Based on the runoff version counts (70–74 at certification), elections appear to be loaded into the ENR system approximately 30–60 days before election day. Expect the General to appear around September–October 2026. See [Monitoring for New Elections](#monitoring-for-new-elections) below.

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

## Pre-Election Seeding — Candidate & Race Data

**The `Lookups` field is populated as soon as an election is registered**, not just on election night. This was confirmed by live-querying the two May 26 Primary Runoff elections: both returned complete `Lookups`, `Race`, and `OfficeSummary` data (with zero vote totals) prior to their election date. The data is fully usable for Stage 1 seeding.

Fields available pre-election from `/enr/election/{id}`:

| Field | Pre-Election Content |
|-------|---------------------|
| `Lookups.Candidates` | Full roster — ID, full name, first/last split |
| `Lookups.Office` | All offices — ID, name, type, district number |
| `Lookups.OfficeType` | Federal, Statewide, District, County Wide, County Race, Propositions |
| `Lookups.County` | All counties with internal ID + FIPS via `MID` |
| `Race.OfficeTypes[]` | Race IDs grouped by office type |
| `OfficeSummary.OS[]` | Per-race candidate list (vote totals zero until election night) |
| `Home.ElecDate` | Election date in `MMDDYYYY` format |

**EVR has no candidate data.** Confirmed: the EVR `EVR_ELECTION` response only contains `id`, `election_date`, `election_name`, `certified`, `early_voting_dates`, and `counties`. Races and candidates are exclusively in the ENR system.

**SOS Candidate Guide** (`/elections/candidates/index.shtml`, `/elections/candidates/guide/2026/`) is static HTML only — no machine-readable filings data. All machine-readable candidate data flows through the ENR `Lookups` field.

---

## Monitoring for New Elections

Unknown election IDs return `{"Version": ""}` with HTTP 200 — not a 404. This makes sequential probing viable for catching new elections the moment they're registered, without waiting for `electionConstants` polling to catch them.

**Strategy:** Poll `electionConstants` daily. When a `GE` key appears under `2026`, immediately pull its `Lookups` to seed races and candidates. Expected window: September–October 2026 for the November 4 General.

**ID range to probe:** Current known IDs top out at 58315. November General IDs are likely in the 59000–63000 range based on spacing. An unknown ID returns `{"Version": ""}` (empty string); a live election returns `{"Version": "enr/{id}/{n}/"}` with `n > 0`. Detection logic:

```python
def probe_election(election_id):
    """Returns True if this election ID is live in the ENR system."""
    r = requests.get(f"{BASE}/election/{election_id}", headers=HEADERS)
    return bool(r.json().get("Version", ""))
```

---

## May 26, 2026 Primary Runoff Results

Both runoffs certified with 254/254 counties reporting. Notable statewide and federal races:

### Republican Runoff (ID 58315) — 157 races, 314 candidates

| Race | Winner | % | Runner-up | % |
|------|--------|---|-----------|---|
| U.S. Senator | Ken Paxton | 63.8% | John Cornyn (I) | 36.2% |
| Attorney General | Mayes Middleton | 55.2% | Chip Roy | 44.8% |
| Railroad Commissioner | Bo French | 50.5% | Jim Wright (I) | 49.5% |
| Ct. of Criminal Appeals Pl. 3 | Thomas Smith | 58.1% | Alison Fox | 41.9% |
| U.S. Rep. District 19 | Tom Sell | 64.3% | Abraham Enriquez | 35.7% |

*Last updated in ENR: Jun 12, 2026 19:23:34*

### Democratic Runoff (ID 58314) — 80 races, 160 candidates

| Race | Winner | % | Runner-up | % |
|------|--------|---|-----------|---|
| Lieutenant Governor | Vikki Goodwin | 67.8% | Marcos Isaias Velez | 32.2% |
| Attorney General | Nathan Johnson | 60.5% | Joe Jaworski | 39.5% |
| U.S. Rep. District 18 | Christian D. Menefee | 69.3% | Al Green | 30.7% |
| U.S. Rep. District 33 | Colin Allred | 54.0% | Julie Johnson | 46.0% |
| U.S. Rep. District 14 | Thurman Bill Bartie | 51.0% | Richard H. Davis | 49.0% |
| U.S. Rep. District 5 | Chelsey Hockett | 53.0% | Ruth "Truth" Torres | 47.0% |
| U.S. Rep. District 35 | Johnny C. Garcia | 63.8% | Maureen Galindo | 36.2% |

*Last updated in ENR: Jun 17, 2026 00:57:03*

Early votes (`EV` field) consistently accounted for roughly 60–65% of total votes in both runoffs.

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
| **Candidate/race data** | **None** | **Yes — via `Lookups` field, available pre-election** |
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

Seed `Race`, `Candidate`, and `Office` records before election night. The `Lookups` field is fully populated the moment the election appears in the system — no need to wait for results to start flowing.

```python
def discover_and_seed(db):
    constants = get_elections()
    for year, types in constants["electionInfo"].items():
        for etype, elections in types.items():
            for eid, meta in elections.items():
                if meta["O"] == "N":      # offline / not yet published
                    continue
                if db.election_known(eid):
                    continue              # already seeded
                
                result = get_election_results(int(eid))
                lookups = result["lookups"]
                
                db.upsert_election(eid, meta, result["home"])
                db.upsert_candidates(lookups["Candidates"])    # ID, BN (full name)
                db.upsert_offices(lookups["Office"])           # ID, ON, OT, SSO (district)
                db.upsert_races(result["race"]["OfficeTypes"]) # race ID → office type
                # Counties: lookups["County"] has ID + MID (FIPS) — likely already in DB
```

**Timing gap:** The November 2026 General Election is not in the system as of June 17. Monitor `electionConstants` daily starting in August; also probe the ID range 59000–63000 with `probe_election()` (see Monitoring section). Once detected, `discover_and_seed()` runs and the full candidate roster drops in immediately.

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
| 58314 | 2026 Democratic Primary Runoff | 05/26/2026 | 80 races, 160 candidates; Johnson won AG 60.5% |
| 58315 | 2026 Republican Primary Runoff | 05/26/2026 | 157 races, 314 candidates; Paxton won Senate 63.8% |
| 51031 | 2025 November Constitutional Amendment | 11/04/2025 | Statewide |
| 51830 | 2025 Special Election — SD9 | 11/04/2025 | District-only |
| 51742 | 2025 Special Election — CD18 | 11/04/2025 | District-only |
| TBD | 2026 General Election | 11/03/2026 | Not yet in system; probe ID range 59000–63000 starting ~Aug 2026 |

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
    """Returns the integer update counter, or None if election not yet live."""
    r = requests.get(f"{BASE}/election/{election_id}", headers=HEADERS)
    version_str = r.json().get("Version", "")   # unknown IDs return {"Version": ""}
    if not version_str:
        return None
    return int(version_str.split("/")[2])        # e.g. "enr/53813/135/" → 135

def probe_election(election_id):
    """Returns True if this election ID is live in the ENR system."""
    return get_version_number(election_id) is not None

def discover_and_seed(db):
    """Pull electionConstants, seed any new elections with candidate/race data."""
    constants = get_elections()
    for year, types in constants["electionInfo"].items():
        for etype, elections in types.items():
            for eid, meta in elections.items():
                if meta["O"] == "N":      # offline / not yet published
                    continue
                if db.election_known(eid):
                    continue              # already seeded
                result = get_election_results(int(eid))
                lookups = result["lookups"]
                db.upsert_election(eid, meta, result["home"])
                db.upsert_candidates(lookups["Candidates"])
                db.upsert_offices(lookups["Office"])
                db.upsert_races(result["race"]["OfficeTypes"])
```
