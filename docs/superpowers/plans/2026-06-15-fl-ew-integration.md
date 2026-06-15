# Florida Election Watch Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `integrations/fl_ew/` — a full Florida Election Watch Tier B integration that seeds Election, Race, and Candidate records from the FL DOS tab-delimited results file, and extends `results/adapters/fl.py` with county-level ResultRows and Last-Modified version detection.

**Architecture:** A new `fl_ew` integration module seeds known FL election date slugs (`YYYYMMDD`), fetches `{slug}_ElecResultsFL.txt` from `flelectionfiles.floridados.gov`, groups rows into races (partitioned by party for primaries), and upserts Election/Race/Candidate rows via the aggregation ingest service. The FL results adapter fetches the same single file, emits one `ResultRow` per candidate × county row, and uses the `Last-Modified` HTTP header for version detection.

**Tech Stack:** Django, Celery, `requests`, `csv` (stdlib), `aggregation.ingest`, FL DOS Election Watch public tab-delimited file at `https://flelectionfiles.floridados.gov/enightfilespublic/`, no auth required. User-Agent: `civicmirror.app`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `elections/models.py` | Modify | Add `Race.Source.FL_EW = 'fl_ew'` |
| `elections/migrations/0018_fl_ew_race_source.py` | Create | Migration for new source choice |
| `integrations/fl_ew/__init__.py` | Create | Package marker |
| `integrations/fl_ew/apps.py` | Create | AppConfig (`label = "fl_ew"`) |
| `integrations/fl_ew/exceptions.py` | Create | `FlEwError`, `FlEwRetryableError` |
| `integrations/fl_ew/client.py` | Create | URL builder, HEAD version check, GET with retry |
| `integrations/fl_ew/parsers.py` | Create | TSV → `list[ElectionRow]` dataclass |
| `integrations/fl_ew/mappers.py` | Create | `map_election`, `build_race_groups`, `map_race`, `map_candidate` |
| `integrations/fl_ew/tasks.py` | Create | `sync_fl_elections` + `sync_fl_races` Celery tasks |
| `integrations/fl_ew/tests/__init__.py` | Create | Test package marker |
| `integrations/fl_ew/tests/test_client.py` | Create | Client unit tests (HTTP mocked) |
| `integrations/fl_ew/tests/test_parsers.py` | Create | Parser unit tests (no DB) |
| `integrations/fl_ew/tests/test_mappers.py` | Create | Mapper unit tests (no DB) |
| `integrations/fl_ew/tests/test_tasks.py` | Create | Task unit tests (DB + Celery mocked) |
| `results/adapters/fl.py` | Create | Results adapter (tab-delimited → `ResultRow` list) |
| `results/tests/test_fl_adapter.py` | Create | Adapter tests (HTTP mocked) |
| `config/settings/base.py` | Modify | Register `integrations.fl_ew` in INSTALLED_APPS |
| `internal/views.py` | Modify | Add `sync_fl_ew_trigger` view |
| `internal/urls.py` | Modify | Add `tasks/sync-fl-ew/` path |
| `internal/task_locks.py` | Modify | Add `"sync_fl_ew"` to `TASK_LOCKS` |
| `aggregation/migrations/0011_seed_fl_ew_precedence.py` | Create | FL source precedence rows |

---

## File Format Reference

**URL pattern:** `https://flelectionfiles.floridados.gov/enightfilespublic/{YYYYMMDD}_ElecResultsFL.txt`

**Tab-delimited, header row included. 15 columns:**

```
ElectionDate  PartyCode  PartyName  RaceCode  RaceName  CountyCode  CountyName
Juris1num  Juris2num  Precincts  PrecinctsReporting  CanNameLast  CanNameFirst
CanNameMiddle  CanVotes
```

**Sample rows (2026-03-24 special election):**
```
03/24/2026  REP  Republican Party  STS  State Senator, District 14  HIL  Hillsborough  014      152  152  Tomkow    Josie      39836
03/24/2026  DEM  Democratic Party  STS  State Senator, District 14  HIL  Hillsborough  014      152  152  Nathan    Brian      40245
```

- `ElectionDate`: `MM/DD/YYYY`
- `Juris2num`: often empty/whitespace — strip before use
- `CanVotes`: integer, may have surrounding whitespace
- No `vote_pct` in the file; adapter sets `vote_pct=None`
- `result_type`: `"official"` if `PrecinctsReporting == Precincts`, else `"unofficial"`
- `jurisdiction_fragment` in ResultRow: `county_code.lower()` (e.g. `"hil"` for Hillsborough)

**Known election slugs:**
```python
KNOWN_ELECTION_SLUGS = [
    "20260818",  # August 18, 2026 Primary
    "20261103",  # November 3, 2026 General Election
]
```

---

## Task 1: Race.Source.FL_EW + Migration

**Files:**
- Modify: `backend/elections/models.py`
- Create: `backend/elections/migrations/0018_fl_ew_race_source.py`

- [ ] **Step 1: Write failing smoke test**

Run inline — no test file needed:
```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -c "from elections.models import Race; print(Race.Source.FL_EW)"
```
Expected: `AttributeError: FL_EW`

- [ ] **Step 2: Add FL_EW to Race.Source**

In `backend/elections/models.py`, find the `Source` class (currently ends at `WA_VOTEWA`) and add one line:

```python
        WA_VOTEWA = 'wa_votewa', 'Washington VoteWA'
        FL_EW = 'fl_ew', 'Florida Election Watch'
```

- [ ] **Step 3: Create migration**

Create `backend/elections/migrations/0018_fl_ew_race_source.py`:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('elections', '0017_wa_votewa_race_source'),
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
                ],
                max_length=20,
            ),
        ),
    ]
```

- [ ] **Step 4: Verify**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -c "from elections.models import Race; print(Race.Source.FL_EW)"
```
Expected: `fl_ew`

- [ ] **Step 5: Commit**

```bash
git add backend/elections/models.py backend/elections/migrations/0018_fl_ew_race_source.py
git commit -m "feat(elections): add Race.Source.FL_EW choice + migration 0018"
```

---

## Task 2: fl_ew Package Scaffold

**Files:**
- Create: `backend/integrations/fl_ew/__init__.py`
- Create: `backend/integrations/fl_ew/apps.py`
- Create: `backend/integrations/fl_ew/exceptions.py`
- Create: `backend/integrations/fl_ew/tests/__init__.py`
- Modify: `backend/config/settings/base.py`

- [ ] **Step 1: Create `__init__.py`**

Create `backend/integrations/fl_ew/__init__.py` as an empty file.

- [ ] **Step 2: Create `apps.py`**

```python
# backend/integrations/fl_ew/apps.py
from django.apps import AppConfig


class FlEwConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.fl_ew"
    label = "fl_ew"
    verbose_name = "Florida Election Watch Integration"
```

- [ ] **Step 3: Create `exceptions.py`**

```python
# backend/integrations/fl_ew/exceptions.py


class FlEwError(Exception):
    pass


class FlEwRetryableError(FlEwError):
    pass
```

- [ ] **Step 4: Create `tests/__init__.py`**

Create `backend/integrations/fl_ew/tests/__init__.py` as an empty file.

- [ ] **Step 5: Register in INSTALLED_APPS**

In `backend/config/settings/base.py`, add `'integrations.fl_ew'` after `'integrations.wa_votewa'`:

```python
    'integrations.wa_votewa',
    'integrations.fl_ew',
```

- [ ] **Step 6: Verify import**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -c "from integrations.fl_ew.exceptions import FlEwError; print('OK')"
```
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add backend/integrations/fl_ew/ backend/config/settings/base.py
git commit -m "feat(fl-ew): scaffold package, AppConfig, exceptions, register in INSTALLED_APPS"
```

---

## Task 3: fl_ew Client

**Files:**
- Create: `backend/integrations/fl_ew/client.py`
- Create: `backend/integrations/fl_ew/tests/test_client.py`

- [ ] **Step 1: Write failing tests**

Create `backend/integrations/fl_ew/tests/test_client.py`:

