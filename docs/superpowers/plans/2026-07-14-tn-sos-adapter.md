# Tennessee SOS Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Tennessee official-source coverage for election discovery, federal/state race and candidate creation, and certified result ingestion from Tennessee SOS calendar, candidate workbook, and historical result files.

**Architecture:** Add a new `integrations.tn_sos` Django app that scrapes official SOS HTML pages, downloads current qualified-candidate XLSX workbooks, and indexes certified result documents. Add a `results.adapters.tn.TennesseeAdapter` that prefers official precinct XLSX result files and defers live election-night dashboard polling until an active-election HAR exposes the transport. Use the existing aggregation ingest service for elections, races, candidates, and result rows.

**Tech Stack:** Django, Celery, `requests`, BeautifulSoup/lxml, `openpyxl`, `pdfplumber` for later fallback parsing, pytest/pytest-django, existing `aggregation.ingest`, existing `results.adapters.base`.

## Global Constraints

- Source of truth is official Tennessee SOS content under `https://sos.tn.gov/elections` and `https://sos-prod.tnsosgovfiles.com/s3fs-public/document/`.
- Do not build live dashboard polling from the July 14, 2026 inactive HAR; it did not expose contest-data requests.
- Build Stage 1 first: election calendar, federal/state race creation, and qualified candidates.
- Prefer XLSX over PDF for result ingestion and candidate parsing.
- Keep local HARs and large downloaded workbooks out of committed fixtures; extract compact fixtures.
- Use `source="tn_sos"` and add `Race.Source.TN_SOS = "tn_sos", "Tennessee SOS"`.
- Preserve source URLs, retrieval timestamps, content checksums, workbook filenames, and parser versions in `source_metadata`.
- Treat county/municipal candidates, local measures, and live election-night results as enhanced/deferred work unless a centralized source is confirmed.

---

## Confirmed Research Findings

- Updated research file: `docs/state-research/TN/TN-Election_Research_UPDATED.md`.
- Calendar HAR confirms `https://sos.tn.gov/elections/calendar` is static HTML with three tables and 339 `<tr>` elements, including a 327-row local election schedule.
- Candidate-list HAR confirms seven 2026 XLSX links:
  - `Governor_2026.xlsx`
  - `USSenate_2026.xlsx`
  - `USHouseCandidates_2026.xlsx`
  - `TNSenate_2026.xlsx`
  - `TNHouse_2026.xlsx`
  - `TNGOPSEC_Filed_2026-03-24.xlsx`
  - `TNDPSEC_Filed_2026-03-24.xlsx`
- Historical-results HAR confirms a large official document index with hundreds of result links, including recent `AllbyPrecinct.xlsx` files.
- Election-night dashboard HAR confirms `https://www.elections.tn.gov/` exists, but the inactive/offseason page loaded no result API, custom dashboard bundle, JSON feed, iframe, or polling endpoint.

## File Structure

- Create `backend/integrations/tn_sos/`: Tennessee SOS integration app.
- Create `backend/integrations/tn_sos/client.py`: HTTP client for calendar, candidate-list, workbook, result-index, and document downloads.
- Create `backend/integrations/tn_sos/parsers.py`: pure parsers for calendar HTML, candidate-list links, candidate XLSX files, historical result index links, and certified XLSX result rows.
- Create `backend/integrations/tn_sos/mappers.py`: pure mapping functions into `Election`, `Race`, `Candidate`, and result adapter-friendly records.
- Create `backend/integrations/tn_sos/tasks.py`: Celery tasks `sync_tn_elections`, `sync_tn_candidates`, and `sync_tn_result_index`.
- Create `backend/results/adapters/tn.py`: certified results adapter using indexed document URLs or `Election.source_metadata["tn_results_url"]`.
- Create focused tests and compact fixtures under `backend/integrations/tn_sos/tests/` and `backend/results/tests/`.
- Modify `backend/elections/models.py` plus a migration to add `Race.Source.TN_SOS`.
- Modify `backend/config/settings/base.py`, `backend/internal/task_locks.py`, `backend/internal/views.py`, and `backend/internal/urls.py` for app registration and scheduler trigger.
- Modify `backend/results/apps.py` to register the TN results adapter.
- Update `docs/state-research/00-MASTER-INDEX.md` after implementation lands.

---

### Task 1: Extract Compact TN Fixtures

