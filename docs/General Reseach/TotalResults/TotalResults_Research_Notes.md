# TotalResults Research Notes

## Objective

Investigate the TotalResults Election Night Reporting (ENR) platform, identify valid client IDs (`cId` values), understand API usage, and determine effective discovery methods for additional jurisdictions.

---

## Confirmed Public Endpoints

Base API:

```text
https://enr-results-api.totalresults.com
```

Confirmed endpoints observed from Arkansas deployment:

```text
/Election/GetElectionList?cId=arkansas
/Election/GetElectionInfo?cId=arkansas
/Contest/GetContestSearchList?cId=arkansas
/Contest/GetContestResults?cId=arkansas&electionID=<id>
/Turnout/GetTurnout?cId=arkansas&electionID=<id>
```

---

## Arkansas Findings

Confirmed working:

```text
https://enr.totalresults.com/arkansas
```

Confirmed API call:

```text
https://enr-results-api.totalresults.com/Election/GetElectionList?cId=arkansas
```

Returns election data from 2012 through 2026.

Example:

```json
{
  "electionID": "b412bdef-f97a-45bc-b3ec-6761d28caf9e",
  "electionName": "2026 Primary Runoff",
  "electionDate": "2026-03-31T00:00:00",
  "isDefault": true
}
```

Observations:

- Recent elections use GUID-based election IDs.
- Older elections use numeric election IDs.
- Platform appears to have migrated identifier formats sometime after 2024.

---

## Initial Enumeration Results

Tested:

- All US state abbreviations
- Common county names
- Miscellaneous guesses

Example:

```text
al
ak
az
...
pulaski
saline
benton
demo
test
```

Result:

```text
No valid clients discovered.
```

Reason:

The platform does not appear to use state abbreviations as client identifiers.

---

## State Name Enumeration

Tested full state names:

```text
alabama
alaska
arizona
arkansas
...
wyoming
```

Output:

```text
CLIENT               COUNT    SAMPLE
arkansas             22       Special Primary House 44
```

Only Arkansas produced election data.

---

## HAR Analysis Findings

Network capture revealed:

### Configuration File

```text
https://enr.totalresults.com/arkansas/config.json
```

Example:

```json
{
  "client": "Arkansas",
  "clientStateId": "arkansas",
  "clientCountyId": "",
  "isCountyClient": false,
  "azureDeploymentPath": "/arkansas",
  "basePath": "/arkansas/"
}
```

Important discovery:

The deployment is configuration-driven.

The application loads configuration from:

```text
https://enr.totalresults.com/<deployment>/config.json
```

This suggests every deployment likely has its own configuration path.

---

## Front-End Architecture

The front-end appears to:

1. Read deployment path from URL.
2. Load `config.json`.
3. Extract `clientStateId`.
4. Use that value as the API `cId`.

Conceptual flow:

```text
Browser
   |
   +--> /arkansas/config.json
              |
              +--> clientStateId = arkansas
                           |
                           +--> API calls use cId=arkansas
```

---

## Discovery Strategy Recommendations

### Preferred Method

Instead of brute-forcing API client IDs:

```text
GetElectionList?cId=<guess>
```

Enumerate deployment paths:

```text
https://enr.totalresults.com/<candidate>/config.json
```

A valid configuration file is a stronger signal than an empty election list.

---

### Inspect Public Deployments

Search for:

```text
site:enr.totalresults.com
```

or references to:

```text
enr.totalresults.com
```

Every discovered deployment may reveal:

- deployment path
- clientStateId
- clientCountyId
- API configuration

---

### JavaScript Bundle Review

Potentially useful strings:

```text
clientId
clientStateId
cId
GetElectionList
GetElectionInfo
Contest
Turnout
```

The front-end bundles may contain additional clues about deployment naming conventions.

---

## CivicMirror Adapter Notes

The Arkansas deployment provides everything required to build a reusable TotalResults adapter.

Required endpoints:

```text
GetElectionList
GetElectionInfo
GetContestSearchList
GetContestResults
GetTurnout
```

The adapter should be configurable by:

```text
cId
electionID
```

Any future TotalResults jurisdiction discovered should be compatible with the same ingestion code by changing only the client identifier.

---

## Key Conclusions

1. Arkansas is a confirmed TotalResults statewide deployment.
2. `cId=arkansas` is valid and public.
3. Full-state-name enumeration found only Arkansas.
4. The platform is configuration-driven.
5. `config.json` is a valuable discovery target.
6. Discovering deployment paths is likely more effective than brute-forcing client IDs.
7. The Arkansas deployment provides a complete reference implementation for building a TotalResults adapter.