```python
"""
Unit tests for FlEwClient. HTTP calls are fully mocked — no network required.
"""
import re
from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib

from integrations.fl_ew.client import KNOWN_ELECTION_SLUGS, FlEwClient
from integrations.fl_ew.exceptions import FlEwError, FlEwRetryableError


# ---------------------------------------------------------------------------
# KNOWN_ELECTION_SLUGS
# ---------------------------------------------------------------------------

def test_known_slugs_are_yyyymmdd():
    for slug in KNOWN_ELECTION_SLUGS:
        assert re.fullmatch(r"\d{8}", slug), f"Slug {slug!r} is not yyyymmdd"


def test_known_slugs_include_august_primary():
    assert "20260818" in KNOWN_ELECTION_SLUGS


def test_known_slugs_include_november_general():
    assert "20261103" in KNOWN_ELECTION_SLUGS


# ---------------------------------------------------------------------------
# results_url / file_url
# ---------------------------------------------------------------------------

def test_file_url_pattern():
    client = FlEwClient()
    url = client.file_url("20260818")
    assert url == (
        "https://flelectionfiles.floridados.gov/enightfilespublic/"
        "20260818_ElecResultsFL.txt"
    )


# ---------------------------------------------------------------------------
# get_last_modified
# ---------------------------------------------------------------------------

def test_get_last_modified_returns_header():
    client = FlEwClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Last-Modified": "Mon, 18 Aug 2026 01:00:00 GMT"}

    with patch.object(client._session, "head", return_value=mock_resp):
        result = client.get_last_modified("20260818")

    assert result == "Mon, 18 Aug 2026 01:00:00 GMT"


def test_get_last_modified_returns_empty_on_404():
    client = FlEwClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch.object(client._session, "head", return_value=mock_resp):
        result = client.get_last_modified("20260818")

    assert result == ""


def test_get_last_modified_returns_empty_on_network_error():
    client = FlEwClient()
    with patch.object(client._session, "head", side_effect=req_lib.ConnectionError("refused")):
        result = client.get_last_modified("20260818")
    assert result == ""


# ---------------------------------------------------------------------------
# fetch_results_file
# ---------------------------------------------------------------------------

def test_fetch_results_file_returns_text():
    client = FlEwClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ElectionDate\tPartyCode\n03/24/2026\tREP\n"

    with patch.object(client._session, "get", return_value=mock_resp):
        text = client.fetch_results_file("20260324")

    assert "ElectionDate" in text


def test_fetch_results_file_raises_retryable_on_503():
    client = FlEwClient(max_retries=1)
    mock_resp = MagicMock()
    mock_resp.status_code = 503

    with patch.object(client._session, "get", return_value=mock_resp):
        with pytest.raises(FlEwRetryableError):
            client.fetch_results_file("20260818")


def test_fetch_results_file_raises_on_404():
    client = FlEwClient(max_retries=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch.object(client._session, "get", return_value=mock_resp):
        with pytest.raises(FlEwError):
            client.fetch_results_file("20260818")


def test_fetch_results_file_raises_retryable_on_network_error():
    client = FlEwClient(max_retries=1)
    with patch.object(client._session, "get", side_effect=req_lib.ConnectionError("down")):
        with pytest.raises(FlEwRetryableError):
            client.fetch_results_file("20260818")
```

- [ ] **Step 2: Run tests — confirm ImportError**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -m pytest --no-migrations integrations/fl_ew/tests/test_client.py -v 2>&1 | head -20
```
Expected: `ImportError` or `ModuleNotFoundError` — `client.py` doesn't exist yet.

- [ ] **Step 3: Create `client.py`**

```python
# backend/integrations/fl_ew/client.py
"""
Florida Election Watch HTTP client.

Public tab-delimited results file:
  https://flelectionfiles.floridados.gov/enightfilespublic/{YYYYMMDD}_ElecResultsFL.txt

No auth required. Version detection via Last-Modified header.
"""
from __future__ import annotations

import logging

import requests

from .exceptions import FlEwError, FlEwRetryableError

logger = logging.getLogger(__name__)

_BASE = "https://flelectionfiles.floridados.gov/enightfilespublic"
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_UA = "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"

KNOWN_ELECTION_SLUGS: list[str] = [
    "20260818",  # August 18, 2026 Primary
    "20261103",  # November 3, 2026 General Election
]


class FlEwClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers["User-Agent"] = _UA

    def file_url(self, slug: str) -> str:
        return f"{_BASE}/{slug}_ElecResultsFL.txt"

    def get_last_modified(self, slug: str) -> str:
        """
        HEAD the results file and return the Last-Modified header value,
        or '' on any error (404, network failure, missing header).
        """
        url = self.file_url(slug)
        try:
            resp = self._session.head(url, timeout=15)
            if resp.status_code != 200:
                return ""
            return resp.headers.get("Last-Modified", "")
        except requests.RequestException as exc:
            logger.warning("fl_ew.client.head_failed slug=%s: %s", slug, exc)
            return ""

    def fetch_results_file(self, slug: str) -> str:
        """
        GET the tab-delimited results file and return its text content.
        Raises FlEwRetryableError on transient failures; FlEwError on 404.
        """
        url = self.file_url(slug)
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise FlEwRetryableError(f"GET {url} failed: {exc}") from exc
                continue

            if resp.status_code == 404:
                raise FlEwError(f"GET {url} returned 404 — file not yet published")
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise FlEwRetryableError(
                        f"GET {url} returned {resp.status_code} after {self.max_retries} retries"
                    )
                continue

            resp.raise_for_status()
            logger.info("fl_ew.client.fetched slug=%s bytes=%d", slug, len(resp.content))
            return resp.text

        raise FlEwRetryableError(f"GET {url} retries exhausted")
```

- [ ] **Step 4: Run tests — confirm all pass**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -m pytest --no-migrations integrations/fl_ew/tests/test_client.py -v
```
Expected: All tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/fl_ew/client.py backend/integrations/fl_ew/tests/test_client.py
git commit -m "feat(fl-ew): add FlEwClient with URL builder, HEAD version check, GET with retry"
```

---

## Task 4: fl_ew Parser

**Files:**
- Create: `backend/integrations/fl_ew/parsers.py`
- Create: `backend/integrations/fl_ew/tests/test_parsers.py`

- [ ] **Step 1: Write failing tests**

Create `backend/integrations/fl_ew/tests/test_parsers.py`:

```python
"""
Unit tests for the FL EW tab-delimited file parser. No DB, no HTTP.
"""
import pytest

from integrations.fl_ew.parsers import ElectionRow, parse_results_file

# Minimal valid file text — two candidates in one race across one county.
_SAMPLE = (
    "ElectionDate\tPartyCode\tPartyName\tRaceCode\tRaceName\tCountyCode\t"
    "CountyName\tJuris1num\tJuris2num\tPrecincts\tPrecinctsReporting\t"
    "CanNameLast\tCanNameFirst\tCanNameMiddle\tCanVotes\n"
    "03/24/2026\tREP\tRepublican Party\tSTS\tState Senator, District 14\t"
    "HIL\tHillsborough\t014\t \t152\t152\tTomkow\tJosie\t\t39836\n"
    "03/24/2026\tDEM\tDemocratic Party\tSTS\tState Senator, District 14\t"
    "HIL\tHillsborough\t014\t \t152\t152\tNathan\tBrian\t\t40245\n"
)

_MULTI_RACE_SAMPLE = (
    "ElectionDate\tPartyCode\tPartyName\tRaceCode\tRaceName\tCountyCode\t"
    "CountyName\tJuris1num\tJuris2num\tPrecincts\tPrecinctsReporting\t"
    "CanNameLast\tCanNameFirst\tCanNameMiddle\tCanVotes\n"
    "08/18/2026\tREP\tRepublican Party\tGOV\tGovernor\t"
    "ALA\tAlachua\t000\t \t100\t80\tSmith\tAlice\t\t5000\n"
    "08/18/2026\tREP\tRepublican Party\tGOV\tGovernor\t"
    "ALA\tAlachua\t000\t \t100\t80\tJones\tBob\t\t4200\n"
    "08/18/2026\tDEM\tDemocratic Party\tGOV\tGovernor\t"
    "ALA\tAlachua\t000\t \t100\t80\tWilliams\tCarol\t\t6100\n"
)


# ---------------------------------------------------------------------------
# parse_results_file
# ---------------------------------------------------------------------------

def test_parse_returns_election_rows():
    rows = parse_results_file(_SAMPLE)
    assert len(rows) == 2
    assert all(isinstance(r, ElectionRow) for r in rows)


def test_parse_election_date():
    rows = parse_results_file(_SAMPLE)
    from datetime import date
    assert rows[0].election_date == date(2026, 3, 24)


