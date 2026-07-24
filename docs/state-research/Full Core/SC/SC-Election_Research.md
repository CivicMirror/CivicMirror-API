# South Carolina Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Complete | VREMS `sync_sc_elections` task — all 3 types (General/Local/Special), 122+ elections/year |
| Stage 1 — Race Creation | ✅ Complete | VREMS `sync_sc_races` task — primary-party partitioned races, candidate status preserved |
| Stage 2 — Results Ingestion | ✅ Adapter built | Clarity Elections adapter (`results/adapters/sc.py`); needs `results_url` set in admin per election |

---

**Site:** https://www.scvotes.gov/election-results
**Operated by:** South Carolina Election Commission
**Researched:** March 4, 2026 | **Updated:** May 24, 2026 (HAR analysis) | **Implemented:** May 24, 2026
**Status:** Public, no authentication required

---

## Implementation

**Module:** `integrations/sc_vrems/`

### Tasks

| Task | Trigger | Schedule |
|---|---|---|
| `sync_sc_elections` | `POST /internal/tasks/sync-sc-vrems/` | Daily (Cloud Scheduler) |
| `sync_sc_races` | Queued by `sync_sc_elections` | Staggered 2s apart per election |

### What `sync_sc_elections` does
1. Calls VREMS `GetYearsByElectionType` + `GetElections` for all 3 types
2. Upserts `Election` records (source_id format: `vrems_sc_{electionId}`)
3. Skips race sync for referendums (`filingPeriodBeginDate == null`) — Election record still created
4. Skips race sync for elections where filing period hasn't opened yet — will pick up on next daily run
5. Queues `sync_sc_races` for each eligible election with a 2-second stagger

### What `sync_sc_races` does
1. Calls VREMS `CandidateSearch` POST for the given `electionId`
2. Groups candidates into races: partitioned by party for primaries; merged by party for generals
3. Upserts `Race` + `Candidate` records
4. Stores raw VREMS `status` (e.g. `Elected`, `Defeated In Primary`) in `Candidate.source_metadata["vrems_status"]`
5. Idempotent — safe to re-run

### Notes on referendum elections
Referendum elections (`filingPeriodBeginDate == null`) get `Election` records created but no `Race` records.
Full ballot measure coverage requires a future investigation of `electionhistory.scvotes.gov`.

### Notes on results (Stage 3)
The Clarity ENR adapter (`results/adapters/sc.py`) is ready. ENR IDs and VREMS IDs use independent
numbering systems — the `results_url` for each election must be set manually in Django admin after
results are posted at `https://www.enr-scvotes.org/SC/{enr_id}/`.

---

## Overview

South Carolina provides election results through the SC Election Commission website (SCVotes.gov) with county-level and precinct-level results. The site is built on **WordPress** using **The Events Calendar Pro** plugin for upcoming elections, and uses the **Clarity Elections (ENR)** platform at `enr-scvotes.org` for live and archived results. A separate **Election History Database** was launched in 2024 at `electionhistory.scvotes.gov`. Candidate and race data is served through a separate ASP.NET Core app at `vrems.scvotes.sc.gov`.

---

## API Access

No public REST API has been officially documented. However, several machine-readable surfaces exist.

### 1. VREMS Candidate API (Confirmed — fully public, no login)

`vrems.scvotes.sc.gov` exposes clean JSON endpoints for election discovery and a structured HTML table for candidate data. Confirmed via HAR analysis on 2026-05-24.

**Auth mechanism:** ASP.NET Core antiforgery cookie only. The cookie is issued automatically on the first GET. No credentials, no login, no API key.

#### Endpoints

**Get available years for an election type**
```
GET https://vrems.scvotes.sc.gov/Candidate/GetYearsByElectionType?electionType={type}
Header: X-Requested-With: XMLHttpRequest
```
Returns JSON array. Example response for `General`:
```json
[{"electionYear":2026},{"electionYear":2024},{"electionYear":2022},{"electionYear":2020},{"electionYear":2018}]
```

