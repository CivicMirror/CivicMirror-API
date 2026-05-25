# Massachusetts Election Data — Ingestion Plan

> **Status:** Plan (Not Yet Implemented)
> **Author:** Research session, May 25 2026
> **Prior research:** `Ma-Elections-Research.md`, `Anthropic_TurboVote_Research.md`
> **Comparable integration:** `integrations/va_elect/` (most recent prior implementation)

---

## 1. Executive Summary

Massachusetts publishes certified election results through `electionstats.state.ma.us`, a server-rendered CakePHP platform ("PD43+") with **no REST API** — data is accessed via HTML scraping for election ID discovery and direct CSV downloads for result data. Candidate and incumbent data is available through the Massachusetts OCPF (Office of Campaign and Political Finance) public REST API at `api.ocpf.us` (fully public, no auth). There is no live election-night (ENR) feed for Massachusetts; `electionstats` is post-certification only.

The integration architecture mirrors the VA (`va_elect`) pattern with one key difference: **election discovery requires HTML scraping** (no structured API) and **result ingestion uses CSV parsing** (not JSON). This is a new pattern not yet present in any existing state integration.

---

## 2. Data Sources

### 2.1 Primary: `electionstats.state.ma.us` (PD43+ Platform)

**Owner:** Massachusetts Secretary of the Commonwealth  
**Platform:** PD43+ (multi-state server-rendered CakePHP, no API)  
**Authentication:** None  
**Rate limiting:** None observed; polite crawl (0.5–1s delay) recommended  
**Historical depth:** Elections 1970–present, Ballot Questions 1972–present  
**Coverage:** All 351 MA municipalities, down to ward/precinct level  
**WAF concern:** The `sec.state.ma.us` apex domain is Incapsula-blocked; `electionstats.state.ma.us` is **not** — it is fully accessible with no bot protection observed across 20+ fetches

#### URL Patterns

| Purpose | URL Pattern |
|---|---|
| Election search | `GET /elections/search/year_from:{Y}/year_to:{Y}/stage:General` |
| Election detail | `GET /elections/view/{election_id}/` |
| **Election CSV (town-level)** | `GET /elections/download/{election_id}/precincts_include:0/` |
| **Election CSV (precinct-level)** | `GET /elections/download/{election_id}/precincts_include:1/` |
| BQ search | `GET /ballot_questions/search/year_from:{Y}/year_to:{Y}/` |
| BQ detail (+ metadata JS) | `GET /ballot_questions/view/{bq_id}/` |
| **BQ CSV (town-level)** | `GET /ballot_questions/download/{bq_id}/precincts_include:0/` |
| County expansion (AJAX) | `GET /elections/view/{id}/filter_by_county:{CountyName}` |
| Candidate profile | `GET /candidates/view/{First-Last-Name}` |

`stage` values: `General`, `Primaries`, `Democratic`, `Republican`, `Green-Rainbow`, `Libertarian`, `Working Families`, `United Independent`, `American`, `Independent Voters`

#### Election ID Structure

IDs are integers, non-sequential, discovered via HTML only (no index API):

| Era | Observed ID Range |
|---|---|
| 2016 | ~126695–131805 |
| 2022 | ~154333–154393 |
| 2024 General | ~165299–165516 |
| 2024 Primary | ~160657–160866 |
| 2026 Specials | ~171919–171920 |

#### Known 2024 General Election IDs

| Office | District | Election ID |
|---|---|---|
| President | Statewide | 165300 |
| U.S. Senate | Statewide | 165304 |
| U.S. House 1st | 1st Congressional | 165323 |
| U.S. House 2nd | 2nd Congressional | 165343 |
| U.S. House 3rd | 3rd Congressional | 165309 |
| U.S. House 4th | 4th Congressional | 165373 |
| U.S. House 5th | 5th Congressional | 165353 |
| U.S. House 6th | 6th Congressional | 165336 |
| U.S. House 7th | 7th Congressional | 165413 |
| U.S. House 8th | 8th Congressional | 165302 |
| U.S. House 9th | 9th Congressional | 165316 |

**2024 Ballot Question IDs:**

| Q# | ID | Topic |
|---|---|---|
| Q1 | 11620 | State Auditor authority to audit Legislature |
| Q2 | 11621 | Eliminate MCAS graduation requirement |
| Q3 | 11622 | Transportation network drivers collective bargaining |
| Q4 | 11623 | Natural psychedelic substances |
| Q5 | 11624 | Tipped workers minimum wage phase-up |

#### Election CSV Format

`/elections/download/{id}/precincts_include:0/` — returns town-level results:

```csv
City/Town,,,"Harris/ Walz","Trump/ Vance","Stein/ Caballero-Roca",...,"All Others",Blanks,"Total Votes Cast"
,,,Democratic,Republican,Unenrolled,...
Abington,,,"4,714","4,639",47,...,4,27,"9,499"
...
TOTALS,,,"2,126,518","1,251,303",...,"3,512,930"
```

**Column layout:**
- Row 0: Header — `City/Town` + 2 blank placeholders + candidate names (quoted)
- Row 1: Party affiliations (row-offset — no `City/Town` in col 0)
- Data rows: town + 2 empty (ward/precinct placeholders) + vote counts per candidate + `All Others`, `Blanks`, `Total Votes Cast`
- Final row: `TOTALS` — statewide aggregate
- Numbers ≥1000 are quoted with commas: `"1,019"` → must use Python `csv` module, not naive split