def test_parse_party_fields():
    rows = parse_results_file(_SAMPLE)
    assert rows[0].party_code == "REP"
    assert rows[0].party_name == "Republican Party"
    assert rows[1].party_code == "DEM"


def test_parse_race_fields():
    rows = parse_results_file(_SAMPLE)
    assert rows[0].race_code == "STS"
    assert rows[0].race_name == "State Senator, District 14"


def test_parse_county_fields():
    rows = parse_results_file(_SAMPLE)
    assert rows[0].county_code == "HIL"
    assert rows[0].county_name == "Hillsborough"


def test_parse_juris_fields():
    rows = parse_results_file(_SAMPLE)
    assert rows[0].juris1_num == "014"
    assert rows[0].juris2_num == ""   # stripped whitespace → empty string


def test_parse_precinct_counts():
    rows = parse_results_file(_SAMPLE)
    assert rows[0].precincts == 152
    assert rows[0].precincts_reporting == 152


def test_parse_candidate_name_fields():
    rows = parse_results_file(_SAMPLE)
    assert rows[0].can_name_last == "Tomkow"
    assert rows[0].can_name_first == "Josie"
    assert rows[0].can_name_middle == ""


def test_parse_can_votes():
    rows = parse_results_file(_SAMPLE)
    assert rows[0].can_votes == 39836
    assert rows[1].can_votes == 40245


def test_parse_skips_header_row():
    rows = parse_results_file(_SAMPLE)
    # No row should have election_date=None or race_name="RaceName"
    assert all(r.race_name != "RaceName" for r in rows)


def test_parse_empty_file_returns_empty_list():
    rows = parse_results_file("ElectionDate\tPartyCode\n")
    assert rows == []


def test_parse_multi_race_returns_all_rows():
    rows = parse_results_file(_MULTI_RACE_SAMPLE)
    assert len(rows) == 3


def test_parse_incomplete_results_precincts():
    rows = parse_results_file(_MULTI_RACE_SAMPLE)
    # 80 of 100 precincts reporting
    assert rows[0].precincts == 100
    assert rows[0].precincts_reporting == 80
```

- [ ] **Step 2: Run tests — confirm ImportError**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -m pytest --no-migrations integrations/fl_ew/tests/test_parsers.py -v 2>&1 | head -20
```
Expected: `ImportError` — `parsers.py` doesn't exist yet.

- [ ] **Step 3: Create `parsers.py`**

```python
# backend/integrations/fl_ew/parsers.py
"""
Parser for the Florida Election Watch tab-delimited results file.

File format (header row always present, no brackets):
  ElectionDate  PartyCode  PartyName  RaceCode  RaceName  CountyCode  CountyName
  Juris1num  Juris2num  Precincts  PrecinctsReporting  CanNameLast  CanNameFirst
  CanNameMiddle  CanVotes

ElectionDate format: MM/DD/YYYY
Juris2num is frequently blank/whitespace.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime

logger = logging.getLogger(__name__)


@dataclass
class ElectionRow:
    election_date: date
    party_code: str
    party_name: str
    race_code: str
    race_name: str
    county_code: str
    county_name: str
    juris1_num: str
    juris2_num: str
    precincts: int
    precincts_reporting: int
    can_name_last: str
    can_name_first: str
    can_name_middle: str
    can_votes: int


def _parse_date(raw: str) -> date | None:
    """Parse MM/DD/YYYY into a date object."""
    try:
        return datetime.strptime(raw.strip(), "%m/%d/%Y").date()
    except (ValueError, AttributeError):
        return None


def _safe_int(raw: str) -> int:
    try:
        return int(raw.strip().replace(",", ""))
    except (ValueError, AttributeError):
        return 0


def parse_results_file(text: str) -> list[ElectionRow]:
    """
    Parse the full tab-delimited results file text into a list of ElectionRow.
    The first row is always the header and is skipped.
    """
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    rows: list[ElectionRow] = []

    for line_num, raw in enumerate(reader, start=2):
        election_date = _parse_date(raw.get("ElectionDate", ""))
        if election_date is None:
            logger.warning("fl_ew.parser.bad_date line=%d raw=%r", line_num, raw)
            continue

        try:
            rows.append(ElectionRow(
                election_date=election_date,
                party_code=(raw.get("PartyCode") or "").strip(),
                party_name=(raw.get("PartyName") or "").strip(),
                race_code=(raw.get("RaceCode") or "").strip(),
                race_name=(raw.get("RaceName") or "").strip(),
                county_code=(raw.get("CountyCode") or "").strip(),
                county_name=(raw.get("CountyName") or "").strip(),
                juris1_num=(raw.get("Juris1num") or "").strip(),
                juris2_num=(raw.get("Juris2num") or "").strip(),
                precincts=_safe_int(raw.get("Precincts", "0")),
                precincts_reporting=_safe_int(raw.get("PrecinctsReporting", "0")),
                can_name_last=(raw.get("CanNameLast") or "").strip(),
                can_name_first=(raw.get("CanNameFirst") or "").strip(),
                can_name_middle=(raw.get("CanNameMiddle") or "").strip(),
                can_votes=_safe_int(raw.get("CanVotes", "0")),
            ))
        except Exception as exc:
            logger.warning("fl_ew.parser.row_error line=%d err=%s", line_num, exc)
            continue

    logger.info("fl_ew.parser.parsed rows=%d", len(rows))
    return rows
```

- [ ] **Step 4: Run tests — confirm all pass**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -m pytest --no-migrations integrations/fl_ew/tests/test_parsers.py -v
```
Expected: All tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/fl_ew/parsers.py backend/integrations/fl_ew/tests/test_parsers.py
git commit -m "feat(fl-ew): add tab-delimited parser (ElectionRow dataclass)"
```

---

## Task 5: fl_ew Mappers

**Files:**
- Create: `backend/integrations/fl_ew/mappers.py`
- Create: `backend/integrations/fl_ew/tests/test_mappers.py`

- [ ] **Step 1: Write failing tests**

Create `backend/integrations/fl_ew/tests/test_mappers.py`:

