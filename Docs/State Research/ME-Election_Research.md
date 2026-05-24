# Maine Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API; RCV elections require ranked-choice ballot support |
| Stage 2 — Results Ingestion | ❌ No adapter | SOS + RCV CVR — no adapter built |

---

**Site:** https://www.maine.gov/sos/elections-voting/election-results-data
**Operated by:** Maine Secretary of State
**Researched:** March 4, 2026 · Updated: May 2026
**Status:** Public, no authentication required

---

## Overview

Maine provides election results through the Secretary of State's website. Maine uses ranked-choice voting for certain federal elections and splits Electoral College votes by congressional district, making its result data more granular than most states. The primary geographic unit is the **town** (not county) — Maine has 16 counties but ~500 municipalities.

> **Note:** The old results URL (`/sos/cec/elec/results/`) now 404s. The current landing page is at `/sos/elections-voting/election-results-data` but is JavaScript-rendered and cannot be scraped directly.

---

## Data Access

### Primary State Source

| Property | Detail |
|---|---|
| URL | https://www.maine.gov/sos/elections-voting/election-results-data |
| API | ❌ None |
| Live/Real-time | ❌ None identified |
| Clarity Elections | ❌ Not in use |
| GIS / GeoJSON | ❌ Not offered |
| Download formats | Excel (.xlsx), PDF, Cast Vote Records (RCV elections) |
| Geographic unit | Town / municipality (precinct-level for recent generals) |

### Download URL Pattern (current)

The SOS results are now hosted on a JavaScript-rendered site. Per-year pages follow this pattern:

| Years | URL pattern | Notes |
|---|---|---|
| 2026 | `/sos/elections-voting/election-results-data` | PDF only (special elections to date) |
| 2025 | `/sos/elections-voting/election-results-data` | Excel |
| 2010–2024 | `/sos/elections-voting/election-results-data/previous-election-results` | Accordion list |
| Pre-2010 | N/A | Contact elections division |

Year pages are linked from the accordion and follow two URL formats:
```
# Elections (general/primary)
https://www.maine.gov/sos/elections-voting/election-results-data/2022-election-results#general

# Referendums / ballot measures
https://www.maine.gov/sos/elections-voting/election-results-data/election-results-2023
```
Each year page hosts **Excel (.xlsx)** download links. Some years ≤ 2016 also include TXT or CSV files alongside Excel. Because the pages use an accordion/JS layout, the actual file download links cannot be fetched via static HTTP — the **web-scraping skill** is required to extract them.

---

## API Access

No public REST API. All structured access is through:
1. Downloadable Excel/PDF files from the SOS results page
2. OpenElections pre-processed CSV data (2012–2020)
3. Supplementary APIs (Google Civic, OpenFEC, OpenStates) for candidate/official metadata

---

## OpenElections Coverage

OpenElections (`github.com/openelections/openelections-data-me`) has pre-processed Maine results as structured CSV — the highest-quality machine-readable source available for historical results.

| Year | File | Granularity | Election type |
|---|---|---|---|
| 2012 | `20121106__me__general__town.csv` | Town | General |
| 2016 | `20160614__me__primary__town.csv` | Town | Primary |
| 2016 | `20161108__me__general__precinct.csv` | Precinct | General |
| 2018 | `20181106__me__general__town.csv` | Town | General |
| 2020 | `20201103__me__general__precinct.csv` | Precinct | General |
| 2022 | ❌ Not in repo | — | — |
| 2024 | ❌ Not in repo | — | — |

> For 2022 and 2024, use Maine SOS Excel downloads directly (see below). OpenElections is preferred for 2012–2020 since it is already clean and normalized.

**Base URL for raw CSV downloads:**
```
https://raw.githubusercontent.com/openelections/openelections-data-me/master/{year}/{filename}.csv
```

**CSV schema** (consistent across all files):
```
county, precinct (or town), office, district, party, candidate, votes
```
Sample row:
```
Androscoggin,Auburn,President,,DEM,Joe Biden,6482
```

**Coverage gaps in OpenElections:**
- No primary elections for 2012, 2018, 2020
- No 2022 or 2024 data (must source from Maine SOS Excel downloads)
- No ballot measure data in any year
- No candidate metadata (contact, bio, photo)

---

## Notes

- 16 counties, but results primarily organized by town/municipality
- Ranked-choice voting (RCV) used for federal offices (President, U.S. House CD-2, U.S. Senate)
- Electoral votes split by congressional district: CD-1, CD-2, and 2 at-large
- `{county} Total` rows present in data — must be filtered or handled separately during ingestion
- Unorganized territories and plantations appear as precinct values — require special handling in FIPS mapping
- Maine FIPS state code: `23`

---

## Source Coverage Analysis

