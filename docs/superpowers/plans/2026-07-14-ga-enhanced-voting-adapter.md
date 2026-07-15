# Georgia (GA) Enhanced Voting Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Georgia SOS election discovery, race/candidate creation, and production-safe result ingestion around Georgia's confirmed Enhanced Voting deployment.

**Architecture:** Keep the existing thin `results.adapters.ga.GeorgiaAdapter` as the Stage 2 statewide results adapter, backed by the shared `EnhancedVotingAdapter`. Add a new `integrations.ga_sos` app that discovers elections from `GET /jurisdictions/Georgia`, stores the exact `publicElectionId` as `Election.source_metadata["enr_slug"]`, and seeds races/candidates from `/elections/Georgia/{publicElectionId}/data`. Media export support is a separate audited backfill path, not part of normal polling.

**Tech Stack:** Django, Celery, `requests`, pytest, existing `aggregation.ingest`, existing `results.adapters.enhanced_voting`.

## Global Constraints

- Treat Georgia `publicElectionId` values as opaque source identifiers. Never generate or predict them from dates.
- Use `https://results.sos.ga.gov/results/public/api` as the API base and `Georgia` as the jurisdiction slug.
- Use `/jurisdictions/Georgia` for election discovery; the July 13 capture contained 115 elections and 159 child localities.
- Use `/elections/Georgia/{publicElectionId}/data` for routine race, candidate, and statewide result synchronization.
- Preserve source race names exactly, including primary suffixes like `US Senate - Rep`; store a normalized title separately for matching.
- Remove a final ` - Rep` or ` - Dem` only in normalized fields and only when the source party field agrees.
- The MVP portal at `mvp.sos.ga.gov` is out of scope for this build because it is Salesforce Experience Cloud with active bot checks.
- Do not commit full local HAR files or the 25.8 MB export as test fixtures. Extract compact JSON fixtures from the reviewed files.
- Before production deployment, test `results.sos.ga.gov` from the actual hosting environment and record status code, latency, and response size.

---

## Current Evidence

- Remote research pulled on 2026-07-14 added `docs/state-research/GA/GA-Election_Research_Updated_2026-07-13.md`.
- Local captures reviewed:
  - `docs/state-research/GA/results.sos.ga.gov_Archive [26-07-13 22-20-31].har`
  - `docs/state-research/GA/results.sos.ga.gov_Archive [26-07-13 22-21-53].har`
  - `docs/state-research/GA/results.sos.ga.gov_Archive [26-06-29 12-37-36].har`
  - `docs/state-research/GA/mvp.sos.ga.gov_Archive [26-06-29 12-35-52].har`
  - `docs/state-research/GA/export-06162026GeneralPrimaryRunoff.json`
- Confirmed browser-captured endpoints:
  - `GET /results/public/api/jurisdictions/Georgia`
  - `GET /results/public/api/elections/Georgia/06162026GeneralPrimaryRunoff/data`
  - `GET /results/public/api/elections/Georgia/06162026GeneralPrimaryRunoff/data/ballot-item/{ballotItemUuid}`
  - `GET /cdn/results/Georgia/export-06162026GeneralPrimaryRunoff.json`
- Local export evidence:
  - 27 statewide contests
  - 159 county result objects
  - 1,731 county contest records
  - 56,484 precinct-option records

---

## File Structure

- Create `backend/integrations/ga_sos/`: Georgia SOS integration package for discovery, mapping, tasks, and tests.
- Create `backend/integrations/ga_sos/client.py`: HTTP wrapper for jurisdiction, election metadata, election data, ballot-item detail, and media export.
- Create `backend/integrations/ga_sos/mappers.py`: pure mapping functions from Enhanced Voting JSON to CivicMirror `Election`, `Race`, `Candidate`, and `MeasureOption` fields.
- Create `backend/integrations/ga_sos/tasks.py`: Celery tasks `sync_ga_elections` and `sync_ga_races`.
- Modify `backend/config/settings/base.py`: register `integrations.ga_sos`.
- Modify `backend/internal/task_locks.py`, `backend/internal/views.py`, and `backend/internal/urls.py`: add the internal scheduler trigger.
- Modify `backend/results/adapters/ga.py` only if tests show the current adapter needs a GA-specific metadata fallback. The preferred path is to populate `source_metadata["enr_slug"]` in Stage 1.
- Modify `backend/results/tests/test_ga_adapter.py`: replace predicted example slug `11032026General` with a captured opaque ID such as `06162026GeneralPrimaryRunoff`.