#### Ballot Question CSV Format

`/ballot_questions/download/{id}/precincts_include:0/`:

```csv
Locality,,,Yes,No,Blanks,"Total Votes Cast"
Barnstable,,,"18,328","8,097","1,572","27,997"
...
TOTALS,,,"2,326,911","924,289","261,730","3,512,930"
```

Same structural patterns. `Yes`/`No`/`Blanks`/`Total Votes Cast` are fixed columns.

#### Ballot Question Metadata (JS Object on View Page)

`/ballot_questions/view/{bq_id}/` — page contains an inline JS object at ~200KB offset:

```javascript
election_data[11620] = {Election:{
  "id": "11620",
  "question_number": "1",
  "question": "Do you approve of a law summarized below...",
  "question_alias": "A - Audit The Legislature",
  "summary": "This proposed law would specify that the State Auditor has the authority to audit the Legislature.",
  "is_amendment": "", "is_initiative_petition": "1", "is_referendum": "",
  "is_non_binding": "", "is_local": "", "is_county": "",
  "date": "2024-11-05",
  "year": "2024",
  "n_yes_votes": "2326911", "n_no_votes": "924289", "n_blank_votes": "261730",
  "pct_yes_votes": "0.71570835383858",
  "status": "published"
}};
```

Regex: `election_data\[(\d+)\]\s*=\s*\{Election:\s*(\{[^}]+\})`

#### HTML Selectors for ID Discovery

**Elections search page** (`<table id="search_results_table">`):
- Row selector: `tr[id^="election-id-"]`
- Columns: `td[0]` = year, `td[1]` = office, `td[2]` = district, `td[3]` = stage
- Candidate preview (inside collapsed `<table class="candidates">`): name, party, votes, winner status

**BQ search page:**
- Row selector: `tr[id^="bq-id-"]`
- Columns: `td[0]` = year, `td[1]` = Q#, `td[2]` = question text, `td[3]` = type, `td[4]` = locality

#### Office IDs (from search form `<select>`)

| ID | Office |
|---|---|
| 1 | President |
| 6 | U.S. Senate |
| 5 | U.S. House |
| 3 | Governor |
| 9 | State Senate |
| 8 | State Representative |
| 529 | Governor's Council |
| 530 | District Attorney |
| 386 | Sheriff |

#### Version Fingerprint Strategy

`electionstats` is post-certification data — results change rarely. No ETag or Last-Modified is exposed to page content. The most reliable and pragmatic strategy:

**SHA-256 the CSV body** — download the full CSV and hash it. If the hash matches the cached value, skip processing. At ~50–100KB per CSV, this is cheap. Store hash in Django cache with key `"ma_sos:hash:{election_id}"`.

**Alternative (for election list):** Cache the set of discovered election IDs per year. Only process new IDs. Use a sorted hash of the ID set as the version key.

---

### 2.2 Secondary: `api.ocpf.us` (MA OCPF Public API)

**Owner:** Massachusetts Office of Campaign and Political Finance  
**Base URL:** `https://api.ocpf.us`  
**Authentication:** None (fully public, CORS-enabled)  
**Rate limits:** None documented or observed  
**Spec:** OpenAPI 3.0.1 at `https://api.ocpf.us/swagger/v1/swagger.json`

#### Key Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /filers/listings/C` | All candidate committees (no server-side filter — fetch all, filter client-side) |
| `GET /filer/{cpfId}` | Full filer detail with structured `officeSought`/`officeHeld` and election tags |
| `GET /municipalities` | All 351 MA towns → incumbent elected officials (`electedFilers[]`) |
| `GET /filingSchedules/{year}` | Election schedule — primary and general dates |

#### `/filers/listings/C` Response Shape

```json
{
  "cpfId": 16045,
  "filerName": "Ian Abreu",
  "isActive": true,
  "officeSought": "City Councilor, New Bedford",
  "officeHeld": "City Councilor, New Bedford",
  "isIncumbent": true,
  "accountTypeCode": "D",
  "isCandidate": true,
  "partyAffiliation": "Democratic",
  "filerCity": "New Bedford",
  "filerThumbnailPhotoUrl": "https://ocpf2.blob.core.windows.net/filers-photos/thumbnail/16045_thumbnail.png"
}
```

**⚠️ CRITICAL GOTCHA:** `pageSize`, `isActive`, `officeSought`, `OnlyIncumbents` query params are **silently ignored server-side**. Fetch the full dataset (no query params) and filter client-side. Use `First200=true` + `LoadRemaining=true` for the two-pass approach, or omit both for a single full-dataset response.

**Client-side office filtering patterns:**
- State Representatives: `officeSought` contains `"House, "`
- State Senators: `officeSought` contains `"Senate, "`
- Governor: `officeSought == "Governor"`
- Challengers: `isIncumbent == false` and `officeHeld == "N/A, No office"`

#### `/filer/{cpfId}` Detail Response (structured fields)

```json
{
  "officeSought": {
    "districtCode": 124,
    "officeDescription": "Senate",
    "districtDescription": "Norfolk & Plymouth",
    "officeDistrict": "Senate, Norfolk & Plymouth"
  },
  "officeHeld": { /* same shape; zeroed if challenger */ },
  "partyAffiliation": "Democratic",
  "tags": [
    {
      "tagTypeId": 2,     // 1=On Ballot, 2=Winner
      "year": 2024,
      "officeType": "Senate",
      "districtCode": 124,
      "isSpecialElection": false
    }
  ]
}
```

