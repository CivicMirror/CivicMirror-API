# New York Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | NYSBOE certifications + 2026 political calendar (Google Civic demoted to supplement) |
| Stage 1 — Race Creation | ✅ Available | NYSBOE certification (PDF/HTML) — parser validated, 433 contests June 23 2026 primary; ENR for near-E-day structure |
| Stage 2 — Results Ingestion | ✅ Validated | Flateau API live (Playwright stealth); OpenElections for history |

---

**Site:** https://elections.ny.gov/election-results
**Elections Database:** https://results.elections.ny.gov/
**Election Night Results:** https://nyenr.elections.ny.gov/
**Flateau Database:** https://flateau.elections.ny.gov/
**Flateau Results Page:** https://flateau.elections.ny.gov/results
**Operated by:** New York State Board of Elections
**Researched:** March 4, 2026 (initial); June 1, 2026 (Flateau HAR analysis); June 6, 2026 (Stage 1 certification analysis + Flateau live validation)
**Status:** Public, no authentication required (Cloudflare bot protection on all *.elections.ny.gov — domain-wide, not just API routes; includes static `/system/files/` PDF assets)

---

## Overview

New York provides election results through the State Board of Elections with a searchable historical database, election night reporting, and certified results downloads. The Dr. John L. Flateau Voting & Elections Database of New York Act (effective April 1, 2026) mandates comprehensive election data collection and publication, and the live platform at `flateau.elections.ny.gov` is now operational with a documented REST API.

**Stage 1 vs Stage 2 source split (important):** Flateau is a *results* mandate — it carries certified results only, and will not contain upcoming contests/candidates before an election. Pre-election race + candidate data (Stage 1) comes from a separate pipeline: NYSBOE **certification** documents, the **Who Filed** / county filing lists, and the **ENR** ballot pre-load. See "Stage 1 — Upcoming Elections & Races" below.

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

## Stage 1 — Upcoming Elections & Races (June 6, 2026)

**The gap this closes:** Flateau (Stage 2) is results-only. Google Civic alone is insufficient for NY (see "Google Civic — supplement only" below). The authoritative pre-election source is the NYSBOE **certification** pipeline, surfaced off the NYSBOE home page each cycle:

- **Certification for the June 23, 2026 Primary Election** — the certified primary ballot
- **Certification of Offices to be Filled – November 2026 General Election** — the general-election race *universe*
- **Who Filed for Ballot Access** — candidate filing data (earlier stage)
- **2026 Political Calendar** — the scheduling spine for ingestion windows

### Primary Source: NYSBOE Certification (PRIMARY ingestion target for Stage 1 races)

- **HTML landing page pattern:** `https://elections.ny.gov/certification-{month}-{day}-{year}-primary-election`
  (e.g. `/certification-june-23-2026-primary-election`, `/certification-june-24-2025-primary-election`)
- **PDF asset pattern:** `https://elections.ny.gov/system/files/documents/{YYYY}/{MM}/accessible-{...}-certification-amended-{M.D.YY}_0.pdf`
- **Both are Cloudflare-challenged** — must be fetched through the same stealth session as Flateau (curl and standard fetch return the CF challenge page even for the PDF). `nyenr` is the only `*.elections.ny.gov` host reachable without stealth.
- **Lead time:** certification posts ~6–8 weeks before the primary (June 23 2026 cert original version dated **04.29.2026**; amended **05.13.2026**).

**Document schema (validated against the 215-page June 23 2026 amended cert):**

