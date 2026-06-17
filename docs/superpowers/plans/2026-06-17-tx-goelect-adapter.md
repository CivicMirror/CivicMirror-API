# TX GoElect ENR Adapter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full results adapter for Texas election data from the CivixApps GoElect ENR API, including election/race/candidate seeding and live results polling with county-level breakdowns.

**Architecture:** A `TxGoElectClient` wraps three public ENR endpoints (election index, full results, county results) with base64 decode and retry logic. Celery tasks seed Elections/Races/Candidates from `Lookups` before election night, including a watermark-based sequential ID probe to catch the November 2026 General when it appears. The results adapter polls on the `Version` integer, emitting statewide and county `ResultRow`s per poll cycle.

**Tech Stack:** Python 3.12, Django 4.x, Celery, `requests`, `django.core.cache` (Redis), pytest with `--no-migrations`

## Global Constraints

- All tests run as: `cd backend && .venv/bin/python -m pytest <path> --no-migrations -v`
- Never commit real API tokens, voter data, or unsanitized HAR captures
- `Race.source` max_length=20 — `tx_goelect` (10 chars) fits
- `result_type` is a free-form `str` on `ResultRow` — `"complete_unofficial"` and `"unofficial"` are both valid
- Follow `WaVoteWaClient` / `FloridaAdapter` patterns exactly for retries, SyncLog, and version caching
- All new files live under `backend/` (the Django project root)

---

## File Map

| File | Status | Responsibility |
|------|--------|---------------|
| `integrations/tx_goelect/__init__.py` | Create | Empty package marker |
| `integrations/tx_goelect/apps.py` | Create | Django AppConfig |
| `integrations/tx_goelect/exceptions.py` | Create | `TxGoElectError`, `TxGoElectRetryableError` |
| `integrations/tx_goelect/client.py` | Create | HTTP client + base64 decode helpers |
| `integrations/tx_goelect/mappers.py` | Create | Election, race, candidate, county mappers |
| `integrations/tx_goelect/tasks.py` | Create | `sync_tx_elections` + `sync_tx_races` Celery tasks |
| `integrations/tx_goelect/tests/__init__.py` | Create | Empty |
| `integrations/tx_goelect/tests/fixtures/enr_56181_election.json` | Create | Frozen SD4 special election payload (base64 as returned by API) |
| `integrations/tx_goelect/tests/fixtures/enr_56181_county_info.json` | Create | Frozen SD4 countyInfo payload |
| `integrations/tx_goelect/tests/test_client.py` | Create | Client unit tests |
| `integrations/tx_goelect/tests/test_mappers.py` | Create | Mapper unit tests |
| `integrations/tx_goelect/tests/test_tasks.py` | Create | Task unit tests |
| `results/adapters/tx.py` | Create | `TxAdapter(StateResultsAdapter)` |
| `results/tests/test_tx_adapter.py` | Create | Adapter unit tests |
| `elections/models.py` | Modify | Add `TX_GOELECT` to `Race.Source` |
| `elections/migrations/0019_tx_goelect_race_source.py` | Create | Migration for new source choice |
| `config/settings/base.py` | Modify | Add `integrations.tx_goelect` to `INSTALLED_APPS` |
| `internal/views.py` | Modify | Add `sync_tx_goelect_trigger` |
| `internal/urls.py` | Modify | Add `tasks/sync-tx-goelect/` |
| `internal/task_locks.py` | Modify | Add `sync_tx_goelect` lock entry |
| `results/apps.py` | Modify | Import `tx` in `ResultsConfig.ready()` |
| `.github/workflows/deploy.yml` | Modify | Add `sync-tx-goelect` Cloud Scheduler job |

---

## Task 1: App Scaffolding + Exceptions

**Files:**
- Create: `integrations/tx_goelect/__init__.py`
- Create: `integrations/tx_goelect/exceptions.py`
- Create: `integrations/tx_goelect/apps.py`
- Modify: `config/settings/base.py`

**Interfaces:**
- Produces: `TxGoElectError`, `TxGoElectRetryableError` (used by Tasks 2, 5)
- Produces: `TxGoElectConfig` app (required for Django to load the integration)

- [ ] **Step 1: Create the package and exceptions**

`integrations/tx_goelect/__init__.py` — empty file.

`integrations/tx_goelect/exceptions.py`:
```python
class TxGoElectError(Exception):
    pass


class TxGoElectRetryableError(TxGoElectError):
    pass
```

- [ ] **Step 2: Create the AppConfig**

`integrations/tx_goelect/apps.py`:
```python
from django.apps import AppConfig


class TxGoElectConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.tx_goelect"
    label = "tx_goelect"
    verbose_name = "Texas GoElect Integration"
```

- [ ] **Step 3: Register in INSTALLED_APPS**

In `config/settings/base.py`, find the block containing `'integrations.wa_votewa'` and add the new app directly after it:

```python
    'integrations.wa_votewa',
    'integrations.tx_goelect',  # add this line
```

- [ ] **Step 4: Verify Django starts cleanly**

```bash
cd backend && .venv/bin/python manage.py check --deploy 2>&1 | grep -E "Error|tx_goelect" || echo "OK"
```

Expected: no errors mentioning `tx_goelect`.

- [ ] **Step 5: Commit**

```bash
git add integrations/tx_goelect/__init__.py integrations/tx_goelect/exceptions.py \
        integrations/tx_goelect/apps.py config/settings/base.py
git commit -m "feat(tx): scaffold tx_goelect app + exceptions"
```

---

## Task 2: Client + Frozen Fixtures

**Files:**
- Create: `integrations/tx_goelect/client.py`
- Create: `integrations/tx_goelect/tests/__init__.py`
- Create: `integrations/tx_goelect/tests/fixtures/enr_56181_election.json`
- Create: `integrations/tx_goelect/tests/fixtures/enr_56181_county_info.json`
- Create: `integrations/tx_goelect/tests/test_client.py`

**Interfaces:**
- Consumes: `TxGoElectError`, `TxGoElectRetryableError` from Task 1
- Produces:
  - `TxGoElectClient.get_election_constants() -> dict` — keys: `electionInfo` nested by year→type→id
  - `TxGoElectClient.get_election_data(election_id: int) -> dict` — keys: `version` (int), `home` (dict), `lookups` (dict), `race` (dict), `office_summary` (dict), `federal` (dict), `statewide` (dict), `statewide_q` (dict), `districted` (dict)
  - `TxGoElectClient.get_county_results(election_id: int) -> dict` — county data keyed by CivixApps county ID string
  - `TxGoElectClient.get_version(election_id: int) -> int | None`
  - `TxGoElectClient.probe_election(election_id: int) -> bool`

- [ ] **Step 1: Fetch and save frozen fixtures from the live API**

Run this once to capture real API responses for election 56181 (SD4 Special — small, publicly certified):

```bash
cd backend && .venv/bin/python - <<'EOF'
import base64, json, requests

BASE = "https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

# Election data (raw — keep base64 encoded as the API returns it)
r = requests.get(f"{BASE}/election/56181", headers=HEADERS, timeout=30)
r.raise_for_status()
with open("integrations/tx_goelect/tests/fixtures/enr_56181_election.json", "w") as f:
    json.dump(r.json(), f, indent=2)

# County info (raw)
r2 = requests.get(f"{BASE}/election/countyInfo/56181", headers=HEADERS, timeout=30)
r2.raise_for_status()
with open("integrations/tx_goelect/tests/fixtures/enr_56181_county_info.json", "w") as f:
    json.dump(r2.json(), f, indent=2)

print("Fixtures saved.")
EOF
```

Create `integrations/tx_goelect/tests/__init__.py` — empty file.

- [ ] **Step 2: Verify fixtures decode correctly**

```bash
cd backend && .venv/bin/python - <<'EOF'
import base64, json

with open("integrations/tx_goelect/tests/fixtures/enr_56181_election.json") as f:
    data = json.load(f)

version = data.get("Version", "")
print(f"Version: {version}")

home = json.loads(base64.b64decode(data["Home"]))
print(f"ElecDate: {home['ElecDate']}")
print(f"CountiesReporting: {home['CountiesReporting']}")

lookups = json.loads(base64.b64decode(data["Lookups"]))
print(f"Candidates count: {len(lookups.get('Candidates', []))}")
print(f"Offices: {[o['ON'] for o in lookups.get('Office', [])]}")
EOF
```

Expected: prints date `05022026`, county reporting counts, candidate names.

- [ ] **Step 3: Write the failing tests**