**Get elections for a type + year**
```
GET https://vrems.scvotes.sc.gov/Candidate/GetElections?electionType={type}&year={year}
Header: X-Requested-With: XMLHttpRequest
```
Returns JSON array with full election metadata:
```json
[
  {
    "electionId": "22598",
    "electionName": "Statewide Primary",
    "displayName": "6/9/2026 Statewide Primary",
    "electionDate": "2026-06-09T00:00:00",
    "filingPeriodBeginDate": "2026-03-16T12:00:00"
  }
]
```
Note: `filingPeriodBeginDate` is `null` for referendum/ballot question elections.

**Get candidates for an election**
```
POST https://vrems.scvotes.sc.gov/Candidate/CandidateSearch/
Header: X-Requested-With: XMLHttpRequest
Content-Type: multipart/form-data
Body fields:
  ElectionId            = {electionId}
  ExportFileName        = Candidates_{electionId}
  SelectedOffice        = -1          (all offices)
  SelectedCandidateStatus = All
  CandidateFirstName    = (empty)
  CandidateLastName     = (empty)
  SelectedPoliticalParty = All
  SelectedFilingLocation = All
```
Returns HTML fragment containing `<table id="gridCandidateSearch">` with one row per candidate.

**Candidate table columns (confirmed):**
| Column | Notes |
|---|---|
| Office | Contest name, e.g. "Governor", "State House of Representatives, District 98" |
| Associated Counties | County names; blank for statewide |
| Name on Ballot | Candidate name; contains `<a href="CandidateDetail/?candidateId=...&electionId=...">` |
| Running Mate | Populated for Lt. Governor races |
| Party | Republican, Democratic, or blank for nonpartisan |
| Location of Filing | "State" for statewide; county name for local |
| Candidate Status | See status values below |

**Candidate status values (confirmed):**

Active elections:
- `Active`
- `Withdrew Before Primary`
- `Decertified before Primary`
- `Disqualified before Primary`
- `Not Certified for Primary`

Completed elections:
- `Elected`
- `Defeated In Primary`
- `Defeated in Election`

> ⚠️ Status doubles as outcome for completed elections — a key field for Stage 3 race result population.

#### Election Types (`electionType` parameter values)

| Value | Covers | Year history confirmed |
|---|---|---|
| `General` | Statewide primaries and general elections only | 2018–2026 |
| `Local` | All municipal, county, school district, fire/water district elections — both regular AND local special elections, plus referendums | 2019–2026 |
| `Special` | State-level legislative special elections only (U.S. House, SC Senate, SC House) | 2019–2026 |

> **Important:** Local special elections (town council vacancies, school board seats, etc.) appear under `Local`, NOT under `Special`. The `Special` type is only for state legislative chambers. Confirmed: in 2026, `Special` returned only 1 election (HD98); meanwhile `Local` for 2026 returned 119 elections, including dozens labeled "Special Election."

#### Scale of coverage (2026 confirmed)

| Type | Elections in 2026 | Date range |
|---|---|---|
| General | 2 (Statewide Primary + Statewide General) | Jun–Nov 2026 |
| Local | 119 elections across municipalities, school districts, water/fire districts, referendums | Jan–Dec 2026 |
| Special | 1 (HD98, already completed) | Jan 2026 |
| **Total** | **122** | |

The Local list for 2026 spans election dates from 2026-01-06 through 2026-12-01, with the heaviest concentration on 2026-11-03 (31 elections) and 2026-04-07 (14 elections).

#### Known behavior: empty candidate tables

When a Local election's filing period has not yet opened (`filingPeriodBeginDate` is in the future), `CandidateSearch` returns an empty table — no rows, no error message. Example: City of Sumter (22741) and City of Beaufort (22742) both had `filingPeriodBeginDate` of 2026-07-15 and returned 0 candidates on 2026-05-24. The scraper must handle this gracefully and re-poll as filing opens.