**Files:**
- Create: `backend/integrations/tn_sos/tests/fixtures/calendar_2026.html`
- Create: `backend/integrations/tn_sos/tests/fixtures/candidate_lists_2026.html`
- Create: `backend/integrations/tn_sos/tests/fixtures/results_index_sample.html`
- Create: `backend/integrations/tn_sos/tests/fixtures/candidates_us_senate_2026.xlsx`
- Create: `backend/integrations/tn_sos/tests/fixtures/results_20251202_precinct_sample.xlsx`

**Interfaces:**
- Produces committed fixtures used by parser and adapter tests.

- [ ] **Step 1: Extract HTML fixtures from HAR content**

Run:

```bash
cd /data/Projects/CivicMirror/CivicMirror-API
python3 - <<'PY'
import json
from pathlib import Path

out_dir = Path("backend/integrations/tn_sos/tests/fixtures")
out_dir.mkdir(parents=True, exist_ok=True)

sources = [
    (
        Path("docs/state-research/TN/sos.tn.gov_Archive [26-07-14 13-24-02].har"),
        "https://sos.tn.gov/elections/calendar",
        out_dir / "calendar_2026.html",
    ),
    (
        Path("docs/state-research/TN/sos.tn.gov_Archive [26-07-14 13-24-02].har"),
        "https://sos.tn.gov/elections/2026-candidate-lists",
        out_dir / "candidate_lists_2026.html",
    ),
    (
        Path("docs/state-research/TN/sos.tn.gov_historical [26-07-14 13-25-42].har"),
        "https://sos.tn.gov/elections/results",
        out_dir / "results_index_sample.html",
    ),
]

for har_path, url, out_path in sources:
    data = json.loads(har_path.read_text())
    for entry in data["log"]["entries"]:
        if entry["request"]["url"] == url:
            out_path.write_text(entry["response"]["content"]["text"])
            print(out_path, len(entry["response"]["content"]["text"]))
            break
    else:
        raise SystemExit(f"missing {url}")
PY
```

Expected: three files written; calendar fixture is about 100 KB, candidate-list fixture about 31 KB, results-index fixture about 209 KB.

- [ ] **Step 2: Create small XLSX fixtures manually from official workbook shapes**

Create `backend/integrations/tn_sos/tests/fixtures/candidates_us_senate_2026.xlsx` with `openpyxl`:

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python3 - <<'PY'
from pathlib import Path
from openpyxl import Workbook

out = Path("integrations/tn_sos/tests/fixtures/candidates_us_senate_2026.xlsx")
out.parent.mkdir(parents=True, exist_ok=True)
wb = Workbook()
ws = wb.active
ws.title = "US Senate"
ws.append(["Office", "District", "Candidate Name", "Party", "Status"])
ws.append(["United States Senate", "", "Jane Candidate", "Republican", "Qualified"])
ws.append(["United States Senate", "", "Alex Example", "Democratic", "Qualified"])
wb.save(out)
print(out)
PY
```

Create `backend/integrations/tn_sos/tests/fixtures/results_20251202_precinct_sample.xlsx`:

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python3 - <<'PY'
from pathlib import Path
from openpyxl import Workbook

out = Path("integrations/tn_sos/tests/fixtures/results_20251202_precinct_sample.xlsx")
wb = Workbook()
ws = wb.active
ws.title = "Precinct Results"
ws.append(["County", "Precinct", "Office", "Candidate", "Party", "Votes"])
ws.append(["Davidson", "101", "U.S. House District 7", "Jane Candidate", "REP", 123])
ws.append(["Davidson", "101", "U.S. House District 7", "Alex Example", "DEM", 98])
wb.save(out)
print(out)
PY
```

- [ ] **Step 3: Verify only compact fixtures are staged**

Run:

```bash
git status --short docs/state-research/TN backend/integrations/tn_sos/tests/fixtures
```

Expected: fixtures are untracked; original HAR files remain untracked or ignored per repository policy and should not be staged as test fixtures.

- [ ] **Step 4: Commit**

```bash
git add backend/integrations/tn_sos/tests/fixtures
git commit -m "test(tn): add compact Tennessee SOS fixtures"
```

---

### Task 2: Scaffold `integrations.tn_sos` and Add Source Choice

**Files:**
- Create: `backend/integrations/tn_sos/__init__.py`
- Create: `backend/integrations/tn_sos/apps.py`
- Create: `backend/integrations/tn_sos/exceptions.py`
- Create: `backend/integrations/tn_sos/tests/__init__.py`
- Modify: `backend/config/settings/base.py`
- Modify: `backend/elections/models.py`
- Create: `backend/elections/migrations/0024_add_tn_sos_race_source.py`

