# Michigan Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race / Candidate Creation | ✅ Available (updated) | **BOE entellitrak candidate-listing report** (official filings) + Google Civic. No longer dependent on michiganelections.io. |
| Stage 2 — Results Ingestion | ✅ Adapter path identified (updated) | **MVIC VoteHistory** official statewide results (all 83 counties, back to 2006). michiganelections.io no longer required. |

> **Change note (7/14/2026):** Prior status had Stage 1 Race Creation ⚠️ Blocked and Stage 2 ❌ No adapter, both because `michiganelections.io` was returning 503. HAR captures of the state's own systems show Michigan actually has **two official, unauthenticated results/candidate systems** that fully cover both stages. `michiganelections.io` is still down for maintenance but is now demoted from primary source to optional supplement.

---

**State results portal (official):** https://mvic.sos.state.mi.us/votehistory/
**BOE reporting system (official):** https://mi-boe.entellitrak.com/etk-mi-boe-prod/
**SOS results landing page:** https://www.michigan.gov/sos/elections/election-results-and-data
**County ENR (large counties, vendor):** https://michigan.totalvote.com/
**Third-Party API (down):** https://michiganelections.io/
**Operated by:** Michigan Secretary of State / Bureau of Elections
**Researched:** March 4, 2026 · **Updated:** July 14, 2026 (HAR analysis)
**Status:** Public, no authentication required

---

## Overview

Michigan publishes official statewide results through two separate SOS/BOE systems, neither of which was documented in the original notes:

1. **MVIC VoteHistory** — the Michigan Voter Information Center's results portal. Serves canvassed county- and precinct-level results plus **bulk tab-delimited data files** for every statewide election back to 2006. This is the primary Stage-2 source.
2. **BOE entellitrak** — the Bureau of Elections' reporting platform (entellitrak / JasperReports). Serves the **Official Candidate Listing** (filings) and related reports. This is the primary Stage-1 race/candidate source.

Large counties additionally run their own **KNOWiNK TotalVote** election-night-reporting sites (e.g., Wayne / Detroit), backed by an Azure JSON service. The community `michiganelections.io` REST API (Citizen Labs) remains a useful supplement for ballot proposals and registration data but is currently offline.

---

## Data Access

### 1. MVIC VoteHistory — official statewide results ⭐ PRIMARY (Stage 2)

- **Base:** `https://mvic.sos.state.mi.us/VoteHistory/`
- **UI entry:** `https://mvic.sos.state.mi.us/votehistory/`
- **Auth:** none. **Transport:** HTTPS. **Format:** HTML fragments + bulk flat files.

The landing page drives three dropdowns, which map directly to the query parameters used by the endpoints:

- `resultsType` — `1` = County Results, `2` = Precinct-by-Precinct Results
- `ElectionDateId` — internal election ID. **49 elections, 8/4/1998 (id 31) → 5/5/2026 (id 705).** Recent examples: `705` = 5/5/2026 MAY CONSOLIDATED, `699` = 11/5/2024 STATE GENERAL, `698` = 8/6/2024 STATE PRIMARY, `696` = 2/27/2024 PRESIDENTIAL PRIMARY.
- `CountyCode` — **1–83, alphabetical** (1 = ALCONA … 9 = BAY … 83 = WEXFORD). These are the official MVIC county codes.

**Endpoints (confirmed in HAR):**

| Endpoint | Params | Returns |
|---|---|---|
| `GET /VoteHistory/GetCountyVoteRecords` | `electionId` | HTML fragment: header (date, type, "Counties: n/n", updated timestamp) + per-contest blocks (`contest → party → candidate → votes → pct`, `Total Votes`, then `Total Voter Turnout` by county). **No Cloudflare challenge.** |
| `GET /VoteHistory/GetPrecinctInfo` | `electionId`, `countyCode` | HTML fragment: precinct-by-precinct results, or `"No precinct by precinct election results for selected election date"` when unavailable for that election. |
| `GET /VoteHistory/GetElectionResultFile` | `electionId` | **Bulk tab-delimited election-data file** (all counties). ⚠️ Behind Cloudflare managed challenge (see below). |
| `GET /VoteHistory/GetVoterTurnoutFile` | `electionId` | **Bulk tab-delimited voter-turnout file.** ⚠️ Behind Cloudflare managed challenge. |

