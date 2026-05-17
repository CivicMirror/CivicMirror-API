# CivicMirror API — Copilot Instructions

> **Status: Concept / Pre-development**  
> Developer: Walter LeFort · AI tools: Copilot Pro, Claude, ChatGPT  
> Companion app: https://github.com/tokendad/CivicMirror

## What This Project Is

CivicMirror is an election data aggregation and normalization platform. This repository (`API-CivicMirror`) is the **Django/Celery backend**. It ingests election and ballot data from multiple free public sources, normalizes it into shared models using FIPS codes and OCD-IDs, and serves it via a unified REST API (with a potential GraphQL endpoint) — primarily for the [CivicMirror](https://github.com/tokendad/CivicMirror) web app, and potentially as a public API.

The `Docs/` tree is primary reference material: `Sources.md` covers the full data source catalog, `Docs/State Research/` has per-state results access research, `WV-Results-Adapter-Plan.md` documents the first results adapter (Clarity Elections), and `Docs/concept.md` is the authoritative project concept document.

---

## Core Data Points

These represent minimum data standards when sourcing and normalizing content.

- **Elections** — Primary (open/closed/non-partisan), General, Special, Mid-Term, Party
- **Ballot Measures** — Resolutions, Referendums (direct & indirect)
- **Candidates** — Contact info, website/phone, party affiliation, CV/résumé, platform statement
- **Officials** — Incumbent status, office held, district represented, term start/end dates
- **Districts & Jurisdictions** — Federal (House, Senate, Presidential), State (legislative, gubernatorial), Local (county, municipal, school board, special district), geographic boundaries (GeoJSON / FIPS codes)

---

## Normalization Strategy

- Standardize jurisdiction identifiers using **FIPS codes** and **OCD-IDs** (Open Civic Data Division Identifiers)
- Map source-specific election types to a common taxonomy (`primary`, `general`, `special`, etc.)
- Deduplicate candidates across sources using name + district + party matching
- Normalize all dates to **ISO 8601** format
- **Output:** REST API with JSON responses (primary); GraphQL endpoint for CivicMirror front-end flexibility (future)

---

## Project Roadmap

1. Define canonical data schema / JSON structure
2. Prototype ingestion pipeline for Google Civic API
3. Add OpenStates and Ballotpedia adapters
4. Build normalization / deduplication layer
5. Expose unified REST API
6. CivicMirror integration
7. Public API documentation

---

## Planned Backend Structure

```
backend/
  config/
    celery.py          # Celery app + beat schedule
  elections/
    models.py          # Election, Race models
    admin.py           # Django admin
    migrations/
  results/
    adapters/
      base.py          # ResultRow dataclass, BaseAdapter ABC
      registry.py      # @register decorator, list_supported_states()
      clarity.py       # Generic Clarity Elections adapter (JSON API)
      wv.py            # WestVirginiaAdapter (5-line @register wrapper)
    tasks.py           # ingest_official_results, poll_pending_results
    tests/
  requirements/
    base.txt
```

---

## Google Civic Information API

**Base URL:** `https://www.googleapis.com/civicinfo/v2`  
**Auth:** `?key={CIVIC_API_KEY}` — store in env var `CIVIC_API_KEY`, never hardcode.

### Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /elections` | All upcoming/recent elections — use for scheduled sync into `Election` model |
| `GET /voterinfo?address=...&electionId=...` | Races, candidates, polling info for a specific address |
| `GET /representatives` | Elected officials by address (future use) |

`voterinfo` requires a specific `electionId` — always call `/elections` first. For ZIP-only queries use `"{zip} USA"` as the address string. The API returns `400` for valid addresses with no active contests — treat as "no data", not an error.

### Model Mapping

```python
# Election (from /elections)
Election.objects.update_or_create(
    source_id=election["id"],
    defaults={
        "name": election["name"],
        "election_date": election["electionDay"],
        "jurisdiction_level": parse_jurisdiction(election["ocdDivisionId"]),
        "state": parse_state(election["ocdDivisionId"]),
        "source": "civic_api",
    }
)

# Race (from voterinfo contest)
Race.objects.update_or_create(
    election=election_obj,
    office_title=contest.get("office") or contest.get("referendumTitle"),
    jurisdiction=contest["district"]["name"],
    defaults={
        "race_type": "measure" if contest["type"] == "Referendum" else "candidate",
        "geography_scope": contest["district"].get("scope", ""),
        "source": "civic_api",
        "certification_status": "upcoming",
    }
)
```

**Race type determination:** `contest.type == "Referendum"` → `race_type = "measure"` (create `MeasureOption` rows for Yes/No/Abstain); all other types → `race_type = "candidate"` (create `Candidate` rows).

### Celery Sync Pattern

```python
@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_elections(self):
    client = CivicAPIClient()
    try:
        for election in client.list_elections():
            sync_election_races.delay(election["id"])
    except CivicAPIError as exc:
        raise self.retry(exc=exc)
```

Sync interval: `CIVIC_SYNC_INTERVAL_HOURS = 6` (configurable via settings).

### Error Handling

| Status | Action |
|---|---|
| 400 | Log warning, skip — no data for this address/election |
| 403 | Raise immediately, alert ops (bad API key) |
| 429 | Retry with exponential backoff |
| 503 | Retry with backoff via Celery |

### State/ZIP Filtering

- **By ZIP:** Call `voterinfo` with `"{zip} USA"` for each active election; deduplicate results by `(office_title, jurisdiction, election_id)`.
- **By state:** Use state capital address as representative query; supplement with statewide-scope races already in the database.

### Known Limitations

- Local race coverage varies — when `voterinfo` returns no contests, prompt user to use the local race wizard.
- `referendumText` can be very long — truncate to 2000 chars for the display field; store full text separately.
- Candidate photos/bios are not provided; source from candidate website links in the response.

---

## Data Sources

| Source | Coverage | Format | Notes |
|---|---|---|---|
| [Google Civic Information API](https://developers.google.com/civic-information) | Federal, State, Local | REST/JSON | Elections, races, candidates, polling by address |
| [OpenStates API](https://openstates.org/api/v3/) | State Legislative | REST/JSON | Bills, legislators, votes |
| [Ballotpedia](https://ballotpedia.org/API_documentation) | Federal, State, Local | REST/JSON | Candidate & ballot measure data |
| [OpenFEC API](https://api.open.fec.gov/developers/) | Federal | REST/JSON | Campaign finance, candidates, filings |
| [MIT Election Data Lab (MEDSL)](https://electionlab.mit.edu/data) | Federal, State | CSV/JSON | Historical results |
| [EAVS (EAC)](https://www.eac.gov/research-and-data/election-administration-voting-survey) | State | CSV | Election admin statistics |

---

## Data Source Tiers

**Tier 1 — Core (build around these first):**
- **Google Civic Information API** (`https://www.googleapis.com/civicinfo/v2`) — upcoming elections, live ballot races, candidates, polling locations; requires address + `electionId` for ballot detail
- **OpenFEC API** (`https://api.open.fec.gov/v1/`) — federal candidate metadata
- **U.S. Census Geocoder + TIGER/Line** — address/ZIP → district resolution
- **Open Civic Data division IDs** — shared OCD identifier normalization
- **`unitedstates/congress-legislators`** — federal incumbent enrichment + FEC crosswalk IDs

**Tier 2 — Add next:**
- **OpenStates API** (`https://v3.openstates.org/`) — state legislative incumbents, bills, votes
- **Ballotpedia** — candidate & ballot measure enrichment (federal, state, local)
- **OpenElections** (CSV/GitHub) — certified historical results; state adapter patterns
- **MEDSL / Harvard Dataverse** — historical result backfill
- **EAVS (EAC)** — election administration statistics

**Deprecated / do not use:** ProPublica Congress API (discontinued), OpenSecrets API (discontinued).

---

## Results Adapter Pattern

Each state adapter lives in `backend/results/adapters/{state_abbr_lower}.py` and uses a `@register` decorator to self-register. The base class provides a `fetch()` method that returns a list of `ResultRow` objects.

```python
# ResultRow fields (from base.py)
@dataclass
class ResultRow:
    candidate_name: str | None
    option_label: str | None       # for ballot measures
    vote_count: int
    result_type: str               # "UNOFFICIAL" or "OFFICIAL"
    office_title: str | None = None  # used to match Race.office_title
```

**`office_title` matching** in `_process_race_results`: pre-filter rows where `office_title` matches `race.office_title` (case-insensitive), fall back to all rows if no match (graceful degradation).

**`result_type` logic:** all Clarity results ingest as `UNOFFICIAL` regardless of precinct reporting percentage; only an explicit admin action (or future hook) sets `OFFICIAL`.

---

## Clarity Elections Adapter (Generic)

Clarity Elections powers results for WV, CO, IA, SC, and others. The adapter uses the **JSON API** (preferred over `detailxml.zip`):

1. `GET /{state}/{electionId}/current_ver.txt` → numeric version ID (e.g. `371599`)
2. `GET /{state}/{electionId}/{version}/json/en/summary.json` → all contest results

**Critical:** `web.{hash}` in the browser URL (e.g. `web.345435`) is the Angular SPA bundle version — **not** the data version. Always fetch `current_ver.txt` for the data version.

Cache the version number and only re-fetch `summary.json` when the version changes (efficient polling).

`summary.json` contest object fields: `"C"` = contest name, `"CH"` = candidate names array, `"V"` = votes array, `"W"` = winner flags array (1=winner), `"PR"/"TP"` = precincts reporting/total, `"CATKEY"` = party category (`C_1`=Rep, `C_2`=Dem, `C_3`=Non-Partisan).

`results_url` on the `Election` model is set **manually in Django admin** (intentional — keeps mapping auditable; does not auto-discover).

States with Clarity access: WV, CO, IA, SC (ENR Web 4.x — accessible). GA, AR, KY, NC, TX, PA return 403.

---

## Celery Beat Schedule

The `poll_pending_results` task runs **daily at 06:00 UTC**. It queries `Election` objects where `election_date < today`, `status = RESULTS_PENDING`, and `state in list_supported_states()`, then fires `ingest_official_results.delay(state, pk)` for each.

Beat entry name: `"poll-pending-election-results"`.

---

## Per-State Data Access Reference

Before writing a state adapter, check `Docs/State Research/{STATE}-Election_Research.md`. Key access tiers:
- **CA**: Full REST API at `https://api.sos.ca.gov` — JSON default, `?f=csv` for CSV; contest IDs change per election cycle; consult `json-endpoints.csv` from `https://media.sos.ca.gov/media/`
- **CT, PA**: Socrata/SODA APIs via open data portals
- **NC**: Public FTP site with weekly updates
- **MI**: Community REST API at `michiganelections.io`
- **AZ**: FTP feed at `ftp://ftp.azsos.gov/ElectionResults/` (XML, real-time on election night)
- **Most states (35+)**: Excel/PDF downloads only — no programmatic API

`Docs/State Research/00-MASTER-INDEX.md` has the full state-by-state quick reference table.

---

## Key External Libraries

- `clarify` (PyPI) — Clarity Elections XML parser; valid alternative to the JSON approach for county-level detail
- `lxml`, `python-dateutil` — dependencies for the Clarity adapter