#### `/municipalities` Response Shape

351 entries (one per MA city/town):
```json
{
  "code": 1,
  "city": "ABINGTON",
  "county": "Plymouth",
  "pop2020": 17062,
  "electedFilers": [
    {
      "cpfId": 15021,
      "officeNameHeld": "Senate, Norfolk & Plymouth",
      "partyAffiliation": "Democratic",
      "isSenate": true,
      "isHouse": false
    }
  ]
}
```

#### `/filingSchedules/{year}` Response

```json
{
  "year": 2024,
  "primaryElectionDate": "9/3/2024",
  "generalElectionDate": "11/5/2024"
}
```

Use this to seed `Election` records for upcoming elections.

---

### 2.3 Historical: OpenElections MA

**Repo:** `openelections/openelections-data-ma`  
**Coverage:** 2000–2020 (no 2022, no 2024 as of current master)  
**Format:** CSVs at `https://raw.githubusercontent.com/openelections/openelections-data-ma/master/{year}/{filename}.csv`

**CSV Schema:**
```csv
town,ward,precinct,office,district,party,candidate,votes
Seekonk,,1,U.S. House,4th,Democratic,Jake Auchincloss,918
```

Fields: `town`, `ward`, `precinct`, `office`, `district`, `party`, `candidate`, `votes`

Use as **backfill only** (not for ongoing sync). The `electionstats` adapter covers all the same years with more detail.

---

### 2.4 Academic Backfill: MEDSL Harvard Dataverse

| Dataset | DOI | Coverage |
|---|---|---|
| 2020 Precinct Returns by State | `doi:10.7910/DVN/NT66Z3` | `2020-ma-precinct-general.csv` confirmed |
| 2024 State Precinct Returns | `doi:10.7910/DVN/DODOBJ` | 2024 general (MA inclusion unconfirmed) |

Open access (CC0), no API key. Download via: `https://dataverse.harvard.edu/api/access/datafile/{file_id}`

Use as **academic validation / cross-check only**.

---

## 3. Integration Architecture

### 3.1 Django App: `integrations/ma_sos/`

Follows the `va_elect` pattern (most complete prior implementation). This is the first integration to combine HTML scraping for discovery with CSV parsing for results.

```
backend/integrations/ma_sos/
  __init__.py
  apps.py            # MaSosConfig(label='ma_sos')
  exceptions.py      # MaSosError, MaSosRetryableError
  client.py          # HTTP client — scraper + CSV fetcher + OCPF client
  parsers.py         # HTML parsers — extract election IDs, BQ metadata from HTML
  mappers.py         # Pure transformation functions
  tasks.py           # Celery tasks (2-stage: sync_ma_elections + sync_ma_races)
  tests/
    __init__.py
    test_client.py
    test_parsers.py
    test_mappers.py
    test_tasks.py
```

**`apps.py`:**
```python
class MaSosConfig(AppConfig):
    name = 'integrations.ma_sos'
    label = 'ma_sos'
    verbose_name = 'Massachusetts SOS'
```

### 3.2 Results Adapter: `results/adapters/ma.py`

`MassachusettsAdapter` registered with `@register`. Follows the VA adapter pattern with CSV parsing instead of JSON.

**`fetch_results(election_date, election_id: int) → AdapterResult`:**
1. Look up `Election` by PK, check `election.source_metadata["electionstats_id"]`
2. Download CSV: `GET /elections/download/{electionstats_id}/precincts_include:0/`
3. Compute SHA-256 of CSV body → check cache key `"ma_sos:hash:{election_id}"`
4. If hash unchanged: return `AdapterResult(unchanged=True, source_version=cached_hash)`
5. Parse CSV → list of `ResultRow`
6. Return `AdapterResult(rows=..., source_version=new_hash, source_url=csv_url)`

**CSV → ResultRow mapping:**
- Candidate rows: `candidate_name=col_header`, `option_label=None`, `vote_count=int(cell)`, `result_type="official"` (all electionstats results are certified)
- Tally rows (`"All Others"`, `"Blanks"`, `"Total Votes Cast"`): `is_write_in_aggregate=True` for `"All Others"`, skip `"Blanks"` and totals
- `office_title` from `election.office_title` (passed through from Race)
- `raw={"town": town, "ward": ward, "pct": pct, "party": party_from_row1}` for precinct-level granularity

### 3.3 Migration: `Race.Source.MA_SOS`

New migration (`0012_add_ma_sos_race_source.py`) adding `Race.Source.MA_SOS = 'ma_sos', 'Massachusetts SOS'` (8 chars, within `max_length=20`).

### 3.4 Internal Trigger: `sync_ma_sos_trigger`

Added to `internal/views.py` following the identical pattern as `sync_va_elect_trigger`:
```python
_SYNC_MA_SOS_LOCK_TTL = 23 * 60 * 60  # 23 hours

def sync_ma_sos_trigger(request):
    window = _schedule_window_daily()
    lock_key = f"task_lock:sync_ma_sos:{window}"
    acquired = cache.add(lock_key, 1, _SYNC_MA_SOS_LOCK_TTL)
    if not acquired:
        return JsonResponse({"status": "already_running"}, status=202)
    task = sync_ma_elections.delay()
    return JsonResponse({"task_id": task.id}, status=202)
```

URL: `POST /internal/tasks/sync-ma-sos/`

