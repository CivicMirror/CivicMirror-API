# Washington VoteWA Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `integrations/wa_votewa/` — a full Washington election/race discovery integration mirroring the VA ELECT pattern — and extend `results/adapters/wa.py` with county fan-out, WA-specific version detection, and richer raw IDs.

**Architecture:** A new `wa_votewa` integration module seeds known WA election date slugs (yyyymmdd format), fetches VoteWA public API metadata, upserts Election/Race/Candidate rows via the aggregation ingest service, and schedules PDC enrichment. The WA results adapter is upgraded from its current 4-line stub to do county fan-out using `localityElections[]`, emitting county-scoped `ResultRow` entries with `jurisdiction_fragment` set to the county slug.

**Tech Stack:** Django, Celery, `requests`, `aggregation.ingest`, VoteWA public JSON API (`results.votewa.gov`), no auth required.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `elections/models.py` | Modify | Add `Race.Source.WA_VOTEWA` |
| `elections/migrations/0017_wa_votewa_race_source.py` | Create | Migration for new source choice |
| `backend/integrations/wa_votewa/__init__.py` | Create | Package marker |
| `backend/integrations/wa_votewa/apps.py` | Create | Django AppConfig |
| `backend/integrations/wa_votewa/exceptions.py` | Create | `WaVoteWaError`, `WaVoteWaRetryableError` |
| `backend/integrations/wa_votewa/client.py` | Create | VoteWA HTTP client + seed slug list |
| `backend/integrations/wa_votewa/mappers.py` | Create | Election / Race / Candidate / MeasureOption mapping |
| `backend/integrations/wa_votewa/tasks.py` | Create | `sync_wa_elections`, `sync_wa_races` Celery tasks |
| `backend/integrations/wa_votewa/tests/__init__.py` | Create | Package marker |
| `backend/integrations/wa_votewa/tests/test_client.py` | Create | Client unit tests (HTTP mocked) |
| `backend/integrations/wa_votewa/tests/test_mappers.py` | Create | Mapper unit tests (no DB) |
| `backend/integrations/wa_votewa/tests/test_tasks.py` | Create | Task unit tests (DB + Celery mocked) |
| `backend/results/adapters/wa.py` | Modify | Full override: county fan-out, version detect, raw IDs |
| `backend/results/tests/test_wa_adapter.py` | Modify | Add county fan-out + version-detect tests |
| `backend/config/settings/base.py` | Modify | Register `integrations.wa_votewa` in INSTALLED_APPS |

---

## Task 1: Race.Source.WA_VOTEWA + Migration

**Files:**
- Modify: `backend/elections/models.py`
- Create: `backend/elections/migrations/0017_wa_votewa_race_source.py`

- [ ] **Step 1: Write failing test**

```python
# Run this inline — no test file needed
# cd backend && python -m pytest --no-migrations -q -k "false" 2>/dev/null; python -c "
# from elections.models import Race; print(Race.Source.WA_VOTEWA)
# "
# Expected: AttributeError — WA_VOTEWA doesn't exist yet
```

Run: `cd /data/Projects/CivicMirror/CivicMirror-API/backend && python -c "from elections.models import Race; print(Race.Source.WA_VOTEWA)"`  
Expected: `AttributeError: WA_VOTEWA`

- [ ] **Step 2: Add WA_VOTEWA to Race.Source**

In `backend/elections/models.py`, find the `Source` class and add the new choice after `CA_SOS`:

```python
    class Source(models.TextChoices):
        CIVIC_API = 'civic_api', 'Civic API'
        OPENELECTIONS = 'openelections', 'OpenElections'
        MEDSL = 'medsl', 'MEDSL'
        COMMUNITY = 'community', 'Community'
        RESULTS_ADAPTER = 'results_adapter', 'Results Adapter'
        SC_VREMS = 'sc_vrems', 'SC VREMS'
        IA_SOS = 'ia_sos', 'Iowa SOS'
        CO_SOS = 'co_sos', 'Colorado SOS'
        VA_ELECT = 'va_elect', 'Virginia ELECT'
        MA_SOS = 'ma_sos', 'Massachusetts SOS'
        CA_SOS = 'ca_sos', 'California SOS'
        WA_VOTEWA = 'wa_votewa', 'Washington VoteWA'
```

- [ ] **Step 3: Create migration**

Create `backend/elections/migrations/0017_wa_votewa_race_source.py`:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('elections', '0016_candidate_contributing_sources'),
    ]

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
                    ('ma_sos', 'Massachusetts SOS'),
                    ('ca_sos', 'California SOS'),
                    ('wa_votewa', 'Washington VoteWA'),
                ],
                max_length=20,
            ),
        ),
    ]
```

- [ ] **Step 4: Verify the attribute exists**

Run: `cd /data/Projects/CivicMirror/CivicMirror-API/backend && python -c "from elections.models import Race; print(Race.Source.WA_VOTEWA)"`  
Expected: `wa_votewa`

- [ ] **Step 5: Commit**

```bash
git add backend/elections/models.py backend/elections/migrations/0017_wa_votewa_race_source.py
git commit -m "feat(elections): add Race.Source.WA_VOTEWA choice + migration"
```

---

## Task 2: wa_votewa Package Scaffold

**Files:**
- Create: `backend/integrations/wa_votewa/__init__.py`
- Create: `backend/integrations/wa_votewa/apps.py`
- Create: `backend/integrations/wa_votewa/exceptions.py`
- Create: `backend/integrations/wa_votewa/tests/__init__.py`

- [ ] **Step 1: Create `__init__.py`**

```python
# backend/integrations/wa_votewa/__init__.py
```
(empty file)

- [ ] **Step 2: Create `apps.py`**

```python
# backend/integrations/wa_votewa/apps.py
from django.apps import AppConfig


class WaVoteWaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.wa_votewa"
    label = "wa_votewa"
    verbose_name = "Washington VoteWA Integration"
```

- [ ] **Step 3: Create `exceptions.py`**

```python
# backend/integrations/wa_votewa/exceptions.py


class WaVoteWaError(Exception):
    pass


class WaVoteWaRetryableError(WaVoteWaError):
    pass
```

- [ ] **Step 4: Create `tests/__init__.py`**

```python
# backend/integrations/wa_votewa/tests/__init__.py
```
(empty file)

- [ ] **Step 5: Register in INSTALLED_APPS**

In `backend/config/settings/base.py`, add `'integrations.wa_votewa'` after `'integrations.wa_pdc'`:

```python
    'integrations.wa_pdc',
    'integrations.wa_votewa',
```

- [ ] **Step 6: Verify import**

Run: `cd /data/Projects/CivicMirror/CivicMirror-API/backend && python -c "from integrations.wa_votewa.exceptions import WaVoteWaError; print('OK')"`  
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add backend/integrations/wa_votewa/ backend/config/settings/base.py
git commit -m "feat(wa-votewa): scaffold package + register in INSTALLED_APPS"
```

---

## Task 3: wa_votewa Client

**Files:**
- Create: `backend/integrations/wa_votewa/client.py`
- Create: `backend/integrations/wa_votewa/tests/test_client.py`

- [ ] **Step 1: Write failing tests**

Create `backend/integrations/wa_votewa/tests/test_client.py`:

```python
"""
Unit tests for WaVoteWaClient. HTTP calls are fully mocked — no network required.
"""
from unittest.mock import MagicMock, patch

import pytest

from integrations.wa_votewa.client import (
    KNOWN_ELECTION_SLUGS,
    WaVoteWaClient,
)
from integrations.wa_votewa.exceptions import WaVoteWaError, WaVoteWaRetryableError


# ---------------------------------------------------------------------------
# KNOWN_ELECTION_SLUGS
# ---------------------------------------------------------------------------

def test_known_slugs_are_yyyymmdd():
    import re
    for slug in KNOWN_ELECTION_SLUGS:
        assert re.fullmatch(r"\d{8}", slug), f"Slug {slug!r} is not yyyymmdd"


def test_known_slugs_include_confirmed_har_date():
    assert "20260428" in KNOWN_ELECTION_SLUGS


# ---------------------------------------------------------------------------
# get_election_metadata
# ---------------------------------------------------------------------------

def test_get_election_metadata_returns_json():
    client = WaVoteWaClient()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"electionDate": "2026-04-28", "isOfficialResults": True}

    with patch.object(client, "_get", return_value=mock_resp) as mock_get:
        result = client.get_election_metadata("20260428")

    mock_get.assert_called_once()
    called_url = mock_get.call_args[0][0]
    assert "elections/washington/20260428" in called_url
    assert result["electionDate"] == "2026-04-28"


def test_get_election_metadata_retryable_error_propagates():
    client = WaVoteWaClient()
    with patch.object(client, "_get", side_effect=WaVoteWaRetryableError("timeout")):
        with pytest.raises(WaVoteWaRetryableError):
            client.get_election_metadata("20260428")


# ---------------------------------------------------------------------------
# get_election_data
# ---------------------------------------------------------------------------

def test_get_election_data_returns_json():
    client = WaVoteWaClient()
    payload = {"jurisdiction": {"shortName": "washington"}, "ballotItems": []}
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload

    with patch.object(client, "_get", return_value=mock_resp):
        result = client.get_election_data("20260428")

    assert result["jurisdiction"]["shortName"] == "washington"


# ---------------------------------------------------------------------------
# get_county_data
# ---------------------------------------------------------------------------

def test_get_county_data_returns_json():
    client = WaVoteWaClient()
    payload = {"jurisdiction": {"shortName": "mason-county-wa"}, "ballotItems": []}
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload

    with patch.object(client, "_get", return_value=mock_resp) as mock_get:
        result = client.get_county_data("mason-county-wa", "20260428")

    called_url = mock_get.call_args[0][0]
    assert "elections/mason-county-wa/20260428/data" in called_url
    assert result["jurisdiction"]["shortName"] == "mason-county-wa"


def test_get_county_data_returns_empty_on_error():
    """County 404 / network error → returns {} without raising."""
    client = WaVoteWaClient()
    with patch.object(client, "_get", side_effect=WaVoteWaError("404")):
        result = client.get_county_data("unknown-county-wa", "20260428")
    assert result == {}


# ---------------------------------------------------------------------------
# _get retries
# ---------------------------------------------------------------------------

def test_get_raises_retryable_on_network_error():
    client = WaVoteWaClient(max_retries=1)
    import requests as req
    with patch.object(client._session, "get", side_effect=req.ConnectionError("refused")):
        with pytest.raises(WaVoteWaRetryableError):
            client._get("https://results.votewa.gov/fake")


def test_get_raises_retryable_on_503():
    client = WaVoteWaClient(max_retries=1)
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    with patch.object(client._session, "get", return_value=mock_resp):
        with pytest.raises(WaVoteWaRetryableError):
            client._get("https://results.votewa.gov/fake")


def test_get_raises_on_404():
    client = WaVoteWaClient(max_retries=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch.object(client._session, "get", return_value=mock_resp):
        with pytest.raises(WaVoteWaError):
            client._get("https://results.votewa.gov/fake")
```

- [ ] **Step 2: Run tests — confirm they fail**

Run: `cd /data/Projects/CivicMirror/CivicMirror-API/backend && python -m pytest --no-migrations integrations/wa_votewa/tests/test_client.py -v`  
Expected: `ImportError` or `ModuleNotFoundError` — `client.py` doesn't exist yet.

- [ ] **Step 3: Create `client.py`**

Create `backend/integrations/wa_votewa/client.py`:

```python
"""
Washington VoteWA public results API client.

Public API base: https://results.votewa.gov/results/public/api
No auth required. Cache-Control: public, max-age=60.

Confirmed endpoints (from 2026-04-28 HAR):
  GET /api/elections/washington/{yyyymmdd}
  GET /api/elections/washington/{yyyymmdd}/data
  GET /api/elections/{county_slug}/{yyyymmdd}/data
  GET /api/elections/washington/{yyyymmdd}/data/ballot-item/{ballot_item_id}
"""
from __future__ import annotations

import logging

import requests

from .exceptions import WaVoteWaError, WaVoteWaRetryableError

logger = logging.getLogger(__name__)

_API_BASE = "https://results.votewa.gov/results/public/api"
_STATE_SLUG = "washington"
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Known WA election date keys (yyyymmdd). Seeded from SOS calendar research.
# Archive discovery is a future improvement; these cover 2026 elections.
KNOWN_ELECTION_SLUGS: list[str] = [
    "20260210",  # February 2026 (public route observed in VoteWA)
    "20260428",  # April 28, 2026 Special Election (confirmed in HAR)
    "20260804",  # August 4, 2026 Top-2 Primary
    "20261103",  # November 3, 2026 General Election
]


class WaVoteWaClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "CivicMirror-WA-VoteWA/1.0"})

    def _get(self, url: str, timeout: int | None = None) -> requests.Response:
        effective_timeout = timeout or self.timeout
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=effective_timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise WaVoteWaRetryableError(f"GET {url} failed: {exc}") from exc
                continue
            if resp.status_code == 404:
                raise WaVoteWaError(f"GET {url} returned 404")
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise WaVoteWaRetryableError(f"GET {url} returned {resp.status_code}")
                continue
            resp.raise_for_status()
            return resp
        raise WaVoteWaRetryableError(f"GET {url} retries exhausted")

    def get_election_metadata(self, slug: str) -> dict:
        """
        GET /api/elections/washington/{slug}

        Lightweight. Returns: id, electionDate, asOf, lastUpdated,
        isOfficialResults, publicReportCategories, ...
        """
        url = f"{_API_BASE}/elections/{_STATE_SLUG}/{slug}"
        try:
            resp = self._get(url, timeout=15)
        except WaVoteWaRetryableError as exc:
            raise WaVoteWaRetryableError(f"Metadata fetch failed slug={slug}: {exc}") from exc
        try:
            return resp.json()
        except ValueError as exc:
            raise WaVoteWaError(f"Invalid JSON from {url}: {exc}") from exc

    def get_election_data(self, slug: str) -> dict:
        """
        GET /api/elections/washington/{slug}/data

        Full statewide composite (1–3 MB). Returns: jurisdiction, election,
        localityElections[], ballotItems[], statistics[], voterRegistration[], ...
        """
        url = f"{_API_BASE}/elections/{_STATE_SLUG}/{slug}/data"
        try:
            resp = self._get(url, timeout=60)
        except WaVoteWaRetryableError as exc:
            raise WaVoteWaRetryableError(f"Data fetch failed slug={slug}: {exc}") from exc
        try:
            return resp.json()
        except ValueError as exc:
            raise WaVoteWaError(f"Invalid JSON from {url}: {exc}") from exc

    def get_county_data(self, county_slug: str, slug: str) -> dict:
        """
        GET /api/elections/{county_slug}/{slug}/data

        County-local data (confirmed for mason-county-wa). Returns: ballotItems[],
        precincts[], voterTurnout[], ...
        On any error returns {} so a single county failure doesn't abort the sync.
        """
        url = f"{_API_BASE}/elections/{county_slug}/{slug}/data"
        try:
            resp = self._get(url, timeout=60)
        except (WaVoteWaRetryableError, WaVoteWaError):
            logger.warning(
                "wa_votewa.client.county_data_failed county=%s slug=%s", county_slug, slug
            )
            return {}
        try:
            return resp.json()
        except ValueError:
            logger.warning(
                "wa_votewa.client.county_data_invalid_json county=%s slug=%s", county_slug, slug
            )
            return {}
```

- [ ] **Step 4: Run tests — confirm they pass**