**Example (from HAR) — `GetCountyVoteRecords?electionId=705`:**
> 2026 Michigan Election Results · Date 5/5/2026 · Type: MAY CONSOLIDATED, OFFICIAL · Counties 3/3
> 35TH DISTRICT STATE SENATOR — PARTIAL TERM ENDING 1/1/2027 (1) POSITION
> DEMOCRATIC — GREENE, CHEDRICK — 36,583 — 58.88%
> REPUBLICAN — TUNNEY, JASON — 24,491 — 39.42%
> LIBERTARIAN — SLEDZ, ALI K. — 1,058 — 1.70%
> Total Votes: 62,132 · Total Voter Turnout 67,068 (Bay 22,218 / Midland 17,570 / Saginaw 27,280)

> ⚠️ **Cloudflare note:** The two bulk-file endpoints (`GetElectionResultFile`, `GetVoterTurnoutFile`) return HTTP 403 with `cf-mitigated: challenge` to a plain client — verified live 7/14/2026. The browser HAR passed the challenge, so ingestion needs the **Playwright-stealth** path (same pattern as the NY domains). The **`GetCountyVoteRecords` / `GetPrecinctInfo` HTML endpoints did NOT challenge** and are a curl-friendly fallback if the flat-file route is blocked.

### 2. BOE entellitrak — official candidate listings / reports ⭐ PRIMARY (Stage 1)

- **Base:** `https://mi-boe.entellitrak.com/etk-mi-boe-prod/`
- **Report endpoint:** `GET page.request.do?page=page.miboePublicReport&electionType={PRI|GEN|…}&electionYear={YYYY}`
- **Platform:** entellitrak (Tyler/MicroPact) serving a **JasperReports HTML export** (identifiable by `JR_PAGE_ANCHOR` / `jrPage` table markers; a `-- Select a Race --` dropdown is populated client-side from report title bands).
- **Auth:** none.

**Example (from HAR) — `electionType=PRI&electionYear=2026`:** "The Office of Secretary of State Jocelyn Benson — Official Candidate Listing — All State and Judicial Offices — Primary Election — Tuesday, August 4, 2026." Each contest lists candidates with columns: **Party / Incumbent · Filing Method · Status · Candidate Name · Candidate Address · Filed On**. Status codes seen: `DISQ` (disqualified), `WITHD` (withdrawn). Filing methods seen: `Petitions`. This is the authoritative Stage-1 candidate/race source (Governor, U.S. Senate, U.S. House by district, State offices, Judicial).

> Parsing: treat the inner Jasper table as the payload. Detect contest headers via title bands (`isTitleBand`-style span text, e.g. `"… Year Term (n) Position"`), then read candidate rows beneath each. This is a rendered-report parse, not a clean API, so pin it to the report layout and add a schema guard.

### 3. County ENR — KNOWiNK TotalVote (large counties)