**Interfaces:**
- Produces `TnSosError`, `TnSosRetryableError`, installed app `integrations.tn_sos`, and `Race.Source.TN_SOS`.

- [ ] **Step 1: Write a failing smoke test**

Create `backend/integrations/tn_sos/tests/test_app_setup.py`:

```python
from django.apps import apps

from elections.models import Race


def test_tn_sos_app_is_registered():
    assert apps.get_app_config("tn_sos").name == "integrations.tn_sos"


def test_tn_sos_race_source_exists():
    assert Race.Source.TN_SOS == "tn_sos"
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
cd backend && pytest integrations/tn_sos/tests/test_app_setup.py -v
```

Expected: import/app config or `Race.Source.TN_SOS` failure.

- [ ] **Step 3: Add the app files**

Create `backend/integrations/tn_sos/apps.py`:

```python
from django.apps import AppConfig


class TennesseeSosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.tn_sos"
    label = "tn_sos"
    verbose_name = "Tennessee SOS Integration"
```

Create `backend/integrations/tn_sos/exceptions.py`:

```python
class TnSosError(Exception):
    """Non-retryable Tennessee SOS integration error."""


class TnSosRetryableError(TnSosError):
    """Transient Tennessee SOS integration error that warrants retry."""
```

Add `"integrations.tn_sos"` to `INSTALLED_APPS` near the other `integrations.*` apps.

- [ ] **Step 4: Add the race source and migration**

In `backend/elections/models.py`, add:

```python
TN_SOS = 'tn_sos', 'Tennessee SOS'
```

near the other SOS sources. Generate the migration:

```bash
cd backend && python3 manage.py makemigrations elections --name add_tn_sos_race_source
```

- [ ] **Step 5: Verify**

Run:

```bash
cd backend && pytest integrations/tn_sos/tests/test_app_setup.py -v
cd backend && python3 manage.py check
```

Expected: tests pass and Django check reports no issues.

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/tn_sos backend/config/settings/base.py backend/elections/models.py backend/elections/migrations
git commit -m "feat(tn): scaffold Tennessee SOS integration"
```

---

### Task 3: Build the Tennessee SOS Client

**Files:**
- Create: `backend/integrations/tn_sos/client.py`
- Create: `backend/integrations/tn_sos/tests/test_client.py`

**Interfaces:**
- Produces `TnSosClient.get_calendar_html() -> str`, `get_candidate_list_html() -> str`, `get_results_index_html() -> str`, `download_file(url: str) -> tuple[bytes, str]`.

- [ ] **Step 1: Write failing client tests**

Create `backend/integrations/tn_sos/tests/test_client.py`:

```python
from unittest.mock import MagicMock

import pytest

from integrations.tn_sos.client import (
    CANDIDATE_LIST_URL,
    ELECTION_CALENDAR_URL,
    RESULTS_INDEX_URL,
    TnSosClient,
)
from integrations.tn_sos.exceptions import TnSosError, TnSosRetryableError