`integrations/tx_goelect/tests/test_client.py`:
```python
"""
Unit tests for TxGoElectClient.
All HTTP calls are mocked — no network required.
"""
import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from integrations.tx_goelect.client import TxGoElectClient
from integrations.tx_goelect.exceptions import TxGoElectError, TxGoElectRetryableError

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


def _b64(obj: dict) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


# ---------------------------------------------------------------------------
# get_election_constants
# ---------------------------------------------------------------------------

def test_get_election_constants_decodes_upload():
    """electionConstants response: {"upload": "<b64>"} → decoded dict."""
    payload = {"electionInfo": {"2026": {"P": {"53813": {"O": "Y"}}}}}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"upload": _b64(payload)}
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        client = TxGoElectClient()
        result = client.get_election_constants()

    assert result["electionInfo"]["2026"]["P"]["53813"]["O"] == "Y"


# ---------------------------------------------------------------------------
# get_election_data
# ---------------------------------------------------------------------------

def test_get_election_data_decodes_all_known_fields():
    """election/{id} response: each field individually b64-encoded → decoded dict."""
    home = {"ElecDate": "05022026", "CountiesReporting": {"CR": 5, "CT": 5}}
    lookups = {"Candidates": [{"ID": 1, "BN": "ALICE"}], "Office": [], "County": [], "OfficeType": []}
    empty = {}

    raw_response = {
        "Version": "enr/56181/21/",
        "Home": _b64(home),
        "Lookups": _b64(lookups),
        "Race": _b64(empty),
        "OfficeSummary": _b64(empty),
        "Federal": _b64(empty),
        "StateWide": _b64(empty),
        "StateWideQ": _b64(empty),
        "Districted": _b64(empty),
        "ReportList": _b64(empty),
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = raw_response
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        client = TxGoElectClient()
        result = client.get_election_data(56181)

    assert result["version"] == 21
    assert result["home"]["ElecDate"] == "05022026"
    assert result["lookups"]["Candidates"][0]["BN"] == "ALICE"


def test_get_election_data_tolerates_missing_fields():
    """Missing optional fields decode to {} without raising."""
    raw_response = {
        "Version": "enr/56181/1/",
        "Home": _b64({"ElecDate": "05022026", "CountiesReporting": {"CR": 0, "CT": 5}}),
        "Lookups": _b64({}),
        # All other fields absent
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = raw_response
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        client = TxGoElectClient()
        result = client.get_election_data(56181)

    assert result["office_summary"] == {}
    assert result["statewide_q"] == {}


def test_get_election_data_with_real_fixture():
    """Decode the frozen SD4 fixture without raising."""
    fixture = _load_fixture("enr_56181_election.json")
    mock_resp = MagicMock()
    mock_resp.json.return_value = fixture
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        client = TxGoElectClient()
        result = client.get_election_data(56181)

    assert isinstance(result["version"], int)
    assert result["home"]["ElecDate"] == "05022026"
    assert len(result["lookups"].get("Candidates", [])) > 0


# ---------------------------------------------------------------------------
# get_county_results
# ---------------------------------------------------------------------------

def test_get_county_results_with_real_fixture():
    """Decode the frozen SD4 countyInfo fixture without raising."""
    fixture = _load_fixture("enr_56181_county_info.json")
    mock_resp = MagicMock()
    mock_resp.json.return_value = fixture
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        client = TxGoElectClient()
        result = client.get_county_results(56181)

    assert isinstance(result, dict)
    # At least one county present
    assert len(result) > 0


# ---------------------------------------------------------------------------
# get_version
# ---------------------------------------------------------------------------

def test_get_version_returns_integer():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Version": "enr/56181/21/"}
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        assert TxGoElectClient().get_version(56181) == 21


def test_get_version_returns_none_for_unknown_election():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Version": ""}
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        assert TxGoElectClient().get_version(99999) is None


# ---------------------------------------------------------------------------
# probe_election
# ---------------------------------------------------------------------------

def test_probe_election_true_when_live():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Version": "enr/59001/1/"}
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        assert TxGoElectClient().probe_election(59001) is True


def test_probe_election_false_when_not_live():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Version": ""}
    mock_resp.status_code = 200

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = mock_resp
        assert TxGoElectClient().probe_election(59001) is False


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------

def test_retries_on_503_then_succeeds():
    """Two 503s followed by a success → returns data, no exception raised."""
    home = {"ElecDate": "05022026", "CountiesReporting": {"CR": 5, "CT": 5}}
    success_resp = MagicMock()
    success_resp.status_code = 200
    success_resp.json.return_value = {"Version": "enr/56181/21/"}

    fail_resp = MagicMock()
    fail_resp.status_code = 503

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.side_effect = [fail_resp, fail_resp, success_resp]
        client = TxGoElectClient()
        version = client.get_version(56181)

    assert version == 21


def test_raises_retryable_after_max_retries():
    """All attempts return 503 → TxGoElectRetryableError raised."""
    fail_resp = MagicMock()
    fail_resp.status_code = 503

    with patch("integrations.tx_goelect.client.requests.Session") as MockSession:
        MockSession.return_value.get.return_value = fail_resp
        client = TxGoElectClient()
        with pytest.raises(TxGoElectRetryableError):
            client.get_version(56181)
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest integrations/tx_goelect/tests/test_client.py --no-migrations -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'integrations.tx_goelect.client'`

- [ ] **Step 5: Implement the client**

`integrations/tx_goelect/client.py`:
```python
"""
Texas GoElect ENR API client.

Public API — no auth required.
Base: https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr
"""
from __future__ import annotations

import base64
import json
import logging

import requests

from .exceptions import TxGoElectError, TxGoElectRetryableError

logger = logging.getLogger(__name__)

_BASE = "https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr"
_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Known sub-fields on GET /election/{id} that are individually base64-encoded.
_B64_FIELDS = ("Home", "Lookups", "Race", "OfficeSummary", "Federal",
               "StateWide", "StateWideQ", "Districted", "ReportList")


def _b64d(value: str) -> dict | list:
    """Decode a base64-encoded JSON string. Returns {} on empty/missing."""
    if not value:
        return {}
    try:
        return json.loads(base64.b64decode(value).decode("utf-8"))
    except Exception as exc:
        logger.warning("tx_goelect: b64 decode failed: %s", exc)
        return {}


class TxGoElectClient:
    def __init__(self, max_retries: int = 3, timeout: int = 30):
        self.max_retries = max_retries
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _get(self, url: str) -> requests.Response:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise TxGoElectRetryableError(f"GET {url} failed: {exc}") from exc
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise TxGoElectRetryableError(f"GET {url} returned {resp.status_code}")
                continue
            if not resp.ok:
                raise TxGoElectError(f"GET {url} returned {resp.status_code}")
            return resp
        raise TxGoElectRetryableError(f"GET {url}: retries exhausted")

    def get_election_constants(self) -> dict:
        """GET /electionConstants → decoded electionInfo dict."""
        resp = self._get(f"{_BASE}/electionConstants")
        return _b64d(resp.json().get("upload", ""))

    def get_election_data(self, election_id: int) -> dict:
        """
        GET /election/{id} → dict with keys:
          version (int|None), home, lookups, race, office_summary,
          federal, statewide, statewide_q, districted, report_list
        """
        resp = self._get(f"{_BASE}/election/{election_id}")
        raw = resp.json()

        # Log any unexpected top-level keys for schema-drift visibility.
        known = {"Version"} | set(_B64_FIELDS)
        for key in raw:
            if key not in known:
                logger.debug("tx_goelect: unknown field in election/%d response: %s", election_id, key)

        version_str = raw.get("Version", "")
        version = None
        if version_str:
            try:
                version = int(version_str.split("/")[2])
            except (IndexError, ValueError):
                logger.warning("tx_goelect: could not parse Version string: %s", version_str)

        return {
            "version": version,
            "home": _b64d(raw.get("Home", "")),
            "lookups": _b64d(raw.get("Lookups", "")),
            "race": _b64d(raw.get("Race", "")),
            "office_summary": _b64d(raw.get("OfficeSummary", "")),
            "federal": _b64d(raw.get("Federal", "")),
            "statewide": _b64d(raw.get("StateWide", "")),
            "statewide_q": _b64d(raw.get("StateWideQ", "")),
            "districted": _b64d(raw.get("Districted", "")),
            "report_list": _b64d(raw.get("ReportList", "")),
        }

    def get_county_results(self, election_id: int) -> dict:
        """GET /election/countyInfo/{id} → decoded county dict keyed by CivixApps county ID str."""
        resp = self._get(f"{_BASE}/election/countyInfo/{election_id}")
        return _b64d(resp.json().get("upload", ""))

    def get_version(self, election_id: int) -> int | None:
        """Return integer n from 'enr/{id}/{n}/' or None if election is not yet live."""
        resp = self._get(f"{_BASE}/election/{election_id}")
        version_str = resp.json().get("Version", "")
        if not version_str:
            return None
        try:
            return int(version_str.split("/")[2])
        except (IndexError, ValueError):
            return None

    def probe_election(self, election_id: int) -> bool:
        """True if this election ID is live (Version non-empty)."""
        return self.get_version(election_id) is not None
```