```python
"""
Unit tests for fl_ew mappers. No DB required.
"""
from datetime import date
from unittest.mock import MagicMock

import pytest

from integrations.fl_ew.mappers import (
    build_candidate_name,
    build_race_groups,
    infer_election_status,
    infer_election_type,
    map_candidate,
    map_election,
    map_race,
    normalize,
)
from integrations.fl_ew.parsers import ElectionRow


def _make_row(
    race_name="State Senator, District 14",
    party_code="REP",
    party_name="Republican Party",
    race_code="STS",
    juris1_num="014",
    juris2_num="",
    county_code="HIL",
    county_name="Hillsborough",
    can_name_last="Tomkow",
    can_name_first="Josie",
    can_name_middle="",
    can_votes=39836,
    precincts=152,
    precincts_reporting=152,
    election_date=None,
):
    return ElectionRow(
        election_date=election_date or date(2026, 3, 24),
        party_code=party_code,
        party_name=party_name,
        race_code=race_code,
        race_name=race_name,
        county_code=county_code,
        county_name=county_name,
        juris1_num=juris1_num,
        juris2_num=juris2_num,
        precincts=precincts,
        precincts_reporting=precincts_reporting,
        can_name_last=can_name_last,
        can_name_first=can_name_first,
        can_name_middle=can_name_middle,
        can_votes=can_votes,
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def test_normalize():
    assert normalize("  State Senator  ") == "state senator"
    assert normalize("State  Senator") == "state senator"
    assert normalize(None) == ""


def test_build_candidate_name_no_middle():
    row = _make_row(can_name_first="Josie", can_name_middle="", can_name_last="Tomkow")
    assert build_candidate_name(row) == "Josie Tomkow"


def test_build_candidate_name_with_middle():
    row = _make_row(can_name_first="Edwin", can_name_middle="S.", can_name_last="Perez")
    assert build_candidate_name(row) == "Edwin S. Perez"


def test_build_candidate_name_last_only():
    row = _make_row(can_name_first="", can_name_middle="", can_name_last="Yes")
    assert build_candidate_name(row) == "Yes"


# ---------------------------------------------------------------------------
# infer_election_type
# ---------------------------------------------------------------------------

def test_infer_election_type_primary():
    assert infer_election_type(date(2026, 8, 18)) == "primary"


def test_infer_election_type_general():
    assert infer_election_type(date(2026, 11, 3)) == "general"


def test_infer_election_type_special():
    assert infer_election_type(date(2026, 3, 24)) == "special"
    assert infer_election_type(date(2026, 4, 14)) == "special"


# ---------------------------------------------------------------------------
# infer_election_status
# ---------------------------------------------------------------------------

def test_infer_status_upcoming():
    from unittest.mock import patch
    with patch("integrations.fl_ew.mappers.timezone") as mock_tz:
        mock_tz.localdate.return_value = date(2026, 1, 1)
        assert infer_election_status(date(2026, 8, 18)) == "upcoming"


def test_infer_status_active():
    from unittest.mock import patch
    with patch("integrations.fl_ew.mappers.timezone") as mock_tz:
        mock_tz.localdate.return_value = date(2026, 8, 18)
        assert infer_election_status(date(2026, 8, 18)) == "active"


def test_infer_status_results_pending():
    from unittest.mock import patch
    with patch("integrations.fl_ew.mappers.timezone") as mock_tz:
        mock_tz.localdate.return_value = date(2026, 8, 19)
        assert infer_election_status(date(2026, 8, 18)) == "results_pending"


# ---------------------------------------------------------------------------
# map_election
# ---------------------------------------------------------------------------

def test_map_election_primary():
    row = _make_row(election_date=date(2026, 8, 18))
    result = map_election("20260818", row.election_date)

    assert result["source_id"] == "fl_ew:20260818"
    assert result["state"] == "FL"
    assert result["election_date"] == date(2026, 8, 18)
    assert result["election_type"] == "primary"
    assert result["jurisdiction_level"] == "state"
    assert result["source_metadata"]["fl_ew_slug"] == "20260818"


def test_map_election_general():
    result = map_election("20261103", date(2026, 11, 3))
    assert result["election_type"] == "general"
    assert "November" in result["name"] or "2026" in result["name"]


def test_map_election_special():
    result = map_election("20260324", date(2026, 3, 24))
    assert result["election_type"] == "special"


# ---------------------------------------------------------------------------
# build_race_groups
# ---------------------------------------------------------------------------

def test_build_race_groups_general_merges_parties():
    """In a general election, both REP and DEM candidates for same race → one group."""
    rows = [
        _make_row(party_code="REP", can_name_last="Tomkow"),
        _make_row(party_code="DEM", can_name_last="Nathan"),
    ]
    groups = build_race_groups(rows, is_primary=False)
    assert len(groups) == 1
    assert len(groups[0]["rows"]) == 2


def test_build_race_groups_primary_splits_by_party():
    """In a primary, REP and DEM rows for same race_name → two groups."""
    rows = [
        _make_row(race_name="Governor", party_code="REP", juris1_num="000"),
        _make_row(race_name="Governor", party_code="DEM", juris1_num="000"),
    ]
    groups = build_race_groups(rows, is_primary=True)
    assert len(groups) == 2
    party_codes = {g["party_code"] for g in groups}
    assert party_codes == {"REP", "DEM"}


def test_build_race_groups_different_districts():
    """Different juris1_num → always separate groups regardless of primary flag."""
    rows = [
        _make_row(race_name="State Senator", juris1_num="014", party_code="REP"),
        _make_row(race_name="State Senator", juris1_num="016", party_code="REP"),
    ]
    groups = build_race_groups(rows, is_primary=False)
    assert len(groups) == 2


# ---------------------------------------------------------------------------
# map_race
# ---------------------------------------------------------------------------

def _make_election_obj(status="upcoming", election_type="special"):
    e = MagicMock()
    e.status = status
    e.election_type = election_type
    e.source_id = "fl_ew:20260324"
    e.canonical_key = "fl:special:2026-03-24:state"
    return e


def test_map_race_basic():
    election = _make_election_obj()
    group = {
        "race_name": "State Senator, District 14",
        "race_code": "STS",
        "juris1_num": "014",
        "juris2_num": "",
        "party_code": "",
        "party_name": "",
        "rows": [_make_row()],
    }
    result = map_race(election, group)

    assert result["race_type"] == "candidate"
    assert result["office_title"] == "State Senator, District 14"
    assert result["source_metadata"]["fl_ew_race_code"] == "STS"
    assert result["source_metadata"]["fl_ew_juris1_num"] == "014"
    assert result["vote_method"] == "single_choice"
    assert result["max_selections"] == 1


def test_map_race_certification_upcoming():
    election = _make_election_obj(status="upcoming")
    group = {
        "race_name": "Governor",
        "race_code": "GOV",
        "juris1_num": "000",
        "juris2_num": "",
        "party_code": "REP",
        "party_name": "Republican Party",
        "rows": [],
    }
    result = map_race(election, group)
    assert result["certification_status"] == "upcoming"


def test_map_race_certification_results_pending():
    election = _make_election_obj(status="results_pending")
    group = {
        "race_name": "Governor",
        "race_code": "GOV",
        "juris1_num": "000",
        "juris2_num": "",
        "party_code": "",
        "party_name": "",
        "rows": [],
    }
    result = map_race(election, group)
    assert result["certification_status"] == "results_pending"


# ---------------------------------------------------------------------------
# map_candidate
# ---------------------------------------------------------------------------

def test_map_candidate_basic():
    row = _make_row(
        can_name_first="Josie",
        can_name_middle="",
        can_name_last="Tomkow",
        party_code="REP",
        party_name="Republican Party",
    )
    name, party, fields = map_candidate(row)

    assert name == "Josie Tomkow"
    assert party == "Republican Party"
    assert fields["incumbent"] is False
    assert fields["source_metadata"]["fl_ew_party_code"] == "REP"


def test_map_candidate_uses_party_name_over_code():
    row = _make_row(party_code="REP", party_name="Republican Party")
    _, party, _ = map_candidate(row)
    assert party == "Republican Party"


def test_map_candidate_falls_back_to_party_code():
    row = _make_row(party_code="NPA", party_name="")
    _, party, _ = map_candidate(row)
    assert party == "NPA"
```

- [ ] **Step 2: Run tests — confirm ImportError**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -m pytest --no-migrations integrations/fl_ew/tests/test_mappers.py -v 2>&1 | head -20
```
Expected: `ImportError` — `mappers.py` doesn't exist yet.

- [ ] **Step 3: Create `mappers.py`**

```python
# backend/integrations/fl_ew/mappers.py
"""
Mappers for FL Election Watch tab-delimited data → CivicMirror model fields.
"""
from __future__ import annotations

from datetime import date

from django.utils import timezone

from elections.models import Candidate, Election, Race

from .parsers import ElectionRow


def normalize(text: str | None) -> str:
    return " ".join((text or "").strip().lower().split())


def build_candidate_name(row: ElectionRow) -> str:
    parts = [row.can_name_first, row.can_name_middle, row.can_name_last]
    return " ".join(p for p in parts if p).strip()


def infer_election_type(election_date: date) -> str:
    if election_date.month == 11:
        return Election.ElectionType.GENERAL
    if election_date.month in {8, 9}:
        return Election.ElectionType.PRIMARY
    return Election.ElectionType.SPECIAL


def infer_election_status(election_date: date) -> str:
    today = timezone.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def map_election(slug: str, election_date: date) -> dict:
    """Map a date slug → Election model field values."""
    election_type = infer_election_type(election_date)
    date_label = election_date.strftime("%B %-d, %Y")
    type_label = election_type.replace("_", " ").title()
    name = f"Florida {date_label} {type_label}"

    return {
        "source_id": f"fl_ew:{slug}",
        "name": name,
        "election_date": election_date,
        "election_type": election_type,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "FL",
        "status": infer_election_status(election_date),
        "source_metadata": {
            "fl_ew_slug": slug,
        },
    }


def build_race_groups(rows: list[ElectionRow], is_primary: bool) -> list[dict]:
    """
    Group ElectionRow list into race dicts.

    For primary elections: partition by (race_name, juris1_num, juris2_num, party_code)
    so that REP and DEM primaries for the same office are tracked as separate races.

    For general/special elections: partition by (race_name, juris1_num, juris2_num)
    so all candidates across parties share one race.
    """
    groups: dict[tuple, dict] = {}

    for row in rows:
        if is_primary:
            key = (row.race_name, row.juris1_num, row.juris2_num, row.party_code)
            party_code = row.party_code
            party_name = row.party_name
        else:
            key = (row.race_name, row.juris1_num, row.juris2_num)
            party_code = ""
            party_name = ""

        if key not in groups:
            groups[key] = {
                "race_name": row.race_name,
                "race_code": row.race_code,
                "juris1_num": row.juris1_num,
                "juris2_num": row.juris2_num,
                "party_code": party_code,
                "party_name": party_name,
                "rows": [],
            }
        groups[key]["rows"].append(row)

    return list(groups.values())


