# Virginia Election Data Ingestion Plan

**Date:** 2026-05-25  
**Project:** CivicMirror-API  
**Scope:** Elections, Races, Candidates, Results, Ballot Measures for Virginia  
**Status of current integration:** ❌ No VA adapter built yet

---

## Executive Summary

Virginia is one of the most capable state election data ecosystems but does **not** use Clarity Elections — it uses **Enhanced Voting** (`app.enhancedvoting.com/results/public/api`), a different platform with a public JSON REST API requiring no authentication. All contests (statewide, district, ballot measures) are available as a flat `ballotItems[]` array from a single API endpoint. Historical results (2005–2023) are also available via a separate SBE bulk-CSV system. Candidate data with full contact info is available directly from SBE HTML tables. The integration requires a **new custom adapter** in `results/adapters/va.py` and a **new Django integration app** (`integrations/va_elect/`) for Stage 1 race/candidate creation — it cannot reuse the Clarity adapter pattern.

---

## Confidence Assessment

| Finding | Confidence | Evidence |
|---|---|---|
| Enhanced Voting API is the results platform | ✅ HIGH | Live API tested, confirmed multiple elections |
| All races in flat root-level `ballotItems[]` | ✅ HIGH | Live `/data` endpoint verified, 2025-Nov-General + 2026-April-21-Special |
| `contestType: "BallotMeasure"` (not "Referendum") | ✅ HIGH | Live data confirmed for redistricting referendum |
| Election slug format inconsistency | ✅ HIGH | 3 distinct naming conventions confirmed across 2023-2026 |
| SBE CSV stops at 2023 (specials) / 2022 (November General) | ✅ HIGH | Directory listings confirmed |
| SBE candidate list HTML has full contact info | ✅ HIGH | Live fetch confirmed email, phone, address fields |
| VPAP blocked (403) | ✅ HIGH | Confirmed in multiple probe attempts |
| OpenElections VA data empty (PR #16 unmerged) | ✅ HIGH | Official repo confirmed empty, fork has data |
| VA race creation via Civic API is untested | ✅ HIGH | Documented in project's own Stage1-Race-Creation-Plan.md |
| Enhanced Voting blob CSV URL not resolvable | ⚠️ MEDIUM | All URL patterns returned 404/error; needs browser DevTools inspection |
| `isPrimary` field always `false` in Enhanced Voting API | ✅ HIGH | Confirmed on 4 primary elections tested |

---

## Data Source Inventory

| Source | What It Provides | Format | Auth | URL |
|---|---|---|---|---|
| **Enhanced Voting API** | All races + results (2023-present) | JSON REST | None | `https://app.enhancedvoting.com/results/public/api` |
| **SBE ELECTIONRESULTS CSV** | Precinct-level results (2005–2023) | CSV | None | `https://apps.elections.virginia.gov/SBE_CSV/ELECTIONS/ELECTIONRESULTS/` |
| **SBE ELECTIONWINNERS CSV** | Winners + contact info (2005–2023) | CSV | None | `https://apps.elections.virginia.gov/SBE_CSV/ELECTIONS/ELECTIONWINNERS/` |
| **SBE Candidate List HTML** | All candidates + contact info (current) | HTML table | None | `https://www.elections.virginia.gov/casting-a-ballot/candidate-list/` |
| **SBE Ballot Measures** | Constitutional amendment text | HTML | None | `https://www.elections.virginia.gov/election-law/proposed-amendments-for-{year}/` |
| **Google Civic API** | Elections + races (statewide/federal) | REST/JSON | API Key | `https://www.googleapis.com/civicinfo/v2` |
| **OpenStates API** | Current VA legislators (incumbency) | REST/JSON | API Key | `https://v3.openstates.org/people?jurisdiction=Virginia` |
| **Historical Elections DB** | Precinct-level results (1924-present) | CSV download | None | `https://historical.elections.virginia.gov/elections/download/{id}/precincts_include:1/` |
| **OpenElections VA (fork)** | County/precinct results 1980-2025 | CSV | None | `https://raw.githubusercontent.com/Tenjin25/openelections-data-va/master/` |

---

## Architecture Overview

```mermaid
graph TD
    A[Cloud Scheduler] --> B[sync_va_elections task]
    A --> C[poll_pending_results task]

    B --> D[Scrape elections.virginia.gov\nfor ENR slugs]
    D --> E[GET /api/elections/Virginia/{slug}\n app.enhancedvoting.com]
    E --> F[Upsert Election records\nstate=VA, source=va_elect]
    F --> G[sync_va_races.delay per election]

    G --> H[GET /api/elections/Virginia/{slug}/data\nballotItems flat array]
    H --> I{contestType?}
    I -->|Candidate| J[Create Race + Candidate rows\nsource=va_elect, canonical_key=...]
    I -->|BallotMeasure| K[Create Race + MeasureOption rows\nYes / No per referendum[].text]
    
    J --> L[Supplement: Scrape SBE candidate list\nfor email, phone, website, address]
    K --> M[Supplement: Scrape SBE ballot measure page\nfor full amendment text]

    C --> N[Query Elections:\nstatus=RESULTS_PENDING, state=VA]
    N --> O[ingest_official_results.delay VA, pk]
    O --> P[VirginiaAdapter.fetch_results]
    P --> Q[GET /api/elections/Virginia/{slug}/data\nballotItems summaryResults]
    Q --> R{Changed since last fetch?\nasOf timestamp cache}
    R -->|No change| S[AdapterResult unchanged=True\nskip DB write]
    R -->|Changed| T[Build ResultRow list\nmap ballotOptions to rows]
    T --> U[_process_race_results\nupsert OfficialResult rows]

    V[SBE CSV Historical Import\nmanagement command] --> W[Download ELECTIONRESULTS/{year}/{name}.csv]
    W --> X[Process 23-col precinct CSV\nsum votes per candidate per election]
    X --> U
```

---

## Stage 1: Elections

### Source
- **Primary**: Google Civic API (already integrated via `integrations/civic/`) — VA is `ocd-division/country:us/state:va`
- **Supplement**: Scrape `elections.virginia.gov/resultsreports/election-results/` to discover all ENR slugs

### Virginia Election Calendar Notes
- **Odd-year elections**: Governor, Lt. Governor, AG, all 100 House of Delegates seats, all 40 VA Senate seats — elected in odd years (2025, 2027, 2029...)
- **Governor term limit**: Cannot serve consecutive terms
- **Federal elections**: U.S. Senate + 11 U.S. House seats — even years
- **133 localities**: 95 counties + **38 independent cities** (legally separate from counties; use `place:` OCD ID, not `county:`)
- **Semi-open primary**: No party registration; voters choose party on election day

### Election Source ID Pattern
```python
# Proposed source_id convention for va_elect integration:
f"va_elect_{slug}"  # e.g., "va_elect_2025-November-General"
```

### ENR Slug Discovery
The Enhanced Voting API has **no election index endpoint** — `GET /api/elections/Virginia` returns 404. Slug discovery requires scraping `elections.virginia.gov/resultsreports/election-results/` and extracting ENR link hrefs.

**Slug format inconsistencies across years:**

| Era | Format | Example |
|---|---|---|
| 2023 | Abbreviated kebab | `2023-Nov-Gen` |
| 2024 major | CamelCase or underscore | `2024NovemberGeneral`, `2024_June_Democratic_Primary` |
| 2025+ | Full-word kebab | `2025-November-General` |
| Specials | Date-kebab | `2025-September-9-Special` |
| Edge cases | Trailing underscore | `2025-April-8-Town-of-Marion-Special_` |

> ⚠️ The API accepts both `Virginia` and `virginia` as the jurisdiction name (case-insensitive), but the scraper should preserve the slug exactly as it appears in the href.

---

## Stage 2: Races & Candidates

### New Django App: `integrations/va_elect/`

```
backend/integrations/va_elect/
├── __init__.py
├── apps.py               # VaElectConfig
├── client.py             # VaElectClient
├── exceptions.py         # VaElectError, VaElectRetryableError
├── mappers.py            # map_election, map_race, map_candidate, build_canonical_key
├── tasks.py              # sync_va_elections, sync_va_races
└── tests/
    ├── __init__.py
    ├── test_client.py
    └── test_tasks.py
```

### Enhanced Voting API — Race Data Structure

**Endpoint:** `GET https://app.enhancedvoting.com/results/public/api/elections/Virginia/{slug}/data`

**Key structural facts (confirmed from live data):**
1. ALL contests (statewide, district, ballot measures) are in a **flat root-level `ballotItems[]`** array — no nesting by locality
2. `childLocalities` within `jurisdiction` contains ONLY summary metadata — **no ballot item data**
3. Statewide races have `reportingUnits: 133`; district races have `reportingUnits: 1`
4. Statewide races populate `crossCounties[]` with all 133 locality names; district races have `crossCounties: []`

**`contestType` values:**

| contestType | Meaning | `ballotOptions[].nativeId` | `isWinner` |
|---|---|---|---|
| `"Candidate"` | Election race | `"cs{n}"` or `"wi-cc{n}"` (write-ins) | `true`/`false` |
| `"BallotMeasure"` | Referendum/constitutional amendment | `"bms{n}"` | `null` |

**Full `ballotItem` field map for race creation:**

```python
# From ballotItem object → Race model
{
    "id":            → source_metadata["enr_ballot_item_id"]
    "name[en].text": → office_title (e.g., "Governor", "Member, House of Delegates (1st District)")
    "voteTotal":     → (informational; not stored on Race)
    "contestType":   → race_type: "candidate" if "Candidate", "measure" if "BallotMeasure"
    "reportingStatus.reportingUnits": → 133 = statewide, 1 = single district
    "crossCounties": → [] means district race; list = statewide
    "referendum[en].text": → (BallotMeasure only) measure question HTML text
    "isOfficialResults": → certification_status
    "publishPublicElectionId": → the election slug (stored in source_metadata)
}

# From ballotOptions[] → Candidate or MeasureOption model
{
    "name[en].text":  → candidate.name (or measure_option.label)
    "party.abbreviation": → candidate.party
    "isWinner":       → (set via ResultRow, not directly on Candidate model)
    "isWriteIn":      → used to flag write-in aggregate rows
}
```

**2025 November General `ballotItems` order (confirmed):**
- `[0]` Governor (statewide, 133 units)
- `[1]` Lieutenant Governor (statewide, 133 units)
- `[2]` Attorney General (statewide, 133 units)
- `[3]–[102]` Member, House of Delegates (1st–100th District) (district, 1 unit each)

### Canonical Key Pattern

Following the established pattern (`{source}:{election_source_id}:{normalized_office}:{normalized_geography}:{party}`):

```python
# va_elect mappers.py
def build_canonical_key(election_source_id, office_title, district_label, contest_type, party="nonpartisan"):
    parts = [
        "va_elect",
        election_source_id,                         # "va_elect_2025-November-General"
        normalize(office_title),                    # "governor"
        normalize(district_label) or "statewide",  # "statewide" or "1st district"
        normalize(party) or "nonpartisan",          # "republican" or "nonpartisan"
    ]
    return ":".join(parts)
# → "va_elect:va_elect_2025-November-General:governor:statewide:nonpartisan"
# → "va_elect:va_elect_2025-November-General:member house of delegates (1st district):1st district:nonpartisan"
```

> **Note:** A `Race.Source.VA_ELECT = 'va_elect'` entry must be added to `elections/models.py` and a migration generated.

### New Election Source Choices Entry (Migration Required)

```python
# elections/models.py — Race.Source (add to existing enum)
VA_ELECT = 'va_elect', 'Virginia ELECT'
```

### Candidate Data Supplement

For candidate contact info not available in the Enhanced Voting API, supplement from **SBE Candidate List HTML tables**:

**URL pattern (confirmed working):**
```
https://www.elections.virginia.gov/casting-a-ballot/candidate-list/november-4-2025-gen-elect-all-office/
```

**Available contact fields (confirmed):**
| Field | SBE Candidate List | ELECTIONWINNERS CSV | OpenStates |
|---|---|---|---|
| Name | ✅ | ✅ | ✅ |
| Party | ✅ | ✅ | ✅ |
| Office/District | ✅ | ✅ | ✅ |
| Incumbent flag | ✅ | ✅ (`IsIncumbant`) | ✅ |
| Campaign Email | ✅ | ✅ | ❌ |
| Campaign Phone | ✅ | ❌ | ✅ (office phone) |
| Campaign Website | ✅ | ❌ | ✅ (homepage link) |
| Campaign Address | ✅ | ✅ | ✅ (district office) |
| Headshot/Bio | ❌ | ❌ | ✅ (image URL) |
| Birth date | ❌ | ❌ | ✅ |

> For **current legislators** (incumbents), supplement with OpenStates API to add biographical data (image, gender, office addresses, committee memberships).

---

## Stage 3: Results Ingestion

### New Results Adapter: `results/adapters/va.py`

Virginia uses **Enhanced Voting**, not Clarity — this is a **fully custom adapter** implementing `StateResultsAdapter` from scratch.

**Version/change detection strategy:** Cache the `election.asOf` timestamp from the API metadata endpoint. If `asOf` is unchanged since last fetch, return `AdapterResult(unchanged=True)`.

```python
# results/adapters/va.py — Skeleton

from django.core.cache import cache
import requests
from .base import StateResultsAdapter, AdapterResult, ResultRow
from .registry import register

_ENR_BASE = "https://app.enhancedvoting.com/results/public/api"
_CACHE_TTL = 86400 * 30  # 30 days

@register
class VirginiaAdapter(StateResultsAdapter):
    state = "VA"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election
        election = Election.objects.get(pk=election_id)
        slug = election.source_metadata.get("enr_slug")
        if not slug:
            return AdapterResult(rows=[], source_url="", mapping_confidence="none",
                                 notes="No ENR slug in election.source_metadata")

        # Step 1: Check version (asOf timestamp)
        meta_url = f"{_ENR_BASE}/elections/Virginia/{slug}"
        meta = requests.get(meta_url, timeout=15).json()
        as_of = meta.get("asOf", "")
        cache_key = f"va_elect:ver:{election_id}:{slug}"
        if cache.get(cache_key) == as_of:
            return AdapterResult(rows=[], source_url=meta_url, mapping_confidence="full",
                                 unchanged=True, source_version=as_of)

        # Step 2: Fetch full data
        data_url = f"{_ENR_BASE}/elections/Virginia/{slug}/data"
        data = requests.get(data_url, timeout=60).json()
        is_official = meta.get("isOfficialResults", False)
        result_type = "official" if is_official else "unofficial"

        # Step 3: Parse ballotItems
        rows = self._parse_ballot_items(data.get("ballotItems", []), result_type)

        return AdapterResult(
            rows=rows,
            source_url=data_url,
            mapping_confidence="full",
            source_version=as_of,
        )

    def _parse_ballot_items(self, ballot_items: list, result_type: str) -> list[ResultRow]:
        rows = []
        for item in ballot_items:
            contest_type = item.get("contestType", "")
            office_title = _get_text(item.get("name", []))
            ballot_options = item.get("summaryResults", {}).get("ballotOptions", [])

            for opt in ballot_options:
                opt_name = _get_text(opt.get("name", []))
                vote_count = opt.get("voteCount", 0) or 0
                is_winner = opt.get("isWinner")
                is_write_in = opt.get("isWriteIn", False)

                if contest_type == "BallotMeasure":
                    row = ResultRow(
                        candidate_name=None,
                        option_label=opt_name,         # "Yes" or "No"
                        vote_count=vote_count,
                        is_winner=is_winner,
                        result_type=result_type,
                        office_title=office_title,
                        raw={"ballot_item_id": item.get("id"), "native_id": opt.get("nativeId")},
                    )
                else:  # Candidate
                    party_abbr = (opt.get("party") or {}).get("abbreviation", "")
                    row = ResultRow(
                        candidate_name=opt_name,
                        option_label=None,
                        vote_count=vote_count,
                        is_winner=is_winner,
                        result_type=result_type,
                        office_title=office_title,
                        is_write_in_aggregate=is_write_in,
                        raw={
                            "ballot_item_id": item.get("id"),
                            "native_id": opt.get("nativeId"),
                            "party": party_abbr,
                        },
                    )
                rows.append(row)
        return rows


def _get_text(names: list, lang: str = "en") -> str:
    for n in names:
        if n.get("languageId") == lang:
            return n.get("text", "").strip()
    return (names[0].get("text", "").strip() if names else "")
```

**Register the VA adapter on startup** (`results/apps.py`):
```python
# results/apps.py — existing file, add va:
def ready(self):
    from results.adapters import co, ia, sc, va, wv  # noqa: F401
```

**Store ENR slug on the Election model:**
The VA adapter reads `election.source_metadata["enr_slug"]`. This must be populated when the election is created in `sync_va_elections`. The `source_metadata` JSONField already exists on the `Election` model.

> **Design note:** Unlike Clarity, where `results_url` is set manually in Django admin, the VA adapter reads the `enr_slug` from `source_metadata` which is programmatically populated by the `sync_va_elections` task. This avoids manual admin configuration.

---

## Stage 3b: Historical Results — SBE CSV (2005–2023)

For historical data backfill, a management command or Celery task imports from the SBE ELECTIONRESULTS CSV system.

### SBE ELECTIONRESULTS CSV — 23-Column Schema

```
Column          | Type   | Example
----------------|--------|--------
CandidateUid    | GUID   | {038F4688-D41E-4641-BD4E-BA16A1F4C371}
FirstName       | string | JENNIFER
MiddleName      | string | LEIGH
LastName        | string | MCCLELLAN
Suffix          | string | (blank)
TOTAL_VOTES     | int    | 216
Party           | string | Democratic
WriteInVote     | bit    | 0 / 1
LocalityUid     | GUID   | {5E3D1733-...}
LocalityCode    | string | 025 (3-digit FIPS)
LocalityName    | string | BRUNSWICK COUNTY
PrecinctUid     | GUID   | (blank for virtual precincts)
PrecinctName    | string | 101 - BRODNAX / ##AB - Central Absentee Precinct
DistrictUid     | GUID
DistrictType    | string | Congressional / State Senate / House of Delegates / Election
DistrictName    | string | 04 (Congressional District 4)
OfficeUid       | GUID
OfficeTitle     | string | Member, House of Representatives
ElectionUid     | GUID
ElectionType    | string | Special / General / Primary
ElectionDate    | date   | 2023-02-21 00:00:00
ElectionName    | string | 2023 February Special
NumberOfSeats   | int    | 1
```

**Critical notes:**
- One row = one candidate × one precinct (NOT election-level totals)
- To get election totals: `SUM(TOTAL_VOTES) WHERE CandidateUid = X AND ElectionUid = Y`
- Virtual precincts (filter or handle separately):
  - `##AB - Central Absentee Precinct` — mailed absentee
  - `##EV - Central Absentee Precinct` — early voting
  - `##PE - Central Absentee Precinct` — post-election
  - `## Provisional` — provisional ballots

**Directory URL pattern:**
```
https://apps.elections.virginia.gov/SBE_CSV/ELECTIONS/ELECTIONRESULTS/{YEAR}/{ELECTION_NAME}.csv
```
(URL-encode election name spaces as `%20`)

**Coverage gap:** The SBE CSV system covers special elections in 2023 but the **2023 November General and all 2024+ elections are absent** — they are only in Enhanced Voting API.

---

## Stage 4: Ballot Measures

### Types
Virginia has three ballot measure types:
1. **Constitutional Amendment** — must pass General Assembly in two consecutive sessions, then voter ratification; appear on odd-year November ballots
2. **State Bond Referendum** — statewide voter approval for major bond issuance
3. **Local Referendum** — county/city bond or ordinance questions

### Data Sources

**Amendment text source (HTML):**
```
https://www.elections.virginia.gov/election-law/proposed-amendments-for-{year}/
```
Contains: ballot question, full amendment text with underlined/stricken language, voter explanation, pro/con statements.

**Local referendum data (XLSX):**
```
https://www.elections.virginia.gov/media/castyourballot/candidatelist/{YEAR}/{year}NG-Referendums-{date}.xlsx
```
Contains: question text, locality, Yes/No framing.

**API representation (Enhanced Voting):**
- `contestType: "BallotMeasure"`
- `referendum[].text` — HTML-formatted question text in 4 languages (en, es, ko, vi)
- `summaryResults.ballotOptions[].nativeId` uses `"bms{n}"` prefix
- `isWinner: null` (no winner designation for ballot measures)

**Confirmed 2026 April 21 redistricting referendum vote (for reference):**
- Yes: 1,604,276 (51.7%) 
- No: 1,499,393 (48.3%)
- (Results voided by VA Supreme Court)

### Ballot Measure Ingestion Flow

1. Enhanced Voting API returns `contestType: "BallotMeasure"` items in `ballotItems[]`
2. `VirginiaAdapter._parse_ballot_items()` maps `ballotOptions` to `ResultRow(option_label=...)` 
3. Task layer creates `MeasureOption` records for "Yes", "No" (and any additional options from `referendum[].text`)
4. Full amendment text can be scraped from SBE `/election-law/proposed-amendments-for-{year}/` and stored in `Race.source_metadata["referendum_text"]`

---

## Implementation Plan

### Phased Approach

#### Phase 1 — Results Adapter (Highest Value, Fastest)

**Files to create:**
- `backend/results/adapters/va.py` — custom `VirginiaAdapter` (as sketched above)

**Files to modify:**
- `backend/results/apps.py` — add `va` to adapter imports in `ready()`

**Migration required:**
- Add `VA_ELECT = 'va_elect', 'Virginia ELECT'` to `Race.Source` choices in `elections/models.py`
- Generate and apply migration

**Admin setup:**
- Create a VA Election record in Django admin
- Set `source_metadata = {"enr_slug": "2025-November-General"}` on the Election record (or let sync_va_elections do it programmatically)

**Tests to add (`results/tests/test_clarity_adapter.py` or new `test_va_adapter.py`):**
```python
def test_va_adapter_registered():
    from results.adapters import va  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states
    assert "VA" in list_supported_states()

def test_va_adapter_no_slug_returns_none_confidence():
    ...

def test_va_adapter_version_unchanged_skips_db():
    ...

def test_va_adapter_parses_candidate_contest():
    ...

def test_va_adapter_parses_ballot_measure_contest():
    ...
```

#### Phase 2 — Stage 1 Elections + Races Integration

**New Django app:** `backend/integrations/va_elect/`

Following the pattern from `sc_vrems/` or `co_sos/`:

1. **`client.py`** — `VaElectClient`:
   - `get_election_slugs()` — scrape `elections.virginia.gov/resultsreports/election-results/` for ENR links
   - `get_election_data(slug)` — `GET /api/elections/Virginia/{slug}/data`
   - `get_election_metadata(slug)` — `GET /api/elections/Virginia/{slug}`
   - `get_candidate_list(election_label)` — scrape SBE candidate list HTML table

2. **`mappers.py`** — Pure transformation functions:
   - `map_election(slug, metadata)` → `Election` field dict
   - `map_race(election_obj, ballot_item)` → `Race` field dict + `canonical_key`
   - `map_candidate(ballot_option, race)` → `Candidate` field dict
   - `map_measure_option(ballot_option, race)` → `MeasureOption` field dict
   - `build_canonical_key(...)` — pattern: `va_elect:{election_source_id}:{office}:{district}:{party}`

3. **`tasks.py`** — Two Celery tasks:
   - `sync_va_elections()` — discover slugs, upsert Election records, queue race sync
   - `sync_va_races(election_pk, slug)` — fetch ballotItems, upsert Race/Candidate/MeasureOption

4. **Add to `settings/base.py` Cloud Scheduler entry** (following ADR-002 pattern):
   - Trigger endpoint: `POST /internal/tasks/sync-va-elections/`

#### Phase 3 — Historical Data Backfill (Optional)

**Management command:** `manage.py ingest_va_historical_results --year=2022`

- Downloads from `apps.elections.virginia.gov/SBE_CSV/ELECTIONS/ELECTIONRESULTS/{YEAR}/`
- One-time import for years 2005–2022
- Matches against existing Race records by `(OfficeTitle, DistrictName, ElectionDate)`
- Creates `OfficialResult` records with `result_type="official"` (post-certification)

---

## Key Implementation Decisions

### 1. ENR Slug on Election.source_metadata vs. results_url

**Decision:** Store the ENR slug in `Election.source_metadata["enr_slug"]` rather than `results_url`.

**Rationale:** The `results_url` field is a holdover from the Clarity adapter pattern where the admin must manually paste a URL. For Virginia, the slug is programmatically discoverable and should be set automatically. The `source_metadata` JSONField is the correct place for VA-specific metadata.

### 2. Version Cache Strategy

**Clarity approach:** Cache numeric version string from `current_ver.txt`  
**VA approach:** Cache `asOf` ISO timestamp from `GET /api/elections/Virginia/{slug}` (lightweight metadata call, ~5KB vs 1-3MB full data call)

Cache key: `"va_elect:ver:{election_id}:{slug}"` — consistent with Clarity's `"clarity:ver:{election_id}"` pattern

### 3. Race Matching for Historical Data

The `_process_race_results` task layer matches adapter `ResultRow.office_title` against `Race.office_title` (case-insensitive). For Virginia, office titles in Enhanced Voting are like `"Member, House of Delegates (1st District)"`. Race records created in Stage 1 by `sync_va_races` must use **exactly the same `office_title` string** that the adapter returns.

### 4. Virginia's 133 Localities and `jurisdiction_fragment`

For locality-level result breakdowns (via `/data/ballot-item/{id}` endpoint), the `ResultRow.jurisdiction_fragment` field can store the locality name. However, the primary `fetch_results()` implementation uses the statewide aggregate (root-level `summaryResults`) — locality-level breakdowns are optional and can be a Phase 4 enhancement.

### 5. `isPrimary` Field Is Unreliable

The Enhanced Voting API always returns `"isPrimary": false` regardless of election type. To determine if an election is a primary, parse the slug: if slug contains `Primary` → set `Election.election_type = "primary"`.

---

## Gaps, Risks, and Next Steps

| Gap | Risk | Recommendation |
|---|---|---|
| Enhanced Voting blob CSV URL unknown | Low (API JSON is sufficient) | Use browser DevTools on ENR page to capture download XHR URL; needed only for ELECTIONWINNERS/turnout CSVs |
| No `/elections/Virginia` index endpoint | Medium | Always scrape elections.virginia.gov for slug discovery; maintain a known-slugs list as fallback |
| Slug naming inconsistency | Medium | Use scraper as source of truth; normalize by stripping `elections/` prefix from href |
| VA Civic API race creation untested | Medium | Run `sync_election_races` against next VA election ID; validate contest coverage |
| SBE candidate list URL pattern varies by election | Medium | Document URL pattern from SBE; build URL generator based on election date and type |
| OpenElections VA PR #16 unmerged | Low | Use `Tenjin25/openelections-data-va` fork until merged; monitor PR status |
| VPAP blocked | Low | Contact VPAP for data partnership; Ballotpedia paid API as alternative for candidate bios |
| `Race.Source.VA_ELECT` migration needed | High | Block on this before any integration work begins |
| OpenStates API key required | Low | Register at open.pluralpolicy.com (free) |

---

## Footnotes

[^1]: Enhanced Voting API base URL confirmed: `mcande21/ulster-elections:scripts/ENHANCED_VOTING_EXTRACTION.md` SHA `2e09f07bf2f2d3bea649261dd0dc0312f3e6277b`

[^2]: All `ballotItems` at root level confirmed from live `GET https://app.enhancedvoting.com/results/public/api/elections/Virginia/2025-November-General/data`

[^3]: `contestType: "BallotMeasure"` confirmed from `GET https://app.enhancedvoting.com/results/public/api/elections/Virginia/2026-April-21-Special/data` offset ~685,000

[^4]: `childLocalities` contains only summary metadata (no ballotItems) — confirmed across 2025-November-General and 2026-April-21-Special full data responses

[^5]: `isPrimary` always `false` — verified on `2025-June-Republican-Primary`, `2025-June-Democratic-Primary`, `2024_June_Democratic_Primary`, `2024_March_Republican_Primary`

[^6]: Election slug format documentation: scraped from `https://www.elections.virginia.gov/resultsreports/election-results/` listing all 2023-2026 elections

[^7]: SBE CSV stops at 2023 specials for ELECTIONRESULTS — confirmed via directory listing `https://apps.elections.virginia.gov/SBE_CSV/ELECTIONS/ELECTIONRESULTS/2023/` (8 special elections only; no November General)

[^8]: SBE CSV 23-column schema: verified from `https://apps.elections.virginia.gov/SBE_CSV/ELECTIONS/ELECTIONRESULTS/2023/2023%20April%20Frederick%20County%20Special.csv`

[^9]: ELECTIONWINNERS 10-column schema with StreetAddress/Email confirmed: `https://apps.elections.virginia.gov/SBE_CSV/ELECTIONS/ELECTIONWINNERS/2023/`

[^10]: SBE candidate list HTML has full contact info (email, phone, website, address) — confirmed via fetch of `https://www.elections.virginia.gov/casting-a-ballot/candidate-list/november-4-2025-gen-elect-all-office/`

[^11]: All existing adapters (WV, IA, CO, SC) are Clarity thin wrappers — confirmed from `tokendad/CivicMirror-API:backend/results/adapters/wv.py`, `ia.py`, `co.py`, `sc.py`

[^12]: Results task `_bootstrap_races_from_results` uses `_MEASURE_TITLE_KEYWORDS` for auto-detection: `tokendad/CivicMirror-API:backend/results/tasks.py:109-201`

[^13]: `Race.Source` enum requires new `VA_ELECT` entry — confirmed from `tokendad/CivicMirror-API:backend/elections/models.py:71-79`

[^14]: `results/apps.py` `ready()` must import the VA adapter for `@register` to fire — confirmed from `tokendad/CivicMirror-API:backend/results/apps.py:8-10`

[^15]: SC VREMS canonical key pattern: `sc_vrems:{election_source_id}:{office}:{geography}:{party}` — `tokendad/CivicMirror-API:backend/integrations/sc_vrems/mappers.py:128-138`

[^16]: Virginia Civic API OCD division ID: `ocd-division/country:us/state:va`; independent cities use `place:` not `county:` — `tokendad/CivicMirror-API:backend/integrations/civic/mappers.py:20-33`

[^17]: Historical Elections Database CSV download URL pattern: `https://historical.elections.virginia.gov/elections/download/{id}/precincts_include:1/` — `nonpartisan-redistricting-datahub/pdv-resources:ex_parser.ipynb:96-130`

[^18]: OpenElections VA official repo is empty; data lives in `Tenjin25/openelections-data-va` fork (PR #16 unmerged) — confirmed from `openelections/openelections-data-va` master branch tree

[^19]: 2025 November General ballotItems[0-2]: Governor (3,433,340 votes), Lt. Governor (3,414,177), AG (3,396,499); statewide, 133 reporting units each

[^20]: ENR blob CSV URL cannot be constructed from public API data — all URL patterns return 404/error; needs browser DevTools capture of download XHR
