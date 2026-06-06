# Pennsylvania Election Results — Research Notes

> **Last Updated:** June 6, 2026 (major update — original: March 4, 2026)

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Blocked | No free PA state API for candidates; Google Civic unreliable for PA; OpenFEC covers 17 US House seats only |
| Stage 2 — Results Ingestion | ⚠️ Partial path | electionreturns.pa.gov has internal API (Incapsula-protected); data.pa.gov Socrata has **mail ballot data only** (not results) |

---

**Results Site:** https://www.electionreturns.pa.gov/
**Open Data:** https://data.pa.gov/
**Candidate DB:** https://www.pavoterservices.pa.gov/ElectionInfo/ElectionInfo.aspx
**DOS Filing Info:** https://www.dos.pa.gov/VotingElections/CandidatesCommittees/RunningforOffice/
**Operated by:** Pennsylvania Department of State
**Researched:** March 4, 2026 — **Updated:** June 6, 2026
**Status:** Public, no authentication required (sites behind Incapsula WAF)

---

## Overview

Pennsylvania provides election results through the Department of State's election returns website and the PA Open Data portal. The state offers county-level and precinct-level data. However, PA has **no free, programmatic, state-operated source of pre-election candidate/race data** — its infrastructure is fundamentally a results-reporting system, not a candidate-enumeration system.

### Key 2026 Dates

| Date | Event |
|---|---|
| March 10, 2026 | Primary petition filing deadline |
| **May 19, 2026** | **Primary Election (completed)** |
| August 3, 2026 | Independent/minor party nomination papers deadline (general) |
| August 10, 2026 | Last day for objections / candidate withdrawals |
| **November 3, 2026** | **General Election** |

### 2026 Races on Ballot

| Office | Seats | Notes |
|---|---|---|
| Governor | 1 | Shapiro (D incumbent) vs. Garrity (R) |
| Lt. Governor | 1 | On ballot |
| US House | 17 | All districts |
| State House | 203 | All seats |
| State Senate | 25 | Even-numbered districts |
| US Senate | 0 | Not up in 2026 |

---

## Data Access — State-Operated Sources

### 1. PA Open Data Portal (data.pa.gov) — ⚠️ Mail Ballot Data Only

> **IMPORTANT:** Previous research incorrectly assumed data.pa.gov would have candidate/race/results data via Socrata. It does NOT. The portal only hosts **mail ballot administrative data**.

- **URL:** https://data.pa.gov/
- **API:** Socrata/SODA — `https://data.pa.gov/resource/{4x4-code}.json`
- **Authentication:** None required (API key recommended for higher rate limits)

| Dataset Type | Available? | Notes |
|---|---|---|
| Mail Ballot Requests | ✅ Yes | One dataset per election (snapshots from SURE system) |
| Voter Hall of Fame | ✅ Yes | 50+ year consecutive voters |
| **Candidate Lists** | **❌ No** | Never published on data.pa.gov |
| **Race/Office Info** | **❌ No** | Never published on data.pa.gov |
| **Election Results** | **❌ No** | Results are on electionreturns.pa.gov, NOT Socrata |
| **Ballot Questions** | **❌ No** | Never published on data.pa.gov |

**Known Socrata 4x4 Codes:**

| Dataset | 4x4 Code |
|---|---|
| 2024 General Election Mail Ballot Requests | `3q5t-ddp8` |
| 2021 General Election Mail Ballot Requests | `teba-zcwg` |
| 2020 Primary Mail Ballot Requests | `mcba-yywm` |

**Verdict:** ❌ Cannot be used for Stage 1 (Race Creation) or Stage 2 (Results Ingestion). Only useful for mail ballot tracking, which is outside CivicMirror scope.

---

### 2. Election Returns (electionreturns.pa.gov) — Results Only (No Public API)

- **URL:** https://www.electionreturns.pa.gov/
- **Platform:** Custom PA application (NOT Clarity Elections)
- **Security:** Behind Incapsula WAF — blocks non-browser HTTP requests
- **Pre-election data:** ❌ None — site shows nothing until results are reported

**Undocumented Internal API Endpoints (discovered via research):**

```
GET /api/ElectionReturn/GetCountyBreak?officeId={id}&districtId={id}&methodOfVote={method}
GET /api/ElectionReturn/GetData
```

- Parameters use internal database IDs with no public mapping
- Unstable — can change without notice
- Returns vote counts only, NOT pre-election candidate lists
- **Incapsula blocks non-browser requests** — would require Playwright for access

**Export:** Report Center provides CSV/PDF downloads of results (manual)

**Verdict:** ❌ Cannot be used for Stage 1. Potential Stage 2 source but requires browser automation (Incapsula bypass) and reverse-engineering internal IDs.

---

### 3. PA Voter Services — Candidate Database (Browser-Only)

**Discovered June 2026** — The DOS "Running for Office" page links to this search tool.

- **URL:** https://www.pavoterservices.pa.gov/ElectionInfo/ElectionInfo.aspx
- **Alternative:** https://www.pavoterservices.pa.gov/Pages/CandidateDetails.aspx
- **Platform:** ASP.NET WebForms application
- **Security:** Behind Incapsula WAF
- **Features:** Advanced search by office, district, committee, election year
- **Data:** Candidate filings, campaign finance links, committee registrations
- **API:** ❌ No public API
- **Bulk export:** ❌ None

**Scraping feasibility:** Hard — ASP.NET postback mechanism requires ViewState management. Would need Playwright/browser automation. Could follow Iowa PDF-parsing model but with browser automation instead.

**Verdict:** ⚠️ **Richest state-operated source of pre-election candidate data** but inaccessible programmatically without browser automation.

---