---

### Task 1: Scaffold `integrations.ga_sos`

**Files:**
- Create: `backend/integrations/ga_sos/__init__.py`
- Create: `backend/integrations/ga_sos/apps.py`
- Create: `backend/integrations/ga_sos/exceptions.py`
- Create: `backend/integrations/ga_sos/tests/__init__.py`
- Modify: `backend/config/settings/base.py`

**Interfaces:**
- Produces: `GaSosError` and `GaSosRetryableError`.

- [ ] **Step 1: Add the app config**

```python
# backend/integrations/ga_sos/apps.py
from django.apps import AppConfig


class GeorgiaSosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.ga_sos"
    label = "ga_sos"
    verbose_name = "Georgia SOS Integration"
```

- [ ] **Step 2: Add exceptions**

```python
# backend/integrations/ga_sos/exceptions.py
class GaSosError(Exception):
    """Non-retryable Georgia SOS integration error."""


class GaSosRetryableError(GaSosError):
    """Transient Georgia SOS integration error that warrants a Celery retry."""
```

- [ ] **Step 3: Register the app**

In `backend/config/settings/base.py`, add:

```python
    "integrations.ga_sos",
```

near the other `integrations.*` apps.

- [ ] **Step 4: Verify the app loads**

Run:

```bash
cd backend && python manage.py check
```

Expected: `System check identified no issues`.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ga_sos backend/config/settings/base.py
git commit -m "feat(ga): scaffold Georgia SOS integration"
```

---

### Task 2: Create Compact Fixtures From Local Research Captures

**Files:**
- Create: `backend/integrations/ga_sos/tests/fixtures/jurisdiction_georgia.json`
- Create: `backend/integrations/ga_sos/tests/fixtures/election_data_06162026.json`
- Create: `backend/integrations/ga_sos/tests/fixtures/media_export_sample_06162026.json`

**Interfaces:**
- Produces compact, committed fixtures that preserve the shapes needed by parser/mapper tests without committing local HARs.

- [ ] **Step 1: Extract the jurisdiction fixture from the July 13 HAR**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path

har_path = Path("docs/state-research/GA/results.sos.ga.gov_Archive [26-07-13 22-20-31].har")
out_path = Path("backend/integrations/ga_sos/tests/fixtures/jurisdiction_georgia.json")
data = json.loads(har_path.read_text())
for entry in data["log"]["entries"]:
    url = entry["request"]["url"]
    if url.endswith("/results/public/api/jurisdictions/Georgia"):
        payload = json.loads(entry["response"]["content"]["text"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(len(payload["elections"]), len(payload["childLocalities"]))
        break
else:
    raise SystemExit("jurisdiction response not found")
PY
```

Expected output: `115 159`.

- [ ] **Step 2: Extract the election data fixture from the July 13 HAR**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path

har_path = Path("docs/state-research/GA/results.sos.ga.gov_Archive [26-07-13 22-21-53].har")
out_path = Path("backend/integrations/ga_sos/tests/fixtures/election_data_06162026.json")
data = json.loads(har_path.read_text())
for entry in data["log"]["entries"]:
    url = entry["request"]["url"]
    if url.endswith("/results/public/api/elections/Georgia/06162026GeneralPrimaryRunoff/data"):
        payload = json.loads(entry["response"]["content"]["text"])
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(len(payload["ballotItems"]), len(payload["localityElections"]))
        break
else:
    raise SystemExit("election data response not found")