---

## 4. Data Model Mapping

### 4.1 Election Model Mapping

From electionstats search page HTML row (`tr[id^="election-id-"]`):

```python
Election.objects.update_or_create(
    source_id=f"ma_sos_{election_id}",
    defaults={
        "name": f"{year} MA {office} {district} {stage}",
        "election_date": election_date_from_schedule,   # from OCPF /filingSchedules/{year}
        "election_type": infer_election_type(stage),     # "general" | "primary" | "special"
        "jurisdiction_level": infer_jurisdiction(office), # "national" | "state" | "local"
        "state": "MA",
        "status": "results_certified",
        "source_metadata": {
            "electionstats_id": election_id,  # int — used by adapter to build CSV URL
            "electionstats_office_id": office_id,
            "stage": stage,
        },
        "source": "openelections",  # Using existing choice — consider adding "ma_sos" to Election.source too
    }
)
```

**`infer_election_type(stage)` mapping:**

| `stage` value | `election_type` |
|---|---|
| `General` | `general` |
| `Democratic`, `Republican`, `Green-Rainbow`, `Libertarian`, etc. | `primary` |
| `Primaries` | `primary` |
| Contains `Special` | `special` |

### 4.2 Race Model Mapping

From search page HTML row:

```python
Race.objects.update_or_create(
    canonical_key=build_canonical_key(election_source_id, office, district),
    defaults={
        "election": election_obj,
        "race_type": Race.RaceType.MEASURE if is_ballot_question else Race.RaceType.CANDIDATE,
        "office_title": office,                    # e.g., "U.S. House", "State Senate"
        "jurisdiction": district or "Statewide",  # e.g., "1st Congressional", "Norfolk & Plymouth"
        "geography_scope": infer_geography_scope(office),
        "certification_status": Race.CertStatus.RESULTS_CERTIFIED,
        "source": Race.Source.MA_SOS,
        "source_metadata": {"electionstats_id": election_id},
    }
)
```

**Canonical key format:**
`ma_sos:{election_source_id}:{normalized_office}:{normalized_district}`

Example: `ma_sos:ma_sos_165323:u.s. house:1st congressional`

### 4.3 Candidate Model Mapping

From CSV column headers (row 0) + party row (row 1):

```python
Candidate.objects.update_or_create(
    race=race_obj,
    name=candidate_name,   # e.g., "Richard E. Neal" (parsed from CSV header)
    defaults={
        "party": party,                    # from CSV row 1
        "incumbent": False,               # enriched later from OCPF /municipalities
        "candidate_status": CandidateStatus.RUNNING,
        "source_metadata": {"csv_column_index": col_idx},
    }
)
```

**Tally/synthetic rows to skip:** `"All Others"`, `"Blanks"`, `"Total Votes Cast"` — do NOT create Candidate records for these.

**Is-winner detection:** From search page `<tr class=" is_winner">` inside the candidates preview table. Alternatively, from the highest vote count in the CSV TOTALS row.

**OCPF enrichment (optional, Phase 2):**
- Match candidate name from CSV against OCPF `/filers/listings/C` by `filerName` (fuzzy: lowercase + strip punctuation)
- Enrich: `incumbent`, `website_url` (via filer detail), `image_url` (thumbnail photo), `fec_candidate_id` (from tags)

### 4.4 Ballot Question Model Mapping

From `/ballot_questions/view/{bq_id}/` JS `election_data` object:

```python
Race.objects.update_or_create(
    canonical_key=f"ma_sos:bq_{bq_id}",
    defaults={
        "election": election_obj,
        "race_type": Race.RaceType.MEASURE,
        "office_title": f"Ballot Question {question_number}",
        "jurisdiction": locality or "Statewide",
        "geography_scope": "statewide" if not is_local else "district",
        "certification_status": Race.CertStatus.RESULTS_CERTIFIED,
        "vote_method": Race.VoteMethod.YES_NO,
        "source": Race.Source.MA_SOS,
        "yes_vote_details": question_alias or "",
        "no_vote_details": "",
        "source_metadata": {
            "electionstats_bq_id": bq_id,
            "question_number": question_number,
            "summary": summary[:2000],  # truncate at 2000 chars
            "is_initiative_petition": bool(is_initiative_petition),
            "is_referendum": bool(is_referendum),
            "is_local": bool(is_local),
            "full_question_text": question,
        },
    }
)

# Create MeasureOption rows:
MeasureOption.objects.update_or_create(race=bq_race, option_label="Yes")
MeasureOption.objects.update_or_create(race=bq_race, option_label="No")
```

---

## 5. Task Architecture

### Stage 1: `sync_ma_elections` (discovery + Election upsert)

