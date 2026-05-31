# Arkansas Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ✅ **Open REST API** | **TotalResults.com** ENR — public JSON API, no auth, no bot wall, official/certified data. Adapter is straightforward. |

---

**Primary source (current ENR):** https://enr.totalresults.com/arkansas
**Results API:** https://enr-results-api.totalresults.com
**SOS portal:** https://www.sos.arkansas.gov/elections/research/election-results
**Operated by:** Arkansas Secretary of State (ENR vendor: TotalResults.com)
**Researched:** March 4, 2026
**Updated:** May 31, 2026 — new vendor (TotalResults) identified; open API verified; Stage 2 resolved
**Status:** Public, no authentication required

---

## Overview

Arkansas migrated its election-night reporting (ENR) from **Clarity/Scytl** to a new vendor, **TotalResults.com**, for the 2024/2026 era. The transition is the cause of the "results temporarily unavailable for download" banner on the SOS site. Three data layers exist:

1. **Current ENR — TotalResults open JSON API** (2024/2026 forward). *This is the recommended Stage 2 source — clean, ungated, official.*
2. **Legacy ENR — Clarity/Scytl** (`results.enr.clarityelections.com/AR/...`, through ~2022). Akamai-gated; avoid (same situation as Kentucky's Clarity).
3. **SOS bulk archives** — ZIP/PDF downloads by county and polling location (historical; partially unavailable during transition).

---

## Current ENR — TotalResults.com (RECOMMENDED)

- **Public UI:** `https://enr.totalresults.com/arkansas` (and `/arkansas/{county}`, e.g. `/arkansas/pulaski`)
  - Azure-hosted Vite/React SPA. Returns HTTP 200 to plain requests — **no Akamai, no bot wall, no acceptable-use gate.**
- **Results API base:** `https://enr-results-api.totalresults.com`
  - **No authentication required.** Verified live with `cId=arkansas`.
  - Backend appears to be ASP.NET (RFC9110 validation-error responses).
  - Called server-side from Django → CORS is irrelevant.
- **Client ID (`cId`):** `arkansas`

### API Endpoints

Base: `https://enr-results-api.totalresults.com`

| Endpoint | Params | Returns |
|---|---|---|
| `Election/GetElectionList` | `cId` | Array of `{electionID (GUID), electionName, electionDate, isDefault}` |
| `Election/GetElectionInfo` | `cId`, `electionID` | Metadata + `turnout` + `contestTypes` + `isOfficial`, `versionID`, `lastUpdated` |
| `Contest/GetContestSearchList` | `cId`, `electionID` | Contests keyed by GUID + candidate `choices` |
| `Contest/GetContestResults` | `cId`, `electionID`, `contestType` (`Federal`/`State`/…), opt. `locationId`, `code` | Vote tallies per contest & choice |
| `Contest/GetSingleContestResults` | `cId`, `electionID`, … | Single contest detail |
| `Contest/GetContestRecountResults` | `cId`, `electionID`, opt. `locationID`, `code` | Recount results |
| `Turnout/GetTurnout` | `cId`, `electionID` | Turnout by jurisdiction |

Optional: `&locationId={countyId}` for county-level results (contests expose `hasLocationResults:true`); `&code={district}` for districted contests.

Also present (not needed for ingestion): GIS/boundary API at `enr-data.azureedge.us` and `enr-prod-public.s3.us-east-1.amazonaws.com` (uses Bearer auth; map polygons only). A bulk `…/results/{client}/{electionID}/FullDataFile.json` exists on S3 but the client path segment is not the `arkansas` slug (403) — the live API is the better path.

### Response shape (observed)

`GetElectionInfo` / `GetContestResults` envelope:
```
{
  "versionID": "v3313",
  "lastUpdated": "2026-04-29T16:34:17Z",
  "electionID": "7f77a178-...",
  "isOfficial": true,                // certified flag
  "turnout": { "registeredVoters": 1802792, "precinctsReporting": 2897,
               "totalPrecincts": 2897, "totalBallotsCast": 437247,
               "reportingPercent": 100, "votePercent": 24 },
  "response": { ... }
}
```

`GetContestSearchList` → `response.contests[contestId]`:
```
{ "contestId", "contestName": "REP U.S. Senate", "contestTypeCode": "Federal",
  "contestOrder", "voteFor": 1, "districtID",
  "choices": { "<choiceId>": { "id", "name": "Jeb Little", "partyID",
                               "color", "order", "isWriteIn", "isWinner" } } }
```

`GetContestResults` → `response.contests[contestId]`:
```
{ "contestID", "districtID", "precinctsReporting", "totalPrecincts",
  "totalVotes", "hasRecount", "hasLocationResults",
  "choices": [ { "choiceID", "totalVotes", "partyID", "votePercent", "isWinner" } ] }
```

Note: `GetContestSearchList` carries candidate identity (name/party); `GetContestResults` carries the tallies. Join on `choiceID`/`contestID`.

### Sample (2026 Preferential Primary)
- electionID `7f77a178-af02-40ec-92db-c5cc50882c68`, date 2026-03-03, `isOfficial: true`, 100% reporting.
- Example contest: "REP U.S. Senate", `contestTypeCode` Federal, `totalVotes` 281,973.

---

## Recommended Path for CivicMirror (Stage 2)

Use the **TotalResults API directly** as a Stage 2 adapter:

1. `GetElectionList?cId=arkansas` → upsert Elections (GUID = stable external key; `electionDate`, `electionName`).
2. For each election: `GetElectionInfo` (turnout, `isOfficial`, `versionID`) → store version for change-detection.
3. `GetContestSearchList` → upsert Races + candidate choices (name, party).
4. `GetContestResults` per `contestType` → load vote tallies, join choices by `choiceID`.
5. Poll on `versionID`/`lastUpdated`; skip when unchanged. Gate "certified" status on `isOfficial`.

**Historical backfill (pre-TotalResults era):** SOS ZIP/PDF archives, **OpenElections** (`openelections-data-ky` equivalent for AR), and **MEDSL** normalized CSVs. Legacy Clarity/Scytl is Akamai-gated — avoid.

### Data model mapping

| TotalResults | CivicMirror model |
|---|---|
| election (`electionID` GUID, `electionDate`) | **election** |
| `contestTypeCode` (Federal/State/Local) | race grouping/category |
| contest (`contestName`, `voteFor`, `districtID`) | **race** |
| choice (`name`, `partyID`, `isWinner`) | candidate / choice |
| contest result (`totalVotes` per `choiceID`) | result row |
| `isOfficial` | certified vs unofficial baseline |
| `versionID` / `lastUpdated` | ingestion change-detection / dedupe |
| `locationId` (county), precincts | sub-jurisdiction dimension (optional) |

---

## 2026 Election Calendar Context (Stage 1)

- **Preferential Primary & Nonpartisan General:** March 3, 2026
- **Primary Runoff:** March 31, 2026
- **General Election:** November 3, 2026
- Plus several 2026 special primary/runoff/general elections (see `GetElectionList`).
- Reference docs:
  - 2026 Election Calendar (rev. 6-2025): `https://www.sos.arkansas.gov/uploads/elections/2026_Election_Calendar_Rev._6-2025_.pdf`
  - Voter info: `https://www.sos.arkansas.gov/elections/for-voters`
  - Arkansas Advocate 2026 voter guide: `https://arkansasadvocate.com/voter-guide/2026-primary-election/`
  - 2026 general-election candidates (AR Association of Counties): `https://www.arcounties.org/site/assets/files/6757/2026candidatesgeneralelection.pdf`
  - Wikipedia overview: `https://en.wikipedia.org/wiki/2026_Arkansas_elections`

---

## Notes

- ENR vendor: **TotalResults.com** (current); **Clarity/Scytl** (legacy, ≤2022).
- 2,897 precincts statewide (2026 primary); ~1.80M registered voters.
- `contestType` values observed: Federal (others: State, county/local — enumerate via `contestTypes` in `GetElectionInfo`).
- SOS data-request contact: `electionsemail@sos.arkansas.gov`.
- Nonpartisan judicial contests appear without party (e.g., justices, circuit judges).

---

## Source Coverage Analysis

The earlier "ZIP download only / no adapter / vendor-transition risk" assessment is now resolved. Arkansas's new ENR vendor, **TotalResults.com**, exposes a fully public, unauthenticated JSON REST API (`enr-results-api.totalresults.com`, `cId=arkansas`) with election lists, contest metadata, candidate choices, vote tallies, turnout, and an `isOfficial` certified flag plus `versionID`/`lastUpdated` for change-detection — making Stage 2 ingestion a clean API adapter rather than a scraping problem. This is a markedly better situation than Clarity-based states (e.g., Kentucky), which are Akamai-gated. **Google Civic API** and **Ballotpedia** remain the supplements for candidate bios, ballot-measure detail, and incumbents; **MEDSL**/**OpenElections** and the SOS ZIP/PDF archives cover pre-TotalResults historical results; the legacy Clarity/Scytl host should be avoided (bot-protected).