PY
```

Expected output: `27 159`.

- [ ] **Step 3: Create a small media export sample**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path

source = Path("docs/state-research/GA/export-06162026GeneralPrimaryRunoff.json")
out = Path("backend/integrations/ga_sos/tests/fixtures/media_export_sample_06162026.json")
payload = json.loads(source.read_text())
sample = {
    "electionDate": payload["electionDate"],
    "electionName": payload["electionName"],
    "createdAt": payload["createdAt"],
    "results": {
        **{k: payload["results"][k] for k in ("id", "name", "reportingStatuses")},
        "ballotItems": payload["results"]["ballotItems"][:2],
    },
    "localResults": payload["localResults"][:2],
}
out.write_text(json.dumps(sample, indent=2, sort_keys=True) + "\n")
print(len(sample["results"]["ballotItems"]), len(sample["localResults"]))
PY
```

Expected output: `2 2`.

- [ ] **Step 4: Confirm no full HAR/export fixture was staged**

Run:

```bash
git status --short backend/integrations/ga_sos/tests/fixtures docs/state-research/GA
```

Expected: only the three compact fixture files are staged later; local HARs and the large export remain unstaged unless a separate docs decision is made.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ga_sos/tests/fixtures
git commit -m "test(ga): add compact Georgia Enhanced Voting fixtures"
```

---

### Task 3: Build the Georgia Enhanced Voting Client

**Files:**
- Create: `backend/integrations/ga_sos/client.py`
- Create: `backend/integrations/ga_sos/tests/test_client.py`

**Interfaces:**
- Produces: `GaSosClient.get_jurisdiction() -> dict`, `list_elections() -> list[dict]`, `get_election_metadata(public_election_id: str) -> dict`, `get_election_data(public_election_id: str) -> dict`, `get_ballot_item_detail(public_election_id: str, ballot_item_id: str) -> dict`, `get_media_export(media_export_path: str) -> dict`.

- [ ] **Step 1: Write tests for endpoint construction and retry behavior**

```python
# backend/integrations/ga_sos/tests/test_client.py
from unittest.mock import MagicMock

import pytest

from integrations.ga_sos.client import GaSosClient
from integrations.ga_sos.exceptions import GaSosError, GaSosRetryableError


def _response(payload, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status.side_effect = None
    return resp


def test_list_elections_reads_jurisdiction_catalog():
    client = GaSosClient()
    client._session.get = MagicMock(return_value=_response({
        "elections": [{"publicElectionId": "06162026GeneralPrimaryRunoff"}]
    }))

    rows = client.list_elections()

    assert rows == [{"publicElectionId": "06162026GeneralPrimaryRunoff"}]
    assert client._session.get.call_args.args[0] == (
        "https://results.sos.ga.gov/results/public/api/jurisdictions/Georgia"
    )


def test_get_election_data_uses_opaque_public_id():
    client = GaSosClient()
    client._session.get = MagicMock(return_value=_response({"ballotItems": []}))

    assert client.get_election_data("06162026GeneralPrimaryRunoff") == {"ballotItems": []}
    assert client._session.get.call_args.args[0].endswith(
        "/elections/Georgia/06162026GeneralPrimaryRunoff/data"
    )


def test_404_is_non_retryable():
    client = GaSosClient(max_retries=0)
    resp = _response({}, status_code=404)
    resp.raise_for_status.side_effect = Exception("not found")
    client._session.get = MagicMock(return_value=resp)

    with pytest.raises(GaSosError):
        client.get_election_metadata("missing")


def test_503_is_retryable():
    client = GaSosClient(max_retries=0)
    client._session.get = MagicMock(return_value=_response({}, status_code=503))

    with pytest.raises(GaSosRetryableError):
        client.get_jurisdiction()
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
cd backend && pytest integrations/ga_sos/tests/test_client.py -v
```

Expected: import failure for `integrations.ga_sos.client`.

- [ ] **Step 3: Implement the client**

```python
# backend/integrations/ga_sos/client.py
from __future__ import annotations

import logging

import requests

from .exceptions import GaSosError, GaSosRetryableError

logger = logging.getLogger(__name__)

API_BASE = "https://results.sos.ga.gov/results/public/api"
CDN_BASE = "https://results.sos.ga.gov/cdn/results"
JURISDICTION = "Georgia"
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class GaSosClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "CivicMirror-GA-SOS/1.0"})

    def _get_json(self, url: str, timeout: int | None = None) -> dict:
        effective_timeout = timeout or self.timeout
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=effective_timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise GaSosRetryableError(f"GET {url} failed: {exc}") from exc
                continue
            if resp.status_code == 404:
                raise GaSosError(f"GET {url} returned 404")
            if resp.status_code in RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise GaSosRetryableError(f"GET {url} returned {resp.status_code}")
                continue
            try:
                resp.raise_for_status()
            except requests.HTTPError as exc:
                raise GaSosError(f"GET {url} returned {resp.status_code}") from exc
            try:
                return resp.json()
            except ValueError as exc:
                raise GaSosError(f"Invalid JSON from {url}: {exc}") from exc
        raise GaSosRetryableError(f"GET {url} retries exhausted")

    def get_jurisdiction(self) -> dict:
        return self._get_json(f"{API_BASE}/jurisdictions/{JURISDICTION}", timeout=15)

    def list_elections(self) -> list[dict]:
        return self.get_jurisdiction().get("elections") or []

    def get_election_metadata(self, public_election_id: str) -> dict:
        return self._get_json(f"{API_BASE}/elections/{JURISDICTION}/{public_election_id}", timeout=15)

    def get_election_data(self, public_election_id: str) -> dict:
        return self._get_json(f"{API_BASE}/elections/{JURISDICTION}/{public_election_id}/data", timeout=60)

    def get_ballot_item_detail(self, public_election_id: str, ballot_item_id: str) -> dict:
        return self._get_json(
            f"{API_BASE}/elections/{JURISDICTION}/{public_election_id}/data/ballot-item/{ballot_item_id}",
            timeout=60,
        )

    def get_media_export(self, media_export_path: str) -> dict:
        return self._get_json(f"{CDN_BASE}/{media_export_path.lstrip('/')}", timeout=120)