def _response(text="", content=b"", status_code=200, url="https://example.test/file"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.content = content or text.encode()
    resp.url = url
    resp.raise_for_status.side_effect = None
    return resp


def test_get_calendar_html_uses_official_url():
    client = TnSosClient()
    client._session.get = MagicMock(return_value=_response("<html>calendar</html>"))

    assert "calendar" in client.get_calendar_html()
    assert client._session.get.call_args.args[0] == ELECTION_CALENDAR_URL


def test_get_candidate_list_html_uses_official_url():
    client = TnSosClient()
    client._session.get = MagicMock(return_value=_response("<html>candidates</html>"))

    assert "candidates" in client.get_candidate_list_html()
    assert client._session.get.call_args.args[0] == CANDIDATE_LIST_URL


def test_get_results_index_html_uses_official_url():
    client = TnSosClient()
    client._session.get = MagicMock(return_value=_response("<html>results</html>"))

    assert "results" in client.get_results_index_html()
    assert client._session.get.call_args.args[0] == RESULTS_INDEX_URL


def test_download_file_returns_bytes_and_resolved_url():
    client = TnSosClient()
    client._session.get = MagicMock(return_value=_response(content=b"xlsx", url="https://cdn.test/file.xlsx"))

    content, resolved_url = client.download_file("https://cdn.test/file.xlsx")

    assert content == b"xlsx"
    assert resolved_url == "https://cdn.test/file.xlsx"


def test_404_is_non_retryable():
    client = TnSosClient(max_retries=0)
    resp = _response(status_code=404)
    client._session.get = MagicMock(return_value=resp)

    with pytest.raises(TnSosError):
        client.get_calendar_html()


def test_503_is_retryable():
    client = TnSosClient(max_retries=0)
    client._session.get = MagicMock(return_value=_response(status_code=503))

    with pytest.raises(TnSosRetryableError):
        client.get_calendar_html()
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
cd backend && pytest integrations/tn_sos/tests/test_client.py -v
```

Expected: import failure for `integrations.tn_sos.client`.

- [ ] **Step 3: Implement the client**

Create `backend/integrations/tn_sos/client.py`:

```python
from __future__ import annotations

import logging
import time

import requests

from .exceptions import TnSosError, TnSosRetryableError

logger = logging.getLogger(__name__)

ELECTION_CALENDAR_URL = "https://sos.tn.gov/elections/calendar"
CANDIDATE_LIST_URL = "https://sos.tn.gov/elections/2026-candidate-lists"
RESULTS_INDEX_URL = "https://sos.tn.gov/elections/results"
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class TnSosClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3, backoff_seconds: float = 1.0):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "CivicMirror-TN-SOS/1.0"})

    def _get(self, url: str, timeout: int | None = None) -> requests.Response:
        effective_timeout = timeout or self.timeout
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=effective_timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise TnSosRetryableError(f"GET {url} failed: {exc}") from exc
                time.sleep(self.backoff_seconds * (2**attempt))
                continue
            if resp.status_code == 404:
                raise TnSosError(f"GET {url} returned 404")
            if resp.status_code in RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise TnSosRetryableError(f"GET {url} returned {resp.status_code}")
                time.sleep(self.backoff_seconds * (2**attempt))
                continue
            try:
                resp.raise_for_status()
            except requests.RequestException as exc:
                raise TnSosError(f"GET {url} returned {resp.status_code}") from exc
            return resp
        raise TnSosRetryableError(f"GET {url} retries exhausted")

    def get_calendar_html(self) -> str:
        return self._get(ELECTION_CALENDAR_URL, timeout=20).text

    def get_candidate_list_html(self) -> str:
        return self._get(CANDIDATE_LIST_URL, timeout=20).text

    def get_results_index_html(self) -> str:
        return self._get(RESULTS_INDEX_URL, timeout=30).text

    def download_file(self, url: str) -> tuple[bytes, str]:
        resp = self._get(url, timeout=60)
        return resp.content, resp.url
```

- [ ] **Step 4: Verify**

Run:

```bash
cd backend && pytest integrations/tn_sos/tests/test_client.py -v
```

Expected: all client tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/tn_sos/client.py backend/integrations/tn_sos/tests/test_client.py
git commit -m "feat(tn): add SOS HTTP client"
```

---

### Task 4: Parse Calendar, Candidate Links, Workbooks, and Result Index

**Files:**
- Create: `backend/integrations/tn_sos/parsers.py`
- Create: `backend/integrations/tn_sos/tests/test_parsers.py`

**Interfaces:**
- Produces dataclasses `TnElectionRow`, `TnCandidateWorkbookLink`, `TnCandidateRecord`, `TnResultLink`, `TnResultRecord`.
- Produces functions `parse_calendar(html: str) -> list[TnElectionRow]`, `parse_candidate_workbook_links(html: str) -> list[TnCandidateWorkbookLink]`, `parse_candidate_workbook(content: bytes, source_url: str) -> list[TnCandidateRecord]`, `parse_results_index(html: str) -> list[TnResultLink]`, `parse_precinct_xlsx(content: bytes, source_url: str) -> list[TnResultRecord]`.

- [ ] **Step 1: Write parser tests**

Create `backend/integrations/tn_sos/tests/test_parsers.py` with tests for fixture-backed behavior:

```python
from pathlib import Path

from integrations.tn_sos.parsers import (
    parse_calendar,
    parse_candidate_workbook,
    parse_candidate_workbook_links,
    parse_precinct_xlsx,
    parse_results_index,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_calendar_finds_august_and_november_statewide_elections():
    rows = parse_calendar((FIXTURES / "calendar_2026.html").read_text())

    names = {row.name for row in rows}
    assert any("August 6, 2026" in name for name in names)
    assert any("November 3, 2026" in name for name in names)
    assert any(row.county == "Haywood" and "Stanton" in row.jurisdiction for row in rows)


def test_parse_candidate_workbook_links_prefers_xlsx_office_files():
    links = parse_candidate_workbook_links((FIXTURES / "candidate_lists_2026.html").read_text())

    names = {link.filename for link in links}
    assert "Governor_2026.xlsx" in names
    assert "USSenate_2026.xlsx" in names
    assert "TNHouse_2026.xlsx" in names
    assert all(link.url.endswith(".xlsx") for link in links)


def test_parse_candidate_workbook_returns_qualified_candidates():
    records = parse_candidate_workbook(
        (FIXTURES / "candidates_us_senate_2026.xlsx").read_bytes(),
        "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/USSenate_2026.xlsx",
    )

    assert records[0].office == "United States Senate"
    assert records[0].candidate_name == "Jane Candidate"
    assert records[0].party == "Republican"


def test_parse_results_index_finds_recent_precinct_spreadsheets():
    links = parse_results_index((FIXTURES / "results_index_sample.html").read_text())

    urls = {link.url for link in links}
    assert any("20251202AllbyPrecinct.xlsx" in url for url in urls)
    assert any("20241105AllbyPrecinct.xlsx" in url for url in urls)


def test_parse_precinct_xlsx_returns_result_records():
    records = parse_precinct_xlsx(
        (FIXTURES / "results_20251202_precinct_sample.xlsx").read_bytes(),
        "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/20251202AllbyPrecinct.xlsx",
    )

    assert records[0].county == "Davidson"
    assert records[0].precinct == "101"
    assert records[0].office_title == "U.S. House District 7"
    assert records[0].candidate_name == "Jane Candidate"
    assert records[0].vote_count == 123
```

- [ ] **Step 2: Run parser tests and verify failure**

Run:

```bash
cd backend && pytest integrations/tn_sos/tests/test_parsers.py -v
```

Expected: import failure for `integrations.tn_sos.parsers`.

- [ ] **Step 3: Implement parser dataclasses and helpers**

Create `backend/integrations/tn_sos/parsers.py` with:

```python
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from openpyxl import load_workbook


@dataclass(frozen=True)
class TnElectionRow:
    name: str
    election_date: date
    county: str
    jurisdiction: str
    source_url: str
    is_statewide: bool


@dataclass(frozen=True)
class TnCandidateWorkbookLink:
    office_group: str
    filename: str
    url: str


@dataclass(frozen=True)
class TnCandidateRecord:
    office: str
    district: str
    candidate_name: str
    party: str
    status: str
    source_url: str
    source_row: int


@dataclass(frozen=True)
class TnResultLink:
    election_date: date | None
    label: str
    url: str
    file_type: str
    result_level: str
    source_version: str


@dataclass(frozen=True)
class TnResultRecord:
    county: str
    precinct: str
    office_title: str
    candidate_name: str
    party: str
    vote_count: int
    source_url: str


def document_checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
```

Then add the parse functions using BeautifulSoup and `openpyxl`. Keep parsing tolerant: map headers by normalized text and skip rows that lack an office, candidate, or numeric vote count.

- [ ] **Step 4: Verify**

Run:

```bash
cd backend && pytest integrations/tn_sos/tests/test_parsers.py -v
```

Expected: all parser tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/tn_sos/parsers.py backend/integrations/tn_sos/tests/test_parsers.py
git commit -m "feat(tn): parse SOS calendar candidates and result files"
```

---

### Task 5: Map TN Records into CivicMirror Fields

**Files:**
- Create: `backend/integrations/tn_sos/mappers.py`
- Create: `backend/integrations/tn_sos/tests/test_mappers.py`

**Interfaces:**
- Consumes parser dataclasses from Task 4.
- Produces `map_election(row: TnElectionRow) -> dict`, `map_race(election_obj, record: TnCandidateRecord) -> dict`, `map_candidate(record: TnCandidateRecord) -> dict`, `normalized_office_title(office: str, district: str) -> str`.

- [ ] **Step 1: Write mapper tests**

Create `backend/integrations/tn_sos/tests/test_mappers.py`:

```python
from datetime import date
from types import SimpleNamespace

from elections.models import Candidate, Election, Race
from integrations.tn_sos.mappers import map_candidate, map_election, map_race, normalized_office_title
from integrations.tn_sos.parsers import TnCandidateRecord, TnElectionRow