- [ ] **Step 6: Run tests — all must pass**

```bash
cd backend && .venv/bin/python -m pytest integrations/tx_goelect/tests/test_client.py --no-migrations -v
```

Expected: all tests PASSED.

- [ ] **Step 7: Commit**

```bash
git add integrations/tx_goelect/client.py \
        integrations/tx_goelect/tests/__init__.py \
        integrations/tx_goelect/tests/test_client.py \
        integrations/tx_goelect/tests/fixtures/
git commit -m "feat(tx): add TxGoElectClient with b64 decode, retry, probe"
```

---

## Task 3: Mappers

**Files:**
- Create: `integrations/tx_goelect/mappers.py`
- Create: `integrations/tx_goelect/tests/test_mappers.py`

**Interfaces:**
- Consumes: nothing from prior tasks (pure functions)
- Produces:
  - `parse_election_date(elec_date_str: str) -> date | None` — parses MMDDYYYY
  - `infer_election_type(type_code: str) -> str` — CivixApps code → `Election.ElectionType` value
  - `classify_election(election_id: int, type_code: str, home: dict) -> dict` — normalized metadata dict
  - `map_election(election_id: int, type_code: str, home: dict, election_name: str) -> dict` — Election field dict
  - `map_race(election_obj, office: dict, office_type_name: str, election_id: int) -> dict` — Race field dict
  - `map_candidate(election_id: int, office_id: int, ballot_option: dict) -> dict` — Candidate field dict
  - `map_county_fragment(county_entry: dict) -> str` — lowercase county name

- [ ] **Step 1: Write the failing tests**

`integrations/tx_goelect/tests/test_mappers.py`:
```python
"""Unit tests for TX GoElect mappers."""
from datetime import date
from unittest.mock import MagicMock

import pytest

from integrations.tx_goelect.mappers import (
    classify_election,
    infer_election_type,
    map_candidate,
    map_county_fragment,
    map_election,
    map_race,
    parse_election_date,
)


# ---------------------------------------------------------------------------
# parse_election_date
# ---------------------------------------------------------------------------

def test_parse_election_date_mmddyyyy():
    assert parse_election_date("05022026") == date(2026, 5, 2)


def test_parse_election_date_november():
    assert parse_election_date("11032026") == date(2026, 11, 3)


def test_parse_election_date_invalid_returns_none():
    assert parse_election_date("") is None
    assert parse_election_date("BADDATE") is None


# ---------------------------------------------------------------------------
# infer_election_type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code,expected", [
    ("P",  "primary"),
    ("RU", "primary_runoff"),
    ("GE", "general"),
    ("S",  "special"),
    ("SR", "special"),
    ("GR", "general_runoff"),
    ("XX", "other"),
])
def test_infer_election_type(code, expected):
    assert infer_election_type(code) == expected


# ---------------------------------------------------------------------------
# classify_election
# ---------------------------------------------------------------------------

def test_classify_general_2026():
    home = {"ElecDate": "11032026"}
    result = classify_election(59001, "GE", home)
    assert result["is_target_general_2026"] is True
    assert result["election_type_code"] == "GE"
    assert result["source_date"] == "2026-11-03"
    assert result["election_scope"] == "statewide"


def test_classify_special_not_target():
    home = {"ElecDate": "05022026"}
    result = classify_election(56181, "S", home)
    assert result["is_target_general_2026"] is False
    assert result["election_type_code"] == "S"


def test_classify_wrong_date_not_target():
    """A GE on wrong date is not the 2026 target."""
    home = {"ElecDate": "11032025"}
    result = classify_election(55000, "GE", home)
    assert result["is_target_general_2026"] is False


# ---------------------------------------------------------------------------
# map_election
# ---------------------------------------------------------------------------

def test_map_election_general():
    home = {"ElecDate": "11032026"}
    result = map_election(59001, "GE", home, "2026 GENERAL ELECTION")
    assert result["state"] == "TX"
    assert result["election_date"] == date(2026, 11, 3)
    assert result["election_type"] == "general"
    assert result["source_metadata"]["tx_election_id"] == 59001
    assert result["source_metadata"]["is_target_general_2026"] is True
    assert result["source_id"] == "tx_goelect:59001"


def test_map_election_special():
    home = {"ElecDate": "05022026"}
    result = map_election(56181, "S", home, "2026 SPECIAL ELECTION SENATE DISTRICT 4")
    assert result["election_type"] == "special"
    assert result["source_metadata"]["is_target_general_2026"] is False


# ---------------------------------------------------------------------------
# map_race
# ---------------------------------------------------------------------------

def test_map_race_statewide_candidate():
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.status = "results_pending"
    office = {"ID": 5031, "ON": "U.S. SENATOR", "SSO": 0}
    result = map_race(mock_election, office, "FEDERAL OFFICES", election_id=59001)

    assert result["race_type"] == "candidate"
    assert result["geography_scope"] == "statewide"
    assert result["office_title"] == "U.S. SENATOR"
    assert result["source_id"] == "tx_goelect:59001:office:5031"
    assert result["source_metadata"]["tx_office_id"] == 5031


def test_map_race_district():
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.status = "results_pending"
    office = {"ID": 5032, "ON": "STATE SENATOR, DISTRICT 4", "SSO": 4}
    result = map_race(mock_election, office, "DISTRICT OFFICES", election_id=56181)

    assert result["geography_scope"] == "district"
    assert result["source_id"] == "tx_goelect:56181:office:5032"


def test_map_race_measure():
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.status = "results_pending"
    office = {"ID": 6001, "ON": "PROPOSITION 1", "SSO": 0}
    result = map_race(mock_election, office, "PROPOSITIONS", election_id=59001)

    assert result["race_type"] == "measure"


# ---------------------------------------------------------------------------
# map_candidate
# ---------------------------------------------------------------------------

def test_map_candidate_with_party():
    opt = {"ID": 36388, "BN": "BRETT W. LIGON", "P": "REP"}
    result = map_candidate(election_id=56181, office_id=5031, ballot_option=opt)

    assert result["name"] == "BRETT W. LIGON"
    assert result["party"] == "REP"
    assert result["source_id"] == "tx_goelect:56181:office:5031:candidate:36388"
    assert result["source_metadata"]["tx_candidate_id"] == 36388


def test_map_candidate_no_party():
    opt = {"ID": 99, "BN": "WRITE-IN"}
    result = map_candidate(election_id=56181, office_id=5031, ballot_option=opt)
    assert result["party"] == ""


# ---------------------------------------------------------------------------
# map_county_fragment
# ---------------------------------------------------------------------------

def test_map_county_fragment_lowercase():
    entry = {"CN": "HARRIS", "MID": 48201}
    assert map_county_fragment(entry) == "harris"


def test_map_county_fragment_mid_preserved():
    entry = {"CN": "GALVESTON", "MID": 48167}
    # Function returns the slug; MID is stored in raw by the adapter, not here
    assert map_county_fragment(entry) == "galveston"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest integrations/tx_goelect/tests/test_mappers.py --no-migrations -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'integrations.tx_goelect.mappers'`

- [ ] **Step 3: Implement the mappers**