#### CandidateDetail endpoint (confirmed from link hrefs)
```
GET https://vrems.scvotes.sc.gov/Candidate/CandidateDetail/?candidateId={id}&electionId={id}&searchType=Default
```
Returns a detailed candidate page. Contains contact information, filing fee, and additional metadata beyond what the search table provides. electionId in this link points to the **General** election record even when the candidate appears in a Primary search — this is intentional system behavior.

---

### 2. WordPress / Tribe Events REST API (Unofficial, Unconfirmed)

The Events Calendar Pro plugin may expose a REST endpoint. To be tested:
```
GET https://scvotes.gov/wp-json/tribe/events/v1/events?per_page=50&start_date=2026-05-24
```

### 3. iCal / Webcal Feed (Confirmed Available)

The upcoming elections calendar publishes a live iCal feed:
```
webcal://scvotes.gov/?post_type=tribe_events&ical=1&eventDisplay=list
```
Exportable `.ics`: `https://scvotes.gov/calendar/list/?shortcode=24f53d40&ical=1`

Parseable fields: event title, start/end datetime, location/county, event URL, categories.

---

## Scraping Analysis — Three Stages

### Stage 1: Creating the Election

**Primary source for upcoming elections:** `https://scvotes.gov/elections-statistics/upcoming-elections/` via iCal feed.

**Richer source (confirmed):** `vrems.scvotes.sc.gov/Candidate/GetElections` — returns structured JSON with `electionId`, `electionName`, `electionDate`, and `filingPeriodBeginDate` for all 122 elections in 2026 across all three types. This is strictly superior to the iCal feed for machine consumption.

**Recommended scraping flow for election creation:**
```python
# One session, three type sweeps
for election_type in ["General", "Local", "Special"]:
    years = GET /GetYearsByElectionType?electionType={election_type}
    for year in years:
        elections = GET /GetElections?electionType={election_type}&year={year}
        # Each election object is a complete Stage 1 record
```

**Fields available for Election record from VREMS:**
| Field | Source |
|---|---|
| `election_id` | `electionId` |
| `name` | `electionName` |
| `display_name` | `displayName` |
| `election_date` | `electionDate` |
| `election_type` | parameter used (`General` / `Local` / `Special`) |
| `filing_period_begin` | `filingPeriodBeginDate` (null for referendums) |

**Annual PDF schedule (supplemental):** `https://scvotes.gov/wp-content/uploads/{year}/{month}/{date}.pdf`

---

### Stage 2: Creating Individual Races (Candidates)

**Source:** `POST vrems.scvotes.sc.gov/Candidate/CandidateSearch/`

All data returned in a single POST per election. No pagination. Returns all candidates across all offices for the given `electionId`.

**Scraping flow:**
1. `GET /Candidate/SelectElection` — establish session cookie + extract `__RequestVerificationToken` from HTML (needed only for the SelectElection POST redirect, not for CandidateSearch)
2. `POST /Candidate/CandidateSearch/` with `ElectionId` + filter defaults → parse HTML table

> The SelectElection → 302 → CandidateSearch redirect flow used in the browser is **not required** for scraping. You can POST directly to `/Candidate/CandidateSearch/` using only the session cookie from Step 1, skipping the form submission redirect entirely.

**Fields extractable per candidate row:**
| Field | Notes |
|---|---|
| `candidate_id` | `data-key` attribute on `<tr>` |
| `candidate_detail_id` | `candidateId` in href (may differ — links to General election record) |
| `office` | Contest name |
| `associated_counties` | Blank for statewide races |
| `name_on_ballot` | Display name used on the ballot |
| `running_mate` | For Lt. Governor only |
| `party` | Republican / Democratic / blank |
| `filing_location` | "State" or county name |
| `status` | Active / outcome status for completed races |

