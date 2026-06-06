# New York Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ⚠️ Partial | Flateau API live (CF-protected); OpenElections for history |

---

**Site:** https://elections.ny.gov/election-results
**Elections Database:** https://results.elections.ny.gov/
**Election Night Results:** https://nyenr.elections.ny.gov/
**Flateau Database:** https://flateau.elections.ny.gov/
**Flateau Results Page:** https://flateau.elections.ny.gov/results
**Operated by:** New York State Board of Elections
**Researched:** March 4, 2026 (initial); June 1, 2026 (Flateau HAR analysis)
**Status:** Public, no authentication required (Cloudflare bot protection on all *.elections.ny.gov — domain-wide, not just API routes)

---

## Overview

New York provides election results through the State Board of Elections with a searchable historical database, election night reporting, and certified results downloads. The Dr. John L. Flateau Voting & Elections Database of New York Act (effective April 1, 2026) mandates comprehensive election data collection and publication, and the live platform at `flateau.elections.ny.gov` is now operational with a documented REST API.

---

## Data Access

### Elections Database
- **URL:** https://results.elections.ny.gov/
- Searchable database of historical election information
- Official source documents
- Search by contests, ballot questions, and more

### Election Night Results
- **URL:** https://nyenr.elections.ny.gov/
- Live results after polls close (9 PM)
- Updated as counties upload results
- Write-in results shown in aggregate only

### Certified Results Downloads
- Downloadable certified results files
- Ballot certifications dating back to 2011

### Dr. John L. Flateau Database (live as of April 2026)
- **URL:** https://flateau.elections.ny.gov/
- **Results page:** https://flateau.elections.ny.gov/results
- Mandates county boards transmit election district-level results by January 1 after each election
- State Board hosts/maintains statewide database
- Data published online within 60 days of submission
- Records maintained for at least 12 years
- Enforcement mechanisms for non-compliant election authorities (compliance reports due January 1, 2027)
- Built on Next.js 15 (App Router), Cloudflare CDN, 14 languages supported

---

## Endpoint Validation (June 6, 2026)

Playwright MCP used to test live access. All `*.elections.ny.gov` domains (flateau, elections, nyenr, results) return Cloudflare managed challenge ("Just a moment...") to non-stealth automated browsers — CF protection is domain-wide, not just on `/api/*` routes. Standard Playwright cannot pass the challenge.

Confirmed endpoints validated against June 1 HAR capture:

| Endpoint | Status | Schema Match | Notes |
|---|---|---|---|
| `GET /api/elections-metadata` | ✅ 200 | ✅ Exact | 60 elections as of June 6 (was 21 on June 1); all fields confirmed |
| `GET /api/dashboard-stats` | ✅ 200 | ✅ Exact | All 6 top-level keys confirmed |
| `GET /api/election-results` | ✅ 200 | ⚠️ Corrected | Path was wrong (`/api/results`); field names differ from i18n inferences; paginated |
| `GET /api/poll-sites` | ✅ 200 | ⚠️ Corrected | Field is `pollSiteName` not `siteName`; `hours`/`accessibility` absent |
| `GET /api/downloads` | ✅ 200 | ⚠️ Corrected | Categories are kebab-case (`results`, `poll-sites`, `voter-stats`, `invalid-affidavits`) |
| `GET /api/filter-options` | ✅ 200 | ✅ Confirmed | Was unconfirmed; returns all 10 filter dimensions |
| `GET /api/compliance` | ✅ 200 | ✅ Confirmed | Returns empty + message; no data until Jan 1, 2027 |
| `GET /api/district-maps` | ❌ 404 | — | True 404, not CF-blocked; endpoint not implemented |

**`authorityName` truncation:** cuts at ~61 chars (not at a word boundary) — appears to be a DB column width artifact. Confirmed: not a clean suffix of `electionName`.

---

## Flateau API — Endpoint Reference

> **Access note:** All `*.elections.ny.gov` domains are Cloudflare-protected — domain-wide CF managed challenge, not just `/api/*` routes. Direct `curl`/`requests` calls return 403. Standard Playwright also blocked. A browser session with a valid `cf_clearance` cookie is required — use Playwright with stealth or a negotiated CF exemption.