Run: `cd /data/Projects/CivicMirror/CivicMirror-API/backend && python -m pytest --no-migrations integrations/wa_votewa/tests/test_client.py -v`  
Expected: All tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/wa_votewa/client.py backend/integrations/wa_votewa/tests/test_client.py
git commit -m "feat(wa-votewa): add VoteWA HTTP client with known election slug seed list"
```

---

## Task 4: wa_votewa Mappers

**Files:**
- Create: `backend/integrations/wa_votewa/mappers.py`
- Create: `backend/integrations/wa_votewa/tests/test_mappers.py`

- [ ] **Step 1: Write failing tests**

Create `backend/integrations/wa_votewa/tests/test_mappers.py`:

```python
"""
Unit tests for wa_votewa mappers. No DB required.
"""
from datetime import date
from unittest.mock import MagicMock

import pytest

from integrations.wa_votewa.mappers import (
    _get_text,
    infer_election_type,
    infer_election_status,
    map_candidate,
    map_election,
    map_measure_option,
    map_race,
    normalize,
    parse_election_date,
    parse_election_date_from_slug,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def test_get_text_english():
    names = [{"languageId": "en", "text": "Governor"}, {"languageId": "es", "text": "Gobernador"}]
    assert _get_text(names) == "Governor"


def test_get_text_fallback_to_first():
    names = [{"languageId": "es", "text": "Gobernador"}]
    assert _get_text(names) == "Gobernador"


def test_get_text_empty():
    assert _get_text([]) == ""


def test_normalize():
    assert normalize("  Governor  ") == "governor"
    assert normalize("Member,  House   of  Delegates") == "member, house of delegates"
    assert normalize(None) == ""


def test_parse_election_date_from_meta():
    meta = {"electionDate": "2026-04-28"}
    assert parse_election_date(meta) == date(2026, 4, 28)


def test_parse_election_date_missing():
    assert parse_election_date({}) is None


def test_parse_election_date_from_slug():
    assert parse_election_date_from_slug("20260428") == date(2026, 4, 28)


def test_parse_election_date_from_slug_bad():
    assert parse_election_date_from_slug("not-a-date") is None


# ---------------------------------------------------------------------------
# infer_election_type
# ---------------------------------------------------------------------------

def test_infer_type_general():
    assert infer_election_type(date(2026, 11, 3)) == "general"


def test_infer_type_primary():
    assert infer_election_type(date(2026, 8, 4)) == "primary"


def test_infer_type_special():
    assert infer_election_type(date(2026, 4, 28)) == "special"
    assert infer_election_type(date(2026, 2, 10)) == "special"


# ---------------------------------------------------------------------------
# map_election
# ---------------------------------------------------------------------------

def test_map_election_basic():
    meta = {"electionDate": "2026-04-28", "isOfficialResults": True}
    result = map_election("20260428", meta)

    assert result["source_id"] == "wa_votewa:20260428"
    assert result["state"] == "WA"
    assert result["election_date"] == date(2026, 4, 28)
    assert result["election_type"] == "special"
    assert result["jurisdiction_level"] == "state"
    assert result["source_metadata"]["enr_slug"] == "20260428"
    assert result["source_metadata"]["votewa_jurisdiction_slug"] == "washington"


def test_map_election_uses_api_name():
    meta = {"electionDate": "2026-11-03", "electionName": "2026 November General Election"}
    result = map_election("20261103", meta)
    assert result["name"] == "2026 November General Election"


def test_map_election_constructs_name_when_missing():
    meta = {"electionDate": "2026-04-28"}
    result = map_election("20260428", meta)
    assert "Washington" in result["name"]


# ---------------------------------------------------------------------------
# map_race
# ---------------------------------------------------------------------------

def _make_election(status="results_pending", slug="20260428"):
    e = MagicMock()
    e.status = status
    e.source_metadata = {"enr_slug": slug}
    return e


def _make_ballot_item(contest_type="BallotMeasure", name_text="Proposition 1", item_id="item-001"):
    return {
        "id": item_id,
        "contestType": contest_type,
        "name": [{"languageId": "en", "text": name_text}],
        "summaryResults": {"ballotOptions": []},
    }


def test_map_race_measure():
    election = _make_election()
    item = _make_ballot_item(contest_type="BallotMeasure", name_text="Proposition 1")
    result = map_race(election, item)

    assert result["race_type"] == "measure"
    assert result["office_title"] == "Proposition 1"
    assert result["source_metadata"]["votewa_ballot_item_id"] == "item-001"
    assert result["source_metadata"]["contest_type"] == "BallotMeasure"
    assert result["geography_scope"] == "statewide"
    assert result["jurisdiction"] == "Washington"


def test_map_race_candidate():
    election = _make_election()
    item = _make_ballot_item(contest_type="Candidate", name_text="State Senator")
    result = map_race(election, item)

    assert result["race_type"] == "candidate"
    assert result["office_title"] == "State Senator"
    assert result["vote_method"] == "single_choice"


def test_map_race_county_scope():
    election = _make_election()
    item = _make_ballot_item(contest_type="BallotMeasure", name_text="Fire District Levy")
    item["parentId"] = "parent-agg-001"
    result = map_race(election, item, jurisdiction_slug="mason-county-wa")

    assert result["geography_scope"] == "county"
    assert result["source_metadata"]["votewa_parent_ballot_item_id"] == "parent-agg-001"
    assert "Mason" in result["jurisdiction"]


# ---------------------------------------------------------------------------
# map_candidate
# ---------------------------------------------------------------------------

def test_map_candidate_with_party():
    opt = {
        "nativeId": "opt-001",
        "isWriteIn": False,
        "party": {"abbreviation": "D", "name": "Democratic"},
    }
    result = map_candidate(opt)

    assert result["party"] == "Democratic"
    assert result["source_metadata"]["votewa_native_id"] == "opt-001"
    assert result["source_metadata"]["is_write_in"] is False
    assert result["incumbent"] is False


def test_map_candidate_write_in():
    opt = {"nativeId": "wi-001", "isWriteIn": True, "party": {}}
    result = map_candidate(opt)
    assert result["source_metadata"]["is_write_in"] is True


def test_map_candidate_no_party():
    opt = {"nativeId": "opt-002", "isWriteIn": False}
    result = map_candidate(opt)
    assert result["party"] == ""


# ---------------------------------------------------------------------------
# map_measure_option
# ---------------------------------------------------------------------------

def test_map_measure_option_yes():
    opt = {
        "nativeId": "yes-001",
        "name": [{"languageId": "en", "text": "Yes"}],
    }
    result = map_measure_option(opt)
    assert result["option_label"] == "Yes"
    assert result["source_metadata"]["votewa_native_id"] == "yes-001"


def test_map_measure_option_falls_back_to_native_id():
    opt = {"nativeId": "fallback-id", "name": []}
    result = map_measure_option(opt)
    assert result["option_label"] == "fallback-id"
```

- [ ] **Step 2: Run tests — confirm they fail**

Run: `cd /data/Projects/CivicMirror/CivicMirror-API/backend && python -m pytest --no-migrations integrations/wa_votewa/tests/test_mappers.py -v`  
Expected: `ImportError` — `mappers.py` doesn't exist yet.

- [ ] **Step 3: Create `mappers.py`**

Create `backend/integrations/wa_votewa/mappers.py`:

```python
"""
Mappers for VoteWA public API data → CivicMirror model fields.
"""
from __future__ import annotations

from datetime import date, datetime

from elections.models import Candidate, Election, Race


def _get_text(names: list, lang: str = "en") -> str:
    """Extract display text from a VoteWA multilingual name list."""
    for n in names:
        if n.get("languageId") == lang:
            return (n.get("text") or "").strip()
    return ((names[0].get("text") or "").strip()) if names else ""


def normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def parse_election_date(meta: dict) -> date | None:
    raw = meta.get("electionDate")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


def parse_election_date_from_slug(slug: str) -> date | None:
    """Parse a yyyymmdd slug into a date."""
    try:
        return datetime.strptime(slug, "%Y%m%d").date()
    except ValueError:
        return None


def infer_election_type(election_date: date) -> str:
    if election_date.month == 11:
        return Election.ElectionType.GENERAL
    if election_date.month in {8, 9}:
        return Election.ElectionType.PRIMARY
    return Election.ElectionType.SPECIAL


def infer_election_status(election_date: date) -> str:
    from django.utils import timezone as tz
    today = tz.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def map_election(slug: str, meta: dict) -> dict:
    """
    Map VoteWA election metadata → Election model field values.

    slug:  yyyymmdd route key, e.g. "20260428"
    meta:  response from GET /api/elections/washington/{slug}
    """
    election_date = parse_election_date(meta) or parse_election_date_from_slug(slug)
    election_type = infer_election_type(election_date) if election_date else Election.ElectionType.OTHER

    date_label = election_date.strftime("%Y %B %-d") if election_date else slug
    name = meta.get("electionName") or f"Washington {date_label} Election"

    return {
        "source_id": f"wa_votewa:{slug}",
        "name": name,
        "election_date": election_date,
        "election_type": election_type,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "WA",
        "status": infer_election_status(election_date) if election_date else Election.Status.UPCOMING,
        "source_metadata": {
            "enr_slug": slug,
            "votewa_jurisdiction_slug": "washington",
            "is_official_results": meta.get("isOfficialResults", False),
        },
    }


def map_race(
    election_obj: Election,
    ballot_item: dict,
    jurisdiction_slug: str = "washington",
) -> dict:
    """
    Map a VoteWA ballotItems[] entry → Race model field values.

    jurisdiction_slug: "washington" for state-level items;
                       "{county}-county-wa" for county-local items.
    """
    contest_type = ballot_item.get("contestType", "Candidate")
    office_title = _get_text(ballot_item.get("name") or [])
    ballot_item_id = ballot_item.get("id", "")
    parent_ballot_item_id = ballot_item.get("parentId") or ballot_item.get("parentBallotItemId")

    race_type = (
        Race.RaceType.MEASURE
        if contest_type == "BallotMeasure"
        else Race.RaceType.CANDIDATE
    )

    certification_status = (
        Race.CertificationStatus.UPCOMING
        if election_obj.status in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_PENDING
    )

    is_county = jurisdiction_slug != "washington"
    if is_county:
        # "mason-county-wa" → "Mason County"
        jurisdiction = (
            jurisdiction_slug.replace("-wa", "").replace("-", " ").title()
        )
        geography_scope = "county"
    else:
        jurisdiction = "Washington"
        geography_scope = "statewide"

    enr_slug = (election_obj.source_metadata or {}).get("enr_slug", "")

    return {
        "race_type": race_type,
        "office_title": office_title,
        "normalized_office_title": normalize(office_title),
        "jurisdiction": jurisdiction,
        "geography_scope": geography_scope,
        "certification_status": certification_status,
        "source": Race.Source.WA_VOTEWA,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": (
            Race.VoteMethod.YES_NO
            if race_type == Race.RaceType.MEASURE
            else Race.VoteMethod.SINGLE_CHOICE
        ),
        "max_selections": 1,
        "ocd_division_id": "",
        "source_metadata": {
            "votewa_ballot_item_id": ballot_item_id,
            "votewa_parent_ballot_item_id": parent_ballot_item_id,
            "votewa_jurisdiction_slug": jurisdiction_slug,
            "enr_slug": enr_slug,
            "contest_type": contest_type,
        },
    }