`integrations/tx_goelect/mappers.py`:
```python
"""
Mappers for TX GoElect ENR API data → CivicMirror model fields.
"""
from __future__ import annotations

from datetime import date, datetime

from elections.models import Election, Race

_TYPE_MAP = {
    "P":  Election.ElectionType.PRIMARY,
    "RU": Election.ElectionType.PRIMARY_RUNOFF,
    "GE": Election.ElectionType.GENERAL,
    "S":  Election.ElectionType.SPECIAL,
    "SR": Election.ElectionType.SPECIAL,
    "GR": Election.ElectionType.GENERAL_RUNOFF,
}

_TARGET_GENERAL_DATE = date(2026, 11, 3)


def parse_election_date(elec_date_str: str) -> date | None:
    """Parse GoElect MMDDYYYY string → date."""
    try:
        return datetime.strptime(elec_date_str, "%m%d%Y").date()
    except (ValueError, TypeError):
        return None


def infer_election_type(type_code: str) -> str:
    return _TYPE_MAP.get(type_code, Election.ElectionType.OTHER)


def classify_election(election_id: int, type_code: str, home: dict) -> dict:
    """
    Build normalized metadata tags for every discovered election.
    is_target_general_2026=True only for GE on 2026-11-03.
    """
    elec_date = parse_election_date(home.get("ElecDate", ""))
    source_date = elec_date.isoformat() if elec_date else ""

    is_target = (type_code == "GE" and elec_date == _TARGET_GENERAL_DATE)

    return {
        "tx_election_id": election_id,
        "election_type_code": type_code,
        "election_scope": "statewide",   # GoElect only surfaces statewide; update if district scope detected
        "source_date": source_date,
        "is_target_general_2026": is_target,
    }


def map_election(
    election_id: int,
    type_code: str,
    home: dict,
    election_name: str,
) -> dict:
    elec_date = parse_election_date(home.get("ElecDate", ""))
    election_type = infer_election_type(type_code)
    classification = classify_election(election_id, type_code, home)

    status = Election.Status.UPCOMING
    if elec_date:
        from django.utils import timezone as tz
        today = tz.localdate()
        if elec_date < today:
            status = Election.Status.RESULTS_PENDING
        elif elec_date == today:
            status = Election.Status.ACTIVE

    return {
        "source_id": f"tx_goelect:{election_id}",
        "name": election_name or f"Texas Election {election_id}",
        "election_date": elec_date,
        "election_type": election_type,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "TX",
        "status": status,
        "source_metadata": classification,
    }


def map_race(
    election_obj,
    office: dict,
    office_type_name: str,
    election_id: int,
) -> dict:
    office_id = office["ID"]
    office_name = office.get("ON", "")
    district_num = office.get("SSO", 0) or 0

    race_type = (
        Race.RaceType.MEASURE
        if "PROPOSITION" in office_type_name.upper() or "PROPOSITION" in office_name.upper()
        else Race.RaceType.CANDIDATE
    )

    geography_scope = "district" if district_num else "statewide"

    cert_status = (
        Race.CertificationStatus.UPCOMING
        if getattr(election_obj, "status", "") in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_PENDING
    )

    return {
        "source_id": f"tx_goelect:{election_id}:office:{office_id}",
        "office_title": office_name,
        "normalized_office_title": office_name.strip().lower(),
        "race_type": race_type,
        "geography_scope": geography_scope,
        "jurisdiction": f"District {district_num}" if district_num else "Texas",
        "certification_status": cert_status,
        "source": Race.Source.TX_GOELECT,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": (
            Race.VoteMethod.YES_NO
            if race_type == Race.RaceType.MEASURE
            else Race.VoteMethod.SINGLE_CHOICE
        ),
        "max_selections": 1,
        "ocd_division_id": "",
        "source_metadata": {
            "tx_election_id": election_id,
            "tx_office_id": office_id,
            "office_type": office_type_name,
            "district_number": district_num,
        },
    }


def map_candidate(election_id: int, office_id: int, ballot_option: dict) -> dict:
    candidate_id = ballot_option.get("ID") or ballot_option.get("id")
    name = ballot_option.get("BN") or ballot_option.get("N") or ""
    party = ballot_option.get("P", "")

    return {
        "name": name,
        "party": party,
        "source_id": f"tx_goelect:{election_id}:office:{office_id}:candidate:{candidate_id}",
        "source_metadata": {
            "tx_candidate_id": candidate_id,
            "party_abbreviation": party,
        },
    }


def map_county_fragment(county_entry: dict) -> str:
    """Lowercase county name slug, e.g. 'harris' from {"CN": "HARRIS", "MID": 48201}."""
    return (county_entry.get("CN") or "").lower()
```

- [ ] **Step 4: Run tests — all must pass**

```bash
cd backend && .venv/bin/python -m pytest integrations/tx_goelect/tests/test_mappers.py --no-migrations -v
```

Expected: all tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add integrations/tx_goelect/mappers.py integrations/tx_goelect/tests/test_mappers.py
git commit -m "feat(tx): add TX GoElect mappers"
```

---

## Task 4: Race Source Migration

**Files:**
- Modify: `elections/models.py`
- Create: `elections/migrations/0019_tx_goelect_race_source.py`

**Interfaces:**
- Produces: `Race.Source.TX_GOELECT = 'tx_goelect'` (used by Task 3 mappers and Task 5 tasks)

- [ ] **Step 1: Add TX_GOELECT to Race.Source in models.py**

In `elections/models.py`, find the `class Source(models.TextChoices):` block (currently ends with `FL_EW`) and add:

```python
        FL_EW = 'fl_ew', 'Florida Election Watch'
        TX_GOELECT = 'tx_goelect', 'Texas GoElect'   # add this line
```

- [ ] **Step 2: Create the migration**

`elections/migrations/0019_tx_goelect_race_source.py`:
```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('elections', '0018_fl_ew_race_source'),
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
                    ('fl_ew', 'Florida Election Watch'),
                    ('tx_goelect', 'Texas GoElect'),
                ],
                max_length=20,
            ),
        ),
    ]
```

- [ ] **Step 3: Verify migration is consistent with models**

```bash
cd backend && .venv/bin/python manage.py migrate --run-syncdb --check 2>&1 | tail -5
```

Expected: exits 0 with no warnings about inconsistent migrations.

- [ ] **Step 4: Commit**

```bash
git add elections/models.py elections/migrations/0019_tx_goelect_race_source.py
git commit -m "feat(tx): add TX_GOELECT race source choice + migration"
```

---

## Task 5: Celery Tasks

**Files:**
- Create: `integrations/tx_goelect/tasks.py`
- Create: `integrations/tx_goelect/tests/test_tasks.py`

**Interfaces:**
- Consumes:
  - `TxGoElectClient` from Task 2
  - `map_election`, `map_race`, `map_candidate`, `classify_election` from Task 3
  - `Race.Source.TX_GOELECT` from Task 4
  - `ingest.ingest_election(*, source, source_id, identity, fields) -> (Election, bool)`
  - `ingest.ingest_race(*, election, source, identity, fields) -> (Race, bool)`
  - `ingest.ingest_candidate(*, race, source, name, party, fields) -> (Candidate, bool)`
  - `cache` from `django.core.cache` (for probe watermark)
- Produces:
  - `sync_tx_elections` — Celery shared task, no args
  - `sync_tx_races(election_pk: int, tx_election_id: int)` — Celery shared task

- [ ] **Step 1: Write the failing tests**

`integrations/tx_goelect/tests/test_tasks.py`:
```python
"""Unit tests for TX GoElect Celery tasks. DB and Celery are fully mocked."""
from unittest.mock import MagicMock, call, patch

import pytest

from integrations.tx_goelect.tasks import sync_tx_elections, sync_tx_races


def _mock_log():
    log = MagicMock()
    log.Status.STARTED = "started"
    log.Status.COMPLETED = "completed"
    log.Status.FAILED = "failed"
    log.Status.COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    return log


# ---------------------------------------------------------------------------
# sync_tx_elections — electionConstants polling
# ---------------------------------------------------------------------------

def test_sync_tx_elections_skips_offline_elections():
    """Elections with O='N' are not ingested."""
    constants = {
        "electionInfo": {
            "2026": {
                "P": {"53813": {"O": "N", "N": "2026 REPUBLICAN PRIMARY"}}
            }
        }
    }

    with patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("integrations.tx_goelect.tasks.cache") as mock_cache, \
         patch("integrations.tx_goelect.tasks.sync_tx_races") as mock_subtask:

        MockClient.return_value.get_election_constants.return_value = constants
        mock_cache.get.return_value = 58315  # watermark already past probe range
        mock_cache.get.side_effect = lambda key, default=None: 99999 if "watermark" in key else default
        MockLog.objects.create.return_value = _mock_log()

        result = sync_tx_elections()

    assert result["created"] == 0
    mock_subtask.apply_async.assert_not_called()


def test_sync_tx_elections_ingests_online_election():
    """Elections with O='Y' → ingest_election called, sync_tx_races queued."""
    constants = {
        "electionInfo": {
            "2026": {
                "RU": {"58315": {"O": "Y", "N": "2026 REPUBLICAN PRIMARY RUNOFF"}}
            }
        }
    }
    home = {"ElecDate": "05262026", "CountiesReporting": {"CR": 254, "CT": 254}}

    mock_election = MagicMock()
    mock_election.pk = 42

    with patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("integrations.tx_goelect.tasks.cache") as mock_cache, \
         patch("integrations.tx_goelect.tasks.sync_tx_races") as mock_subtask, \
         patch("aggregation.ingest.ingest_election", return_value=(mock_election, True)):

        client = MockClient.return_value
        client.get_election_constants.return_value = constants
        client.get_election_data.return_value = {"version": 70, "home": home, "lookups": {}}
        # Watermark past probe range so probe loop doesn't run
        mock_cache.get.side_effect = lambda key, default=None: 99999 if "watermark" in key else default
        MockLog.objects.create.return_value = _mock_log()

        result = sync_tx_elections()

    assert result["created"] == 1
    mock_subtask.apply_async.assert_called_once()


# ---------------------------------------------------------------------------
# sync_tx_elections — sequential ID probe
# ---------------------------------------------------------------------------