### 4. DOS Website (dos.pa.gov) — Filing PDFs

The Department of State publishes election-related PDFs:

- [2026 Election Calendar](https://www.dos.pa.gov/content/dam/copapwp-pagov/en/dos/programs/voting-and-elections/running-for-office/2026/2026-general-election-calendar.pdf) — Dates/deadlines (parseable)
- [Petition Objections Order](https://www.dos.pa.gov/content/dam/copapwp-pagov/en/dos/programs/voting-and-elections/running-for-office/2026/election%20notice%20and%20order%202026%20with%20attachment%20-%20filed%201-22-2026.pdf) — Legal filings
- [Post-Primary Withdrawal Form](https://www.dos.pa.gov/content/dam/copapwp-pagov/en/dos/programs/voting-and-elections/running-for-office/2026/petition-filing-2026/post-primary%20withdrawal%20form-all%20offices%20-%20final.pdf) — Procedural

To obtain electronic copies of nomination petitions: [Candidate Database](https://www.pavoterservices.pa.gov/ElectionInfo/ElectionInfo.aspx) or email RA-elections@pa.gov.

**Verdict:** ⚠️ Calendar PDF is parseable for election dates. Candidate data is procedural, not structured roster.

---

### 5. Campaign Finance Online (campaignfinanceonline.pa.gov) — Signal Only

- Candidate committee registrations searchable
- Contains: candidate name, office, party, committee name, treasurer
- No API, no bulk export
- Committee registration ≠ certified candidate

**Verdict:** ❌ Not reliable for certified candidates.

---

### 6. vote.pa.gov — Voter Portal

- Voter registration, polling place lookup, mail-in ballot applications
- PA OVR-VBM API is **restricted** to approved organizations (registration submissions only)
- No candidate or ballot data exposed programmatically

**Verdict:** ❌ Irrelevant for Stage 1/2.

---

## Third-Party Sources

| Source | Stage 1? | Cost | PA Coverage | Notes |
|---|---|---|---|---|
| **Google Civic API** | ⚠️ Limited | Free | Unreliable for PA primaries | Already in use — continue as fallback |
| **OpenFEC** | ✅ Federal only | Free (API key) | 17 US House races | `GET /candidates/?election_year=2026&state=PA&office=H` |
| **AP Elections API** | ✅ Full | Paid (enterprise) | Full | Gold standard. Contact: elections_api_info@ap.org |
| **Ballotpedia API** | ✅ Full | Paid (custom) | Full | Contact: data@ballotpedia.org |
| **CivicEngine / BallotReady** | ✅ Full | Paid (custom) | Full | developers.civicengine.com |
| **Democracy Works** | ⚠️ Limited | Paid | Full | Voter guidance focus, less candidate enumeration |
| **OpenStates** | ❌ No | Free | Current legislators only | `/people` endpoint — no candidates/challengers |
| **OpenElections** | ❌ Historical | Free | Historical results | `github.com/openelections/openelections-data-pa` |

---

## Recommended Strategy for Stage 1 — Race Creation

### Tier 1 — Free, Immediate

1. **Google Civic API** — Continue using. May populate races as November approaches.
2. **OpenFEC API** — Add PA US House candidates (17 districts). Free, structured JSON.

### Tier 2 — Free with Effort

3. **pavoterservices.pa.gov scraping** — Browser-automate the Candidate Database for state-level races (Governor, State House 203 seats, State Senate 25 seats). Requires Playwright + ASP.NET form handling. Similar to Iowa PDF-parsing approach.

### Tier 3 — Post-Election Bootstrap

4. **electionreturns.pa.gov** — When results are posted, use Clarity-style bootstrap (auto-create races from results). Requires Incapsula bypass and reverse-engineering internal API IDs.

### Tier 4 — Paid API

5. **Ballotpedia or CivicEngine** — If PA is high-priority, commercial API provides complete coverage.

### Key Deadline

General election ballot fully certified after **August 10, 2026** (objection period ends). Ideal time for final candidate data pull.

---

## Contacts

| Entity | Contact | Purpose |
|---|---|---|
| PA Bureau of Elections | RA-elections@pa.gov / (717) 787-5280 | Data export requests |
| Ballotpedia Data Team | data@ballotpedia.org | API pricing |
| AP Elections | elections_api_info@ap.org | Enterprise API pricing |
| FEC | api.open.fec.gov | Free API key signup |

---

## Notes

- 67 counties — election data is decentralized
- Major swing state with high data demand
- Detailed mail-in ballot tracking data (on data.pa.gov Socrata)
- PA Open Data portal provides **mail ballot data only** — NOT election results, candidates, or races
- All PA state election websites are behind Incapsula WAF (blocks non-browser requests)
- **No free PA state API exists for pre-election candidate data** — this is a structural limitation

---

## Source Coverage Analysis

Pennsylvania is one of the harder states for programmatic candidate data access. The state has no public API for candidates or races — its open data portal (data.pa.gov) only hosts mail ballot tracking data via Socrata/SODA, while election results live on a separate site (electionreturns.pa.gov) with undocumented, Incapsula-protected internal APIs. The PA Voter Services Candidate Database at `pavoterservices.pa.gov` contains the richest state-operated candidate information but is a browser-only ASP.NET WebForms application with no API or bulk export capability. Candidate data is fundamentally scattered across 67 county boards of elections with no state-level aggregation in machine-readable format. For programmatic access: use **Google Civic API** (unreliable for PA), **OpenFEC** (federal races only — free), or paid services (**Ballotpedia**, **CivicEngine**, **AP Elections**). The post-election path via electionreturns.pa.gov internal API may work for combined Stage 1+2 bootstrap with browser automation.