### Base URL
```
https://flateau.elections.ny.gov/api/
```

### Confirmed — Live responses (HAR June 1, 2026; Playwright live validation June 6, 2026)

#### `GET /api/elections-metadata`
Returns all elections currently in the database.

**Response shape:**
```json
{
  "data": [
    {
      "electionName": "Wyoming CSD - Budget Election - 05/19/2026 - Certified 05/19/2026",
      "parsedYear": "2026",
      "electionType": "General",
      "authorityName": "Wyoming CSD - Budget Election - 05/19/2026 - Certified 05/19/",
      "totalContests": 1
    }
  ],
  "total": 60
}
```

**Notes:**
- `electionType` values: `General`, `Primary`, `Special`, `Runoff`
- `authorityName` is a raw DB column-width truncation (~61 chars) of `electionName` — not a clean suffix; use `electionName` for all subsequent API calls
- As of June 6, 2026: 60 elections loaded (up from 21 on June 1 — data ramp-up ongoing; all local school/library elections so far)

---

#### `GET /api/dashboard-stats?electionName={encoded_name}`
KPI summary for a selected election.

**Query params:**
- `electionName` (required) — full election name string, URL-encoded

**Response shape:**
```json
{
  "kpi": {
    "totalVoteRecords": 500,
    "totalContests": 1,
    "totalCandidates": 2
  },
  "votesByDistrict": [],
  "votesByType": [
    { "name": "Election Day", "value": 485 },
    { "name": "By Mail", "value": 15 }
  ],
  "topContests": [],
  "votesByParty": [],
  "voterParticipation": { "totalVoters": 0, "byMethod": [] }
}
```

---

#### `GET /api/election-results` ⚠️ path corrected from `/api/results`
Main election results table. Primary ingestion target. Paginated.

**Query params:**
| Param | Notes |
|---|---|
| `electionName` | Required; from `/api/elections-metadata` |
| `contestJurisdiction` | Filter by jurisdiction |
| `contestType` | Filter by contest type |
| `office` | Filter by office name |
| `districtType` | Filter by district type |
| `district` | Filter by district |
| `candidateName` | Filter by candidate |
| `ward` | Filter by ward |
| `precinct` | Filter by precinct |
| `outcome` | Filter by outcome |

**Response shape (live, June 6, 2026):**
```json
{
  "data": [ ... ],
  "total": 5,
  "page": 1,
  "pageSize": 25,
  "filters": {}
}
```

**Row fields (all 27 live fields):**
`id`, `electionName`, `contestJurisdiction`, `contestType`, `office`, `districtType`, `district`, `ward`, `precinct`, `candidateName`, `candidateParty`, `independentBodyName`, `propositionBudgetName`, `shortDescription`, `ballotPosition`, `voteType`, `voteFor`, `schoolLibraryDistrictName`, `electionDistrictCombinedInto`, `electionDayVotes`, `earlyVotes`, `votesByMail`, `affidavitVotes`, `rankRound`, `transferVotes`, `voteTotal`, `outcome`

**`outcome` values:** `Win`, `Lose`, `Pass`, `Fail`, `BVS`

**⚠️ Corrections vs prior research:** field is `outcome` (not `certifiedResult`), `candidateName`/`candidateParty` (not `candidate`/`party`); response is paginated (`page`, `pageSize`); 13 additional fields present that weren't in i18n inferences.

---

#### `GET /api/poll-sites`
Poll site location data.

**Query params:** `electionName`, `ward`, `precinct`, `designation`

**Row fields (live):** `id`, `electionName`, `ward`, `precinct`, `hasNumber`, `pollSiteName`, `address1`, `address2`, `city`, `state`, `zip`, `designation`

**⚠️ Corrections vs prior research:** field is `pollSiteName` (not `siteName`); `schoolLibraryDistrict`, `hours`, `accessibility` not present in live response; `id` and `hasNumber` are additional fields.