def map_candidate(ballot_option: dict) -> dict:
    """Map a VoteWA ballotOptions[] entry → Candidate model field values."""
    party_data = ballot_option.get("party") or {}
    party_abbr = party_data.get("abbreviation", "")
    party_name_raw = party_data.get("name", "")
    if isinstance(party_name_raw, list):
        party_name = _get_text(party_name_raw)
    else:
        party_name = party_name_raw if isinstance(party_name_raw, str) else ""

    return {
        "party": party_name or party_abbr,
        "incumbent": False,
        "candidate_status": Candidate.CandidateStatus.RUNNING,
        "source_metadata": {
            "votewa_native_id": ballot_option.get("nativeId"),
            "party_abbreviation": party_abbr,
            "is_write_in": bool(ballot_option.get("isWriteIn", False)),
        },
    }


def map_measure_option(ballot_option: dict) -> dict:
    """Map a VoteWA ballotOptions[] entry for a BallotMeasure → MeasureOption field values."""
    return {
        "option_label": (
            _get_text(ballot_option.get("name") or []) or ballot_option.get("nativeId", "")
        ),
        "source_metadata": {
            "votewa_native_id": ballot_option.get("nativeId"),
        },
    }
```

- [ ] **Step 4: Run tests — confirm they pass**

Run: `cd /data/Projects/CivicMirror/CivicMirror-API/backend && python -m pytest --no-migrations integrations/wa_votewa/tests/test_mappers.py -v`  
Expected: All tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/wa_votewa/mappers.py backend/integrations/wa_votewa/tests/test_mappers.py
git commit -m "feat(wa-votewa): add election/race/candidate/measure-option mappers"
```

---

## Task 5: wa_votewa Tasks

**Files:**
- Create: `backend/integrations/wa_votewa/tasks.py`
- Create: `backend/integrations/wa_votewa/tests/test_tasks.py`

- [ ] **Step 1: Write failing tests**

Create `backend/integrations/wa_votewa/tests/test_tasks.py`:

```python
"""
Unit tests for wa_votewa Celery tasks.
Django ORM + Celery are mocked — no DB required.
"""
from datetime import date as _date
from unittest.mock import MagicMock, patch

import pytest

from integrations.wa_votewa.tasks import sync_wa_elections, sync_wa_races


# ---------------------------------------------------------------------------
# sync_wa_elections
# ---------------------------------------------------------------------------

def test_sync_wa_elections_skips_on_404():
    """When every slug returns a 404, no elections are created."""
    from integrations.wa_votewa.exceptions import WaVoteWaError

    with patch("integrations.wa_votewa.tasks.WaVoteWaClient") as MockClient, \
         patch("integrations.wa_votewa.tasks.SyncLog") as MockLog:

        client = MockClient.return_value
        client.get_election_metadata.side_effect = WaVoteWaError("404")

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log
        MockLog.Status.STARTED = "started"
        MockLog.Status.COMPLETED = "completed"
        MockLog.Status.FAILED = "failed"

        result = sync_wa_elections()

    assert result["created"] == 0
    assert result["skipped"] == len(result["skipped"] or []) or result["skipped"] > 0


def test_sync_wa_elections_dispatches_subtasks():
    """Valid slug → ingest_election called, subtask queued."""
    mock_election_obj = MagicMock()
    mock_election_obj.pk = 42
    mock_election_obj.source_metadata = {}

    with patch("integrations.wa_votewa.tasks.WaVoteWaClient") as MockClient, \
         patch("integrations.wa_votewa.tasks.SyncLog") as MockLog, \
         patch("integrations.wa_votewa.tasks.sync_wa_races") as mock_subtask, \
         patch("aggregation.ingest.ingest_election", return_value=(mock_election_obj, True)):

        client = MockClient.return_value
        # Only the first slug succeeds; the rest 404
        from integrations.wa_votewa.exceptions import WaVoteWaError
        client.get_election_metadata.side_effect = [
            {"electionDate": "2026-04-28", "isOfficialResults": True},
            WaVoteWaError("404"),
            WaVoteWaError("404"),
            WaVoteWaError("404"),
        ]

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log
        MockLog.Status.STARTED = "started"
        MockLog.Status.COMPLETED = "completed"
        MockLog.Status.FAILED = "failed"

        result = sync_wa_elections()

    mock_subtask.apply_async.assert_called_once()
    assert result["created"] == 1
    assert result["skipped"] == 3


# ---------------------------------------------------------------------------
# sync_wa_races
# ---------------------------------------------------------------------------

def _make_ballot_item(contest_type="BallotMeasure", name_text="Prop 1", item_id="bi-001"):
    return {
        "id": item_id,
        "contestType": contest_type,
        "name": [{"languageId": "en", "text": name_text}],
        "summaryResults": {
            "ballotOptions": [
                {
                    "name": [{"languageId": "en", "text": "Yes"}],
                    "nativeId": "opt-yes",
                    "voteCount": 100,
                    "votePercent": 60.0,
                }
            ]
        },
    }


def test_sync_wa_races_no_ballot_items():
    """Empty ballotItems → task completes with zero races."""
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.source_id = "wa_votewa:20260428"

    with patch("integrations.wa_votewa.tasks.Election") as MockElection, \
         patch("integrations.wa_votewa.tasks.WaVoteWaClient") as MockClient, \
         patch("integrations.wa_votewa.tasks.SyncLog") as MockLog:

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception

        client = MockClient.return_value
        client.get_election_data.return_value = {"ballotItems": []}

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log
        MockLog.Status.STARTED = "started"
        MockLog.Status.COMPLETED = "completed"
        MockLog.Status.FAILED = "failed"

        result = sync_wa_races(1, "20260428")

    assert result == {"races": 0, "candidates": 0}


def test_sync_wa_races_measure_item():
    """A BallotMeasure ballot item → ingest_race called with race_type=measure."""
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.source_id = "wa_votewa:20260428"
    mock_election.status = "results_pending"
    mock_election.source_metadata = {"enr_slug": "20260428"}

    mock_race = MagicMock()
    mock_race.pk = 10

    with patch("integrations.wa_votewa.tasks.Election") as MockElection, \
         patch("integrations.wa_votewa.tasks.WaVoteWaClient") as MockClient, \
         patch("integrations.wa_votewa.tasks.SyncLog") as MockLog, \
         patch("integrations.wa_votewa.tasks.MeasureOption") as MockMO, \
         patch("aggregation.ingest.ingest_race", return_value=(mock_race, True)) as mock_ir, \
         patch("integrations.wa_votewa.tasks.sync_wa_pdc_candidates", create=True):

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception
        MockElection.Status.UPCOMING = "upcoming"
        MockElection.Status.ACTIVE = "active"

        client = MockClient.return_value
        client.get_election_data.return_value = {
            "ballotItems": [_make_ballot_item("BallotMeasure", "Prop 1")]
        }

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log
        MockLog.Status.STARTED = "started"
        MockLog.Status.COMPLETED = "completed"
        MockLog.Status.FAILED = "failed"

        result = sync_wa_races(1, "20260428")

    mock_ir.assert_called_once()
    call_kwargs = mock_ir.call_args[1]
    assert call_kwargs["identity"]["race_type"] == "measure"
    assert result["races"]["created"] == 1


def test_sync_wa_races_candidate_item():
    """A Candidate ballot item → ingest_race + ingest_candidate called."""
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.source_id = "wa_votewa:20260428"
    mock_election.status = "results_pending"
    mock_election.source_metadata = {"enr_slug": "20260428"}

    mock_race = MagicMock()
    mock_cand = MagicMock()

    ballot_item = {
        "id": "bi-cand-001",
        "contestType": "Candidate",
        "name": [{"languageId": "en", "text": "State Senator"}],
        "summaryResults": {
            "ballotOptions": [
                {
                    "name": [{"languageId": "en", "text": "Alice Smith"}],
                    "nativeId": "opt-alice",
                    "isWriteIn": False,
                    "party": {"abbreviation": "D", "name": "Democratic"},
                }
            ]
        },
    }

    with patch("integrations.wa_votewa.tasks.Election") as MockElection, \
         patch("integrations.wa_votewa.tasks.WaVoteWaClient") as MockClient, \
         patch("integrations.wa_votewa.tasks.SyncLog") as MockLog, \
         patch("aggregation.ingest.ingest_race", return_value=(mock_race, True)), \
         patch("aggregation.ingest.ingest_candidate", return_value=(mock_cand, True)) as mock_ic, \
         patch("integrations.wa_votewa.tasks.sync_wa_pdc_candidates", create=True):

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception
        MockElection.Status.UPCOMING = "upcoming"
        MockElection.Status.ACTIVE = "active"

        client = MockClient.return_value
        client.get_election_data.return_value = {"ballotItems": [ballot_item]}

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log
        MockLog.Status.STARTED = "started"
        MockLog.Status.COMPLETED = "completed"
        MockLog.Status.FAILED = "failed"

        result = sync_wa_races(1, "20260428")

    mock_ic.assert_called_once()
    call_kwargs = mock_ic.call_args[1]
    assert call_kwargs["name"] == "Alice Smith"
    assert result["candidates"]["created"] == 1
```

- [ ] **Step 2: Run tests — confirm they fail**

Run: `cd /data/Projects/CivicMirror/CivicMirror-API/backend && python -m pytest --no-migrations integrations/wa_votewa/tests/test_tasks.py -v`  
Expected: `ImportError` — `tasks.py` doesn't exist yet.

- [ ] **Step 3: Create `tasks.py`**

Create `backend/integrations/wa_votewa/tasks.py`:

```python
"""
Washington VoteWA Celery tasks.

Stage 1 — sync_wa_elections:
  Seed known WA election slugs from KNOWN_ELECTION_SLUGS.
  Fetch metadata for each from the VoteWA public API.
  Upsert Election records (enr_slug in source_metadata); queue sync_wa_races.

Stage 2 — sync_wa_races:
  Fetch state-level ballotItems[] from VoteWA /data endpoint.
  Upsert Race + Candidate or Race + MeasureOption via aggregation ingest.
  Schedule sync_wa_pdc_candidates after race sync completes.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Election, MeasureOption
from ops.models import SyncLog

from .client import KNOWN_ELECTION_SLUGS, WaVoteWaClient
from .exceptions import WaVoteWaError, WaVoteWaRetryableError
from .mappers import _get_text, map_candidate, map_election, map_race

logger = logging.getLogger(__name__)
_SOURCE = "wa_votewa"


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_wa_elections(self):
    """Stage 1: Seed known Washington elections and queue race syncs."""
    sync_log = SyncLog.objects.create(
        source=_SOURCE,
        task_name="sync_wa_elections",
        status=SyncLog.Status.STARTED,
    )
    client = WaVoteWaClient()
    created_count = updated_count = queued_count = skipped_count = 0

    try:
        from aggregation import ingest

        election_objects: list[tuple[str, object]] = []

        for slug in KNOWN_ELECTION_SLUGS:
            try:
                meta = client.get_election_metadata(slug)
            except WaVoteWaError as exc:
                logger.warning("wa_votewa.sync_elections.meta_failed slug=%s: %s", slug, exc)
                skipped_count += 1
                continue

            mapped = map_election(slug, meta)
            if not mapped.get("election_date"):
                logger.warning("wa_votewa.sync_elections.no_date slug=%s", slug)
                skipped_count += 1
                continue

            source_id = mapped.pop("source_id")
            identity = {
                "state":              mapped["state"],
                "election_type":      mapped["election_type"],
                "election_date":      mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            fields = {k: v for k, v in mapped.items() if k not in identity}
            enr_slug_value = (fields.get("source_metadata") or {}).get("enr_slug", "")

            election_obj, was_created = ingest.ingest_election(
                source=_SOURCE,
                source_id=source_id,
                identity=identity,
                fields=fields,
            )
            if was_created:
                created_count += 1
            else:
                updated_count += 1

            if enr_slug_value:
                current_meta = dict(election_obj.source_metadata or {})
                if not current_meta.get("enr_slug"):
                    current_meta["enr_slug"] = enr_slug_value
                    election_obj.source_metadata = current_meta
                    election_obj.save(update_fields=["source_metadata"])

            election_objects.append((slug, election_obj))

        for idx, (slug, election_obj) in enumerate(election_objects):
            sync_wa_races.apply_async(
                args=[election_obj.pk, slug],
                countdown=idx * 5,
            )
            queued_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.records_skipped = skipped_count
        sync_log.notes = f"Queued {queued_count} race syncs; {skipped_count} slugs skipped"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "records_skipped",
            "notes", "status", "completed_at",
        ])
        return {
            "created": created_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "queued": queued_count,
        }

    except Exception as exc:
        logger.exception("wa_votewa.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_wa_races(self, election_pk: int, slug: str):
    """Stage 2: Fetch ballotItems and upsert Race + Candidate/MeasureOption."""
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("wa_votewa.sync_races.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source=_SOURCE,
        task_name="sync_wa_races",
        status=SyncLog.Status.STARTED,
    )
    client = WaVoteWaClient()
    race_created = race_updated = cand_created = cand_updated = 0

    try:
        data = client.get_election_data(slug)
        ballot_items = data.get("ballotItems") or []
        logger.info(
            "wa_votewa.sync_races election=%s ballot_items=%d",
            election_obj.source_id or election_obj.pk, len(ballot_items),
        )

        if not ballot_items:
            sync_log.notes = "No ballot items in /data response"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"races": 0, "candidates": 0}

        from aggregation import ingest

        for ballot_item in ballot_items:
            race_fields = map_race(election_obj, ballot_item, jurisdiction_slug="washington")
            # ingest sets source from contributing_sources precedence
            race_fields.pop("source", None)
            race_identity = {
                "office_title":    race_fields.pop("office_title"),
                "ocd_division_id": race_fields.pop("ocd_division_id", "") or "",
                "race_type":       race_fields.pop("race_type"),
            }
            if not race_identity["office_title"]:
                logger.warning(
                    "wa_votewa.sync_races.null_title election=%s item_id=%s",
                    election_obj.source_id or election_obj.pk, ballot_item.get("id"),
                )
                continue

            race_obj, race_was_new = ingest.ingest_race(
                election=election_obj,
                source=_SOURCE,
                identity=race_identity,
                fields=race_fields,
            )
            if race_was_new:
                race_created += 1
            else:
                race_updated += 1

            ballot_options = (ballot_item.get("summaryResults") or {}).get("ballotOptions") or []

            if race_identity["race_type"] == "candidate":
                seen_names: set[str] = set()
                for opt in ballot_options:
                    name = _get_text(opt.get("name") or [])
                    if not name or name in seen_names:
                        continue
                    seen_names.add(name)
                    cand_fields = map_candidate(opt)
                    party = cand_fields.pop("party", "")
                    _, cand_was_new = ingest.ingest_candidate(
                        race=race_obj,
                        source=_SOURCE,
                        name=name,
                        party=party,
                        fields=cand_fields,
                    )
                    if cand_was_new:
                        cand_created += 1
                    else:
                        cand_updated += 1

            elif race_identity["race_type"] == "measure":
                for opt in ballot_options:
                    label = _get_text(opt.get("name") or []) or opt.get("nativeId", "")
                    if not label:
                        continue
                    MeasureOption.objects.get_or_create(race=race_obj, option_label=label)

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        sync_log.records_created = race_created + cand_created
        sync_log.records_updated = race_updated + cand_updated
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "status", "completed_at"])

        # PDC enrichment runs after races exist
        try:
            from integrations.wa_pdc.tasks import sync_wa_pdc_candidates
            sync_wa_pdc_candidates.apply_async(args=[election_pk], countdown=10)
        except Exception:
            logger.warning(
                "wa_votewa.sync_races: could not schedule PDC enrichment for election %d",
                election_pk,
            )

        return {
            "races": {"created": race_created, "updated": race_updated},
            "candidates": {"created": cand_created, "updated": cand_updated},
        }

    except WaVoteWaRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception(
            "wa_votewa.sync_races.failed election=%s slug=%s",
            election_obj.source_id or election_obj.pk, slug,
        )
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

- [ ] **Step 4: Run tests — confirm they pass**

Run: `cd /data/Projects/CivicMirror/CivicMirror-API/backend && python -m pytest --no-migrations integrations/wa_votewa/tests/test_tasks.py -v`  
Expected: All tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/wa_votewa/tasks.py backend/integrations/wa_votewa/tests/test_tasks.py
git commit -m "feat(wa-votewa): add sync_wa_elections + sync_wa_races tasks with PDC trigger"
```

---

## Task 6: Enhanced WA Results Adapter (County Fan-out)

The current `wa.py` is a 4-line stub. Replace it with a full override that adds WA-specific version detection (`asOf` then `lastUpdated`), county fan-out via `localityElections[]`, and richer `ResultRow.raw` IDs.

**Files:**
- Modify: `backend/results/adapters/wa.py`
- Modify: `backend/results/tests/test_wa_adapter.py`

- [ ] **Step 1: Write new adapter tests**

Replace the contents of `backend/results/tests/test_wa_adapter.py` with:

```python
"""
Unit tests for the Washington results adapter.
HTTP calls are fully mocked — no network required.
"""
from unittest.mock import MagicMock, call, patch

import pytest

from results.adapters.base import AdapterResult
from results.adapters.wa import WashingtonAdapter


def test_wa_adapter_registered():
    import results.adapters.wa  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "WA" in list_supported_states()
    assert get_adapter("WA") is WashingtonAdapter
    assert get_adapter("wa") is WashingtonAdapter


def test_fetch_results_no_slug():
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "wa_votewa:test"
    mock_election.source_metadata = {}

    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results(None, election_id=99)

    assert isinstance(result, AdapterResult)
    assert result.mapping_confidence == "none"
    assert result.rows == []
    assert "enr_slug" in result.notes


def test_fetch_results_version_unchanged_uses_as_of():
    """If asOf matches cache, returns unchanged=True without fetching /data."""
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "20260428"}
    mock_election.pk = 2

    meta_payload = {
        "asOf": "2026-05-13T13:05:15.0369431Z",
        "lastUpdated": "2026-05-11T14:08:47Z",
        "isOfficialResults": True,
    }

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.wa.requests.get") as mock_get, \
         patch("results.adapters.wa.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = "2026-05-13T13:05:15.0369431Z"

        meta_resp = MagicMock()
        meta_resp.json.return_value = meta_payload
        mock_get.return_value = meta_resp

        result = adapter.fetch_results(None, election_id=2)

    assert result.unchanged is True
    assert result.source_version == "2026-05-13T13:05:15.0369431Z"
    assert result.rows == []
    assert mock_get.call_count == 1


def test_fetch_results_falls_back_to_last_updated_for_version():
    """When asOf is absent, version comes from lastUpdated."""
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "20260428"}
    mock_election.pk = 3

    meta_payload = {
        "lastUpdated": "2026-05-11T14:08:47Z",
        "isOfficialResults": False,
    }
    data_payload = {"jurisdiction": {}, "localityElections": [], "ballotItems": []}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.wa.requests.get") as mock_get, \
         patch("results.adapters.wa.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None

        meta_resp = MagicMock()
        meta_resp.json.return_value = meta_payload
        data_resp = MagicMock()
        data_resp.json.return_value = data_payload
        mock_get.side_effect = [meta_resp, data_resp]

        result = adapter.fetch_results(None, election_id=3)

    assert result.source_version == "2026-05-11T14:08:47Z"
    assert result.unchanged is False


def test_fetch_results_state_level_ballot_measure():
    """State-level BallotMeasure rows have jurisdiction_fragment='' and votewa raw IDs."""
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "20260428"}
    mock_election.pk = 2

    meta_payload = {"asOf": "2026-05-13T13:05:15Z", "isOfficialResults": True}
    data_payload = {
        "localityElections": [],
        "ballotItems": [
            {
                "id": "01000000-b872-6dac-8b23-08de95a613ed",
                "contestType": "BallotMeasure",
                "name": [{"languageId": "en", "text": "Rochester Fire District"}],
                "summaryResults": {
                    "ballotOptions": [
                        {
                            "name": [{"languageId": "en", "text": "Yes"}],
                            "nativeId": "yes-001",
                            "voteCount": 5000,
                            "votePercent": 60.0,
                            "isWinner": None,
                        }
                    ]
                },
            }
        ],
    }

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.wa.requests.get") as mock_get, \
         patch("results.adapters.wa.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None

        meta_resp = MagicMock()
        meta_resp.json.return_value = meta_payload
        data_resp = MagicMock()
        data_resp.json.return_value = data_payload
        mock_get.side_effect = [meta_resp, data_resp]

        result = adapter.fetch_results(None, election_id=2)

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.option_label == "Yes"
    assert row.vote_count == 5000
    assert row.jurisdiction_fragment == ""
    assert row.raw["votewa_ballot_item_id"] == "01000000-b872-6dac-8b23-08de95a613ed"
    assert row.raw["votewa_native_id"] == "yes-001"
    assert row.result_type == "official"


def test_fetch_results_county_fanout():
    """localityElections triggers a county data fetch; county rows have jurisdiction_fragment set."""
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "20260428"}
    mock_election.pk = 4

    meta_payload = {"asOf": "2026-05-13T13:05:15Z", "isOfficialResults": False}
    data_payload = {
        "localityElections": [
            {
                "jurisdiction": {"shortName": "mason-county-wa", "id": "some-guid"},
            }
        ],
        "ballotItems": [],
    }
    county_payload = {
        "ballotItems": [
            {
                "id": "county-item-001",
                "parentId": "state-agg-001",
                "contestType": "BallotMeasure",
                "name": [{"languageId": "en", "text": "Mason County Fire Levy"}],
                "summaryResults": {
                    "ballotOptions": [
                        {
                            "name": [{"languageId": "en", "text": "Yes"}],
                            "nativeId": "yes-c",
                            "voteCount": 1200,
                            "votePercent": 55.0,
                        }
                    ]
                },
            }
        ]
    }

    meta_resp = MagicMock()
    meta_resp.json.return_value = meta_payload
    data_resp = MagicMock()
    data_resp.json.return_value = data_payload
    county_resp = MagicMock()
    county_resp.json.return_value = county_payload

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.wa.requests.get") as mock_get, \
         patch("results.adapters.wa.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None
        mock_get.side_effect = [meta_resp, data_resp, county_resp]

        result = adapter.fetch_results(None, election_id=4)

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.jurisdiction_fragment == "mason-county-wa"
    assert row.raw["votewa_ballot_item_id"] == "county-item-001"
    assert row.raw["votewa_parent_ballot_item_id"] == "state-agg-001"
    assert row.vote_count == 1200
    assert mock_get.call_count == 3


def test_fetch_results_county_error_does_not_abort():
    """A failed county fetch is logged and skipped; state rows still returned."""
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "20260428"}
    mock_election.pk = 5

    meta_payload = {"asOf": "v1", "isOfficialResults": True}
    data_payload = {
        "localityElections": [
            {"jurisdiction": {"shortName": "broken-county-wa"}}
        ],
        "ballotItems": [
            {
                "id": "state-item-001",
                "contestType": "BallotMeasure",
                "name": [{"languageId": "en", "text": "Statewide Prop"}],
                "summaryResults": {
                    "ballotOptions": [
                        {"name": [{"languageId": "en", "text": "Yes"}], "nativeId": "s-yes",
                         "voteCount": 900, "votePercent": 50.0}
                    ]
                },
            }
        ],
    }

    meta_resp = MagicMock()
    meta_resp.json.return_value = meta_payload
    data_resp = MagicMock()
    data_resp.json.return_value = data_payload

    import requests as req_lib
    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.wa.requests.get") as mock_get, \
         patch("results.adapters.wa.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None
        mock_get.side_effect = [meta_resp, data_resp, req_lib.ConnectionError("refused")]

        result = adapter.fetch_results(None, election_id=5)

    assert len(result.rows) == 1
    assert result.rows[0].jurisdiction_fragment == ""


def test_voter_portal_endpoints_never_called():
    """The adapter must not call voter.votewa.gov endpoints."""
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "20260428"}
    mock_election.pk = 6

    meta_payload = {"asOf": "v1", "isOfficialResults": True}
    data_payload = {"localityElections": [], "ballotItems": []}

    meta_resp = MagicMock()
    meta_resp.json.return_value = meta_payload
    data_resp = MagicMock()
    data_resp.json.return_value = data_payload

    called_urls: list[str] = []

    def capture_get(url, **kwargs):
        called_urls.append(url)
        resp = MagicMock()
        resp.json.return_value = meta_payload if "data" not in url else data_payload
        return resp

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.wa.requests.get", side_effect=capture_get), \
         patch("results.adapters.wa.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None
        adapter.fetch_results(None, election_id=6)

    for url in called_urls:
        assert "voter.votewa.gov" not in url, f"Voter portal URL was called: {url}"
```

- [ ] **Step 2: Run new tests against old adapter — confirm failures**

Run: `cd /data/Projects/CivicMirror/CivicMirror-API/backend && python -m pytest --no-migrations results/tests/test_wa_adapter.py -v`  
Expected: Several `FAILED` — version-detect, county fan-out, and raw ID tests will all fail.

- [ ] **Step 3: Replace `wa.py` with the full enhanced adapter**

Replace the entire contents of `backend/results/adapters/wa.py`:

```python
"""
Washington results adapter using the VoteWA public results API.

Extends EnhancedVotingAdapter with:
  - WA-specific version detection: prefers asOf, falls back to lastUpdated
  - County fan-out via localityElections[]; each county slug triggers a
    county /data fetch, and county ResultRows get jurisdiction_fragment=county_slug
  - Full raw ID preservation: votewa_ballot_item_id, votewa_parent_ballot_item_id,
    votewa_native_id, votewa_jurisdiction_slug
"""
from __future__ import annotations

import logging

import requests
from django.core.cache import cache

from .base import AdapterResult, ResultRow
from .enhanced_voting import EnhancedVotingAdapter, _get_text, _safe_float, _safe_int
from .registry import register

logger = logging.getLogger(__name__)

_WA_API_BASE = "https://results.votewa.gov/results/public/api"
_FETCH_TIMEOUT_META = 15
_FETCH_TIMEOUT_DATA = 60


@register
class WashingtonAdapter(EnhancedVotingAdapter):
    state = "WA"
    state_name = "washington"
    base_url = _WA_API_BASE

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("WAAdapter: election %s not found", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election {election_id} not found",
            )

        slug = (election.source_metadata or {}).get("enr_slug")
        if not slug:
            logger.warning("WAAdapter: no enr_slug for election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes="No ENR slug in election.source_metadata — populate enr_slug to enable results",
            )

        meta_url = f"{_WA_API_BASE}/elections/washington/{slug}"
        try:
            meta_resp = requests.get(meta_url, timeout=_FETCH_TIMEOUT_META)
            meta_resp.raise_for_status()
            meta = meta_resp.json()
        except requests.RequestException as exc:
            logger.error("WAAdapter: meta fetch failed slug=%s: %s", slug, exc)
            return AdapterResult(
                rows=[], source_url=meta_url, mapping_confidence="none",
                notes=f"Meta fetch failed: {exc}",
            )

        # Prefer asOf; fall back to lastUpdated
        as_of = meta.get("asOf") or meta.get("lastUpdated") or ""
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == as_of and as_of:
            logger.debug("WAAdapter: version unchanged slug=%s as_of=%s", slug, as_of)
            return AdapterResult(
                rows=[], source_url=meta_url, mapping_confidence="full",
                unchanged=True, source_version=as_of,
            )

        data_url = f"{_WA_API_BASE}/elections/washington/{slug}/data"
        try:
            data_resp = requests.get(data_url, timeout=_FETCH_TIMEOUT_DATA)
            data_resp.raise_for_status()
            data = data_resp.json()
        except requests.RequestException as exc:
            logger.error("WAAdapter: data fetch failed slug=%s: %s", slug, exc)
            return AdapterResult(
                rows=[], source_url=data_url, mapping_confidence="none",
                notes=f"Data fetch failed: {exc}",
            )

        is_official = meta.get("isOfficialResults", False)
        result_type = "official" if is_official else "unofficial"

        rows: list[ResultRow] = []

        # State-level rows (jurisdiction_fragment is empty string)
        rows.extend(
            _parse_ballot_items(data.get("ballotItems", []), result_type, jurisdiction_fragment="")
        )

        # County fan-out: one /data call per participating county
        for locality_election in (data.get("localityElections") or []):
            county_slug = _county_slug(locality_election)
            if not county_slug:
                continue
            county_url = f"{_WA_API_BASE}/elections/{county_slug}/{slug}/data"
            try:
                county_resp = requests.get(county_url, timeout=_FETCH_TIMEOUT_DATA)
                county_resp.raise_for_status()
                county_data = county_resp.json()
            except requests.RequestException as exc:
                logger.warning(
                    "WAAdapter: county fetch failed county=%s slug=%s: %s",
                    county_slug, slug, exc,
                )
                continue
            rows.extend(
                _parse_ballot_items(
                    county_data.get("ballotItems", []),
                    result_type,
                    jurisdiction_fragment=county_slug,
                )
            )

        logger.info(
            "WAAdapter: slug=%s rows=%d official=%s counties=%d",
            slug, len(rows), is_official, len(data.get("localityElections") or []),
        )

        return AdapterResult(
            rows=rows,
            source_url=data_url,
            mapping_confidence="full",
            source_version=as_of,
        )


def _county_slug(locality_election: dict) -> str | None:
    """Extract county jurisdiction slug from a localityElections[] entry."""
    jurisdiction = locality_election.get("jurisdiction") or {}
    slug = jurisdiction.get("shortName") or ""
    return slug or None


def _parse_ballot_items(
    ballot_items: list,
    result_type: str,
    jurisdiction_fragment: str,
) -> list[ResultRow]:
    """
    Parse VoteWA ballotItems[] into ResultRow list.

    Differs from the generic EnhancedVotingAdapter parser in that it:
      - Sets jurisdiction_fragment on each row
      - Preserves votewa_ballot_item_id, votewa_parent_ballot_item_id, votewa_native_id
        and votewa_jurisdiction_slug in ResultRow.raw
    """
    rows: list[ResultRow] = []
    for item in ballot_items:
        contest_type = item.get("contestType", "")
        office_title = _get_text(item.get("name", []))
        ballot_item_id = item.get("id")
        parent_id = item.get("parentId") or item.get("parentBallotItemId")
        ballot_options = (item.get("summaryResults") or {}).get("ballotOptions", [])

        for opt in ballot_options:
            opt_name = _get_text(opt.get("name", []))
            vote_count = _safe_int(opt.get("voteCount"))
            vote_pct = _safe_float(opt.get("votePercent"))
            is_winner = opt.get("isWinner")
            is_write_in = bool(opt.get("isWriteIn", False))
            native_id = opt.get("nativeId")

            base_raw = {
                "votewa_ballot_item_id": ballot_item_id,
                "votewa_parent_ballot_item_id": parent_id,
                "votewa_native_id": native_id,
                "votewa_jurisdiction_slug": jurisdiction_fragment or "washington",
                "contest_type": contest_type,
            }

            if contest_type == "BallotMeasure":
                rows.append(ResultRow(
                    candidate_name=None,
                    option_label=opt_name or None,
                    vote_count=vote_count,
                    vote_pct=vote_pct,
                    is_winner=None,
                    result_type=result_type,
                    office_title=office_title or None,
                    jurisdiction_fragment=jurisdiction_fragment,
                    raw=base_raw,
                ))
            else:
                party_abbr = (opt.get("party") or {}).get("abbreviation", "")
                rows.append(ResultRow(
                    candidate_name=opt_name or None,
                    option_label=None,
                    vote_count=vote_count,
                    vote_pct=vote_pct,
                    is_winner=bool(is_winner) if is_winner is not None else None,
                    result_type=result_type,
                    office_title=office_title or None,
                    is_write_in_aggregate=is_write_in,
                    jurisdiction_fragment=jurisdiction_fragment,
                    raw={**base_raw, "party": party_abbr},
                ))
    return rows
```

- [ ] **Step 4: Run all adapter tests — confirm they pass**

Run: `cd /data/Projects/CivicMirror/CivicMirror-API/backend && python -m pytest --no-migrations results/tests/test_wa_adapter.py -v`  
Expected: All tests `PASSED`.

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `cd /data/Projects/CivicMirror/CivicMirror-API/backend && python -m pytest --no-migrations -q`  
Expected: All existing tests continue to pass.

- [ ] **Step 6: Commit**

```bash
git add backend/results/adapters/wa.py backend/results/tests/test_wa_adapter.py
git commit -m "feat(wa): upgrade WA adapter with county fan-out, WA version detection, full raw IDs"
```

---

## Task 7: Run Full Suite + Final Commit

- [ ] **Step 1: Run all wa_votewa and wa adapter tests together**

Run: `cd /data/Projects/CivicMirror/CivicMirror-API/backend && python -m pytest --no-migrations integrations/wa_votewa/ results/tests/test_wa_adapter.py -v`  
Expected: All tests `PASSED`.

- [ ] **Step 2: Run full test suite**

Run: `cd /data/Projects/CivicMirror/CivicMirror-API/backend && python -m pytest --no-migrations -q`  
Expected: No regressions. All existing tests continue to pass.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat(wa-votewa): complete Washington VoteWA integration (ADR-009)"
```

---

## Self-Review Checklist

**Spec coverage (ADR-009 § Implementation Plan):**

| ADR step | Covered in |
|---|---|
| 1. `wa_votewa/` client for SOS discovery + VoteWA API | Task 3 |
| 2. Election seeding with `enr_slug` + `votewa_jurisdiction_slug` | Tasks 4 & 5 |
| 3. Race + option/candidate mapping from `ballotItems[]` | Tasks 4 & 5 |
| 4. Tests using fixtures derived from HAR data | Tasks 3, 4, 5, 6 |
| 5. WA adapter: version detect, county fan-out, raw IDs | Task 6 |
| 6. Schedule PDC enrichment after races exist | Task 5 |
| 7. Candidate contest HAR caveat documented (synthetic tests) | Tasks 4 & 5 |
| 8. `mediaExportPath` CDN validation | Deferred (ADR says "after basic API path works") |

**ADR constraints honoured:**
- voter.votewa.gov endpoints: explicitly tested to never be called (Task 6, last test).
- county fan-out: county errors are caught and logged — one bad county doesn't abort the sync.
- `parentBallotItemId` stored in both raw (adapter) and `source_metadata` (mapper).
- GUID join keys are treated as case-insensitive strings in raw storage (no normalization needed; stored as-is from API).

**No placeholders detected.**

**Type consistency verified:** `_get_text`, `_safe_int`, `_safe_float` imported from `enhanced_voting` in `wa.py`; the same helpers are re-implemented locally in `mappers.py` (isolated from adapter layer by design — mappers don't depend on adapter internals).