```

- [ ] **Step 4: Verify tests pass**

Run:

```bash
cd backend && pytest integrations/ga_sos/tests/test_client.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ga_sos/client.py backend/integrations/ga_sos/tests/test_client.py
git commit -m "feat(ga): add Enhanced Voting API client"
```

---

### Task 4: Map Elections, Races, Candidates, and Measures

**Files:**
- Create: `backend/integrations/ga_sos/mappers.py`
- Create: `backend/integrations/ga_sos/tests/test_mappers.py`

**Interfaces:**
- Produces: `map_election(row: dict) -> dict`, `map_race(election_obj, ballot_item: dict) -> dict`, `map_candidate(ballot_option: dict) -> dict`, `map_measure_option(ballot_option: dict) -> dict`, `normalize_office_title(title: str, party_name: str = "") -> str`.

- [ ] **Step 1: Write mapper tests from fixtures**

```python
# backend/integrations/ga_sos/tests/test_mappers.py
import json
from pathlib import Path
from types import SimpleNamespace

from elections.models import Candidate, Election, Race
from integrations.ga_sos.mappers import (
    map_candidate,
    map_election,
    map_measure_option,
    map_race,
    normalize_office_title,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text())


def test_map_election_preserves_opaque_public_id():
    row = next(
        e for e in _fixture("jurisdiction_georgia.json")["elections"]
        if e["publicElectionId"] == "06162026GeneralPrimaryRunoff"
    )

    mapped = map_election(row)

    assert mapped["source_id"] == "ga_sos:06162026GeneralPrimaryRunoff"
    assert mapped["state"] == "GA"
    assert mapped["jurisdiction_level"] == Election.JurisdictionLevel.STATE
    assert mapped["source_metadata"]["enr_slug"] == "06162026GeneralPrimaryRunoff"
    assert mapped["source_metadata"]["ga_public_election_id"] == "06162026GeneralPrimaryRunoff"


def test_normalize_office_title_removes_agreeing_primary_suffix_only():
    assert normalize_office_title("US Senate - Rep", "REP") == "us senate"
    assert normalize_office_title("Secretary of State - Dem", "DEM") == "secretary of state"
    assert normalize_office_title("Special State Senate - District 7", "") == (
        "special state senate district 7"
    )