def test_map_statewide_election_uses_tn_identity():
    row = TnElectionRow(
        name="Thursday, August 6, 2026 - Primary and General Election",
        election_date=date(2026, 8, 6),
        county="",
        jurisdiction="Tennessee",
        source_url="https://sos.tn.gov/elections/calendar",
        is_statewide=True,
    )

    mapped = map_election(row)

    assert mapped["source_id"] == "tn_sos:2026-08-06:statewide"
    assert mapped["state"] == "TN"
    assert mapped["election_type"] == Election.ElectionType.PRIMARY
    assert mapped["jurisdiction_level"] == Election.JurisdictionLevel.STATE


def test_normalized_office_title_keeps_district():
    assert normalized_office_title("Tennessee House", "District 52") == "tennessee house district 52"


def test_map_race_uses_tn_source():
    election = SimpleNamespace(status=Election.Status.RESULTS_PENDING, source_metadata={})
    record = TnCandidateRecord(
        office="United States Senate",
        district="",
        candidate_name="Jane Candidate",
        party="Republican",
        status="Qualified",
        source_url="https://example.test/USSenate_2026.xlsx",
        source_row=2,
    )

    mapped = map_race(election, record)

    assert mapped["source"] == Race.Source.TN_SOS
    assert mapped["office_title"] == "United States Senate"
    assert mapped["geography_scope"] == "federal"
    assert mapped["race_type"] == Race.RaceType.CANDIDATE


def test_map_candidate_preserves_workbook_metadata():
    record = TnCandidateRecord(
        office="United States Senate",
        district="",
        candidate_name="Jane Candidate",
        party="Republican",
        status="Qualified",
        source_url="https://example.test/USSenate_2026.xlsx",
        source_row=2,
    )

    mapped = map_candidate(record)

    assert mapped["party"] == "Republican"
    assert mapped["candidate_status"] == Candidate.CandidateStatus.RUNNING
    assert mapped["source_metadata"]["tn_source_row"] == 2
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
cd backend && pytest integrations/tn_sos/tests/test_mappers.py -v
```

Expected: import failure for `integrations.tn_sos.mappers`.

- [ ] **Step 3: Implement mappers**

Create `backend/integrations/tn_sos/mappers.py` following GA/WA mapper patterns. Infer geography:

- `United States` and `U.S.` offices -> `geography_scope="federal"`, `jurisdiction="Tennessee"`.
- `Governor` -> `geography_scope="statewide"`, `jurisdiction="Tennessee"`.
- `Tennessee Senate` and `Tennessee House` with district -> `district`.
- Candidate status from qualified workbook -> `CandidateStatus.RUNNING`.

- [ ] **Step 4: Verify**

Run:

```bash
cd backend && pytest integrations/tn_sos/tests/test_mappers.py -v
```

Expected: mapper tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/tn_sos/mappers.py backend/integrations/tn_sos/tests/test_mappers.py
git commit -m "feat(tn): map SOS records into CivicMirror fields"
```

---

### Task 6: Add Election and Candidate Sync Tasks

**Files:**
- Create: `backend/integrations/tn_sos/tasks.py`
- Create: `backend/integrations/tn_sos/tests/test_tasks.py`

**Interfaces:**
- Produces Celery tasks `sync_tn_elections()`, `sync_tn_candidates(election_pk: int | None = None)`, `sync_tn_result_index()`.

- [ ] **Step 1: Write task tests**

Test with mocked `TnSosClient` and parser outputs that:

- `sync_tn_elections` ingests statewide calendar elections with `source="tn_sos"`.
- `sync_tn_candidates` downloads all candidate XLSX links and ingests races/candidates.
- `sync_tn_result_index` writes matching result links into `Election.source_metadata["tn_result_links"]`.
- `sync_tn_candidates` deduplicates candidates by `(race, name, party)`.

- [ ] **Step 2: Implement `sync_tn_elections`**

Use the existing aggregation pattern:

```python
from aggregation import ingest

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
    source="tn_sos",
    source_id=source_id,
    identity=identity,
    fields=fields,
)
```

Queue `sync_tn_candidates` after statewide election ingestion.

- [ ] **Step 3: Implement `sync_tn_candidates`**

For each current workbook link:

1. Download file.
2. Compute checksum.
3. Parse candidate records.
4. Map race fields and ingest race.
5. Map candidate fields and ingest candidate.
6. Store workbook URL/checksum in `Election.source_metadata["tn_candidate_workbooks"]`.