def map_race(election_obj: Election, group: dict) -> dict:
    """Map a race group dict → Race model field values."""
    office_title = group["race_name"]
    certification_status = (
        Race.CertificationStatus.UPCOMING
        if election_obj.status in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_PENDING
    )

    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office_title,
        "normalized_office_title": normalize(office_title),
        "jurisdiction": "Florida",
        "geography_scope": "statewide" if not group["juris1_num"] else "district",
        "certification_status": certification_status,
        "source": Race.Source.FL_EW,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "source_metadata": {
            "fl_ew_race_code": group["race_code"],
            "fl_ew_juris1_num": group["juris1_num"],
            "fl_ew_juris2_num": group["juris2_num"],
            "fl_ew_party_code": group["party_code"],
            "fl_ew_party_name": group["party_name"],
        },
    }


def map_candidate(row: ElectionRow) -> tuple[str, str, dict]:
    """
    Map an ElectionRow → (name, party, fields) for ingest_candidate.

    Returns a 3-tuple so the caller can unpack directly into the ingest call.
    """
    name = build_candidate_name(row)
    party = row.party_name or row.party_code
    fields = {
        "incumbent": False,
        "candidate_status": Candidate.CandidateStatus.RUNNING,
        "source_metadata": {
            "fl_ew_party_code": row.party_code,
        },
    }
    return name, party, fields
```

- [ ] **Step 4: Run tests — confirm all pass**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -m pytest --no-migrations integrations/fl_ew/tests/test_mappers.py -v
```
Expected: All tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/fl_ew/mappers.py backend/integrations/fl_ew/tests/test_mappers.py
git commit -m "feat(fl-ew): add election/race/candidate mappers"
```

---

## Task 6: fl_ew Tasks

**Files:**
- Create: `backend/integrations/fl_ew/tasks.py`
- Create: `backend/integrations/fl_ew/tests/test_tasks.py`

- [ ] **Step 1: Write failing tests**

Create `backend/integrations/fl_ew/tests/test_tasks.py`:

```python
"""
Unit tests for fl_ew Celery tasks. DB and Celery are mocked — no network.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from integrations.fl_ew.tasks import sync_fl_elections, sync_fl_races


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _mock_sync_log():
    log = MagicMock()
    log.Status = MagicMock()
    log.Status.STARTED = "started"
    log.Status.COMPLETED = "completed"
    log.Status.FAILED = "failed"
    return log


def _make_election_obj(pk=1, status="upcoming", election_type="primary"):
    e = MagicMock()
    e.pk = pk
    e.status = status
    e.election_type = election_type
    e.source_id = "fl_ew:20260818"
    e.canonical_key = "fl:primary:2026-08-18:state"
    e.source_metadata = {"fl_ew_slug": "20260818"}
    return e


# ---------------------------------------------------------------------------
# sync_fl_elections
# ---------------------------------------------------------------------------

def test_sync_fl_elections_skips_404_slugs():
    """When file returns 404, no elections are created."""
    from integrations.fl_ew.exceptions import FlEwError

    mock_log = _mock_sync_log()
    with patch("integrations.fl_ew.tasks.FlEwClient") as MockClient, \
         patch("integrations.fl_ew.tasks.SyncLog") as MockSyncLog:

        MockSyncLog.objects.create.return_value = mock_log
        MockSyncLog.Status.STARTED = "started"
        MockSyncLog.Status.COMPLETED = "completed"

        client = MockClient.return_value
        client.get_last_modified.return_value = ""  # 404 / file not found

        result = sync_fl_elections()

    assert result["created"] == 0
    assert result["skipped"] > 0


def test_sync_fl_elections_creates_election_and_queues_races():
    """Valid slug → election upserted, sync_fl_races queued."""
    mock_election = _make_election_obj()
    mock_log = _mock_sync_log()

    with patch("integrations.fl_ew.tasks.FlEwClient") as MockClient, \
         patch("integrations.fl_ew.tasks.SyncLog") as MockSyncLog, \
         patch("integrations.fl_ew.tasks.sync_fl_races") as mock_races, \
         patch("aggregation.ingest.ingest_election", return_value=(mock_election, True)):

        MockSyncLog.objects.create.return_value = mock_log
        MockSyncLog.Status.STARTED = "started"
        MockSyncLog.Status.COMPLETED = "completed"

        client = MockClient.return_value
        # First slug has a file, rest don't
        from integrations.fl_ew.client import KNOWN_ELECTION_SLUGS
        side_effects = ["Mon, 18 Aug 2026 01:00:00 GMT"] + [""] * (len(KNOWN_ELECTION_SLUGS) - 1)
        client.get_last_modified.side_effect = side_effects

        result = sync_fl_elections()

    mock_races.apply_async.assert_called_once()
    assert result["created"] == 1
    assert result["queued"] == 1


# ---------------------------------------------------------------------------
# sync_fl_races
# ---------------------------------------------------------------------------

_TSV = (
    "ElectionDate\tPartyCode\tPartyName\tRaceCode\tRaceName\tCountyCode\t"
    "CountyName\tJuris1num\tJuris2num\tPrecincts\tPrecinctsReporting\t"
    "CanNameLast\tCanNameFirst\tCanNameMiddle\tCanVotes\n"
    "08/18/2026\tREP\tRepublican Party\tSTS\tState Senator, District 14\t"
    "HIL\tHillsborough\t014\t\t152\t152\tSmith\tAlice\t\t39000\n"
    "08/18/2026\tDEM\tDemocratic Party\tSTS\tState Senator, District 14\t"
    "HIL\tHillsborough\t014\t\t152\t80\tJones\tBob\t\t41000\n"
)


def test_sync_fl_races_no_rows_returns_zero():
    """Empty file → task completes with zero races."""
    _EMPTY_TSV = "ElectionDate\tPartyCode\tPartyName\tRaceCode\tRaceName\tCountyCode\tCountyName\tJuris1num\tJuris2num\tPrecincts\tPrecinctsReporting\tCanNameLast\tCanNameFirst\tCanNameMiddle\tCanVotes\n"
    mock_election = _make_election_obj()
    mock_log = _mock_sync_log()

    with patch("integrations.fl_ew.tasks.Election") as MockElection, \
         patch("integrations.fl_ew.tasks.FlEwClient") as MockClient, \
         patch("integrations.fl_ew.tasks.SyncLog") as MockSyncLog:

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception
        MockSyncLog.objects.create.return_value = mock_log
        MockSyncLog.Status.STARTED = "started"
        MockSyncLog.Status.COMPLETED = "completed"

        client = MockClient.return_value
        client.fetch_results_file.return_value = _EMPTY_TSV

        result = sync_fl_races(1, "20260818")

    assert result == {"races": 0, "candidates": 0}


def test_sync_fl_races_general_election_creates_one_race_two_candidates():
    """General election: REP + DEM for same office → one race, two candidates."""
    mock_election = _make_election_obj(election_type="special")
    mock_race = MagicMock()
    mock_race.pk = 10
    mock_cand = MagicMock()
    mock_log = _mock_sync_log()

    with patch("integrations.fl_ew.tasks.Election") as MockElection, \
         patch("integrations.fl_ew.tasks.FlEwClient") as MockClient, \
         patch("integrations.fl_ew.tasks.SyncLog") as MockSyncLog, \
         patch("aggregation.ingest.ingest_race", return_value=(mock_race, True)) as mock_ir, \
         patch("aggregation.ingest.ingest_candidate", return_value=(mock_cand, True)) as mock_ic:

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception
        MockElection.Status.UPCOMING = "upcoming"
        MockElection.Status.ACTIVE = "active"
        MockSyncLog.objects.create.return_value = mock_log
        MockSyncLog.Status.STARTED = "started"
        MockSyncLog.Status.COMPLETED = "completed"

        client = MockClient.return_value
        client.fetch_results_file.return_value = _TSV

        result = sync_fl_races(1, "20260818")

    # One race (both parties merged in general), two candidates
    assert mock_ir.call_count == 1
    assert mock_ic.call_count == 2
    assert result["races"]["created"] == 1
    assert result["candidates"]["created"] == 2


def test_sync_fl_races_primary_creates_two_races():
    """Primary election: REP + DEM for same office → two separate races."""
    mock_election = _make_election_obj(election_type="primary")
    mock_race = MagicMock()
    mock_race.pk = 10
    mock_cand = MagicMock()
    mock_log = _mock_sync_log()

    with patch("integrations.fl_ew.tasks.Election") as MockElection, \
         patch("integrations.fl_ew.tasks.FlEwClient") as MockClient, \
         patch("integrations.fl_ew.tasks.SyncLog") as MockSyncLog, \
         patch("aggregation.ingest.ingest_race", return_value=(mock_race, True)) as mock_ir, \
         patch("aggregation.ingest.ingest_candidate", return_value=(mock_cand, True)) as mock_ic:

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception
        MockElection.Status.UPCOMING = "upcoming"
        MockElection.Status.ACTIVE = "active"
        MockSyncLog.objects.create.return_value = mock_log
        MockSyncLog.Status.STARTED = "started"
        MockSyncLog.Status.COMPLETED = "completed"

        client = MockClient.return_value
        client.fetch_results_file.return_value = _TSV

        result = sync_fl_races(1, "20260818")

    # Two races (one per party), one candidate each
    assert mock_ir.call_count == 2
    assert mock_ic.call_count == 2
    assert result["races"]["created"] == 2
```

- [ ] **Step 2: Run tests — confirm ImportError**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -m pytest --no-migrations integrations/fl_ew/tests/test_tasks.py -v 2>&1 | head -20
```
Expected: `ImportError` — `tasks.py` doesn't exist yet.

- [ ] **Step 3: Create `tasks.py`**

```python
# backend/integrations/fl_ew/tasks.py
"""
Florida Election Watch Celery tasks.