def test_map_race_uses_ga_source_and_ballot_item_id():
    data = _fixture("election_data_06162026.json")
    item = next(b for b in data["ballotItems"] if b["name"][0]["text"] == "US Senate - Rep")
    election = SimpleNamespace(
        status=Election.Status.RESULTS_PENDING,
        source_id="ga_sos:06162026GeneralPrimaryRunoff",
        source_metadata={"enr_slug": "06162026GeneralPrimaryRunoff"},
    )

    mapped = map_race(election, item)

    assert mapped["source"] == Race.Source.GA_SOS
    assert mapped["office_title"] == "US Senate - Rep"
    assert mapped["normalized_office_title"] == "us senate"
    assert mapped["geography_scope"] == "federal"
    assert mapped["source_metadata"]["ga_ballot_item_id"] == item["id"]
    assert mapped["source_metadata"]["enr_slug"] == "06162026GeneralPrimaryRunoff"


def test_map_candidate_reads_party_from_enhanced_voting_api_shape():
    item = _fixture("election_data_06162026.json")["ballotItems"][0]
    option = item["summaryResults"]["ballotOptions"][0]

    mapped = map_candidate(option)

    assert mapped["candidate_status"] == Candidate.CandidateStatus.RUNNING
    assert mapped["party"] in {"REP", "Republican"}
    assert mapped["source_metadata"]["ga_native_id"] == option.get("nativeId")


def test_map_candidate_reads_party_from_media_export_shape():
    item = _fixture("media_export_sample_06162026.json")["results"]["ballotItems"][0]
    option = item["ballotOptions"][0]

    mapped = map_candidate(option)

    assert mapped["party"] == "REP"
    assert mapped["source_metadata"]["party_abbreviation"] == "REP"


def test_map_measure_option_preserves_label():
    mapped = map_measure_option({"name": [{"languageId": "en", "text": "Yes"}], "nativeId": "yes-1"})
    assert mapped["option_label"] == "Yes"
    assert mapped["source_metadata"]["ga_native_id"] == "yes-1"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
cd backend && pytest integrations/ga_sos/tests/test_mappers.py -v
```

Expected: import failure for `integrations.ga_sos.mappers`.

- [ ] **Step 3: Implement the mappers**

The implementation should mirror `integrations.va_elect.mappers` and `integrations.wa_votewa.mappers`, with these GA-specific differences:

```python
SOURCE = "ga_sos"
STATE = "GA"
JURISDICTION = "Georgia"
```

Use `Race.Source.GA_SOS` for race source. Store metadata:

```python
"source_metadata": {
    "ga_ballot_item_id": ballot_item.get("id", ""),
    "enr_slug": (election_obj.source_metadata or {}).get("enr_slug", ""),
    "ga_public_election_id": (election_obj.source_metadata or {}).get("ga_public_election_id", ""),
    "contest_type": contest_type,
    "party_name": ballot_item.get("partyName", ""),
    "reporting_units": (ballot_item.get("reportingStatus") or {}).get("reportingUnits"),
    "total_units": (ballot_item.get("reportingStatus") or {}).get("totalUnits"),
}
```

Candidate party extraction must support both shapes:

```python
party_abbr = (
    ((ballot_option.get("party") or {}).get("abbreviation") or "")
    or ballot_option.get("politicalParty", "")
)
```

- [ ] **Step 4: Verify mapper tests pass**

Run:

```bash
cd backend && pytest integrations/ga_sos/tests/test_mappers.py -v
```

Expected: all mapper tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ga_sos/mappers.py backend/integrations/ga_sos/tests/test_mappers.py
git commit -m "feat(ga): map Georgia elections races and candidates"
```

---

### Task 5: Add Georgia Election and Race Sync Tasks

**Files:**
- Create: `backend/integrations/ga_sos/tasks.py`
- Create: `backend/integrations/ga_sos/tests/test_tasks.py`

**Interfaces:**
- Produces: `sync_ga_elections()` and `sync_ga_races(election_pk: int, public_election_id: str)`.

- [ ] **Step 1: Write task tests**

Test the following behaviors:

- `sync_ga_elections` calls `client.list_elections()`.
- Each discovered election is ingested with `source="ga_sos"`.
- `Election.source_metadata["enr_slug"]` is set to the exact `publicElectionId`.
- `sync_ga_races` is queued for each ingested election.
- `sync_ga_races` upserts candidate races and candidates from `ballotItems[]`.
- Ballot measure contests create `MeasureOption` rows.

- [ ] **Step 2: Implement `sync_ga_elections`**

Use the same ingest pattern as `integrations.wa_votewa.tasks.sync_wa_elections`:

```python
mapped = map_election(row)
source_id = mapped.pop("source_id")
identity = {
    "state": mapped["state"],
    "election_type": mapped["election_type"],
    "election_date": mapped["election_date"],
    "jurisdiction_level": mapped["jurisdiction_level"],
}
fields = {k: v for k, v in mapped.items() if k not in identity}
election_obj, was_created = ingest.ingest_election(
    source="ga_sos",
    source_id=source_id,
    identity=identity,
    fields=fields,
)
```

After ingest, force-write `enr_slug` and `ga_public_election_id` into `election_obj.source_metadata` when missing, because the results adapter depends on `enr_slug`.

- [ ] **Step 3: Implement `sync_ga_races`**

Use the same ingest pattern as `sync_wa_races`, but call GA mappers and use `source="ga_sos"`. Skip ballot items with blank office titles. Deduplicate candidates by `(name, party)` within a race.

- [ ] **Step 4: Verify focused tests pass**

Run:

```bash
cd backend && pytest integrations/ga_sos/tests/test_tasks.py -v
```

Expected: all GA task tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ga_sos/tasks.py backend/integrations/ga_sos/tests/test_tasks.py
git commit -m "feat(ga): sync elections races and candidates"
```

---

### Task 6: Wire Internal Scheduling

**Files:**
- Modify: `backend/internal/task_locks.py`
- Modify: `backend/internal/views.py`
- Modify: `backend/internal/urls.py`
- Create or modify: `backend/internal/tests/test_task_locks.py`

**Interfaces:**
- Produces: `POST /internal/tasks/sync-ga-sos/`.

- [ ] **Step 1: Add a task lock**

In `TASK_LOCKS`, add:

```python
"sync_ga_sos": (WINDOW_DAILY, 23 * _HOUR),
```

- [ ] **Step 2: Add the internal trigger**

In `backend/internal/views.py`, import:

```python
from integrations.ga_sos.tasks import sync_ga_elections
```

Then add:

```python
@csrf_exempt
@require_POST
@require_internal_task_token
def sync_ga_sos_trigger(request):
    return _trigger("sync_ga_sos", sync_ga_elections, request)
```

- [ ] **Step 3: Add the URL**

In `backend/internal/urls.py`, add:

```python
path("tasks/sync-ga-sos/", views.sync_ga_sos_trigger, name="internal-sync-ga-sos"),
```

- [ ] **Step 4: Verify URL resolution and lock registry**

Run:

```bash
cd backend && python manage.py shell -c 'from django.urls import resolve; print(resolve("/internal/tasks/sync-ga-sos/").url_name)'
cd backend && python manage.py shell -c 'from internal.task_locks import TASK_LOCKS; print(TASK_LOCKS["sync_ga_sos"])'
```

Expected:

```text
internal-sync-ga-sos
('daily', 82800)
```

- [ ] **Step 5: Commit**

```bash
git add backend/internal/task_locks.py backend/internal/views.py backend/internal/urls.py backend/internal/tests
git commit -m "feat(ga): add internal sync trigger"
```

---

### Task 7: Tighten the Existing GA Results Adapter Tests

**Files:**
- Modify: `backend/results/tests/test_ga_adapter.py`
- Modify: `backend/results/adapters/ga.py` only if needed.

**Interfaces:**
- Preserves: `GeorgiaAdapter.fetch_results(election_date, election_id) -> AdapterResult`.

- [ ] **Step 1: Replace predicted slug examples**

In `backend/results/tests/test_ga_adapter.py`, replace `11032026General` with `06162026GeneralPrimaryRunoff` or another captured opaque `publicElectionId`.

- [ ] **Step 2: Add a test that documents discovery requirement**

```python
def test_ga_adapter_requires_discovered_enr_slug():
    assert "jurisdictions/Georgia" in GeorgiaAdapter.__doc__ or GeorgiaAdapter.state_name == "Georgia"