- [ ] **Step 4: Implement `sync_tn_result_index`**

Parse the historical result index. For each indexed `AllbyPrecinct.xlsx`, find matching TN elections by date and store compact link metadata in `source_metadata["tn_result_links"]`.

- [ ] **Step 5: Verify focused task tests**

Run:

```bash
cd backend && pytest integrations/tn_sos/tests/test_tasks.py -v
```

Expected: task tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/tn_sos/tasks.py backend/integrations/tn_sos/tests/test_tasks.py
git commit -m "feat(tn): sync elections candidates and result index"
```

---

### Task 7: Add Certified Results Adapter

**Files:**
- Create: `backend/results/adapters/tn.py`
- Create: `backend/results/tests/test_tn_adapter.py`
- Modify: `backend/results/apps.py`

**Interfaces:**
- Produces registered `TennesseeAdapter.fetch_results(election_date, election_id) -> AdapterResult`.

- [ ] **Step 1: Write adapter tests**

Create `backend/results/tests/test_tn_adapter.py`:

```python
from unittest.mock import MagicMock, patch

from results.adapters.registry import get_adapter
from results.adapters.tn import TennesseeAdapter


def test_tn_adapter_registered():
    assert get_adapter("TN") is TennesseeAdapter


def test_fetch_results_requires_indexed_result_url():
    adapter = TennesseeAdapter()
    election = MagicMock()
    election.source_metadata = {}

    with patch("elections.models.Election.objects.get", return_value=election):
        result = adapter.fetch_results(None, election_id=1)

    assert result.mapping_confidence == "none"
    assert "tn_results_url" in result.notes or "tn_result_links" in result.notes


def test_fetch_results_parses_precinct_xlsx_fixture():
    adapter = TennesseeAdapter()
    election = MagicMock()
    election.pk = 1
    election.source_metadata = {
        "tn_results_url": "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/20251202AllbyPrecinct.xlsx"
    }

    fixture = open("integrations/tn_sos/tests/fixtures/results_20251202_precinct_sample.xlsx", "rb").read()

    with patch("elections.models.Election.objects.get", return_value=election), \
         patch("results.adapters.tn.TnSosClient") as client_cls, \
         patch("results.adapters.tn.cache") as cache:
        cache.get.return_value = None
        client_cls.return_value.download_file.return_value = (fixture, election.source_metadata["tn_results_url"])
        result = adapter.fetch_results(None, election_id=1)

    assert result.mapping_confidence == "full"
    assert len(result.rows) == 2
    assert result.rows[0].office_title == "U.S. House District 7"
    assert result.rows[0].candidate_name == "Jane Candidate"
    assert result.rows[0].vote_count == 123
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
cd backend && pytest results/tests/test_tn_adapter.py -v
```

Expected: import failure for `results.adapters.tn`.

- [ ] **Step 3: Implement `backend/results/adapters/tn.py`**

Implement a certified-results-only adapter:

- Load `Election.source_metadata["tn_results_url"]`, or pick the first `.xlsx` link from `source_metadata["tn_result_links"]`.
- Download via `TnSosClient.download_file`.
- Compute checksum with `document_checksum`.
- Use cache key `tn_sos:document:{election_id}`.
- Parse rows with `parse_precinct_xlsx`.
- Emit `ResultRow(result_type="official")`.
- Return `mapping_confidence="partial"` for unsupported/non-XLSX documents until the PDF fallback task is implemented.

- [ ] **Step 4: Register adapter**

In `backend/results/apps.py`, import `tn` with the other adapter modules.

- [ ] **Step 5: Verify**

Run:

```bash
cd backend && pytest results/tests/test_tn_adapter.py -v
```

Expected: adapter tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/results/adapters/tn.py backend/results/tests/test_tn_adapter.py backend/results/apps.py
git commit -m "feat(tn): add certified results adapter"
```

---

### Task 8: Wire Internal Trigger and Locks

**Files:**
- Modify: `backend/internal/task_locks.py`
- Modify: `backend/internal/views.py`
- Modify: `backend/internal/urls.py`
- Modify: `backend/internal/tests/test_views.py`

**Interfaces:**
- Produces `POST /internal/tasks/sync-tn-sos/`.

- [ ] **Step 1: Add lock test**

Add to an internal test file:

```python
from internal.task_locks import TASK_LOCKS


def test_sync_tn_sos_has_lock():
    assert "sync_tn_sos" in TASK_LOCKS
```