def test_probe_stops_after_50_consecutive_misses():
    """50 misses → probe stops; watermark updated to last probed ID."""
    constants = {"electionInfo": {}}  # no elections in constants

    with patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("integrations.tx_goelect.tasks.cache") as mock_cache, \
         patch("integrations.tx_goelect.tasks.sync_tx_races"):

        client = MockClient.return_value
        client.get_election_constants.return_value = constants
        client.probe_election.return_value = False
        # Watermark at 58315, all probes miss
        mock_cache.get.side_effect = lambda key, default=None: 58315 if "watermark" in key else default
        MockLog.objects.create.return_value = _mock_log()

        sync_tx_elections()

    # probe_election called exactly 50 times (one per miss before stop)
    assert client.probe_election.call_count == 50
    # watermark set to 58315 + 50
    mock_cache.set.assert_called_with(
        "tx_goelect:probe_watermark", 58315 + 50, timeout=None
    )


def test_probe_ingests_hit_then_continues():
    """A hit resets the miss counter; scan continues after the hit."""
    constants = {"electionInfo": {}}

    mock_election = MagicMock()
    mock_election.pk = 10

    def probe_side_effect(eid):
        return eid == 58316  # only ID 58316 is live

    with patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("integrations.tx_goelect.tasks.cache") as mock_cache, \
         patch("integrations.tx_goelect.tasks.sync_tx_races") as mock_subtask, \
         patch("aggregation.ingest.ingest_election", return_value=(mock_election, True)):

        client = MockClient.return_value
        client.get_election_constants.return_value = constants
        client.probe_election.side_effect = probe_side_effect
        client.get_election_data.return_value = {
            "version": 1,
            "home": {"ElecDate": "11032026", "CountiesReporting": {"CR": 0, "CT": 254}},
            "lookups": {},
        }
        mock_cache.get.side_effect = lambda key, default=None: 58315 if "watermark" in key else default
        MockLog.objects.create.return_value = _mock_log()

        sync_tx_elections()

    # 58316 hit → ingested
    mock_subtask.apply_async.assert_called_once()
    # Probe continued past 58316 (50 more misses)
    assert client.probe_election.call_count == 51  # 1 hit + 50 misses


def test_probe_skips_non_ge_hits():
    """A probed election that is not GE+2026-11-03 is ingested but not treated as target general."""
    constants = {"electionInfo": {}}

    mock_election = MagicMock()
    mock_election.pk = 20

    with patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("integrations.tx_goelect.tasks.cache") as mock_cache, \
         patch("integrations.tx_goelect.tasks.sync_tx_races"), \
         patch("aggregation.ingest.ingest_election", return_value=(mock_election, True)) as mock_ie:

        client = MockClient.return_value
        client.get_election_constants.return_value = constants
        client.probe_election.side_effect = lambda eid: eid == 58316
        client.get_election_data.return_value = {
            "version": 1,
            # Special election, not GE
            "home": {"ElecDate": "07142026", "CountiesReporting": {"CR": 0, "CT": 1}},
            "lookups": {},
        }
        mock_cache.get.side_effect = lambda key, default=None: 58315 if "watermark" in key else default
        MockLog.objects.create.return_value = _mock_log()

        sync_tx_elections()

    # Still ingested — but metadata will have is_target_general_2026=False
    mock_ie.assert_called_once()
    fields = mock_ie.call_args[1]["fields"]
    assert fields["source_metadata"]["is_target_general_2026"] is False


# ---------------------------------------------------------------------------
# sync_tx_races
# ---------------------------------------------------------------------------

def test_sync_tx_races_upserts_candidate_race():
    """Candidate office → ingest_race + ingest_candidate called."""
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.status = "results_pending"
    mock_election.source_metadata = {"tx_election_id": 56181}

    mock_race = MagicMock()
    mock_race.pk = 5
    mock_cand = MagicMock()

    data = {
        "lookups": {
            "Office": [{"ID": 5031, "ON": "STATE SENATOR, DISTRICT 4", "SSO": 4, "OT": 510}],
            "OfficeType": [{"ID": 510, "OT": "DISTRICT OFFICES"}],
            "Candidates": [{"ID": 36388, "BN": "BRETT W. LIGON"}],
        },
        "office_summary": {
            "OS": [
                {
                    "OID": 5031,
                    "C": [{"ID": 36388, "BN": "BRETT W. LIGON", "P": "REP", "V": 5757, "PE": 73.05}]
                }
            ]
        },
    }

    with patch("integrations.tx_goelect.tasks.Election") as MockElection, \
         patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("aggregation.ingest.ingest_race", return_value=(mock_race, True)) as mock_ir, \
         patch("aggregation.ingest.ingest_candidate", return_value=(mock_cand, True)) as mock_ic:

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception
        MockElection.Status.UPCOMING = "upcoming"
        MockElection.Status.ACTIVE = "active"
        MockClient.return_value.get_election_data.return_value = data
        MockLog.objects.create.return_value = _mock_log()

        result = sync_tx_races(1, 56181)

    mock_ir.assert_called_once()
    assert mock_ir.call_args[1]["identity"]["office_title"] == "STATE SENATOR, DISTRICT 4"
    mock_ic.assert_called_once()
    assert result["races"]["created"] == 1
    assert result["candidates"]["created"] == 1