```

If the docstring assertion feels brittle during implementation, use a direct behavior test that confirms no date-derived fallback is attempted when `source_metadata` is empty.

- [ ] **Step 3: Run GA results tests**

Run:

```bash
cd backend && pytest results/tests/test_ga_adapter.py -v
```

Expected: all GA result adapter tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/results/tests/test_ga_adapter.py backend/results/adapters/ga.py
git commit -m "test(ga): document opaque Enhanced Voting election ids"
```

---

### Task 8: Add Optional Media Export Parsing for Audit Backfills

**Files:**
- Create: `backend/integrations/ga_sos/media_export.py`
- Create: `backend/integrations/ga_sos/tests/test_media_export.py`

**Interfaces:**
- Produces: `iter_media_export_rows(payload: dict) -> Iterator[dict]`.

- [ ] **Step 1: Write tests against `media_export_sample_06162026.json`**

Assert that:

- Statewide rows include contest ID `US2R`, candidate `Mike Collins`, party `REP`, and vote count.
- County rows include county name and contest ID.
- Precinct rows include county name, precinct ID, precinct name, reporting status, and vote count.
- Ballot option IDs are scoped to contest IDs.

- [ ] **Step 2: Implement a pure iterator**

Return dictionaries with:

```python
{
    "level": "state" | "county" | "precinct",
    "county": "",
    "precinct_id": "",
    "precinct_name": "",
    "contest_id": "",
    "contest_name": "",
    "candidate_id": "",
    "candidate_name": "",
    "party": "",
    "vote_count": 0,
    "reporting_status": "",
}
```

- [ ] **Step 3: Keep this parser out of normal polling**

Do not call `iter_media_export_rows` from `sync_ga_races`. Save media export ingestion for a later precinct-results task.

- [ ] **Step 4: Commit**

```bash
git add backend/integrations/ga_sos/media_export.py backend/integrations/ga_sos/tests/test_media_export.py
git commit -m "feat(ga): parse media export snapshots"
```

---

### Task 9: Verify End-to-End Locally

**Files:**
- No new files expected.

**Interfaces:**
- Verifies the GA integration works with the existing Django/Celery wiring.

- [ ] **Step 1: Run focused tests**

```bash
cd backend && pytest integrations/ga_sos results/tests/test_ga_adapter.py -v
```

Expected: all focused tests pass.

- [ ] **Step 2: Run lint**

```bash
cd backend && ruff check .
```

Expected: no lint errors.

- [ ] **Step 3: Run Django checks**

```bash
cd backend && python manage.py check
```

Expected: `System check identified no issues`.

- [ ] **Step 4: Smoke-test live access locally**

```bash
cd backend && python manage.py shell -c 'from integrations.ga_sos.client import GaSosClient; c=GaSosClient(); j=c.get_jurisdiction(); print(len(j["elections"]), len(j["childLocalities"]))'
```

Expected from current captures: values near `115 159`. If the count changes, confirm the response is valid JSON and record the new count in the PR notes.

- [ ] **Step 5: Smoke-test production-environment access before enabling schedule**

From the same environment that will run ingestion, request:

```text
https://results.sos.ga.gov/results/public/api/jurisdictions/Georgia
```

Record status code, latency, response size, and whether a CDN/WAF challenge appears. If blocked, route through the existing CivicMirror proxy pattern before enabling the scheduled task.

---

## Self-Review

- Spec coverage: The plan covers remote research pull-in, local HAR/export evidence, election discovery, race/candidate creation, existing GA results adapter behavior, media export handling, internal trigger wiring, and production access validation.
- Placeholder scan: No task relies on an unspecified future design. The only deferred work is explicitly scoped as a later precinct-results task.
- Type consistency: The plan consistently uses `GaSosClient`, `sync_ga_elections`, `sync_ga_races`, `ga_sos`, `Race.Source.GA_SOS`, and `Election.source_metadata["enr_slug"]`.