Stage 1 — sync_fl_elections:
  Probe known FL election date slugs using a HEAD request.
  If the file exists, upsert the Election record and queue sync_fl_races.

Stage 2 — sync_fl_races:
  Fetch the tab-delimited results file for one election.
  Group rows into races (split by party for primaries).
  Upsert Race + Candidate records via aggregation ingest.

Trigger endpoint: POST /internal/tasks/sync-fl-ew/
"""
from __future__ import annotations

import logging
from datetime import datetime

from celery import shared_task
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog

from .client import KNOWN_ELECTION_SLUGS, FlEwClient
from .exceptions import FlEwRetryableError
from .mappers import (
    build_race_groups,
    infer_election_type,
    map_candidate,
    map_election,
    map_race,
)
from .parsers import parse_results_file

logger = logging.getLogger(__name__)
_SOURCE = "fl_ew"


def _slug_to_date(slug: str):
    """Parse a YYYYMMDD slug into a date."""
    try:
        return datetime.strptime(slug, "%Y%m%d").date()
    except ValueError:
        return None


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_fl_elections(self):
    """Stage 1: Probe known FL election slugs and queue race syncs."""
    sync_log = SyncLog.objects.create(
        source=_SOURCE,
        task_name="sync_fl_elections",
        status=SyncLog.Status.STARTED,
    )
    client = FlEwClient()
    created_count = updated_count = queued_count = skipped_count = 0

    try:
        from aggregation import ingest

        election_queue: list[tuple[str, object]] = []

        for slug in KNOWN_ELECTION_SLUGS:
            last_modified = client.get_last_modified(slug)
            if not last_modified:
                logger.info("fl_ew.sync_elections.not_published slug=%s", slug)
                skipped_count += 1
                continue

            election_date = _slug_to_date(slug)
            if election_date is None:
                logger.warning("fl_ew.sync_elections.bad_slug slug=%s", slug)
                skipped_count += 1
                continue

            mapped = map_election(slug, election_date)
            source_id = mapped.pop("source_id")
            identity = {
                "state":              mapped["state"],
                "election_type":      mapped["election_type"],
                "election_date":      mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            fields = {k: v for k, v in mapped.items() if k not in identity}

            election_obj, was_created = ingest.ingest_election(
                source=_SOURCE,
                source_id=source_id,
                identity=identity,
                fields=fields,
            )

            current_meta = dict(election_obj.source_metadata or {})
            if not current_meta.get("fl_ew_slug"):
                current_meta["fl_ew_slug"] = slug
                election_obj.source_metadata = current_meta
                election_obj.save(update_fields=["source_metadata"])

            if was_created:
                created_count += 1
            else:
                updated_count += 1

            election_queue.append((slug, election_obj))

        for idx, (slug, election_obj) in enumerate(election_queue):
            sync_fl_races.apply_async(
                args=[election_obj.pk, slug],
                countdown=idx * 5,
            )
            queued_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.records_skipped = skipped_count
        sync_log.notes = f"Queued {queued_count} race sync(s); {skipped_count} slug(s) not yet published"
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
        logger.exception("fl_ew.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_fl_races(self, election_pk: int, slug: str):
    """Stage 2: Fetch results file and upsert Race + Candidate records."""
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("fl_ew.sync_races.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source=_SOURCE,
        task_name="sync_fl_races",
        status=SyncLog.Status.STARTED,
    )
    client = FlEwClient()
    race_created = race_updated = cand_created = cand_updated = 0

    try:
        text = client.fetch_results_file(slug)
        rows = parse_results_file(text)

        if not rows:
            sync_log.notes = "File fetched but contained no data rows"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"races": 0, "candidates": 0}

        from aggregation import ingest

        is_primary = election_obj.election_type == Election.ElectionType.PRIMARY
        race_groups = build_race_groups(rows, is_primary=is_primary)

        for group in race_groups:
            race_fields = map_race(election_obj, group)
            race_fields.pop("source", None)

            race_identity = {
                "office_title":    race_fields.pop("office_title"),
                "ocd_division_id": race_fields.pop("ocd_division_id", "") or "",
                "race_type":       race_fields.pop("race_type"),
            }

            if not race_identity["office_title"]:
                logger.warning(
                    "fl_ew.sync_races.null_title election=%s group=%r",
                    election_obj.source_id, group.get("race_name"),
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

            seen_names: set[str] = set()
            for row in group["rows"]:
                name, party, fields = map_candidate(row)
                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                _, cand_was_new = ingest.ingest_candidate(
                    race=race_obj,
                    source=_SOURCE,
                    name=name,
                    party=party,
                    fields=fields,
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
        sync_log.save(update_fields=[
            "records_created", "records_updated", "status", "completed_at",
        ])

        return {
            "races": {"created": race_created, "updated": race_updated},
            "candidates": {"created": cand_created, "updated": cand_updated},
        }

    except FlEwRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("fl_ew.sync_races.failed election=%s slug=%s", election_pk, slug)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

- [ ] **Step 4: Run tests — confirm all pass**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -m pytest --no-migrations integrations/fl_ew/tests/test_tasks.py -v
```
Expected: All tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/fl_ew/tasks.py backend/integrations/fl_ew/tests/test_tasks.py
git commit -m "feat(fl-ew): add sync_fl_elections + sync_fl_races tasks"
```

---

## Task 7: Florida Results Adapter

**Files:**
- Create: `backend/results/adapters/fl.py`
- Create: `backend/results/tests/test_fl_adapter.py`

- [ ] **Step 1: Write failing tests**

Create `backend/results/tests/test_fl_adapter.py`:

```python
"""
Unit tests for the Florida Election Watch results adapter.
HTTP calls are fully mocked — no network required.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.base import AdapterResult, ResultRow
from results.adapters.fl import FloridaAdapter


def test_fl_adapter_registered():
    import results.adapters.fl  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "FL" in list_supported_states()
    assert get_adapter("FL") is FloridaAdapter
    assert get_adapter("fl") is FloridaAdapter


_MOCK_ELECTION = MagicMock()
_MOCK_ELECTION.source_metadata = {"fl_ew_slug": "20260324"}
_MOCK_ELECTION.pk = 1


_TSV = (
    "ElectionDate\tPartyCode\tPartyName\tRaceCode\tRaceName\tCountyCode\t"
    "CountyName\tJuris1num\tJuris2num\tPrecincts\tPrecinctsReporting\t"
    "CanNameLast\tCanNameFirst\tCanNameMiddle\tCanVotes\n"
    "03/24/2026\tREP\tRepublican Party\tSTS\tState Senator, District 14\t"
    "HIL\tHillsborough\t014\t\t152\t152\tTomkow\tJosie\t\t39836\n"
    "03/24/2026\tDEM\tDemocratic Party\tSTS\tState Senator, District 14\t"
    "HIL\tHillsborough\t014\t\t152\t152\tNathan\tBrian\t\t40245\n"
)


