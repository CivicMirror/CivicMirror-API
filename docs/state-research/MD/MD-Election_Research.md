# Maryland Election Results — Research Notes(Updated 07/21/2026)

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API; SBE election calendar PDF + candidate list drops confirm cycle structure |
| Stage 1 — Race Creation | ✅ Source identified | SBE candidate list CSVs carry office + district + party — sufficient to enumerate races |
| Stage 1 — Candidate Info | ✅ Source identified | SBE candidate list CSVs (rich: contact, socials, committee, running mates) |
| Stage 2 — Results Ingestion (certified) | ✅ Source identified | Archive `election_data/` CSVs — full precinct/county/district files, schema documented below |
| Stage 2 — Live / Election Night | ✅ Source identified | Static HTML result pages (full ballot) + `dashboarddata.json` (featured contests) — no adapter built yet |
| Municipal (long-tail) | ⚠️ LLM pipeline | Per-town DOCX/PDF/XLSX freeform files |

---

**Site:** https://elections.maryland.gov/
**Operated by:** Maryland State Board of Elections (SBE)
**Researched:** March 4, 2026 · **Updated:** July 21, 2026 (HAR capture + live verification)
**Status:** Public, no authentication. Cloudflare-fronted, Dreamweaver-templated static site.
**Vendor:** ❌ **NOT Clarity Elections.** Prior open question resolved — MD SBE publishes homegrown static HTML + flat-file JSON/CSV. No Clarity/Civix, no Power BI, no third-party ENR platform observed anywhere in the HAR.

---

## ⚠️ Adapter Gotchas (read first)

1. **Soft 404s.** Missing pages return **HTTP 200** with a "Page Not Found" HTML body (consistently ~14,424 bytes). Adapters MUST content-check responses (e.g., look for `Page Not Found` or expected markers), never trust status codes. Confirmed on `results_data/`, `2026/election_data/`, `2024/election_data/` (non-archive path).
2. **UTF-8 BOM on JSON.** `dashboarddata.json` is BOM-prefixed — `json.load(f)` fails; use `encoding='utf-8-sig'`.
3. **Pre-formatted numeric strings.** Dashboard JSON votes are `"10,588"`, percentages `"10.48%"`. HTML tables likewise use comma-formatted numbers with leading whitespace. Strip/parse.
4. **CSVs served as `application/octet-stream`**, CRLF line endings, and a **trailing space after the closing quote** on some lines (`..."Against" \r\n`) — pandas handles it, strict parsers may not.
5. **Filenames contain dots**: `2026_GP_governorlt.governor_candidatelist.csv` — don't split extension naively.
6. **Candidate CSV schema drift** between cycles: 2025 has `Twitter`; 2026 renames to `X`, adds `Campaign Mailing Address`, `Campaign Mailing City State and Zip`, `Public Phone`, and a trailing unnamed empty column. Map columns by header name, never by position.
7. **Stale URL:** `elections.maryland.gov/elections/results_data/` (from original research) is dead (soft-404). Certified data moved to per-year archive paths (below).
8. **"Against" columns** exist throughout results CSVs — used for judicial continuance / retention questions. Regular candidate rows leave them empty.

---

## Stage 1 — Elections, Races, Candidates

### Candidate List CSVs (primary source)

**Index:** `https://elections.maryland.gov/elections/{year}/primary_candidates/index.html`
(equivalently `General_candidates/` in archive years; 2025 special: `elections/archive/2025/SP_Primary_Candidate/`)

**Per-office CSVs (2026 gubernatorial primary set):**

```
/elections/2026/primary_candidates/2026_GP_statewide_candidatelist.csv
/elections/2026/primary_candidates/2026_GP_governorlt.governor_candidatelist.csv
/elections/2026/primary_candidates/2026_GP_comptroller_candidatelist.csv
/elections/2026/primary_candidates/2026_GP_attorneygeneral_candidatelist.csv
/elections/2026/primary_candidates/2026_GP_representativeincongressbydistrict_candidatelist.csv
/elections/2026/primary_candidates/2026_GP_statesenatorbydistrict_candidatelist.csv
/elections/2026/primary_candidates/2026_GP_houseofdelegatesbydistrict_candidatelist.csv
/elections/2026/primary_candidates/2026_GP_judgeofthecircuitcourtbydistrictandcounty_candidatelist.csv
```

Also HTML equivalents (`..._candidatelist.html`) and a per-county variant (`2026_GP_all_counties_candidatelist.html`). Cycle prefix: `GP` = Gubernatorial Primary; expect `GG` = Gubernatorial General, `PP`/`PG` = Presidential Primary/General.