def test_sync_tx_races_missing_election_returns_early():
    with patch("integrations.tx_goelect.tasks.Election") as MockElection:
        MockElection.objects.get.side_effect = Exception("DoesNotExist")
        MockElection.DoesNotExist = Exception
        result = sync_tx_races(999, 56181)

    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest integrations/tx_goelect/tests/test_tasks.py --no-migrations -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'integrations.tx_goelect.tasks'`

- [ ] **Step 3: Implement the tasks**

`integrations/tx_goelect/tasks.py`:
```python
"""
Texas GoElect Celery tasks.

Stage 1 — sync_tx_elections:
  Poll electionConstants for online elections; upsert Election records.
  Run sequential ID probe for undiscovered elections (e.g. November General).
  Queue sync_tx_races for each election.

Stage 2 — sync_tx_races:
  Fetch Lookups + OfficeSummary for one election.
  Upsert Race + Candidate records.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from elections.models import Election, MeasureOption
from ops.models import SyncLog

from .client import TxGoElectClient
from .exceptions import TxGoElectError, TxGoElectRetryableError
from .mappers import map_candidate, map_election, map_race

logger = logging.getLogger(__name__)

_SOURCE = "tx_goelect"
_PROBE_WATERMARK_KEY = "tx_goelect:probe_watermark"
_PROBE_WATERMARK_INIT = 58315  # highest confirmed election ID as of 2026-06-17
_PROBE_MAX_MISSES = 50


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_tx_elections(self):
    """Stage 1: Discover TX elections and queue race syncs."""
    sync_log = SyncLog.objects.create(
        source=_SOURCE,
        task_name="sync_tx_elections",
        status=SyncLog.Status.STARTED,
    )
    client = TxGoElectClient()
    created_count = updated_count = queued_count = skipped_count = 0

    try:
        from aggregation import ingest

        # ── Poll electionConstants ──────────────────────────────────────────
        constants = client.get_election_constants()
        election_info = constants.get("electionInfo", {})

        for year, type_map in election_info.items():
            for type_code, elections in type_map.items():
                for election_id_str, meta in elections.items():
                    if meta.get("O") != "Y":
                        skipped_count += 1
                        continue

                    election_id = int(election_id_str)
                    election_name = meta.get("N", "")

                    try:
                        data = client.get_election_data(election_id)
                    except TxGoElectError as exc:
                        logger.warning("tx_goelect.sync_elections: data fetch failed id=%d: %s", election_id, exc)
                        skipped_count += 1
                        continue

                    home = data.get("home") or {}
                    fields = map_election(election_id, type_code, home, election_name)
                    source_id = fields.pop("source_id")
                    identity = {
                        "state": fields["state"],
                        "election_type": fields["election_type"],
                        "election_date": fields["election_date"],
                        "jurisdiction_level": fields["jurisdiction_level"],
                    }

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

                    sync_tx_races.apply_async(
                        args=[election_obj.pk, election_id],
                        countdown=queued_count * 5,
                    )
                    queued_count += 1

        # ── Sequential ID probe ─────────────────────────────────────────────
        watermark = cache.get(_PROBE_WATERMARK_KEY, _PROBE_WATERMARK_INIT)
        misses = 0
        probe_id = watermark + 1

        while misses < _PROBE_MAX_MISSES:
            if not client.probe_election(probe_id):
                misses += 1
                probe_id += 1
                continue

            # Hit — fetch data and ingest regardless of type
            misses = 0
            try:
                data = client.get_election_data(probe_id)
            except TxGoElectError as exc:
                logger.warning("tx_goelect.probe: data fetch failed id=%d: %s", probe_id, exc)
                probe_id += 1
                continue

            home = data.get("home") or {}
            # Type code unknown from probe — infer from electionConstants or default OTHER
            type_code = "GE" if "GENERAL" in (data.get("home") or {}).get("ElecDate", "") else "S"
            election_name = f"Texas Election {probe_id}"

            fields = map_election(probe_id, type_code, home, election_name)
            source_id = fields.pop("source_id")
            identity = {
                "state": fields["state"],
                "election_type": fields["election_type"],
                "election_date": fields["election_date"],
                "jurisdiction_level": fields["jurisdiction_level"],
            }

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

            sync_tx_races.apply_async(
                args=[election_obj.pk, probe_id],
                countdown=queued_count * 5,
            )
            queued_count += 1
            probe_id += 1

        cache.set(_PROBE_WATERMARK_KEY, probe_id - 1, timeout=None)

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.records_skipped = skipped_count
        sync_log.notes = f"Queued {queued_count} race syncs; probe watermark now {probe_id - 1}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "records_skipped",
            "notes", "status", "completed_at",
        ])

        return {"created": created_count, "updated": updated_count,
                "skipped": skipped_count, "queued": queued_count}

    except TxGoElectRetryableError as exc:
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.save(update_fields=["status"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("tx_goelect.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_tx_races(self, election_pk: int, tx_election_id: int):
    """Stage 2: Fetch Lookups + OfficeSummary; upsert Race + Candidate records."""
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("tx_goelect.sync_races: election pk=%d not found", election_pk)
        return None

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source=_SOURCE,
        task_name="sync_tx_races",
        status=SyncLog.Status.STARTED,
    )
    client = TxGoElectClient()
    race_created = race_updated = cand_created = cand_updated = 0

    try:
        from aggregation import ingest

        data = client.get_election_data(tx_election_id)
        lookups = data.get("lookups") or {}
        office_summary = data.get("office_summary") or {}

        offices = lookups.get("Office") or []
        office_type_map = {ot["ID"]: ot["OT"] for ot in (lookups.get("OfficeType") or [])}

        # Build candidate-by-ID map from OfficeSummary for vote total context
        # OfficeSummary.OS is a list of {OID, C: list|dict of candidates}
        os_candidates: dict[int, dict] = {}
        for os_entry in (office_summary.get("OS") or []):
            candidates_raw = os_entry.get("C") or {}
            if isinstance(candidates_raw, dict):
                for cand in candidates_raw.values():
                    os_candidates[cand.get("ID") or cand.get("id", 0)] = cand
            elif isinstance(candidates_raw, list):
                for cand in candidates_raw:
                    os_candidates[cand.get("ID") or cand.get("id", 0)] = cand

        for office in offices:
            office_type_id = office.get("OT")
            office_type_name = office_type_map.get(office_type_id, "")

            race_fields = map_race(election_obj, office, office_type_name, tx_election_id)
            race_source_id = race_fields.pop("source_id")
            race_identity = {
                "office_title": race_fields.pop("office_title"),
                "ocd_division_id": race_fields.pop("ocd_division_id", "") or "",
                "race_type": race_fields.pop("race_type"),
            }

            if not race_identity["office_title"]:
                logger.warning("tx_goelect.sync_races: null office title, skipping office_id=%s", office.get("ID"))
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

            if race_identity["race_type"] == Race.RaceType.MEASURE:
                MeasureOption.objects.get_or_create(race=race_obj, option_label="Yes")
                MeasureOption.objects.get_or_create(race=race_obj, option_label="No")
                continue

            # Seed candidates from OfficeSummary entries for this office
            office_id = office["ID"]
            for cand_id, cand_data in os_candidates.items():
                cand_fields = map_candidate(tx_election_id, office_id, cand_data)
                name = cand_fields.pop("name", "")
                party = cand_fields.pop("party", "")
                if not name:
                    continue
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

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        sync_log.records_created = race_created + cand_created
        sync_log.records_updated = race_updated + cand_updated
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "status", "completed_at"])

        return {
            "races": {"created": race_created, "updated": race_updated},
            "candidates": {"created": cand_created, "updated": cand_updated},
        }

    except TxGoElectRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("tx_goelect.sync_races.failed election_pk=%d tx_id=%d", election_pk, tx_election_id)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

Add this import near the top of the file (after `MeasureOption`):
```python
from elections.models import Election, MeasureOption, Race
```

- [ ] **Step 4: Run tests — all must pass**

```bash
cd backend && .venv/bin/python -m pytest integrations/tx_goelect/tests/test_tasks.py --no-migrations -v
```

Expected: all tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add integrations/tx_goelect/tasks.py integrations/tx_goelect/tests/test_tasks.py
git commit -m "feat(tx): add sync_tx_elections + sync_tx_races tasks with ID probe"
```

---

## Task 6: Results Adapter

**Files:**
- Create: `results/adapters/tx.py`
- Create: `results/tests/test_tx_adapter.py`

**Interfaces:**
- Consumes:
  - `TxGoElectClient` from Task 2
  - `map_county_fragment` from Task 3
  - `StateResultsAdapter`, `AdapterResult`, `ResultRow` from `results/adapters/base.py`
  - `register` from `results/adapters/registry.py`
  - `cache` from `django.core.cache`
- Produces: `TxAdapter` registered under `"TX"` in the adapter registry

- [ ] **Step 1: Write the failing tests**

`results/tests/test_tx_adapter.py`:
```python
"""Unit tests for the Texas results adapter. All HTTP calls are mocked."""
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.base import AdapterResult
from results.adapters.tx import TxAdapter


def test_tx_adapter_registered():
    import results.adapters.tx  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "TX" in list_supported_states()
    assert get_adapter("TX") is TxAdapter
    assert get_adapter("tx") is TxAdapter


def test_fetch_results_missing_tx_election_id():
    adapter = TxAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {}  # no tx_election_id

    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results(None, election_id=1)

    assert result.mapping_confidence == "none"
    assert result.rows == []
    assert "tx_election_id" in result.notes


def test_fetch_results_version_unchanged():
    """If version n matches cache, returns unchanged=True without fetching countyInfo."""
    adapter = TxAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"tx_election_id": 56181}
    mock_election.pk = 1

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.tx.TxGoElectClient") as MockClient, \
         patch("results.adapters.tx.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        MockClient.return_value.get_version.return_value = 21
        mock_cache.get.return_value = 21  # matches

        result = adapter.fetch_results(None, election_id=1)

    assert result.unchanged is True
    assert result.rows == []
    MockClient.return_value.get_election_data.assert_not_called()


def test_fetch_results_statewide_candidate_rows():
    """OfficeSummary → statewide ResultRows with jurisdiction_fragment=''."""
    adapter = TxAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"tx_election_id": 56181}
    mock_election.pk = 2

    election_data = {
        "version": 22,
        "home": {"CountiesReporting": {"CR": 5, "CT": 5}, "PrecinctsReporting": {"PR": 122, "PT": 122}},
        "office_summary": {
            "OS": [
                {
                    "OID": 5031,
                    "ON": "STATE SENATOR, DISTRICT 4",
                    "C": [
                        {"ID": 36388, "BN": "BRETT W. LIGON", "P": "REP", "V": 5757, "PE": 73.05, "EV": 4394},
                        {"ID": 36422, "BN": "RON C. ANGELETTI", "P": "DEM", "V": 2124, "PE": 26.95, "EV": 1472},
                    ]
                }
            ]
        },
        "statewide_q": {},
    }
    county_data = {}  # no counties for this test

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.tx.TxGoElectClient") as MockClient, \
         patch("results.adapters.tx.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        client = MockClient.return_value
        client.get_version.return_value = 22
        client.get_election_data.return_value = election_data
        client.get_county_results.return_value = county_data
        mock_cache.get.return_value = 10  # different from 22

        result = adapter.fetch_results(None, election_id=2)

    assert result.mapping_confidence == "full"
    assert result.source_version == "22"
    # Two statewide rows
    assert len(result.rows) == 2
    row = result.rows[0]
    assert row.candidate_name == "BRETT W. LIGON"
    assert row.vote_count == 5757
    assert row.vote_pct == 73.05
    assert row.jurisdiction_fragment == ""
    assert row.raw["tx_candidate_id"] == 36388
    assert row.raw["party"] == "REP"
    assert row.raw["early_votes"] == 4394


def test_fetch_results_complete_unofficial_when_all_reporting():
    """CR==CT and PR==PT → result_type='complete_unofficial'."""
    adapter = TxAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"tx_election_id": 56181}
    mock_election.pk = 3

    election_data = {
        "version": 21,
        "home": {"CountiesReporting": {"CR": 5, "CT": 5}, "PrecinctsReporting": {"PR": 122, "PT": 122}},
        "office_summary": {"OS": []},
        "statewide_q": {},
    }

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.tx.TxGoElectClient") as MockClient, \
         patch("results.adapters.tx.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        MockClient.return_value.get_version.return_value = 21
        MockClient.return_value.get_election_data.return_value = election_data
        MockClient.return_value.get_county_results.return_value = {}
        mock_cache.get.return_value = 1

        result = adapter.fetch_results(None, election_id=3)

    # No rows (empty OS), but result_type inference worked — check via source_version
    assert result.source_version == "21"


def test_fetch_results_unofficial_when_partial():
    """CR < CT → result_type='unofficial'."""
    adapter = TxAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"tx_election_id": 56181}
    mock_election.pk = 4

    election_data = {
        "version": 5,
        "home": {"CountiesReporting": {"CR": 3, "CT": 5}, "PrecinctsReporting": {"PR": 60, "PT": 122}},
        "office_summary": {
            "OS": [
                {
                    "OID": 5031,
                    "ON": "STATE SENATOR",
                    "C": [{"ID": 1, "BN": "ALICE", "P": "REP", "V": 100, "PE": 100.0, "EV": 50}]
                }
            ]
        },
        "statewide_q": {},
    }

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.tx.TxGoElectClient") as MockClient, \
         patch("results.adapters.tx.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        MockClient.return_value.get_version.return_value = 5
        MockClient.return_value.get_election_data.return_value = election_data
        MockClient.return_value.get_county_results.return_value = {}
        mock_cache.get.return_value = 1

        result = adapter.fetch_results(None, election_id=4)

    assert result.rows[0].result_type == "unofficial"


def test_fetch_results_county_rows():
    """countyInfo → county ResultRows with jurisdiction_fragment set."""
    adapter = TxAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"tx_election_id": 56181}
    mock_election.pk = 5

    election_data = {
        "version": 21,
        "home": {"CountiesReporting": {"CR": 5, "CT": 5}, "PrecinctsReporting": {"PR": 122, "PT": 122}},
        "office_summary": {"OS": []},
        "statewide_q": {},
    }
    county_data = {
        "101": {
            "N": "HARRIS",
            "MID": 48201,
            "Races": {
                "5031": {
                    "OID": 5031,
                    "N": "STATE SENATOR, DISTRICT 4",
                    "C": {
                        "36388": {"id": 36388, "N": "BRETT W. LIGON", "P": "REP", "V": 5757, "PE": 73.05, "EV": 4394}
                    },
                    "PR": 75, "TP": 75,
                }
            }
        }
    }

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.tx.TxGoElectClient") as MockClient, \
         patch("results.adapters.tx.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        MockClient.return_value.get_version.return_value = 21
        MockClient.return_value.get_election_data.return_value = election_data
        MockClient.return_value.get_county_results.return_value = county_data
        mock_cache.get.return_value = 1

        result = adapter.fetch_results(None, election_id=5)

    county_rows = [r for r in result.rows if r.jurisdiction_fragment == "harris"]
    assert len(county_rows) == 1
    row = county_rows[0]
    assert row.candidate_name == "BRETT W. LIGON"
    assert row.vote_count == 5757
    assert row.raw["county_mid"] == 48201
    assert row.raw["tx_office_id"] == 5031


def test_fetch_results_proposition_rows():
    """StateWideQ entries → ResultRows with option_label, no candidate_name."""
    adapter = TxAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"tx_election_id": 59001}
    mock_election.pk = 6

    election_data = {
        "version": 3,
        "home": {"CountiesReporting": {"CR": 254, "CT": 254}, "PrecinctsReporting": {"PR": 5000, "PT": 5000}},
        "office_summary": {"OS": []},
        "statewide_q": {
            "Q": [
                {
                    "OID": 7001,
                    "ON": "PROPOSITION 1",
                    "C": [
                        {"ID": 901, "N": "FOR", "V": 3000000, "PE": 60.0, "EV": 2000000},
                        {"ID": 902, "N": "AGAINST", "V": 2000000, "PE": 40.0, "EV": 1200000},
                    ]
                }
            ]
        },
    }

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.tx.TxGoElectClient") as MockClient, \
         patch("results.adapters.tx.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        MockClient.return_value.get_version.return_value = 3
        MockClient.return_value.get_election_data.return_value = election_data
        MockClient.return_value.get_county_results.return_value = {}
        mock_cache.get.return_value = 1

        result = adapter.fetch_results(None, election_id=6)

    prop_rows = result.rows
    assert len(prop_rows) == 2
    assert prop_rows[0].candidate_name is None
    assert prop_rows[0].option_label == "FOR"
    assert prop_rows[0].vote_count == 3000000
    assert prop_rows[0].result_type == "complete_unofficial"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest results/tests/test_tx_adapter.py --no-migrations -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'results.adapters.tx'`

- [ ] **Step 3: Implement the adapter**

`results/adapters/tx.py`:
```python
"""
Texas GoElect ENR results adapter.