```python
@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ma_elections(self):
    """
    Discover all elections for the current and prior year from electionstats.
    Upsert Election records. Queue Stage 2 tasks for each new/updated election.
    """
    sync_log = SyncLog.objects.create(source="ma_sos", task="sync_ma_elections", status="running")
    try:
        client = MaSosClient()
        year = date.today().year
        
        all_elections = []
        for stage in ["General", "Primaries"]:
            elections = client.get_election_ids(year, stage)
            elections += client.get_election_ids(year - 1, stage)  # prior year too
            all_elections.extend(elections)
        
        # Deduplicate
        seen = set()
        unique_elections = [e for e in all_elections if e["election_id"] not in seen and not seen.add(e["election_id"])]
        
        # OCPF schedule for election dates
        schedule_2024 = client.get_ocpf_schedule(year)
        schedule_2023 = client.get_ocpf_schedule(year - 1)
        
        elections_to_create = [map_election(e, schedule_2024 if e["year"] == year else schedule_2023)
                                for e in unique_elections]
        
        created_count = 0
        with transaction.atomic():
            result = Election.objects.bulk_create(
                elections_to_create,
                update_conflicts=True,
                unique_fields=["source_id"],
                update_fields=["name", "status", "source_metadata", "last_synced_at"],
            )
            created_count = len(result)
        
        # Queue Stage 2 for each election
        for i, election_data in enumerate(unique_elections):
            sync_ma_races.apply_async(
                args=[election_data["election_id"]],
                countdown=i * 3,   # stagger 3s apart
            )
        
        # Also sync ballot questions
        bq_ids = client.get_ballot_question_ids(year)
        for i, bq_id in enumerate(bq_ids):
            sync_ma_ballot_question.apply_async(args=[bq_id], countdown=len(unique_elections) * 3 + i * 3)
        
        sync_log.status = "success"; sync_log.records_created = created_count
        sync_log.save()
    except Exception as exc:
        sync_log.status = "error"; sync_log.last_error = str(exc); sync_log.save()
        raise self.retry(exc=exc)
```

### Stage 2: `sync_ma_races` (race + candidate upsert)

```python
@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ma_races(self, electionstats_id: int):
    """
    Download election CSV, parse races and candidates, upsert to DB.
    """
    try:
        election = Election.objects.get(source_metadata__electionstats_id=electionstats_id)
    except Election.DoesNotExist:
        logger.warning("ma_sos.sync_races.no_election id=%s", electionstats_id)
        return
    
    client = MaSosClient()
    csv_content = client.download_election_csv(electionstats_id, precincts=False)
    
    # Parse CSV headers → candidate name list + party list
    candidates_data = parsers.parse_election_csv(csv_content)
    # candidates_data: [{"name": str, "party": str, "totals_votes": int, ...}, ...]
    
    # Upsert Race
    race_data = map_race(election, electionstats_id, candidates_data)
    with transaction.atomic():
        race, _ = Race.objects.update_or_create(
            canonical_key=race_data.pop("canonical_key"),
            defaults=race_data,
        )
        # Upsert Candidates
        candidates_to_create = [
            Candidate(race=race, **map_candidate(c))
            for c in candidates_data
            if c["name"] not in _TALLY_LABELS
        ]
        Candidate.objects.bulk_create(
            candidates_to_create,
            update_conflicts=True,
            unique_fields=["race", "name"],
            update_fields=["party", "source_metadata"],
        )
```

### Stage 3: `sync_ma_ballot_question` (BQ upsert)

```python
@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ma_ballot_question(self, bq_id: int):
    """
    Fetch BQ metadata from view page JS, download CSV, upsert Race + MeasureOption.
    """
    client = MaSosClient()
    metadata = client.get_ballot_question_metadata(bq_id)  # parses JS election_data object
    csv_content = client.download_bq_csv(bq_id)
    
    election_date = datetime.strptime(metadata["date"], "%Y-%m-%d").date()
    election = _get_or_create_bq_election(election_date)
    
    with transaction.atomic():
        race, _ = Race.objects.update_or_create(
            canonical_key=f"ma_sos:bq_{bq_id}",
            defaults=map_ballot_question(metadata, election),
        )
        MeasureOption.objects.get_or_create(race=race, option_label="Yes")
        MeasureOption.objects.get_or_create(race=race, option_label="No")
```

---

## 6. `client.py` Key Methods

```python
class MaSosClient:
    _ELECTIONSTATS_BASE = "https://electionstats.state.ma.us"
    _OCPF_BASE = "https://api.ocpf.us"
    _UA = "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"

    def get_election_ids(self, year: int, stage: str) -> list[dict]:
        """Fetch and parse election search page → list of {election_id, office, district, stage, year}"""
        url = f"{self._ELECTIONSTATS_BASE}/elections/search/year_from:{year}/year_to:{year}/stage:{stage}"
        r = self._get(url, timeout=30)
        return parsers.parse_election_search_html(r.text)

    def get_ballot_question_ids(self, year: int) -> list[int]:
        """Fetch and parse BQ search page → list of bq_id ints"""
        url = f"{self._ELECTIONSTATS_BASE}/ballot_questions/search/year_from:{year}/year_to:{year}/"
        r = self._get(url, timeout=30)
        return parsers.parse_bq_search_html(r.text)

    def download_election_csv(self, election_id: int, precincts: bool = False) -> bytes:
        """Download election results CSV. Returns raw bytes for SHA-256 fingerprinting."""
        url = f"{self._ELECTIONSTATS_BASE}/elections/download/{election_id}/precincts_include:{1 if precincts else 0}/"
        r = self._get(url, timeout=60)
        return r.content

    def download_bq_csv(self, bq_id: int) -> bytes:
        url = f"{self._ELECTIONSTATS_BASE}/ballot_questions/download/{bq_id}/precincts_include:0/"
        r = self._get(url, timeout=60)
        return r.content

    def get_ballot_question_metadata(self, bq_id: int) -> dict:
        """Fetch view page and parse inline JS election_data object."""
        url = f"{self._ELECTIONSTATS_BASE}/ballot_questions/view/{bq_id}/"
        r = self._get(url, timeout=30)
        return parsers.parse_bq_metadata_js(r.text)

    def get_ocpf_schedule(self, year: int) -> dict:
        url = f"{self._OCPF_BASE}/filingSchedules/{year}"
        r = self._get(url, timeout=15)
        return r.json()

    def get_all_candidate_filers(self) -> list[dict]:
        """Fetch complete OCPF candidate committee listing (no params = full dataset)."""
        url = f"{self._OCPF_BASE}/filers/listings/C"
        r = self._get(url, timeout=60)
        return r.json()

    def get_incumbents_by_municipality(self) -> list[dict]:
        url = f"{self._OCPF_BASE}/municipalities"
        r = self._get(url, timeout=30)
        return r.json()

    def _get(self, url: str, timeout: int = 30) -> requests.Response:
        r = requests.get(url, headers={"User-Agent": self._UA}, timeout=timeout)
        r.raise_for_status()
        return r
```