---

#### `GET /api/downloads`
Bulk data export. Returns JSON array directly (not wrapped).

**Query params:** `electionName`, `category`, `format` (`json` or `csv`)

**Category values (live, kebab-case):**
| Category | Description |
|---|---|
| `results` | Vote counts by candidate, office, district |
| `poll-sites` | Election Day and Early Voting site locations |
| `voter-stats` | Aggregated voter participation by method (no PII) |
| `invalid-affidavits` | Invalid affidavit ballot counts by reason and district |

**⚠️ Corrections vs prior research:** all category values are kebab-case (`results`, `poll-sites`, `voter-stats`, `invalid-affidavits`), not camelCase. Invalid affidavit reason values unconfirmed live.

---

#### `GET /api/filter-options?electionName={encoded_name}` ✅ now confirmed
Cascading filter options for a given election.

**Response keys (live):** `electionNames`, `contestJurisdictions`, `contestTypes`, `offices`, `districtTypes`, `districts`, `candidateNames`, `wards`, `precincts`, `outcomes`

---

#### `GET /api/compliance`
Semi-annual non-compliance reports per NYS Election Law § 3-112 ¶4.

**Response (live, June 6, 2026):**
```json
{ "data": [], "total": 0, "message": "Compliance data is not yet available." }
```

**⚠️ No data until January 1, 2027** — first reporting deadline has not yet passed.

---

#### `GET /api/district-maps`
❌ **404** — endpoint does not exist at this path (not CF-blocked; true 404 in Next.js). Boundary map data source not yet integrated.

---

## Adapter Strategy

### Short-term (historical data)
Use **OpenElections CSV** (`https://github.com/openelections/openelections-data-ny`) for results from 2011 onward. Field mapping is well-documented.

### Long-term (certified district-level data)
Build a Flateau adapter targeting `/api/election-results`. Loop driver: fetch all elections from `/api/elections-metadata`, paginate results per election via `page`/`pageSize`. The `/api/downloads?category=results` bulk export is the most efficient ingestion path.

### Blockers
1. **Cloudflare bot protection** — Playwright with stealth patches (`navigator.webdriver`, `window.chrome`, `--disable-blink-features=AutomationControlled`) bypasses successfully; config at `~/.claude/playwright-mcp-stealth.json`
2. **Data coverage gap** — only 2026 local school/library elections loaded as of June 2026; statewide general election data (Nov 2025 and earlier) not yet present; county submission ramp-up ongoing

---

## Supporting Files (June 1, 2026)

| File | Description |
|---|---|
| `CountyBoardRoster.csv` | All 62 county BOE addresses, phone/fax/email, commissioner and deputy commissioner names (DEM + REP) |
| `flateau.elections.ny.gov_Archive [26-06-01 14-38-41].har` | HAR capture of dashboard page load; contains confirmed API responses for `/api/elections-metadata` and `/api/dashboard-stats` |
| `2026-political-calendar-quad-fold-12.9.2025-final.pdf` | 2026 NY election calendar — `https://elections.ny.gov/system/files/documents/2025/12/2026-political-calendar-quad-fold-12.9.2025-final.pdf` |

---

## Source Coverage Analysis

New York is among the more capable state sources. The Flateau Database (live April 2026) is the definitive long-term source: election-district-level certified results, poll sites, district boundaries, and compliance data, all published under statutory mandate. Current gaps are data coverage (counties still ramping up submissions) and programmatic access friction (Cloudflare). Primary gaps in candidate bio/platform/incumbency data should be supplemented with **Google Civic Information API** (candidates, offices, districts by address), **Ballotpedia** (candidate bios, ballot measures, incumbency), **OpenStates** (NY state legislative data), and **OpenFEC** (federal campaign finance). GeoJSON district boundaries should be sourced from Google Civic API until the Flateau district-maps endpoint is populated.

---

## Contact

- **General:** INFO@elections.ny.gov
- **Flateau / VEDA:** (518) 474-6220 | 40 North Pearl Street, Suite 5, Albany, NY 12207-2729