**Schema (2026, by header name):**
`Office Name`, `Contest Run By District Name and Number`, `Candidate Ballot Last Name and Suffix`, `Candidate First Name and Middle Name`, `Additional Information`, `Office Political Party`, `Candidate Residential Jurisdiction`, `Candidate Gender`, `Candidate Status`, `Filing Type and Date` (e.g., `Regular - 02/13/2026`), `Campaign Mailing Address`, `Campaign Mailing City State and Zip`, `Public Phone`, `Email`, `Website`, `Facebook`, `X`, `Other`, `Committee Name`, `Has Related Candidate`, then a full `Related Candidate *` block (running mate — used for Gov/Lt. Gov tickets).

**Notes:**
- `Contest Run By District Name and Number` = race scoping field (`State Of Maryland`, county name, district number) → race creation key.
- Names come **pre-split** (ballot last name + suffix vs. first + middle) — no name-parsing needed, but suffixes are embedded in the last-name field (`Brunner, Jr.`).
- `Candidate Status` (`Active` / withdrawn etc.) → filter before race creation.
- This is materially richer than Google Civic for candidate profiles (committee, filing date, socials). Google Civic still useful for OCD-ID alignment.

---

## Stage 2 — Certified Results (post-canvass CSVs)

**Location (per-year archive):** `https://elections.maryland.gov/elections/archive/{year}/election_data/index.html`
✅ Verified live for 2024 (317 CSV files). The current cycle's data lands here after certification; during the active cycle `/elections/{year}/election_data/` does **not** exist (soft-404).

**File naming:** `{CYCLE}{YY}_{scope}{Type}.csv`

Per-county (county code `01`–`24`, Allegany=01 … Baltimore City included):
```
PG24_01CountyResults.csv          — county-level totals per contest
PG24_01PrecinctsResults.csv       — precinct-level
PG24_01QuestionResults.csv        — ballot questions, county-level
PG24_01QuestionbyPrecinctsResults.csv
PG24_02CouncResults.csv           — councilmanic-district contests (where applicable)
PG24_05CommissionerResults.csv    — commissioner-district contests (where applicable)
```

Statewide rollups:
```
PG24_AllPrecincts.csv                     (~17 MB for 2024 general)
PG24_AllPrecinctsQuestions.csv
PG24_CongressionalBreakDown.csv
PG24_LegislativeBreakDown.csv
PG24_AllQuestionsCongressionalBreakDown.csv
PG24_AllQuestionsLegislativeBreakDown.csv
PP24_AllPrecincts{Democratic|Republican|Non-partisian}.csv   [sic — "partisian"]
```

**AllPrecincts schema:**
`County`, `County Name`, `Election District - Precinct` (e.g., `001-000`), `Congressional`, `Legislative`, `Office Name`, `Office District`, `Candidate Name`, `Party` (3-letter: DEM/REP/LIB…), `Winner` (`Y`/blank), `Write-In?`, then vote-mode pairs: `Early Votes[/ Against]`, `Election Night Votes[...]`, `Mail-In Ballot 1 Votes[...]`, `Provisional Votes[...]`, `Mail-In Ballot 2 Votes[...]`.

**CountyResults schema:** same contest/candidate columns (no geography prefix) + `Total Votes` / `Total Votes Against`.

Precinct rows carry congressional + legislative district assignments → useful for district-level aggregation and OCD-ID mapping. A precinct reference file also exists per cycle: `/elections/2026/GP26_State_Precinct_Reference.xlsx`.

---

## Stage 2 — Live / Election-Night Results

Maryland regenerates **static HTML** during canvass; there is no discovered results API beyond one flat JSON file. Two ingestion paths:

### A. Full-ballot HTML pages (primary live source)

**Index:** `https://elections.maryland.gov/elections/{year}/primary_results/index.html` (general: `general_results/` — confirm at general time)
Title string: "Unofficial 2026 Gubernatorial Primary Election Results" → flips to official language post-certification.

**Summary pages** (statewide/district totals with vote-mode split):
`gen_results_{year}_{group}[_{districtSeq}].html` — table columns: Name, Party, Early Voting, Election Day, Mail-In Ballot, Provisional, Total, Percentage. `_P` suffix = printable variant.

**Office group enumeration (2026 primary, from HAR):**