---

## 7. `parsers.py` Key Functions

```python
import re, csv, io, json

_ELECTION_ID_RE = re.compile(r'id="election-id-(\d+)"')
_BQ_ID_RE       = re.compile(r'id="bq-id-(\d+)"')
_BQ_DATA_RE     = re.compile(r'election_data\[(\d+)\]\s*=\s*\{Election:\s*(\{[^}]+\})', re.DOTALL)

# Row selectors use BeautifulSoup
def parse_election_search_html(html: str) -> list[dict]:
    """Extract election rows → [{election_id, year, office, district, stage}]"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for tr in soup.select("tr[id^='election-id-']"):
        election_id = int(tr["id"].replace("election-id-", ""))
        tds = tr.find_all("td", recursive=False)
        results.append({
            "election_id": election_id,
            "year": int(tds[0].get_text(strip=True)),
            "office": tds[1].get_text(strip=True),
            "district": tds[2].get_text(strip=True),
            "stage": tds[3].get_text(strip=True),
        })
    return results

def parse_bq_search_html(html: str) -> list[int]:
    return [int(m) for m in _BQ_ID_RE.findall(html)]

def parse_bq_metadata_js(html: str) -> dict:
    """Extract inline JS election_data object → dict of BQ metadata."""
    m = _BQ_DATA_RE.search(html)
    if not m:
        raise MaSosError(f"election_data JS object not found in BQ view page")
    return json.loads(m.group(2))

def parse_election_csv(csv_bytes: bytes) -> list[dict]:
    """
    Parse election results CSV.
    Returns list of candidate dicts: [{name, party, total_votes, is_tally}]
    """
    text = csv_bytes.decode("utf-8")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    
    # Row 0: headers [City/Town, '', '', CandidateName1, CandidateName2, ...]
    # Row 1: parties ['', '', '', 'Democratic', 'Republican', ...]
    # Rows 2..N-1: data rows
    # Row N: TOTALS
    
    headers = rows[0][3:]   # skip first 3 (City/Town + 2 blanks)
    parties = rows[1][3:] if len(rows) > 1 else [""] * len(headers)
    
    # Find TOTALS row
    totals_row = next((r for r in rows if r and r[0].upper() == "TOTALS"), None)
    total_votes = [_parse_int(totals_row[i + 3]) for i in range(len(headers))] if totals_row else []
    
    candidates = []
    for i, name in enumerate(headers):
        candidates.append({
            "name": name.strip('"').strip(),
            "party": parties[i].strip() if i < len(parties) else "",
            "total_votes": total_votes[i] if i < len(total_votes) else 0,
            "is_tally": name.strip('"') in ("All Others", "Blanks", "Total Votes Cast"),
        })
    return candidates

def _parse_int(s: str) -> int:
    """Parse '2,041,668' → 2041668"""
    return int(s.replace(",", "").strip('"').strip())
```

---

## 8. `mappers.py` Key Functions

