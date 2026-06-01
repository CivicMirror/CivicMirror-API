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
**Status:** Public, no authentication required (Cloudflare bot protection on direct API calls)

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

## Flateau API — Endpoint Reference

> **Access note:** All `/api/*` routes are Cloudflare-protected. Direct `curl`/`requests` calls return 403 (CF challenge). A browser session with a valid `__cf_bm` cookie is required — use Playwright with stealth or a negotiated CF exemption.

### Base URL
```
https://flateau.elections.ny.gov/api/
```

### Confirmed — Live responses captured in HAR (June 1, 2026)

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
  "total": 21
}
```

**Notes:**
- `electionType` values: `General`, `Primary`, `Special`, `Runoff`
- `authorityName` is a truncated version of `electionName` — appears to be a DB key artifact; use `electionName` for subsequent API calls
- As of June 1, 2026: 21 elections loaded, all May/June 2026 school/library budget elections (Act only effective April 1, 2026 — data ramp-up ongoing)

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

### Confirmed — Endpoint exists (CF 403, not 404; inferred from i18n bundle + app JS)

#### `GET /api/results`
Main election results table. Primary ingestion target.

**Query params (inferred from i18n filter keys):**
| Param | Notes |
|---|---|
| `electionName` | Required; from `/api/elections-metadata` |
| `contestJurisdiction` | Filter by jurisdiction |
| `contestType` | `General`, `Primary`, `Special`, `ElectiveOffice`, `Proposition`, `Budget`, `Bond` |
| `office` / `officeContest` | Filter by office name |
| `districtType` | Filter by district type |
| `district` | Filter by district |
| `candidateName` | Filter by candidate |
| `municipality` | Filter by municipality |
| `county` | Filter by county |
| `ward` | Filter by ward |
| `precinct` | Filter by precinct |

**Response columns (inferred from `header_*` i18n keys):**
`electionName`, `contestJurisdiction`, `contestType`, `office`, `districtType`, `district`, `candidate`, `party`, `electionDayVotes`, `earlyVotes`, `votesByMail`, `affidavitVotes`, `voteTotal`, `certifiedResult`

**Outcome/certifiedResult values:** `Win`, `Lose`, `Pass`, `Fail`, `BVS`

---

#### `GET /api/poll-sites`
Poll site location data.

**Query params:** `electionName`, `county`, `municipality`, `ward`, `precinct`, `designation`, `type`

**Type values:** `earlyVotingOnly`, `electionDayOnly`, `bothEarlyAndElectionDay`

**Response columns:** `siteName`, `address1`, `address2`, `city`, `state`, `zip`, `ward`, `precinct`, `schoolLibraryDistrict`, `designation`, `hours`, `accessibility`

---

#### `GET /api/downloads` (bulk export)
Triggers bulk data file generation.

**Download categories:**
| Category | Description |
|---|---|
| `electionResults` | Vote counts by candidate, office, district |
| `pollSiteData` | Election Day and Early Voting site locations |
| `voterStatistics` | Aggregated voter participation by method (no PII) |
| `invalidAffidavits` | Invalid affidavit ballot counts by reason and district |

**Invalid affidavit reason values:**
`notRegistered`, `movedWithinState`, `wrongPollingPlace`, `signatureIssue`, `alreadyVoted`, `prevAbsentEarlyMailBallot`, `incompleteAffidavit`, `partyEnrollmentIssue`, `other`

**Formats:** `csv`, `json`

---

#### `GET /api/compliance`
Semi-annual non-compliance reports per NYS Election Law § 3-112 ¶4.

**⚠️ No data until January 1, 2027** — first reporting deadline has not yet passed.

**Columns when live:** `authorityName`, `missingDataset`, `deadline`, `cureDeadline`, `status` (`NonCompliant` / `Cured` / `Pending`), `electionDate`, `reportDate`, `publicationDate`

---

#### `GET /api/district-maps` (or similar)
Interactive boundary map data. Types: `congressional`, `stateSenate`, `stateAssembly`, `countyLegislative`, `municipal`, `schoolDistrict`.

**⚠️ Data source not yet configured** — returns "no boundary data available" as of June 1, 2026.

---

#### Filter options endpoint (likely `/api/filter-options`)
Cascading filter dropdowns in the UI imply a filter-options endpoint that returns available values per dimension given a selected election. Not directly confirmed but strongly implied by UI behavior (`loadingOptions` i18n key, cascading `selectedValueUnavailable` validation).

---

## Adapter Strategy

### Short-term (historical data)
Use **OpenElections CSV** (`https://github.com/openelections/openelections-data-ny`) for results from 2011 onward. Field mapping is well-documented.

### Long-term (certified district-level data)
Build a Flateau adapter targeting `/api/results`. Loop driver: fetch all elections from `/api/elections-metadata`, then paginate results per election. The `/api/downloads` bulk export is likely the most efficient ingestion path once CF access is resolved.

### Blockers
1. **Cloudflare bot protection** — Playwright with stealth is required; no `Authorization` header scheme, session cookies are CF-issued
2. **Data coverage gap** — only 2026 local district elections loaded as of June 2026; statewide general election data (Nov 2025 and earlier) not yet present; county submission ramp-up ongoing

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