**Coverage caveats:**
- Some local municipalities are noted in the scvotes.gov results pages as not posting data. These may still have candidates in VREMS under Local type — not yet confirmed.
- Referendums (`filingPeriodBeginDate` is null) will have no candidates — they are ballot questions, not candidate contests.
- Local elections with future filing periods return empty tables and must be re-polled.

---

### Stage 3: Getting Results

**Source:** `https://www.enr-scvotes.org/SC/{election_id}/web.{version}/#/summary`

South Carolina uses **Clarity Elections** (Election Night Reporting) for all result reporting from 2008 onward. The ENR election ID is separate from the VREMS `electionId`.

**Supplemental source from VREMS:** For completed elections, the `status` field on each candidate row already encodes the outcome (`Elected`, `Defeated In Primary`, `Defeated in Election`). This gives a lightweight winner/loser signal without ENR, suitable for binary race outcomes.

**ENR URL pattern:**
```
https://www.enr-scvotes.org/SC/{enr_election_id}/web.{version}/#/summary
```

Known recent ENR election IDs:
| Election | ENR ID | VREMS ID |
|---|---|---|
| 2026 Special HD98 Recount | 125869 | 22623 |
| 2026 Special HD98 | 125820 | 22623 |
| 2024 General Election | 122436 | (unknown) |
| 2024 Statewide Primaries | 121614 | (unknown) |

> ENR IDs and VREMS IDs are **independent numbering systems** with no known mapping formula. The ENR ID must be discovered by scraping the Election Results page after results are posted.

**Clarity Elections JSON endpoints (to be confirmed):**
```
https://www.enr-scvotes.org/SC/{enr_election_id}/json/en/summary.json
https://www.enr-scvotes.org/SC/{enr_election_id}/json/en/details.json
```

---

## Bonus: Election History Database

**URL:** `http://electionhistory.scvotes.gov/`

Launched in 2024. Consolidates every candidate contest and ballot question on record into a single searchable platform. Best source for historical race data and ballot measures. API status unknown — requires investigation.

---

## Data Coverage Summary

| Stage | Source | Availability | Format | Confidence |
|---|---|---|---|---|
| Election creation | VREMS GetElections (all 3 types) | ✅ Public JSON | JSON | **Confirmed** |
| Election creation (alt) | scvotes.gov iCal feed | ✅ Public | iCal | High |
| Annual schedule | scvotes.gov PDFs | ✅ Public | PDF | Medium |
| Candidates / Races | VREMS CandidateSearch POST | ✅ Public HTML table | HTML (scrape) | **Confirmed** |
| Race outcomes (lightweight) | VREMS status field | ✅ In candidate table | HTML field | **Confirmed** |
| Live/Final Results (full) | enr-scvotes.org (Clarity) | ✅ Public | JSON (unconfirmed) / SPA | Medium |
| Historical races | electionhistory.scvotes.gov | ✅ Public | Unknown | TBD |
| Ballot measures | electionhistory.scvotes.gov | ✅ Public | Unknown | TBD |

---

## Supplemental Sources (unchanged)

- **Google Civic Information API** — elections, candidates, district lookups
- **Ballotpedia** — ballot measures, candidate bios, incumbency
- **OpenStates** — SC state legislative data
- **OpenFEC** — federal candidates and finance
- **MEDSL** — normalized historical results

---

## Notes

- 46 counties; SC Election Commission administers all elections
- Clarity Elections platform confirmed as SC's ENR system
- **VREMS electionId and ENR election ID are separate systems** — no known cross-reference
- Local elections are highly decentralized; some municipalities do not report results to scvotes.gov (check locally for those)
- County-level ENR subdomains exist: `enr-scvotes.org/SC/Greenville/{id}/`, `enr-scvotes.org/SC/Aiken/{id}/`, etc.
- Referendums appear in VREMS under Local type with `filingPeriodBeginDate: null` and 0 candidates
- The `Special` election type in VREMS covers only state legislative chambers; all local specials are under `Local`