def test_fetch_results_no_slug():
    """Election with no fl_ew_slug in source_metadata → mapping_confidence=none."""
    adapter = FloridaAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {}

    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results(date(2026, 3, 24), election_id=1)

    assert isinstance(result, AdapterResult)
    assert result.mapping_confidence == "none"
    assert result.rows == []
    assert "fl_ew_slug" in result.notes


def test_fetch_results_unchanged_version():
    """Cached Last-Modified matches current → returns unchanged=True."""
    adapter = FloridaAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.fl.FlEwClient") as MockClient, \
         patch("results.adapters.fl.cache") as mock_cache:

        mock_mgr.get.return_value = _MOCK_ELECTION
        mock_cache.get.return_value = "Mon, 24 Mar 2026 22:00:00 GMT"

        client = MockClient.return_value
        client.get_last_modified.return_value = "Mon, 24 Mar 2026 22:00:00 GMT"
        client.file_url.return_value = "https://flelectionfiles.floridados.gov/enightfilespublic/20260324_ElecResultsFL.txt"

        result = adapter.fetch_results(date(2026, 3, 24), election_id=1)

    assert result.unchanged is True
    assert result.rows == []
    assert result.source_version == "Mon, 24 Mar 2026 22:00:00 GMT"


def test_fetch_results_returns_one_row_per_candidate_per_county():
    """Two candidates in one county → two ResultRows."""
    adapter = FloridaAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.fl.FlEwClient") as MockClient, \
         patch("results.adapters.fl.cache") as mock_cache:

        mock_mgr.get.return_value = _MOCK_ELECTION
        mock_cache.get.return_value = None

        client = MockClient.return_value
        client.get_last_modified.return_value = "Mon, 24 Mar 2026 22:00:00 GMT"
        client.file_url.return_value = (
            "https://flelectionfiles.floridados.gov/enightfilespublic/20260324_ElecResultsFL.txt"
        )
        client.fetch_results_file.return_value = _TSV

        result = adapter.fetch_results(date(2026, 3, 24), election_id=1)

    assert len(result.rows) == 2
    assert result.mapping_confidence == "full"
    assert result.unchanged is False


def test_result_row_fields():
    """Validate ResultRow field mapping from a known data row."""
    adapter = FloridaAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.fl.FlEwClient") as MockClient, \
         patch("results.adapters.fl.cache") as mock_cache:

        mock_mgr.get.return_value = _MOCK_ELECTION
        mock_cache.get.return_value = None

        client = MockClient.return_value
        client.get_last_modified.return_value = "v1"
        client.file_url.return_value = "https://flelectionfiles.floridados.gov/enightfilespublic/20260324_ElecResultsFL.txt"
        client.fetch_results_file.return_value = _TSV

        result = adapter.fetch_results(date(2026, 3, 24), election_id=1)

    tomkow_row = next(r for r in result.rows if r.candidate_name == "Josie Tomkow")
    assert tomkow_row.vote_count == 39836
    assert tomkow_row.vote_pct is None
    assert tomkow_row.result_type == "official"   # 152/152 precincts reporting
    assert tomkow_row.jurisdiction_fragment == "hil"
    assert tomkow_row.office_title == "State Senator, District 14"
    assert tomkow_row.raw["party_code"] == "REP"
    assert tomkow_row.raw["county_name"] == "Hillsborough"
    assert tomkow_row.raw["fl_ew_slug"] == "20260324"


def test_result_type_unofficial_when_precincts_incomplete():
    """PrecinctsReporting < Precincts → result_type='unofficial'."""
    adapter = FloridaAdapter()
    partial_tsv = (
        "ElectionDate\tPartyCode\tPartyName\tRaceCode\tRaceName\tCountyCode\t"
        "CountyName\tJuris1num\tJuris2num\tPrecincts\tPrecinctsReporting\t"
        "CanNameLast\tCanNameFirst\tCanNameMiddle\tCanVotes\n"
        "08/18/2026\tREP\tRepublican Party\tGOV\tGovernor\t"
        "ALA\tAlachua\t000\t\t100\t60\tSmith\tAlice\t\t5000\n"
    )
    mock_election = MagicMock()
    mock_election.source_metadata = {"fl_ew_slug": "20260818"}
    mock_election.pk = 2

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.fl.FlEwClient") as MockClient, \
         patch("results.adapters.fl.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None

        client = MockClient.return_value
        client.get_last_modified.return_value = "v2"
        client.file_url.return_value = "https://flelectionfiles.floridados.gov/enightfilespublic/20260818_ElecResultsFL.txt"
        client.fetch_results_file.return_value = partial_tsv

        result = adapter.fetch_results(date(2026, 8, 18), election_id=2)

    assert result.rows[0].result_type == "unofficial"


def test_fetch_results_election_not_found():
    adapter = FloridaAdapter()
    with patch("elections.models.Election.objects") as mock_mgr:
        from elections.models import Election
        mock_mgr.get.side_effect = Election.DoesNotExist
        result = adapter.fetch_results(date(2026, 3, 24), election_id=999)

    assert result.mapping_confidence == "none"
    assert result.rows == []


def test_source_version_written_to_result():
    adapter = FloridaAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.fl.FlEwClient") as MockClient, \
         patch("results.adapters.fl.cache") as mock_cache:

        mock_mgr.get.return_value = _MOCK_ELECTION
        mock_cache.get.return_value = None

        client = MockClient.return_value
        client.get_last_modified.return_value = "Mon, 24 Mar 2026 22:00:00 GMT"
        client.file_url.return_value = "https://example.com/f.txt"
        client.fetch_results_file.return_value = _TSV

        result = adapter.fetch_results(date(2026, 3, 24), election_id=1)

    assert result.source_version == "Mon, 24 Mar 2026 22:00:00 GMT"
```

- [ ] **Step 2: Run tests — confirm ImportError**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -m pytest --no-migrations results/tests/test_fl_adapter.py -v 2>&1 | head -20
```
Expected: `ImportError` — `fl.py` doesn't exist yet.

- [ ] **Step 3: Create `results/adapters/fl.py`**

```python
# backend/results/adapters/fl.py
"""
Florida Election Watch results adapter.

Fetches the tab-delimited results file from flelectionfiles.floridados.gov
and maps each row to a ResultRow with:
  - candidate_name from CanNameFirst/CanNameMiddle/CanNameLast
  - vote_count from CanVotes
  - result_type: 'official' if PrecinctsReporting == Precincts, else 'unofficial'
  - jurisdiction_fragment: CountyCode.lower() (e.g. 'hil' for Hillsborough)
  - vote_pct: None (not provided in this file)

Version detection: Last-Modified header cached in Redis by election_id.
"""
from __future__ import annotations

import logging

from django.core.cache import cache

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_VERSION_CACHE_TTL = 86400 * 30  # 30 days


@register
class FloridaAdapter(StateResultsAdapter):
    state = "FL"

    def _version_cache_key(self, election_id: int) -> str:
        return f"fl_ew:ver:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election
        from integrations.fl_ew.client import FlEwClient
        from integrations.fl_ew.mappers import build_candidate_name
        from integrations.fl_ew.parsers import parse_results_file

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("FLAdapter: election %d not found", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election {election_id} not found",
            )

        slug = (election.source_metadata or {}).get("fl_ew_slug")
        if not slug:
            logger.warning("FLAdapter: no fl_ew_slug for election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes="No fl_ew_slug in election.source_metadata — run sync_fl_elections first",
            )

        client = FlEwClient()
        source_url = client.file_url(slug)

        last_modified = client.get_last_modified(slug)
        cache_key = self._version_cache_key(election_id)
        if last_modified and cache.get(cache_key) == last_modified:
            logger.debug("FLAdapter: version unchanged slug=%s", slug)
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="full",
                unchanged=True, source_version=last_modified,
            )

        try:
            text = client.fetch_results_file(slug)
        except Exception as exc:
            logger.error("FLAdapter: fetch failed slug=%s: %s", slug, exc)
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="none",
                notes=f"Fetch failed: {exc}",
            )

        rows_data = parse_results_file(text)
        if not rows_data:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="none",
                notes="File fetched but contained no data rows",
            )

        result_rows: list[ResultRow] = []
        for row in rows_data:
            candidate_name = build_candidate_name(row)
            is_complete = row.precincts > 0 and row.precincts_reporting >= row.precincts
            result_type = "official" if is_complete else "unofficial"

            result_rows.append(ResultRow(
                candidate_name=candidate_name or None,
                option_label=None,
                vote_count=row.can_votes,
                vote_pct=None,
                is_winner=None,
                result_type=result_type,
                office_title=row.race_name or None,
                jurisdiction_fragment=row.county_code.lower(),
                raw={
                    "party_code": row.party_code,
                    "party_name": row.party_name,
                    "race_code": row.race_code,
                    "county_name": row.county_name,
                    "juris1_num": row.juris1_num,
                    "juris2_num": row.juris2_num,
                    "precincts": row.precincts,
                    "precincts_reporting": row.precincts_reporting,
                    "fl_ew_slug": slug,
                },
            ))

        logger.info(
            "FLAdapter: slug=%s rows=%d", slug, len(result_rows),
        )

        return AdapterResult(
            rows=result_rows,
            source_url=source_url,
            mapping_confidence="full",
            source_version=last_modified,
        )
```