| Group | Office | District pages |
|---|---|---|
| 1 | Governor / Lt. Governor | — |
| 2 | Comptroller | — |
| 3 | Attorney General | — |
| 4 | Representative in Congress | `_1`…`_8` |
| 5 | State Senator | `_1`…`_47` |
| 6 | House of Delegates | `_1`…`_71` (seq ≠ district label; subdistricts 1A/1B/1C… map sequentially) |
| 7 | Judge of the Circuit Court | `_1`…`_7`+ (circuits, non-contiguous: 1,2,3,5,6,7,8) |

⚠️ Group-6 and group-7 sequence numbers are **positional**, not district labels — scrape the index page anchors to build the seq→district map each cycle rather than assuming.

**Detail pages** (by-county breakdown per contest/party):
`gen_detail_results_{year}_{office}_{seq}_{Party}.html` — Jurisdiction rows × candidate columns (`DetailsNameCol` / `DetailsVotesCol` classes; summary tables use `table-banded`, `VotesCol` with `headers="EarlyVotes001-"`-style attributes usable as parse anchors).

Scrape cadence: pages are plain GETs, Cloudflare-cached, no auth, no JS rendering needed — requests + lxml is sufficient; no Playwright required (unlike NY).

### B. `dashboarddata.json` (featured-contest feed)

**URL:** `https://elections.maryland.gov/elections/2026/primary_results/dashboarddata.json`
Consumed by `js/dashboard.min.js` on the SBE homepage. `Cache-Control: no-cache`, ETag present.

```json
{
  "lastRefreshed": "07/17/2026 05:51:42 PM",
  "results": [
    {
      "Id": "ric_d5_dem_vf1",
      "OfficeName": "Representative in Congress",
      "District": "District 5",
      "VoterFor": "Democratic Candidates - Vote for 1",
      "PrecinctsReported": "(227 of 227 election day precincts reported)",
      "County": "",
      "candidates": [
        {"name": "Adrian Boafo", "votes": "33,081", "percentage": "32.74%"}
      ]
    }
  ]
}
```

- **Scope-limited:** only contests featured on the homepage dashboard (currently 4: CD-5 & CD-6, D/R). ❌ Not a full-ballot feed — treat as a change-detection heartbeat (`lastRefreshed` + ETag) that triggers the HTML scrape, not as the results source itself.
- `PrecinctsReported` is a display string — regex out `(\d+) of (\d+)`.
- Contest `Id` slugs (`ric_d5_dem_vf1`) are stable-looking keys: office abbreviation + district + party + vote-for.

---

## Municipal Results (long-tail → LLM pipeline)

**Index:** `https://elections.maryland.gov/elections/municipal_results.html` (+ `municipal_results_archive.html`)
Per-town freeform files at `/elections/municipal_results/{year}/{year}-{Town}_Election_Results.{docx|pdf|xlsx}` — ~30+ towns for 2026, zero schema consistency (verified: Charlestown DOCX is a letter from the Town Administrator with a vote list inside a one-cell table). This is exactly the hybrid-architecture LLM-extraction lane; the SBE index page gives a clean file manifest to enumerate.

---

## Notes

- 24 jurisdictions (23 counties + Baltimore City); SBE administers statewide — fully centralized, no per-county ENR hunting (contrast: OH, WI).
- Vote-mode granularity everywhere: Early / Election Day / Mail-In (two canvass rounds in certified CSVs) / Provisional.
- Ballot questions covered in dedicated CSVs with congressional/legislative breakdowns.
- Google Analytics + Google Translate widget are the only third-party scripts; email addresses are Cloudflare-obfuscated (`email-decode.min.js`) — candidate CSV emails are plaintext, so scrape those, not the HTML.

## Source Coverage Analysis (updated)

Maryland is now one of the **most fully covered states in the batch**: centralized administration, certified CSVs at precinct/county/district granularity with a stable documented schema, per-office candidate CSVs rich enough to drive both race creation and candidate profiles, and a low-friction live path (static HTML + JSON heartbeat, no auth, no JS, no stealth). The Clarity question from the original research is **closed — negative**. Remaining gaps: ballot-measure *text* and geographic boundaries (supplement via Ballotpedia / Census TIGER as elsewhere), incumbents (OpenStates), and the municipal long-tail (route to LLM pipeline via the SBE manifest). Recommended build order: (1) certified-archive CSV adapter (highest value, easiest), (2) live HTML scraper keyed off the index-page anchor map with `dashboarddata.json`/ETag as refresh trigger, (3) candidate-list CSV loader for Stage 1.