- [ ] **Step 2: Add trigger view and URL**

In `backend/internal/views.py`, import `sync_tn_elections` and add:

```python
@csrf_exempt
@require_POST
@require_internal_task_token
def sync_tn_sos_trigger(request):
    return _trigger("sync_tn_sos", sync_tn_elections, request)
```

In `backend/internal/urls.py`, add:

```python
path("tasks/sync-tn-sos/", views.sync_tn_sos_trigger, name="internal-sync-tn-sos"),
```

In `TASK_LOCKS`, add:

```python
"sync_tn_sos": (WINDOW_DAILY, 23 * _HOUR),
```

- [ ] **Step 3: Verify URL resolution**

Run:

```bash
cd backend && python3 manage.py shell -c 'from django.urls import resolve; print(resolve("/internal/tasks/sync-tn-sos/").url_name)'
cd backend && python3 manage.py shell -c 'from internal.task_locks import TASK_LOCKS; print(TASK_LOCKS["sync_tn_sos"])'
```

Expected:

```text
internal-sync-tn-sos
('daily', 82800)
```

- [ ] **Step 4: Commit**

```bash
git add backend/internal/task_locks.py backend/internal/views.py backend/internal/urls.py backend/internal/tests
git commit -m "feat(tn): add internal sync trigger"
```

---

### Task 9: Update Coverage Docs and Verification Notes

**Files:**
- Modify: `docs/state-research/00-MASTER-INDEX.md`
- Modify: `docs/design/Phase3-State-Expansion.md`
- Modify: `README.md` if coverage tables mention state status.

**Interfaces:**
- Produces docs that classify TN as buildable/implemented accurately after code lands.

- [ ] **Step 1: Update status wording**

After implementation and tests pass, update TN to:

```text
TN — Stage 1 election/race/candidate sync complete from official SOS calendar and qualified-candidate XLSX files; certified XLSX results adapter available; live dashboard pending active-election transport capture.
```

- [ ] **Step 2: Keep live results marked pending**

Do not mark live/unofficial TN results as complete until a HAR captured during test/live result posting identifies stable data transport.

- [ ] **Step 3: Commit**

```bash
git add docs/state-research/00-MASTER-INDEX.md docs/design/Phase3-State-Expansion.md README.md
git commit -m "docs(tn): update Tennessee coverage status"
```

---

## End-to-End Verification

Run:

```bash
cd backend
pytest integrations/tn_sos results/tests/test_tn_adapter.py internal/tests/test_views.py -v
ruff check .
python3 manage.py check
python3 manage.py shell -c 'from integrations.tn_sos.client import TnSosClient; c=TnSosClient(); print(len(c.get_calendar_html()), len(c.get_candidate_list_html()), len(c.get_results_index_html()))'
```

Expected:

- Focused tests pass.
- Ruff passes.
- Django system check passes.
- Live smoke test returns non-zero HTML lengths for all three official SOS pages.

## Deployment Notes

- Add a Cloud Scheduler job for `sync-tn-sos` only after local and production-environment smoke tests pass.
- Initial production cadence can be daily because TN candidate workbooks may be replaced in place.
- Do not enable live dashboard polling until the active-election capture is reviewed.
- After deployment, manually trigger `sync-tn-sos`, inspect `SyncLog`, and verify TN elections/races/candidates in API responses.

## Deferred Follow-Up: Active Election-Night Capture

Create a separate plan after the next active capture. Capture windows recommended by the research file:

- July 27, 2026
- July 31, 2026
- August 3-5, 2026
- August 6, 2026 before polls close
- August 6, 2026 after results begin posting

The follow-up plan should only proceed if the HAR exposes one of: public JSON, static result files, PHP endpoints, form POSTs returning structured HTML, or a stable server-rendered refresh pattern.

## Self-Review

- Spec coverage: Covers official calendar election creation, candidate workbook race/candidate creation, historical result index, certified XLSX result ingestion, internal trigger wiring, docs, verification, and live-dashboard deferral.
- Placeholder scan: No implementation task depends on an unidentified live endpoint; live ENR is explicitly deferred.
- Type consistency: `TnSosClient`, `TnElectionRow`, `TnCandidateRecord`, `TnResultLink`, `sync_tn_elections`, `sync_tn_candidates`, `sync_tn_result_index`, `Race.Source.TN_SOS`, and `TennesseeAdapter` are named consistently across tasks.