```python
_TALLY_LABELS = {"All Others", "Blanks", "Total Votes Cast", "Write-In"}

_STAGE_TO_ELECTION_TYPE = {
    "General": ElectionType.GENERAL,
    "Primaries": ElectionType.PRIMARY,
    "Democratic": ElectionType.PRIMARY,
    "Republican": ElectionType.PRIMARY,
    "Green-Rainbow": ElectionType.PRIMARY,
    "Libertarian": ElectionType.PRIMARY,
    "Working Families": ElectionType.PRIMARY,
    "United Independent": ElectionType.PRIMARY,
    "American": ElectionType.PRIMARY,
    "Independent Voters": ElectionType.PRIMARY,
}

_FEDERAL_OFFICES = {"President", "U.S. Senate", "U.S. House"}

def normalize(s: str) -> str:
    return s.lower().strip()

def infer_jurisdiction_level(office: str) -> str:
    if office in _FEDERAL_OFFICES:
        return "national"
    if office in ("State Senate", "State Representative", "Governor", "Lieutenant Governor",
                   "Attorney General", "Secretary of the Commonwealth", "Treasurer", "Auditor",
                   "Governor's Council"):
        return "state"
    return "local"

def build_canonical_key(election_source_id: str, office: str, district: str) -> str:
    return f"ma_sos:{election_source_id}:{normalize(office)}:{normalize(district or 'statewide')}"

def map_election(election_data: dict, schedule: dict) -> dict:
    year = election_data["year"]
    stage = election_data["stage"]
    election_date_str = (
        schedule.get("generalElectionDate") if stage == "General"
        else schedule.get("primaryElectionDate")
    )
    election_date = datetime.strptime(election_date_str, "%m/%d/%Y").date() if election_date_str else None
    
    return {
        "source_id": f"ma_sos_{election_data['election_id']}",
        "name": f"{year} MA {election_data['office']} {election_data['district']} — {stage}",
        "election_date": election_date,
        "election_type": _STAGE_TO_ELECTION_TYPE.get(stage, ElectionType.GENERAL),
        "jurisdiction_level": infer_jurisdiction_level(election_data["office"]),
        "state": "MA",
        "status": "results_certified",
        "source_metadata": {
            "electionstats_id": election_data["election_id"],
            "stage": stage,
        },
        "last_synced_at": timezone.now(),
    }

def map_race(election_obj, election_data: dict) -> dict:
    canonical_key = build_canonical_key(
        f"ma_sos_{election_data['election_id']}",
        election_data["office"],
        election_data["district"],
    )
    return {
        "election": election_obj,
        "canonical_key": canonical_key,
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": election_data["office"],
        "jurisdiction": election_data["district"] or "Statewide",
        "geography_scope": "statewide" if not election_data["district"] else "district",
        "certification_status": Race.CertStatus.RESULTS_CERTIFIED,
        "source": Race.Source.MA_SOS,
        "source_metadata": {"electionstats_id": election_data["election_id"]},
    }

def map_candidate(candidate: dict) -> dict:
    return {
        "name": candidate["name"],
        "party": candidate["party"],
        "source_metadata": {"electionstats_total_votes": candidate["total_votes"]},
    }

def map_ballot_question(metadata: dict, election_obj) -> dict:
    return {
        "election": election_obj,
        "race_type": Race.RaceType.MEASURE,
        "office_title": f"Ballot Question {metadata['question_number']}",
        "jurisdiction": metadata.get("locality_id") or "Statewide",
        "geography_scope": "statewide" if not metadata.get("is_local") else "district",
        "certification_status": Race.CertStatus.RESULTS_CERTIFIED,
        "vote_method": Race.VoteMethod.YES_NO,
        "source": Race.Source.MA_SOS,
        "yes_vote_details": metadata.get("question_alias", ""),
        "source_metadata": {
            "electionstats_bq_id": int(metadata["id"]),
            "question_number": metadata["question_number"],
            "summary": (metadata.get("summary") or "")[:2000],
            "is_initiative_petition": bool(metadata.get("is_initiative_petition")),
            "is_referendum": bool(metadata.get("is_referendum")),
            "is_local": bool(metadata.get("is_local")),
            "full_question_text": metadata.get("question", ""),
        },
    }
```

---

## 9. Results Adapter: `results/adapters/ma.py`

```python
import csv, hashlib, io
from django.core.cache import cache
import requests
from .base import BaseAdapter, AdapterResult, ResultRow, register

_ELECTIONSTATS_BASE = "https://electionstats.state.ma.us"
_TALLY_LABELS = {"All Others", "Blanks", "Total Votes Cast", "Write-In"}
_CACHE_TTL = 6 * 60 * 60  # 6 hours

@register
class MassachusettsAdapter(BaseAdapter):
    state = "MA"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election
        election = Election.objects.get(pk=election_id)
        electionstats_id = election.source_metadata.get("electionstats_id")
        if not electionstats_id:
            return AdapterResult(rows=[], notes="no electionstats_id in source_metadata")

        csv_url = f"{_ELECTIONSTATS_BASE}/elections/download/{electionstats_id}/precincts_include:0/"
        r = requests.get(csv_url, headers={"User-Agent": "CivicMirror/1.0"}, timeout=60)
        r.raise_for_status()

        csv_hash = hashlib.sha256(r.content).hexdigest()
        cache_key = f"ma_sos:hash:{election_id}"
        cached_hash = cache.get(cache_key)

        if cached_hash == csv_hash:
            return AdapterResult(unchanged=True, source_version=csv_hash, source_url=csv_url)

        rows = _parse_election_csv(r.content, election.office_title)
        cache.set(cache_key, csv_hash, _CACHE_TTL)
        return AdapterResult(rows=rows, source_version=csv_hash, source_url=csv_url)


def _parse_election_csv(csv_bytes: bytes, office_title: str) -> list[ResultRow]:
    text = csv_bytes.decode("utf-8")
    reader = list(csv.reader(io.StringIO(text)))
    if len(reader) < 3:
        return []

    candidate_names = [h.strip('"').strip() for h in reader[0][3:]]
    parties = reader[1][3:] if len(reader) > 1 else [""] * len(candidate_names)

    totals_row = next((r for r in reader if r and r[0].strip().upper() == "TOTALS"), None)
    if not totals_row:
        return []

    rows = []
    for i, name in enumerate(candidate_names):
        if name in _TALLY_LABELS:
            continue
        vote_count = _parse_int(totals_row[i + 3]) if totals_row else 0
        party = parties[i].strip() if i < len(parties) else ""
        rows.append(ResultRow(
            candidate_name=name,
            option_label=None,
            vote_count=vote_count,
            vote_pct=None,
            is_winner=None,        # TODO: parse from HTML view page if needed
            result_type="official",
            office_title=office_title,
            raw={"party": party, "source": "electionstats"},
        ))
    return rows


def _parse_int(s: str) -> int:
    return int(s.replace(",", "").strip('"').strip())
```

---

## 10. Migrations

### Migration 0012: `Race.Source.MA_SOS`