Maine's primary data source (maine.gov/sos) covers historical election results and RCV round-by-round Cast Vote Records well, but provides no structured data for ballot measures, candidate metadata (contact, party affiliation, platform), official/incumbent information, or geographic district boundaries. No public REST API or real-time results feed exists. Gaps should be filled with **Google Civic Information API** (candidates, districts, election types), **Ballotpedia** (ballot measures, candidate bios), **OpenStates** (state legislative incumbents and terms), **OpenFEC** (federal candidate finance/contact data), and **MEDSL** for normalized historical results. **Clarity Elections** does not appear to be in use for Maine.

---

## Integration Plan

### Data Source Matrix

| Data point | Source | Method | Notes |
|---|---|---|---|
| Election list | Google Civic API | `GET /elections` | Filter by `ocdDivisionId` containing `state:me` |
| Race / contest list | Google Civic API | `GET /voterinfo` | Use Maine ZIP codes as address input |
| Federal candidates | Google Civic API + OpenFEC | REST | Civic API for ballot context; FEC for finance/contact |
| State candidates | Google Civic API + Ballotpedia | REST | OpenStates for incumbents |
| Ballot measures | Ballotpedia | REST/scrape | Maine SOS PDF as backup for certified text |
| Historical results (2012–2020) | OpenElections CSV | GitHub raw download | See table above |
| Recent results (2022–2024) | Maine SOS Excel | Download + parse | URL requires JS navigation — see open questions |
| Incumbents / officials | OpenStates | `GET /people` | Filter `jurisdiction=ocd-division/country:us/state:me` |
| Federal incumbents | `unitedstates/congress-legislators` | GitHub YAML | FEC crosswalk IDs included |
| District boundaries (GeoJSON) | Census TIGER/Line | REST/download | Use FIPS `23` + district type |
| District OCD-IDs | Open Civic Data | REST | `ocd-division/country:us/state:me/...` |

### Ingestion Strategy

**Phase 1 — Elections & Races (Google Civic API)**
1. Call `GET /elections`, filter for Maine (`ocdDivisionId` contains `state:me`)
2. For each active election, call `GET /voterinfo` with representative ZIP codes for each congressional district:
   - CD-1: `04101` (Portland)
   - CD-2: `04401` (Bangor)
   - Statewide: `04330` (Augusta)
3. Upsert `Election` and `Race` records; store `ocdDivisionId` for district linking

**Phase 2 — Historical Results (OpenElections)**
1. Download CSV files from `openelections-data-me` for 2012–2020
2. Parse `county, precinct/town, office, district, party, candidate, votes` columns
3. Filter out `{county} Total` rows (these are subtotals, not actual precincts)
4. Match `office` + `district` strings to existing `Race` records
5. Upsert `Candidate` and `OfficialResult` records; mark `result_type = OFFICIAL`

**Phase 3 — Recent Results (Maine SOS Excel, 2010–2025)**
1. Navigate to `/sos/elections-voting/election-results-data/previous-election-results` using the **web-scraping skill** (JS-rendered accordion) to extract per-year Excel download links
2. For each year, download the Excel file(s) and parse with `openpyxl`
3. The column structure varies by office type — normalize to the same schema as OpenElections CSV
4. **Coverage by year:**
   - 2026: PDF only (special elections) — skip for now
   - 2025: Excel available
   - 2010–2024: Excel (some years ≤ 2016 also have TXT/CSV)
   - Pre-2010: Contact elections division — not in scope

**Phase 4 — Candidates & Incumbents**
1. OpenFEC: `GET /candidates?state=ME&cycle={year}` for federal candidate metadata
2. OpenStates: `GET /people?jurisdiction=ocd-division/country:us/state:me` for state legislative incumbents
3. Ballotpedia API/scrape for candidate bios, ballot measure text

**Phase 5 — Districts & Boundaries**
1. Census TIGER/Line: congressional districts (FIPS `23`), state legislative districts, county/municipal boundaries
2. Store GeoJSON under `District.boundary`; link via OCD-ID

### Data Modeling Notes

- **Town as jurisdiction**: Maine's primary geographic unit is the municipality (~500 towns). Map town names to FIPS place codes using Census Gazetteer (`tl_2020_23_place.shp`).
- **Unorganized territories**: Values like `T3 R12 Twp` or `Cyr Plt` appear in result data. These are unincorporated areas without town status — store as-is in `jurisdiction_fragment`, do not attempt FIPS mapping.
- **OCD-IDs**: Maine congressional districts use `ocd-division/country:us/state:me/cd:1` and `ocd-division/country:us/state:me/cd:2`.
- **`{county} Total` rows**: Rows where the town/precinct column contains `{COUNTY} Total` (e.g., `ANDROSCOGGIN Total`) are county subtotals — skip during ingestion.

### Open Questions

| # | Question | Impact | Status |
|---|---|---|---|
| 1 | What is the Excel column structure for 2022/2024 SOS files? | Parser design | ⏳ Requires web-scraping skill to download and inspect |
| 2 | Does OpenElections plan to add 2022/2024 data for Maine? | Fallback strategy | ⏳ Monitor repo; use SOS as primary for now |
| 3 | Where is the RCV round-by-round CVR data hosted post-URL-migration? | RCV (deprioritized) | ⏳ Pending |