- **Front-end:** `https://michigan.totalvote.com/{CountyName}/…` (e.g., `/Detroit/…`, `/Wayne/…`, `/Iron/…`).
- **AJAX backend (Azure):** `https://phillyresws.azurewebsites.us/ResultsAjax.svc/`
- **Vendor:** **KNOWiNK TotalVote** (KNOWiNK acquired BPro's TotalVote platform ~2020–21; Azure-hosted ENR/EMS). Ties to existing `KNOWiNK/TotalVote` vendor-reference entry. The `phillyresws` host name traces to the platform's Philadelphia deployment lineage.

**Endpoints (confirmed in HAR, JSON):**

| Endpoint | Params | Returns |
|---|---|---|
| `GET /ResultsAjax.svc/GetCandidates` | `ElectionType={primary\|Special\|…}`, `ElectionID=0`, `County={cc}`, `LanguageID=1` | JSON array of contest+candidate records: `ID`, `Party`, `PartyCode`, `desc` (contest, with `<br/>VOTE FOR n`), `label`, `name`. Proposals appear as Yes/No pseudo-candidates. |
| `GET /ResultsAjax.svc/GetVoterTurnoutData` | `County={cc}` | JSON array of precinct turnout: `CountyID`, `CountyName`, `PrecinctName`, `StatePrecinctID`, `PrecinctsReporting`, `TotalPrecincts`, `Voters`, `calcVoterTurnout`, `CountyPercent`, `IsReported`, `CurrentDateTime`. |

- Server-rendered contest pages: `/{County}/ResultsSW.aspx?type={CONTEST_CODE}&cid={cc}` (e.g., `type=MYR` Mayor, `CAL` Council At-Large, `CD2/CD5/CD7` council districts), and `/{County}/ResultsExport.aspx?cid={cc}`.
- ⚠️ **County IDs are TotalVote-internal** (Detroit = `06`, Wayne = `05`) and do **not** match MVIC's 1–83 codes. Maintain a crosswalk if joining to state data.
- Use only as a **county-level election-night supplement**; the canvassed statewide numbers come from MVIC.

### 4. SOS landing page (directory only)

- `https://www.michigan.gov/sos/elections/election-results-and-data/candidate-listings-and-election-results-by-county`
- Sitecore CMS with Coveo search (`/api/coveosearch/token`). This is a **routing/directory page** to per-county sources, not a data source itself. No results payload.

### michiganelections.io (community, currently down)

- Unchanged from prior notes; **503 / maintenance** as of 7/14/2026. Keep as optional supplement for ballot proposals + registrations once restored. No longer on the critical path.

---

## Proposed Adapter Architecture (CivicMirror)

Keyed via the OCD-ID router like the other deterministic states.

**Stage 1 — Race / Candidate creation**
- `mi_boe_entellitrak` adapter → fetch `miboePublicReport` by `electionType`+`electionYear`, parse the JasperReports table into contests + candidate filings (party, status, filing method, address, filed-on). Deterministic, schema-guarded.
- Supplement with Google Civic (districts, contact) as today.

**Stage 2 — Results ingestion**
- **Primary:** `mi_mvic_votehistory_file` adapter → `GetElectionResultFile` / `GetVoterTurnoutFile` bulk tab-delimited, all 83 counties, by `electionId`. Requires **Playwright-stealth** to clear Cloudflare. One fetch per election.
- **Fallback:** `mi_mvic_votehistory_html` adapter → loop `GetCountyVoteRecords` (county) and `GetPrecinctInfo` (precinct); parses the HTML fragments. **No Cloudflare challenge** — use when the flat-file route is blocked or for near-real-time county pulls.
- **County ENR supplement (optional):** `mi_totalvote_knowink` adapter → `phillyresws` JSON for large-county election-night granularity; maintain the TotalVote↔MVIC county crosswalk.

**Election-ID discovery:** scrape the `ElectionDateId` `<select>` on `/votehistory/` to enumerate available elections (id → date/type), then map to OCD election IDs.

---

## API Access (summary)

- **Official statewide results:** MVIC VoteHistory (`GetCountyVoteRecords`, `GetPrecinctInfo`, `GetElectionResultFile`, `GetVoterTurnoutFile`). ✅ New.
- **Official candidate filings:** BOE entellitrak `miboePublicReport`. ✅ New.
- **County ENR:** KNOWiNK TotalVote `phillyresws.azurewebsites.us/ResultsAjax.svc`. ✅ New.
- **Official state REST API:** still none.
- **Third-party REST:** michiganelections.io (down).
- Contact: Elections@Michigan.gov

---

## Notes

- 83 counties, 1,500+ election clerks statewide.
- Qualified Voter File (QVF) is the central voter database. The Voting Dashboard reports **QVF voter-history counts, which intentionally do NOT match tabulator-based results** — do not use the dashboard for vote totals; use MVIC.
- Board of State Canvassers certifies results. MVIC data is labeled `OFFICIAL` once canvassed.
- Paper ballot / optical scan statewide. Member of ERIC.
- MVIC bulk files are tab-delimited ASCII (consistent with Michigan's documented text-file layouts); confirm exact column order against a Playwright-fetched sample before finalizing the parser.

---

## Source Coverage Analysis

Michigan is **substantially better covered than the original notes indicated** — the gap was a documentation gap, not a data gap. Two official SOS/BOE systems provide both stages without the community API: **MVIC VoteHistory** for canvassed county/precinct results and bulk data files (statewide, 1998–2026), and **BOE entellitrak** for official candidate filings. Large counties add **KNOWiNK TotalVote** ENR. Remaining supplements are unchanged: **Google Civic** (districts, candidate contact), **Ballotpedia** (bios, measure classification), **OpenStates** (legislative incumbents), **MEDSL** (normalized historical results), and **michiganelections.io** (ballot proposals / registrations, once it returns). The main engineering caveat is the **Cloudflare managed challenge on the MVIC bulk-file endpoints**, which pushes the primary Stage-2 path onto the Playwright-stealth infrastructure already built for NY; the un-challenged `GetCountyVoteRecords` HTML endpoints provide a deterministic fallback.

## Additional Research on TotalVote (added 5/31/2026)
- https://michigan.totalvote.com/Detroit/ResultsExport.aspx?cid=06
- https://michigan.totalvote.com/Wayne/VoterTurnoutDetails.aspx?cid=05
- Backend confirmed 7/14/2026: `https://phillyresws.azurewebsites.us/ResultsAjax.svc/` (KNOWiNK TotalVote, Azure-hosted).