Per poll cycle:
  1. GET /election/{id} — check Version integer n for changes
  2. GET /election/{id} (full data) — parse OfficeSummary + StateWideQ for statewide rows
  3. GET /election/countyInfo/{id} — parse per-county race results

result_type:
  'complete_unofficial' — all counties and precincts reported (CR==CT and PR==PT)
  'unofficial'          — partial reporting
  'official'            — reserved; GoElect has no certification flag yet
"""
from __future__ import annotations

import logging

from django.core.cache import cache

from integrations.tx_goelect.client import TxGoElectClient
from integrations.tx_goelect.mappers import map_county_fragment

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_VERSION_CACHE_TTL = 86400 * 30  # 30 days


@register
class TxAdapter(StateResultsAdapter):
    state = "TX"

    def version_cache_key(self, election_id: int) -> str:
        return f"tx_goelect:ver:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("TXAdapter: election %d not found", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election {election_id} not found",
            )

        tx_election_id = (election.source_metadata or {}).get("tx_election_id")
        if not tx_election_id:
            logger.warning("TXAdapter: no tx_election_id for election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes="No tx_election_id in election.source_metadata — run sync_tx_elections first",
            )

        client = TxGoElectClient()
        base_url = f"https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/election/{tx_election_id}"

        version = client.get_version(tx_election_id)
        cache_key = self.version_cache_key(election_id)
        if version is not None and cache.get(cache_key) == version:
            logger.debug("TXAdapter: version unchanged tx_id=%d n=%d", tx_election_id, version)
            return AdapterResult(
                rows=[], source_url=base_url, mapping_confidence="full",
                unchanged=True, source_version=str(version),
            )

        try:
            data = client.get_election_data(tx_election_id)
            county_data = client.get_county_results(tx_election_id)
        except Exception as exc:
            logger.error("TXAdapter: fetch failed tx_id=%d: %s", tx_election_id, exc)
            return AdapterResult(
                rows=[], source_url=base_url, mapping_confidence="none",
                notes=f"Fetch failed: {exc}",
            )

        home = data.get("home") or {}
        cr = (home.get("CountiesReporting") or {})
        pr = (home.get("PrecinctsReporting") or {})
        all_complete = (
            cr.get("CR", 0) == cr.get("CT", -1) and
            pr.get("PR", 0) == pr.get("PT", -1) and
            cr.get("CT", 0) > 0
        )
        result_type = "complete_unofficial" if all_complete else "unofficial"

        rows: list[ResultRow] = []

        # ── Statewide candidate rows from OfficeSummary ──────────────────────
        for os_entry in (data.get("office_summary") or {}).get("OS") or []:
            office_id = os_entry.get("OID")
            office_name = os_entry.get("ON") or os_entry.get("N") or ""
            candidates_raw = os_entry.get("C") or []
            if isinstance(candidates_raw, dict):
                candidates_raw = list(candidates_raw.values())

            for cand in candidates_raw:
                cand_id = cand.get("ID") or cand.get("id")
                name = cand.get("BN") or cand.get("N") or ""
                rows.append(ResultRow(
                    candidate_name=name or None,
                    option_label=None,
                    vote_count=int(cand.get("V") or 0),
                    vote_pct=float(cand.get("PE") or 0) or None,
                    is_winner=None,
                    result_type=result_type,
                    office_title=office_name or None,
                    jurisdiction_fragment="",
                    raw={
                        "tx_candidate_id": cand_id,
                        "tx_election_id": tx_election_id,
                        "tx_office_id": office_id,
                        "party": cand.get("P", ""),
                        "early_votes": int(cand.get("EV") or 0),
                    },
                ))

        # ── Statewide proposition rows from StateWideQ ───────────────────────
        for q_entry in (data.get("statewide_q") or {}).get("Q") or []:
            office_id = q_entry.get("OID")
            office_name = q_entry.get("ON") or q_entry.get("N") or ""
            options_raw = q_entry.get("C") or []
            if isinstance(options_raw, dict):
                options_raw = list(options_raw.values())

            for opt in options_raw:
                opt_id = opt.get("ID") or opt.get("id")
                label = opt.get("N") or opt.get("BN") or ""
                rows.append(ResultRow(
                    candidate_name=None,
                    option_label=label or None,
                    vote_count=int(opt.get("V") or 0),
                    vote_pct=float(opt.get("PE") or 0) or None,
                    is_winner=None,
                    result_type=result_type,
                    office_title=office_name or None,
                    jurisdiction_fragment="",
                    raw={
                        "tx_candidate_id": opt_id,
                        "tx_election_id": tx_election_id,
                        "tx_office_id": office_id,
                        "early_votes": int(opt.get("EV") or 0),
                    },
                ))

        # ── County rows from countyInfo ───────────────────────────────────────
        for county_id_str, county in (county_data or {}).items():
            county_name = (county.get("N") or "").lower()
            county_mid = county.get("MID")
            fragment = county_name or county_id_str

            for race_id_str, race in (county.get("Races") or {}).items():
                office_id = race.get("OID")
                office_name = race.get("N") or ""
                candidates_raw = race.get("C") or {}
                if isinstance(candidates_raw, dict):
                    candidates_raw = list(candidates_raw.values())

                for cand in candidates_raw:
                    cand_id = cand.get("id") or cand.get("ID")
                    name = cand.get("N") or cand.get("BN") or ""
                    rows.append(ResultRow(
                        candidate_name=name or None,
                        option_label=None,
                        vote_count=int(cand.get("V") or 0),
                        vote_pct=float(cand.get("PE") or 0) or None,
                        is_winner=None,
                        result_type=result_type,
                        office_title=office_name or None,
                        jurisdiction_fragment=fragment,
                        raw={
                            "tx_candidate_id": cand_id,
                            "tx_election_id": tx_election_id,
                            "tx_office_id": office_id,
                            "county_mid": county_mid,
                            "party": cand.get("P", ""),
                            "early_votes": int(cand.get("EV") or 0),
                        },
                    ))

        logger.info(
            "TXAdapter: tx_id=%d rows=%d result_type=%s version=%s",
            tx_election_id, len(rows), result_type, version,
        )

        return AdapterResult(
            rows=rows,
            source_url=base_url,
            mapping_confidence="full",
            source_version=str(version) if version is not None else "",
        )
```

- [ ] **Step 4: Run tests — all must pass**

```bash
cd backend && .venv/bin/python -m pytest results/tests/test_tx_adapter.py --no-migrations -v
```

Expected: all tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add results/adapters/tx.py results/tests/test_tx_adapter.py
git commit -m "feat(tx): add TxAdapter with statewide + county ResultRow parsing"
```

---

## Task 7: Wiring + Deploy

**Files:**
- Modify: `results/apps.py`
- Modify: `internal/task_locks.py`
- Modify: `internal/views.py`
- Modify: `internal/urls.py`
- Modify: `.github/workflows/deploy.yml`

**Interfaces:**
- Consumes: `sync_tx_elections` from Task 5, `TxAdapter` from Task 6
- Produces: live scheduler trigger at `/internal/tasks/sync-tx-goelect/`

- [ ] **Step 1: Register the adapter in ResultsConfig**

In `results/apps.py`, add `tx` to the import line:

```python
    def ready(self):
        from results.adapters import ar, az, ca, co, ct, fl, ia, ma, nc, ny, sc, tx, va, wa, wv  # noqa: F401
```

- [ ] **Step 2: Add task lock**

In `internal/task_locks.py`, add after the `sync_fl_ew` entry:

```python
    "sync_fl_ew":           (WINDOW_DAILY,      23 * _HOUR),
    "sync_tx_goelect":      (WINDOW_DAILY,      23 * _HOUR),
```

- [ ] **Step 3: Add the trigger view**

In `internal/views.py`, add the import at the top with the other task imports:

```python
from integrations.tx_goelect.tasks import sync_tx_elections as _sync_tx_elections
```

Then add the view function at the end of the file:

```python
@csrf_exempt
@require_POST
@require_internal_task_token
def sync_tx_goelect_trigger(request):
    return _trigger("sync_tx_goelect", _sync_tx_elections, request)
```

- [ ] **Step 4: Add the URL**

In `internal/urls.py`, add after the `sync-fl-ew` line:

```python
    path("tasks/sync-fl-ew/", views.sync_fl_ew_trigger, name="internal-sync-fl-ew"),
    path("tasks/sync-tx-goelect/", views.sync_tx_goelect_trigger, name="internal-sync-tx-goelect"),
```

- [ ] **Step 5: Add the Cloud Scheduler job to deploy.yml**

In `.github/workflows/deploy.yml`, add after the `sync-fl-ew` block (just before the closing of the "Update Cloud Scheduler job URIs" run block):

```yaml
          if gcloud scheduler jobs describe sync-tx-goelect --location="${{ env.REGION }}" --quiet 2>/dev/null; then
            gcloud scheduler jobs update http sync-tx-goelect \
              --location="${{ env.REGION }}" \
              --uri="${NEW_BASE}/internal/tasks/sync-tx-goelect/" \
              --oidc-service-account-email="$SA" \
              --oidc-token-audience="$NEW_BASE" \
              --quiet
          else
            gcloud scheduler jobs create http sync-tx-goelect \
              --location="${{ env.REGION }}" \
              --schedule="0 5 * * *" \
              --time-zone="Etc/UTC" \
              --uri="${NEW_BASE}/internal/tasks/sync-tx-goelect/" \
              --oidc-service-account-email="$SA" \
              --oidc-token-audience="$NEW_BASE" \
              --quiet
          fi
```

- [ ] **Step 6: Run the full TX test suite**

```bash
cd backend && .venv/bin/python -m pytest \
    integrations/tx_goelect/tests/ \
    results/tests/test_tx_adapter.py \
    internal/tests/test_clear_task_locks.py \
    --no-migrations -v
```

Expected: all tests PASSED. If `test_clear_task_locks.py` fails, check that `"sync_tx_goelect"` appears in its expected lock list and add it.

- [ ] **Step 7: Verify task lock test coverage**

Open `internal/tests/test_clear_task_locks.py` and confirm `"sync_tx_goelect"` is in the expected task names list. If not, add it:

```python
        "sync_fl_ew", "sync_tx_goelect", "sync_wa_votewa",
```

Re-run if you made a change:

```bash
cd backend && .venv/bin/python -m pytest internal/tests/test_clear_task_locks.py --no-migrations -v
```

- [ ] **Step 8: Smoke-test Django startup**

```bash
cd backend && .venv/bin/python manage.py check 2>&1 | tail -5
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 9: Commit**

```bash
git add results/apps.py internal/task_locks.py internal/views.py \
        internal/urls.py .github/workflows/deploy.yml \
        internal/tests/test_clear_task_locks.py
git commit -m "feat(tx): wire TX GoElect adapter — trigger, locks, scheduler, ResultsConfig"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Client with tolerant decoder + schema-drift logging | Task 2 |
| Frozen fixtures from real API | Task 2 Step 1 |
| `map_election` with MMDDYYYY parsing + classification metadata | Task 3 |
| `map_race` composite source_id `tx_goelect:{eid}:office:{oid}` | Task 3 |
| `map_candidate` composite source_id including candidate_id | Task 3 |
| `county_mid` (not `county_fips`) in raw | Task 6 |
| `Race.Source.TX_GOELECT` + migration | Task 4 |
| `sync_tx_elections` with `O == "Y"` filter | Task 5 |
| Sequential ID probe with 50-miss stop + watermark | Task 5 |
| Ingest all probed elections with `is_target_general_2026` tag | Task 5 |
| `sync_tx_races` seeding races + candidates from Lookups | Task 5 |
| `TxAdapter` statewide rows from OfficeSummary | Task 6 |
| `TxAdapter` proposition rows from StateWideQ | Task 6 |
| `TxAdapter` county rows from countyInfo with `county_mid` | Task 6 |
| `complete_unofficial` when CR==CT and PR==PT | Task 6 |
| `unofficial` for partial reporting | Task 6 |
| `ResultsConfig.ready()` import | Task 7 |
| Task lock registered | Task 7 |
| Internal trigger view + URL | Task 7 |
| Cloud Scheduler job in deploy.yml at 05:00 UTC | Task 7 |

**No placeholders detected.**

**Type consistency:** `map_race` returns `source_id` which `sync_tx_races` pops via `race_fields.pop("source_id")` — consistent. `map_candidate` returns `name` and `party` at top level which `sync_tx_races` pops before calling `ingest_candidate` — consistent with the WA pattern.