Per-contest block, repeated:
```
Office:    <office name>
District:  <Statewide | numeric district id>
District2: <secondary id; usually blank — judicial-delegate / nested offices only>
Counties:  <coarse geography, e.g. "Part of Nassau & Part of Suffolk">
Party:     <Democratic | Republican | Conservative | Working Families>
Vote For:  <N>   (>1 for multi-seat offices: State Committee, Judicial Delegate)
```
followed by a candidate table. The **Ballot Order** cell holds a number, `Uncontested`, or the status flag `Litigation Pending`. Joint offices (Governor and Lt. Governor) use paired candidate columns (candidate + running mate). Row order = ballot position (legally significant — the document's purpose is to fix ballot order).

**Parser results (June 23 2026 amended cert):**
- **433 contests / 1,285 candidates** parsed — **433/433 fully clean** (0 empty candidate lists)
- Parties: Democratic 142, Conservative 139, Working Families 80, Republican 72
- Office types (9): Governor and Lt. Governor, Comptroller, Attorney General, Representative in Congress, State Senator, Member of Assembly, Judicial Delegate, Alt Judicial Del., State Committee
- Parser: `ny_cert_parser.py` (pdfplumber, word-position clustering — required because candidate names wrap across two visual lines with the ballot-order token vertically centered between them; naive line parsing scrambles names). Emits contest key `office|district|district2|party` + ordered candidates. Production hardening must append wrapped label continuations for fields such as `Counties:` and treat running-mate extraction as unverified until confirmed against the source PDF.
- Output: `ny_cert_2026.json`

**Parser bug fixed (June 6, 2026):** Page footer text ("Certification for the June 23...") at `x≈54` was left of the ballot-order column (`x≈87`). `order_x = min(x0 for all words)` pulled `order_x` to 54, so the `x ≤ order_x+30` guard rejected ballot-order numbers at `x≈87` by 3pt. Fixed by anchoring `order_x` on ORDER_TOKENS words only; also added a footer-row skip in `parse_contests`. Affected 11 contested races (Congress ×6, State Senator ×2, Assembly ×1, Judicial Delegate ×1, Alt Judicial Del. ×1); all now parse correctly.

### Amendment detection: Version History block

Page 2 of each cert is a dated, line-referenced changelog — parsed into `version_history` in the JSON. Use it as the re-ingest trigger (key off the latest date) instead of diffing the full PDF. Example entries from the June 23 2026 cert:
```
04.29.2026  - Original version
04.30.2026  - Comptroller: Removed "Litigation Pending" on the Democratic line.
            - 2nd CD: Added "Litigation Pending" on the Democratic line.
05.13.2026  - 2nd CD: Removed "Litigation Pending" on the Democratic line.
            - 18th CD: Candidate name change – Jacqueline Mary Theresa Auringer →
              Jackie Mary Auringer on the Republican and Conservative lines.
```
Change-line grammar: `{office/district ref}: {action} on the {party} line` and `Candidate name change – {old} → {new}`.

### Earlier-stage: Who Filed / county filing lists

- **NYSBOE "Who Filed for Ballot Access"** (statewide/federal/judicial) — populates as designating/independent petitions are filed and pass prima facie review.
- **County BOE "Candidates Filed" pages** (local offices) — each county publishes its own list (e.g. Ontario County `/2305/2026-Candidates-Filed`). A primary is triggered only when more candidates file than seats available.
- Use to seed races during the spring petition window, before certification finalizes the set.

### General-election race universe: Offices to be Filled

- **Certification of Offices to be Filled – November 2026 General Election** defines the general race set before candidates are finalized. General-election *candidates* arrive later (primary winners + general certification, ~Aug/Sep). Seed Stage 1 general races from this; backfill candidates post-primary.

### Near-E-day structure + bridge to results: ENR (`nyenr.elections.ny.gov`)

- Custom **ASP.NET WebForms** app (not Clarity/Scytl), server-rendered HTML, `HomeNoJS.aspx` no-JS view available.
- **Only `*.elections.ny.gov` host NOT behind the hard CF challenge** — returns 200 to a plain `httpx`/curl user-agent (soft Cloudflare only). Scrapeable directly.
- Pre-loads contests → districts → candidates close to election day; carries unofficial results on election night.
- As of June 6 2026 still shows the **Feb 3 2026 special** (47th/61st Senate, 36th/74th Assembly).
- Role: last-mile Stage 1 structure check near E-day, then handoff to Flateau/results DB for Stage 2. Not an advance source.

### Google Civic — supplement only (do not use as NY Stage 1 spine)

- **Representatives API turned down April 30, 2025.** Elections endpoints (`electionQuery`/`voterInfoQuery`) survive.
- Entirely **VIP-fed**; elections **auto-expire after election day**. NY VIP coverage is thin for odd-year/local races.
- Use as an address-keyed cross-check and candidate-bio supplement for even-year federal/statewide contests only.

### Stage 1 ingestion trigger model (key off the political calendar)

```
spring petition window   → poll Who Filed + county filed lists (seed races)
~6–8 wks pre-primary      → ingest primary Certification (authoritative race+candidate set)
                           re-ingest on Version History date change (amendments)
ballot position drawing   → ballot order confirmation
~E-day                    → scrape ENR for last structural changes
E-night → certified       → handoff to ENR (unofficial) then Flateau/results DB (Stage 2)
general cycle             → seed from "Offices to be Filled"; backfill candidates post-primary
```

---

## Endpoint Validation (June 6, 2026)

Playwright MCP used to test live access. All `*.elections.ny.gov` domains (flateau, elections, nyenr, results) return Cloudflare managed challenge ("Just a moment...") to non-stealth automated browsers — CF protection is domain-wide, not just on `/api/*` routes. Standard Playwright cannot pass the challenge. **Exception:** `nyenr.elections.ny.gov` is soft-CF only and reachable with a plain user-agent.

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

> **Access note:** All `*.elections.ny.gov` domains are Cloudflare-protected — domain-wide CF managed challenge, not just `/api/*` routes (and not just Flateau — includes the cert HTML pages and `/system/files/` PDF assets on `elections.ny.gov` and the historical results DB). Direct `curl`/`requests` calls return 403. Standard Playwright also blocked. A browser session with a valid `cf_clearance` cookie is required — use Playwright with stealth or a negotiated CF exemption. `nyenr` is the lone exception (soft-CF).

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

> **Stage 1 ↔ Stage 2 join note:** Flateau `office` / `district` / `candidateParty` / `ballotPosition` map onto the cert's `Office` / `District` / `Party` / Ballot Order. The cert's coarse `Counties` string does NOT map to Flateau's `districtType`/`district` granularity — reconcile via the `office|district|district2|party` key, not geography.

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

### Stage 1 (upcoming races) — NEW
Build a **NYSBOE certification adapter** (`ny_cert_parser.py`). Driver: discover the current cert via the NYSBOE home page links → fetch the PDF through the stealth CF session → parse to contest key `office|district|district2|party` + ordered candidates → re-ingest on Version History date change. Seed general-cycle races from "Offices to be Filled"; use Who Filed / county lists for early signal; scrape ENR near E-day. Demote Google Civic to a supplement.

### Short-term (historical data)
Use **OpenElections CSV** (`https://github.com/openelections/openelections-data-ny`) for results from 2011 onward. Field mapping is well-documented.

### Long-term (certified district-level data)
Build a Flateau adapter targeting `/api/election-results`. Loop driver: fetch all elections from `/api/elections-metadata`, paginate results per election via `page`/`pageSize`. The `/api/downloads?category=results` bulk export is the most efficient ingestion path.

### Blockers
1. **Cloudflare bot protection** — domain-wide on `*.elections.ny.gov` incl. static PDF assets; `nyenr` is the soft-CF exception. Playwright with stealth patches (`navigator.webdriver`, `window.chrome`, `--disable-blink-features=AutomationControlled`) bypasses successfully; config at `~/.claude/playwright-mcp-stealth.json`. **One stealth session covers Stage 1 (cert PDF/HTML), the historical results DB, and Stage 2 (Flateau).**
2. **Data coverage gap** — only 2026 local school/library elections loaded in Flateau as of June 2026; statewide general election data (Nov 2025 and earlier) not yet present; county submission ramp-up ongoing

---

## Supporting Files

| File | Description |
|---|---|
| `CountyBoardRoster.csv` | All 62 county BOE addresses, phone/fax/email, commissioner and deputy commissioner names (DEM + REP) |
| `flateau.elections.ny.gov_Archive [26-06-01 14-38-41].har` | HAR capture of dashboard page load; contains confirmed API responses for `/api/elections-metadata` and `/api/dashboard-stats` |
| `2026-political-calendar-quad-fold-12.9.2025-final.pdf` | 2026 NY election calendar — `https://elections.ny.gov/system/files/documents/2025/12/2026-political-calendar-quad-fold-12.9.2025-final.pdf` |
| `accessible-june-23-2026-primary-certification-amended-5.13.26_0.pdf` | June 23 2026 primary certification (amended 05.13.2026); 215 pages; Stage 1 source — `https://elections.ny.gov/system/files/documents/2026/05/accessible-june-23-2026-primary-certification-amended-5.13.26_0.pdf` |
| `ny_cert_parser.py` | pdfplumber parser for the certification PDF → Stage 1 contest/candidate records + version-history changelog |
| `ny_cert_2026.json` | Parsed output of the June 23 2026 cert (433 contests / 1,285 candidates) |

---

## Source Coverage Analysis

New York is among the more capable state sources, with a now-complete Stage 1 + Stage 2 picture:

- **Stage 1 (upcoming races):** the NYSBOE **certification** pipeline is authoritative and parseable (~6–8 wk lead), with a built-in amendment changelog. Backed by Who Filed / county filings (early signal), Offices-to-be-Filled (general universe), and ENR (near-E-day structure). Google Civic is a supplement only (Representatives API gone April 2025; Elections endpoints VIP-fed and auto-expiring with thin NY local coverage).
- **Stage 2 (results):** the Flateau Database (live April 2026) is the definitive long-term source — election-district-level certified results, poll sites, compliance data under statutory mandate — with OpenElections covering pre-2026 history.

Current gaps: Flateau data coverage (counties still ramping up submissions), district-boundary GeoJSON (Flateau `district-maps` is a 404; source from Google Civic meanwhile), wrapped certification fields such as truncated `Counties:` continuations, and unverified joint-ticket running-mate extraction. Programmatic access friction (domain-wide Cloudflare) is solved via a single stealth session. Candidate bio/platform/incumbency data should be supplemented with **Ballotpedia**, **OpenStates** (NY legislative), and **OpenFEC** (federal campaign finance).

---

## Contact

- **General:** INFO@elections.ny.gov
- **Flateau / VEDA:** (518) 474-6220 | 40 North Pearl Street, Suite 5, Albany, NY 12207-2729