- [ ] **Step 4: Run adapter tests — confirm all pass**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -m pytest --no-migrations results/tests/test_fl_adapter.py -v
```
Expected: All tests `PASSED`.

- [ ] **Step 5: Run full suite — check for regressions**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -m pytest --no-migrations -q
```
Expected: No regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/results/adapters/fl.py backend/results/tests/test_fl_adapter.py
git commit -m "feat(fl): add Florida Election Watch results adapter"
```

---

## Task 8: Internal Trigger Endpoint

**Files:**
- Modify: `backend/internal/task_locks.py`
- Modify: `backend/internal/views.py`
- Modify: `backend/internal/urls.py`

- [ ] **Step 1: Add lock entry to `task_locks.py`**

In `backend/internal/task_locks.py`, add `"sync_fl_ew"` to the `TASK_LOCKS` dict after `"sync_wa_votewa"`:

```python
    "sync_wa_votewa":       (WINDOW_DAILY,      23 * _HOUR),
    "sync_fl_ew":           (WINDOW_DAILY,      23 * _HOUR),
```

- [ ] **Step 2: Add trigger view to `views.py`**

In `backend/internal/views.py`, add one import at the top with the other integration imports:

```python
from integrations.fl_ew.tasks import sync_fl_elections
```

Then add the view function at the bottom of the file:

```python
@csrf_exempt
@require_POST
@require_internal_task_token
def sync_fl_ew_trigger(request):
    return _trigger("sync_fl_ew", sync_fl_elections, request)
```

- [ ] **Step 3: Add URL to `urls.py`**

In `backend/internal/urls.py`, add after the `sync-wa-votewa` path:

```python
    path("tasks/sync-fl-ew/", views.sync_fl_ew_trigger, name="internal-sync-fl-ew"),
```

- [ ] **Step 4: Verify the URL resolves**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -c "
from django.test import RequestFactory
from django.urls import reverse
print(reverse('internal-sync-fl-ew'))
"
```
Expected: `/internal/tasks/sync-fl-ew/`

- [ ] **Step 5: Commit**

```bash
git add backend/internal/task_locks.py backend/internal/views.py backend/internal/urls.py
git commit -m "feat(fl-ew): wire internal trigger endpoint and scheduler lock"
```

---

## Task 9: Aggregation Precedence Migration

**Files:**
- Create: `backend/aggregation/migrations/0011_seed_fl_ew_precedence.py`

- [ ] **Step 1: Create migration**

```python
# backend/aggregation/migrations/0011_seed_fl_ew_precedence.py
from django.db import migrations

_FL_ROWS = [
    ("FL", "results",  "fl_ew",    0),
    ("FL", "results",  "civic_api", 1),
    ("FL", "date",     "fl_ew",    0),
    ("FL", "date",     "civic_api", 1),
    ("FL", "contacts", "civic_api", 0),
    ("FL", "contacts", "fl_ew",    1),
    ("FL", "identity", "civic_api", 0),
    ("FL", "identity", "fl_ew",    1),
]


def seed_fl_ew_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _FL_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_fl_ew_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="FL").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0010_merge_ia_sc_enr_fec_leaf_nodes"),
    ]

    operations = [
        migrations.RunPython(seed_fl_ew_precedence, remove_fl_ew_precedence),
    ]
```

- [ ] **Step 2: Verify migration runs without errors**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python manage.py migrate aggregation 0011_seed_fl_ew_precedence --run-syncdb 2>&1 | tail -5
```
Expected: `OK` — no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/aggregation/migrations/0011_seed_fl_ew_precedence.py
git commit -m "feat(fl-ew): add FL source precedence migration (0011)"
```

---

## Task 10: Full Suite + Final Integration Check

**Files:** No new files — validation only.

- [ ] **Step 1: Run all fl_ew and fl adapter tests together**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -m pytest --no-migrations integrations/fl_ew/ results/tests/test_fl_adapter.py -v
```
Expected: All tests `PASSED`.

- [ ] **Step 2: Run full test suite**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -m pytest --no-migrations -q
```
Expected: No regressions. All existing tests continue to pass.

- [ ] **Step 3: Verify FL adapter is registered**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -c "
from results.adapters.registry import get_adapter, list_supported_states
print('FL registered:', 'FL' in list_supported_states())
print('Adapter class:', get_adapter('FL'))
"
```
Expected:
```
FL registered: True
Adapter class: <class 'results.adapters.fl.FloridaAdapter'>
```

- [ ] **Step 4: Verify Race.Source.FL_EW and INSTALLED_APPS**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python -c "
from elections.models import Race
print('Race.Source.FL_EW:', Race.Source.FL_EW)
import django
django.setup()
from django.apps import apps
print('fl_ew app loaded:', apps.is_installed('integrations.fl_ew'))
"
```
Expected:
```
Race.Source.FL_EW: fl_ew
fl_ew app loaded: True
```

- [ ] **Step 5: Final commit (plan file)**

```bash
git add docs/superpowers/plans/2026-06-15-fl-ew-integration.md
git commit -m "docs: add FL Election Watch integration implementation plan"
```

---

## Self-Review

**Spec coverage check:**

| Design requirement | Covered in |
|---|---|
| Tab-delimited single-file approach | Tasks 3, 4, 7 |
| `flelectionfiles.floridados.gov` URL (not `myflorida.com`) | Task 3 (`client.py`) |
| `civicmirror.app` User-Agent | Task 3 (`client.py`) |
| `ElectionRow` dataclass with all 15 columns | Task 4 |
| Primary vs general race grouping | Tasks 5 + 6 |
| `Race.Source.FL_EW` + migration 0018 | Task 1 |
| `sync_fl_elections` + `sync_fl_races` Celery tasks | Task 6 |
| Version detection via `Last-Modified` | Tasks 3, 7 |
| `result_type` official/unofficial via precinct counts | Task 7 |
| `jurisdiction_fragment = county_code.lower()` | Task 7 |
| `vote_pct = None` (not in file) | Task 7 |
| Internal trigger endpoint + task lock | Task 8 |
| FL aggregation precedence rows | Task 9 |
| Cloud Scheduler job `sync-fl-ew` | Deploy step — not a code task; create in GCP after deploy mirroring `sync-wa-votewa` config |

**Placeholder scan:** No TBDs, TODOs, or incomplete steps detected.

**Type consistency check:**
- `build_candidate_name(row: ElectionRow) -> str` defined in `mappers.py` Task 5, imported in `fl.py` Task 7 ✓
- `parse_results_file(text: str) -> list[ElectionRow]` defined in `parsers.py` Task 4, used in `tasks.py` Task 6 and `fl.py` Task 7 ✓
- `build_race_groups(rows, is_primary) -> list[dict]` defined Task 5, used Task 6 ✓
- `map_candidate(row) -> tuple[str, str, dict]` defined Task 5, unpacked as `name, party, fields` in Task 6 ✓
- `FlEwClient.get_last_modified(slug) -> str` defined Task 3, used Task 6 + Task 7 ✓
- `FlEwClient.fetch_results_file(slug) -> str` defined Task 3, used Task 6 + Task 7 ✓
- `ElectionRow.county_code` used as `.lower()` for `jurisdiction_fragment` in Task 7 ✓