```python
class Migration(migrations.Migration):
    dependencies = [('elections', '0011_add_election_type_source_metadata')]
    operations = [
        migrations.AlterField(
            model_name='race',
            name='source',
            field=models.CharField(
                choices=[
                    ('civic_api', 'Civic API'),
                    ('openelections', 'OpenElections'),
                    ('medsl', 'MEDSL'),
                    ('community', 'Community'),
                    ('results_adapter', 'Results Adapter'),
                    ('sc_vrems', 'SC VREMS'),
                    ('ia_sos', 'Iowa SOS'),
                    ('co_sos', 'Colorado SOS'),
                    ('va_elect', 'Virginia ELECT'),
                    ('ma_sos', 'Massachusetts SOS'),   # NEW
                ],
                max_length=20,
            ),
        ),
    ]
```

---

## 11. Settings and URL Registration

**`config/settings/base.py` — INSTALLED_APPS:**
```python
'integrations.ma_sos',    # Add after integrations.va_elect
```

**`internal/urls.py`:**
```python
path("tasks/sync-ma-sos/", views.sync_ma_sos_trigger, name="internal-sync-ma-sos"),
```

**`results/apps.py` — register adapter in `ready()`:**
```python
from results.adapters import ma  # noqa: F401
```

---

## 12. Implementation Phases

### Phase 1 — Core Data Pipeline (Priority)
1. Create `integrations/ma_sos/` app scaffold
2. Implement `client.py` (HTTP methods for electionstats + OCPF)
3. Implement `parsers.py` (HTML parsers for election IDs, BQ metadata, CSV)
4. Implement `mappers.py` (pure transformations)
5. Implement `tasks.py` (Stage 1: `sync_ma_elections`, Stage 2: `sync_ma_races`, Stage 3: `sync_ma_ballot_question`)
6. Add `Race.Source.MA_SOS` migration
7. Register app in `INSTALLED_APPS`, register adapter in `results/apps.py`
8. Add internal trigger endpoint

### Phase 2 — Results Adapter
1. Implement `results/adapters/ma.py` (CSV download, SHA-256 version fingerprint, ResultRow parsing)
2. Test with known election IDs (165300, 165304)

### Phase 3 — Tests
1. `test_parsers.py` — test HTML extraction and CSV parsing with fixture data
2. `test_client.py` — test HTTP methods with mocked responses
3. `test_mappers.py` — test all mapping functions
4. `test_tasks.py` — test both Celery tasks (fully mocked, no DB)
5. `test_ma_adapter.py` — test adapter with mocked CSV response

### Phase 4 — OCPF Candidate Enrichment (Optional)
1. Add `sync_ma_ocpf_candidates` task: fetch `/filers/listings/C` → enrich matching Candidate records
2. Add `enrich_ma_incumbents` task: fetch `/municipalities` → mark incumbent=True on matching Candidates

---

## 13. Known Limitations and Edge Cases

| Limitation | Detail | Mitigation |
|---|---|---|
| No live ENR feed | `electionstats` is post-certification only; no real-time results | Note in docs; for election night, only unofficial external sources (AP, DDHQ) |
| HTML page size | Search/view pages are 350–400KB | Skip HTML parsing where possible; use direct CSV downloads |
| Candidate name format in CSV | `"Harris/ Walz"` (President/VP ticket) — not a single candidate | Parse as-is; map to single Candidate; note in source_metadata |
| Write-in candidates | `"Write-In"` may appear as a candidate column; actual names not available from CSV | Create a single Write-In candidate row; `is_write_in_aggregate=True` on the ResultRow |
| Local/municipal elections | Not included in statewide electionstats (only state + federal races shown) | Mark as out-of-scope; local election data unavailable programmatically |
| OCPF server-side filtering | `officeSought`, `isActive`, `pageSize` all silently ignored | Fetch full dataset, filter client-side |
| BQ metadata JS location | `election_data` object starts at ~200KB into the page | Use large offset or stream parsing; regex works on full body |
| ID non-contiguity | Election IDs are not sequential; gaps exist between years | Always discover via search page; never assume sequential IDs |
| No 2022/2024 in OpenElections | OpenElections repo stops at 2020 | Use electionstats for 2022+; OpenElections for historical backfill only |
| sec.state.ma.us is WAF-blocked | All subpages blocked by Imperva | Not needed; `electionstats.state.ma.us` is separate and unblocked |
| Party CSV row offset | Party row (row 1) has no leading `City/Town` cell — columns are offset by 3 | Always use `parties = rows[1][3:]` (skip first 3 placeholder columns) |
| Thousands-separator quoting | `"2,041,668"` — must use Python `csv` module | Never use `.split(",")` — always use `csv.reader` |

---

## 14. Data Source Summary

| Source | Use Case | Method |
|---|---|---|
| `electionstats.state.ma.us` | Election discovery, race/candidate data, results | HTML scrape (ID discovery) + CSV download (data) |
| `api.ocpf.us` | Candidate enrichment, incumbency, election dates | REST API (JSON) |
| OpenElections MA | Historical backfill 2000–2020 | GitHub raw CSVs |
| MEDSL Harvard Dataverse | Academic cross-validation 2020–2024 | Dataverse API |
| Google Civic API | Federal/state races with address lookup | REST API (existing integration) |

---

*Research conducted: 2026-05-25*  
*Next step: Implement Phase 1 — `integrations/ma_sos/` app scaffold*
