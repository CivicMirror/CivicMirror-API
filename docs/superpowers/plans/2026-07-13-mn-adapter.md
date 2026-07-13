# Minnesota (MN) Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build MN's Stage 1 (candidate/race creation) and Stage 2 (election-night results) adapters, scoped to Federal + State offices, validated entirely against the historical Nov 5, 2024 general election (`ersElectionId=170`).

**Architecture:** A new `integrations.mn_sos` Django app parses MN SOS's positional semicolon-delimited flat files (fetched from `electionresultsfiles.sos.mn.gov`) into `Race`/`Candidate` rows via the shared `aggregation.ingest` merge engine. A new `results/adapters/mn.py` `StateResultsAdapter` reuses the same parsing/scope-filtering code to emit `ResultRow`s directly from MN's already-pre-aggregated statewide/by-district files — no precinct-summing pass is needed (confirmed via live recon, see the design spec).

**Tech Stack:** Django, Celery (`shared_task`), `requests`, `beautifulsoup4` (already project dependencies — same stack as the `il_sbe`/`co_sos` adapters this plan mirrors).

## Global Constraints

- Federal + State offices only this build: President, US Senate, US House, State Senate, State House, statewide judicial (Supreme Court/Court of Appeals), Governor when present. County/municipal/school/hospital races, ballot questions, district court, and official certification are explicitly out of scope.
- Historical POC only: build against the Nov 5, 2024 general election (`ersElectionId=170`, files under `electionresultsfiles.sos.mn.gov/20241105/`). Live discovery of future elections' `ersElectionId` is out of scope.
- All HTTP fixtures must be captured from real, live MN SOS responses — no synthetic/invented data (per the design spec's recon-first approach). No live network calls in the test suite itself.
- New Celery task's internal trigger endpoint MUST add a `TASK_LOCKS["sync_mn_sos"]` entry in the same commit that wires the endpoint (binding lesson from the IL build — a regression test now enforces this automatically, see Task 10).
- Run tests with `pytest --no-migrations` (local test-DB creation breaks on an unrelated bad migration in this environment).
- Full design context: `docs/superpowers/specs/2026-07-13-mn-adapter-design.md`.

---

### Task 1: Scaffold the `integrations.mn_sos` Django app

**Files:**
- Create: `backend/integrations/mn_sos/__init__.py` (empty)
- Create: `backend/integrations/mn_sos/apps.py`
- Create: `backend/integrations/mn_sos/exceptions.py`
- Create: `backend/integrations/mn_sos/tests/__init__.py` (empty)
- Modify: `backend/config/settings/base.py`

**Interfaces:**
- Produces: `MnSosError`, `MnSosRetryableError` exception classes used by every later task in this app.

- [ ] **Step 1: Create the app config**

```python
# backend/integrations/mn_sos/apps.py
from django.apps import AppConfig


class MinnesotaSosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.mn_sos"
    label = "mn_sos"
    verbose_name = "Minnesota SOS Integration"
```

- [ ] **Step 2: Create the exceptions module**

```python
# backend/integrations/mn_sos/exceptions.py
class MnSosError(Exception):
    """Non-retryable Minnesota SOS integration error."""


class MnSosRetryableError(MnSosError):
    """Transient error that warrants a Celery retry."""
```

- [ ] **Step 3: Create empty `__init__.py` files**

```bash
touch backend/integrations/mn_sos/__init__.py
mkdir -p backend/integrations/mn_sos/tests
touch backend/integrations/mn_sos/tests/__init__.py
```

- [ ] **Step 4: Register the app in settings**

In `backend/config/settings/base.py`, find this line (in the `INSTALLED_APPS +=` block):

```python
    'integrations.oh_sos',
    'internal',
```

Replace with:

```python
    'integrations.oh_sos',
    'integrations.mn_sos',
    'internal',
```

- [ ] **Step 5: Verify Django can load the app**

Run: `cd backend && python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/mn_sos backend/config/settings/base.py
git commit -m "feat(mn): scaffold integrations.mn_sos app"
```

---

### Task 2: Capture real fixtures and parse the file index page

**Files:**
- Create: `backend/integrations/mn_sos/parsers.py`
- Create: `backend/integrations/mn_sos/tests/fixtures/file_index.html`
- Create: `backend/integrations/mn_sos/tests/test_parsers.py`

**Interfaces:**
- Produces: `parse_file_index(html: str) -> list[dict]`, each dict `{"label": str, "url": str}`.

- [ ] **Step 1: Capture the real file-index fixture**

```bash
mkdir -p backend/integrations/mn_sos/tests/fixtures
curl -s -A "Mozilla/5.0" \
  "https://electionresults.sos.mn.gov/Select/MediaFiles/Index?ersElectionId=170" \
  -o backend/integrations/mn_sos/tests/fixtures/file_index.html
grep -c "downloadlink" backend/integrations/mn_sos/tests/fixtures/file_index.html
```
Expected: a count greater than 30 (confirms the page fetched live, not an error/challenge page).

- [ ] **Step 2: Write the failing test**

```python
# backend/integrations/mn_sos/tests/test_parsers.py
import os

from integrations.mn_sos.parsers import parse_file_index

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_file_index_extracts_label_url_pairs():
    html = _load_fixture("file_index.html")
    files = parse_file_index(html)

    labels = {f["label"] for f in files}
    assert "U.S. Senator Statewide" in labels
    assert "U.S. Representative by District" in labels
    assert "County Races" in labels  # out-of-scope label must still be parsed here;
    # scope filtering is mappers.is_in_scope_file's job, not the parser's.

    by_label = {f["label"]: f["url"] for f in files}
    assert by_label["U.S. Senator Statewide"] == (
        "https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt"
    )


def test_parse_file_index_returns_empty_list_for_no_matches():
    assert parse_file_index("<html><body>no links here</body></html>") == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest --no-migrations integrations/mn_sos/tests/test_parsers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.mn_sos.parsers'`

- [ ] **Step 4: Implement the parser**

```python
# backend/integrations/mn_sos/parsers.py
"""
Parsers for Minnesota Secretary of State election-results file formats.

Confirmed live 2026-07-13 against the Nov 5, 2024 general election
(ersElectionId=170) — see
docs/superpowers/specs/2026-07-13-mn-adapter-design.md.
"""
from __future__ import annotations

from bs4 import BeautifulSoup


def parse_file_index(html: str) -> list[dict]:
    """
    Parse the "Downloadable Text Files" index page into {label, url} pairs.

    Confirmed structure: <a class="downloadlink" href="...">Label Text</a>.
    Includes every listed file, in scope or not — callers filter via
    mappers.is_in_scope_file.
    """
    soup = BeautifulSoup(html, "html.parser")
    files = []
    for link in soup.select("a.downloadlink"):
        url = link.get("href", "").strip()
        label = link.get_text(strip=True)
        if url and label:
            files.append({"label": label, "url": url})
    return files
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest --no-migrations integrations/mn_sos/tests/test_parsers.py -v`
Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/mn_sos/parsers.py backend/integrations/mn_sos/tests/
git commit -m "feat(mn): parse MN SOS file-index page"
```

---

### Task 3: Parse the result-file and candidate-table formats

**Files:**
- Modify: `backend/integrations/mn_sos/parsers.py`
- Create: `backend/integrations/mn_sos/tests/fixtures/ussenate.txt`
- Create: `backend/integrations/mn_sos/tests/fixtures/ushouse.txt`
- Create: `backend/integrations/mn_sos/tests/fixtures/cand.txt`
- Modify: `backend/integrations/mn_sos/tests/test_parsers.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `parse_result_file(text: str) -> list[dict]` (16 keys: `state, county_id, precinct_name, office_id, office_name, district, candidate_order_code, candidate_name, suffix, incumbent_code, party, precincts_reporting, total_precincts, candidate_votes, candidate_pct, total_office_votes`). `parse_candidate_table(text: str) -> list[dict]` (7 keys: `candidate_id, candidate_name, office_id, office_title, county_id, order_code, party`).

- [ ] **Step 1: Capture real fixtures**

```bash
cd backend/integrations/mn_sos/tests/fixtures
curl -s -A "Mozilla/5.0" "https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt" -o ussenate.txt
curl -s -A "Mozilla/5.0" "https://electionresultsfiles.sos.mn.gov/20241105/ushouse.txt" -o ushouse.txt
curl -s -A "Mozilla/5.0" "https://electionresultsfiles.sos.mn.gov/20241105/cand.txt" -o cand.txt
head -2 ussenate.txt cand.txt
cd -
```
Expected `ussenate.txt` head:
```
MN;;;0102;U.S. Senator;;0301;Rebecca Whiting;;;LIB;4103;4103;55215;1.73;3189323
MN;;;0102;U.S. Senator;;0202;Amy Klobuchar;;;DFL;4103;4103;1792441;56.20;3189323
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/integrations/mn_sos/tests/test_parsers.py`:

```python
from integrations.mn_sos.parsers import parse_candidate_table, parse_result_file


def test_parse_result_file_maps_16_positional_fields():
    text = _load_fixture("ussenate.txt")
    rows = parse_result_file(text)

    klobuchar = next(r for r in rows if r["candidate_name"] == "Amy Klobuchar")
    assert klobuchar["office_id"] == "0102"
    assert klobuchar["office_name"] == "U.S. Senator"
    assert klobuchar["district"] == ""
    assert klobuchar["candidate_order_code"] == "0202"
    assert klobuchar["party"] == "DFL"
    assert klobuchar["precincts_reporting"] == "4103"
    assert klobuchar["total_precincts"] == "4103"
    assert klobuchar["candidate_votes"] == "1792441"
    assert klobuchar["candidate_pct"] == "56.20"
    assert klobuchar["total_office_votes"] == "3189323"


def test_parse_result_file_identifies_write_in_row():
    text = _load_fixture("ussenate.txt")
    rows = parse_result_file(text)
    write_in = next(r for r in rows if r["candidate_order_code"] == "9901")
    assert write_in["candidate_name"] == "WRITE-IN"


def test_parse_result_file_by_district_carries_district_in_office_name():
    text = _load_fixture("ushouse.txt")
    rows = parse_result_file(text)
    district_1_office_ids = {r["office_id"] for r in rows if "District 1" in r["office_name"]}
    assert district_1_office_ids == {"0104"}


def test_parse_result_file_skips_malformed_lines():
    text = "not;enough;fields\nMN;;;0102;U.S. Senator;;0202;Amy Klobuchar;;;DFL;4103;4103;1792441;56.20;3189323\n"
    rows = parse_result_file(text)
    assert len(rows) == 1
    assert rows[0]["candidate_name"] == "Amy Klobuchar"


def test_parse_result_file_handles_empty_text():
    assert parse_result_file("") == []


def test_parse_candidate_table_maps_7_positional_fields():
    text = _load_fixture("cand.txt")
    rows = parse_candidate_table(text)

    klobuchar = next(r for r in rows if r["candidate_name"] == "Amy Klobuchar")
    assert klobuchar["candidate_id"] == "01020202"
    assert klobuchar["office_id"] == "0102"
    assert klobuchar["office_title"] == "U.S. Senator"
    assert klobuchar["party"] == "DFL"


def test_parse_candidate_table_skips_malformed_lines():
    text = "too;few\n01020202;Amy Klobuchar;0102;U.S. Senator;88;02;DFL\n"
    rows = parse_candidate_table(text)
    assert len(rows) == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest --no-migrations integrations/mn_sos/tests/test_parsers.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_result_file'`

- [ ] **Step 4: Implement the parsers**

Append to `backend/integrations/mn_sos/parsers.py`:

```python
_RESULT_FIELDS = (
    "state", "county_id", "precinct_name", "office_id", "office_name",
    "district", "candidate_order_code", "candidate_name", "suffix",
    "incumbent_code", "party", "precincts_reporting", "total_precincts",
    "candidate_votes", "candidate_pct", "total_office_votes",
)

_CANDIDATE_FIELDS = (
    "candidate_id", "candidate_name", "office_id", "office_title",
    "county_id", "order_code", "party",
)


def _parse_semicolon_rows(text: str, field_names: tuple[str, ...]) -> list[dict]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(";")
        if len(parts) != len(field_names):
            continue
        rows.append(dict(zip(field_names, parts)))
    return rows


def parse_result_file(text: str) -> list[dict]:
    """
    Parse a MN SOS results file (16-field positional, semicolon-delimited).
    Confirmed live: these files are already aggregated to the file's stated
    granularity (statewide or by-district) — no precinct-summing needed.
    """
    return _parse_semicolon_rows(text, _RESULT_FIELDS)


def parse_candidate_table(text: str) -> list[dict]:
    """Parse cand.txt (7-field positional, semicolon-delimited)."""
    return _parse_semicolon_rows(text, _CANDIDATE_FIELDS)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest --no-migrations integrations/mn_sos/tests/test_parsers.py -v`
Expected: `9 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/mn_sos/parsers.py backend/integrations/mn_sos/tests/
git commit -m "feat(mn): parse MN SOS result-file and candidate-table formats"
```

---

### Task 4: Scope classification and write-in detection

**Files:**
- Create: `backend/integrations/mn_sos/mappers.py`
- Create: `backend/integrations/mn_sos/tests/test_mappers.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `IN_SCOPE_LABELS: frozenset[str]`, `is_in_scope_file(label: str) -> bool`, `is_write_in(candidate_order_code: str) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# backend/integrations/mn_sos/tests/test_mappers.py
from integrations.mn_sos.mappers import is_in_scope_file, is_write_in


def test_is_in_scope_file_matches_confirmed_federal_state_labels():
    for label in (
        "U.S. President Statewide",
        "U.S. Senator Statewide",
        "U.S. Representative by District",
        "State Senator by District",
        "State Representative by District",
        "Supreme Court and Courts of Appeals Races",
    ):
        assert is_in_scope_file(label) is True


def test_is_in_scope_file_excludes_local_and_precinct_labels():
    for label in (
        "County Races",
        "County Races and Questions",
        "Municipal Questions",
        "Municipal and Hospital District Races and Questions",
        "Municipal, Hospital, and School District Races by Precinct",
        "Hospital District Races",
        "School Board Races",
        "School Referendum and Bond Questions",
        "Constitutional Amendment Statewide",
        "U.S. President by Precinct",
        "Precinct Reporting Statistics",
    ):
        assert is_in_scope_file(label) is False


def test_is_in_scope_file_matches_future_governor_label_by_pattern():
    assert is_in_scope_file("Governor and Lieutenant Governor Statewide") is True
    assert is_in_scope_file("governor by county") is False  # county-scoped, not statewide/district


def test_is_write_in_matches_9901_only():
    assert is_write_in("9901") is True
    assert is_write_in("0202") is False
    assert is_write_in("") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest --no-migrations integrations/mn_sos/tests/test_mappers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.mn_sos.mappers'`

- [ ] **Step 3: Implement the mappers**

```python
# backend/integrations/mn_sos/mappers.py
"""
Scope classification for Minnesota SOS downloadable files.

Federal + State offices only this build (county/municipal/school/hospital,
ballot questions, and district court deferred — see
docs/superpowers/specs/2026-07-13-mn-adapter-design.md).
"""
from __future__ import annotations

import re

IN_SCOPE_LABELS = frozenset({
    "U.S. President Statewide",
    "U.S. Senator Statewide",
    "U.S. Representative by District",
    "State Senator by District",
    "State Representative by District",
    "Supreme Court and Courts of Appeals Races",
})

# No Governor/state executive file exists in the Nov 2024 general (off-year
# for MN's governor); match by pattern for future gubernatorial cycles.
_GOVERNOR_PATTERN = re.compile(r"^Governor.*\bStatewide\b", re.IGNORECASE)

_WRITE_IN_ORDER_CODE = "9901"


def is_in_scope_file(label: str) -> bool:
    if label in IN_SCOPE_LABELS:
        return True
    return bool(_GOVERNOR_PATTERN.match(label.strip()))


def is_write_in(candidate_order_code: str) -> bool:
    return candidate_order_code == _WRITE_IN_ORDER_CODE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest --no-migrations integrations/mn_sos/tests/test_mappers.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/mn_sos/mappers.py backend/integrations/mn_sos/tests/test_mappers.py
git commit -m "feat(mn): classify Federal+State in-scope MN SOS files"
```

---

### Task 5: HTTP client

**Files:**
- Create: `backend/integrations/mn_sos/client.py`
- Create: `backend/integrations/mn_sos/tests/test_client.py`

**Interfaces:**
- Consumes: `MnSosRetryableError` (Task 1).
- Produces: `MnSosClient` with `.fetch_file_index(ers_election_id: int) -> str` and `.fetch_file(url: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# backend/integrations/mn_sos/tests/test_client.py
from unittest.mock import MagicMock, patch

import pytest

from integrations.mn_sos.client import MnSosClient
from integrations.mn_sos.exceptions import MnSosRetryableError


def test_fetch_file_index_passes_ers_election_id_param():
    client = MnSosClient()
    mock_response = MagicMock(status_code=200, text="<html>index</html>")

    with patch.object(client._session, "get", return_value=mock_response) as mock_get:
        result = client.fetch_file_index(170)

    assert result == "<html>index</html>"
    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"ersElectionId": 170}
    assert "Select/MediaFiles/Index" in mock_get.call_args.args[0]


def test_fetch_file_gets_the_given_url_directly():
    client = MnSosClient()
    mock_response = MagicMock(status_code=200, text="MN;;;0102;...")

    with patch.object(client._session, "get", return_value=mock_response) as mock_get:
        result = client.fetch_file("https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt")

    assert result == "MN;;;0102;..."
    mock_get.assert_called_once_with(
        "https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt", timeout=30
    )


def test_fetch_file_retries_then_raises_on_persistent_5xx():
    client = MnSosClient(max_retries=1)
    mock_response = MagicMock(status_code=503, text="")

    with patch.object(client._session, "get", return_value=mock_response):
        with pytest.raises(MnSosRetryableError):
            client.fetch_file("https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest --no-migrations integrations/mn_sos/tests/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.mn_sos.client'`

- [ ] **Step 3: Implement the client**

```python
# backend/integrations/mn_sos/client.py
"""
Minnesota Secretary of State HTTP client.

electionresults.sos.mn.gov (the human-facing site) sits behind Radware
bot-detection on some pages (confirmed live 2026-07-13: the MediaFileLayout
doc page 302s behind a JS challenge), but the file-index page
(Select/MediaFiles/Index) and every actual .txt data file — served from the
separate electionresultsfiles.sos.mn.gov host — return 200 cleanly with a
plain browser User-Agent. No further bypass is required for this adapter.
"""
from __future__ import annotations

import logging

import requests

from .exceptions import MnSosRetryableError

logger = logging.getLogger(__name__)

_FILE_INDEX_URL = "https://electionresults.sos.mn.gov/Select/MediaFiles/Index"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_RETRYABLE_STATUSES = {403, 429, 500, 502, 503, 504}


class MnSosClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _get(self, url: str, **kwargs) -> requests.Response:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise MnSosRetryableError(f"MN SOS GET failed: {exc}") from exc
                logger.warning("mn_sos.client.retry attempt=%d url=%s err=%s", attempt, url, exc)
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise MnSosRetryableError(f"MN SOS returned {resp.status_code} for {url}")
                logger.warning(
                    "mn_sos.client.retry attempt=%d url=%s status=%d",
                    attempt, url, resp.status_code,
                )
                continue
            resp.raise_for_status()
            return resp
        raise MnSosRetryableError("MN SOS request retries exhausted")

    def fetch_file_index(self, ers_election_id: int) -> str:
        """GET the "Downloadable Text Files" index page for one election."""
        return self._get(_FILE_INDEX_URL, params={"ersElectionId": ers_election_id}).text

    def fetch_file(self, url: str) -> str:
        """GET a result file or cand.txt directly by its full URL."""
        return self._get(url).text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest --no-migrations integrations/mn_sos/tests/test_client.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/mn_sos/client.py backend/integrations/mn_sos/tests/test_client.py
git commit -m "feat(mn): add MN SOS HTTP client"
```

---

### Task 6: Election, race, and candidate field mappers

**Files:**
- Modify: `backend/integrations/mn_sos/mappers.py`
- Modify: `backend/integrations/mn_sos/tests/test_mappers.py`

**Interfaces:**
- Consumes: `elections.models.Election`, `elections.models.Race`, `elections.models.Candidate` (existing models — `Race.Source.MN_SOS` is added in Task 8; reference it as a string literal `"mn_sos"` here so this task doesn't depend on Task 8 landing first).
- Produces: `map_election() -> dict` (hardcoded 2024 general POC), `map_race(office_id: str, office_title: str) -> dict`, `map_candidate(candidate_row: dict) -> dict`.

- [ ] **Step 1: Write the failing test**

Append to `backend/integrations/mn_sos/tests/test_mappers.py`:

```python
import datetime

from elections.models import Election, Race
from integrations.mn_sos.mappers import map_candidate, map_election, map_race


def test_map_election_returns_2024_general_poc_identity():
    mapped = map_election()
    assert mapped["source_id"] == "mn_sos_2024_general"
    assert mapped["state"] == "MN"
    assert mapped["election_type"] == "general"
    assert mapped["election_date"] == datetime.date(2024, 11, 5)
    assert mapped["jurisdiction_level"] == Election.JurisdictionLevel.STATE
    assert mapped["source_metadata"]["mn_ers_election_id"] == 170
    assert mapped["source_metadata"]["mn_date_path"] == "20241105"


def test_map_race_builds_statewide_office_fields():
    fields = map_race(office_id="0102", office_title="U.S. Senator")
    assert fields["office_title"] == "U.S. Senator"
    assert fields["race_type"] == Race.RaceType.CANDIDATE
    assert fields["source"] == "mn_sos"
    assert fields["source_metadata"]["mn_office_id"] == "0102"


def test_map_candidate_maps_party_and_source_metadata():
    row = {
        "candidate_id": "01020202", "candidate_name": "Amy Klobuchar",
        "office_id": "0102", "office_title": "U.S. Senator",
        "county_id": "88", "order_code": "02", "party": "DFL",
    }
    fields = map_candidate(row)
    assert fields["party"] == "DFL"
    assert fields["source_metadata"]["mn_candidate_id"] == "01020202"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest --no-migrations integrations/mn_sos/tests/test_mappers.py -v`
Expected: FAIL with `ImportError: cannot import name 'map_election'`

- [ ] **Step 3: Implement the mappers**

Append to `backend/integrations/mn_sos/mappers.py`:

```python
import datetime

from elections.models import Election, Race

# Historical POC election: 2024 Minnesota general (confirmed live 2026-07-13).
# Live discovery of future elections' ersElectionId is out of scope for this build.
_POC_ERS_ELECTION_ID = 170
_POC_DATE_PATH = "20241105"
_POC_ELECTION_DATE = datetime.date(2024, 11, 5)


def map_election() -> dict:
    """Return Election model field values for the Nov 2024 general POC election."""
    return {
        "source_id": "mn_sos_2024_general",
        "name": "2024 Minnesota General Election",
        "election_date": _POC_ELECTION_DATE,
        "election_type": "general",
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "MN",
        "status": Election.Status.RESULTS_CERTIFIED,
        "source_metadata": {
            "mn_ers_election_id": _POC_ERS_ELECTION_ID,
            "mn_date_path": _POC_DATE_PATH,
        },
    }


def map_race(office_id: str, office_title: str) -> dict:
    """Map an in-scope MN office to Race model field values."""
    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office_title,
        "jurisdiction": "Minnesota",
        "geography_scope": "district" if "District" in office_title else "statewide",
        "certification_status": Race.CertificationStatus.RESULTS_CERTIFIED,
        "source": "mn_sos",
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "normalized_office_title": " ".join(office_title.lower().split()),
        "source_metadata": {"mn_office_id": office_id},
    }


def map_candidate(candidate_row: dict) -> dict:
    """Map a parsed cand.txt row to Candidate model field values."""
    return {
        "party": candidate_row.get("party", ""),
        "incumbent": False,
        "source_metadata": {
            "mn_candidate_id": candidate_row.get("candidate_id", ""),
            "mn_office_id": candidate_row.get("office_id", ""),
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest --no-migrations integrations/mn_sos/tests/test_mappers.py -v`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/mn_sos/mappers.py backend/integrations/mn_sos/tests/test_mappers.py
git commit -m "feat(mn): add MN election/race/candidate field mappers"
```

---

### Task 7: `Race.Source.MN_SOS` model choice

**Files:**
- Modify: `backend/elections/models.py:109`
- Create: `backend/elections/migrations/0023_add_mn_sos_race_source.py`

**Interfaces:**
- Produces: `Race.Source.MN_SOS == "mn_sos"`.

- [ ] **Step 1: Add the choice**

In `backend/elections/models.py`, find:

```python
        IL_SBE = 'il_sbe', 'Illinois SBE'
```

Replace with:

```python
        IL_SBE = 'il_sbe', 'Illinois SBE'
        MN_SOS = 'mn_sos', 'Minnesota SOS'
```

- [ ] **Step 2: Generate the migration**

Run: `cd backend && python manage.py makemigrations elections`
Expected output: `Migrations for 'elections': elections/migrations/0023_add_mn_sos_race_source.py - Alter field source on race`

- [ ] **Step 3: Verify the migration content**

Run: `cat backend/elections/migrations/0023_add_mn_sos_race_source.py`
Expected: a single `AlterField` on `race.source` whose `choices` list is identical to migration `0022`'s list with one extra tuple appended: `('mn_sos', 'Minnesota SOS')`. If Django produced anything else (e.g. it picked up unrelated model drift), stop and investigate before continuing — `makemigrations` should only ever touch the `source` field's choices here.

- [ ] **Step 4: Run migration check**

Run: `cd backend && python manage.py migrate elections --plan | tail -5`
Expected: `0023_add_mn_sos_race_source` listed as the last (unapplied) migration, no errors.

- [ ] **Step 5: Commit**

```bash
git add backend/elections/models.py backend/elections/migrations/0023_add_mn_sos_race_source.py
git commit -m "feat(mn): add Race.Source.MN_SOS"
```

---

### Task 8: Stage 1 Celery task — `sync_mn_races`

**Files:**
- Create: `backend/integrations/mn_sos/tasks.py`
- Create: `backend/integrations/mn_sos/tests/test_tasks.py`

**Interfaces:**
- Consumes: `MnSosClient` (Task 5), `parse_file_index`/`parse_result_file`/`parse_candidate_table` (Tasks 2-3), `is_in_scope_file`/`is_write_in` (Task 4), `map_election`/`map_race`/`map_candidate` (Task 6), `Race.Source.MN_SOS` (Task 7), `aggregation.ingest.{ingest_election,ingest_race,ingest_candidate}` (existing).
- Produces: `sync_mn_races()` — no-arg Celery task, the entry point the internal trigger endpoint (Task 9) calls.

- [ ] **Step 1: Write the failing test**

```python
# backend/integrations/mn_sos/tests/test_tasks.py
from unittest.mock import patch

import pytest

from elections.models import Candidate, Election, Race
from integrations.mn_sos.tasks import sync_mn_races

_FILE_INDEX_HTML = "<html>fake index</html>"

_IN_SCOPE_FILES = [
    {"label": "U.S. Senator Statewide", "url": "https://x/ussenate.txt"},
]
_OUT_OF_SCOPE_FILES = [
    {"label": "County Races", "url": "https://x/cntyRaces.txt"},
]

_SENATE_RESULT_ROWS = [
    {
        "state": "MN", "county_id": "", "precinct_name": "", "office_id": "0102",
        "office_name": "U.S. Senator", "district": "", "candidate_order_code": "0202",
        "candidate_name": "Amy Klobuchar", "suffix": "", "incumbent_code": "",
        "party": "DFL", "precincts_reporting": "4103", "total_precincts": "4103",
        "candidate_votes": "1792441", "candidate_pct": "56.20", "total_office_votes": "3189323",
    },
    {
        "state": "MN", "county_id": "", "precinct_name": "", "office_id": "0102",
        "office_name": "U.S. Senator", "district": "", "candidate_order_code": "9901",
        "candidate_name": "WRITE-IN", "suffix": "", "incumbent_code": "",
        "party": "WI", "precincts_reporting": "4103", "total_precincts": "4103",
        "candidate_votes": "3578", "candidate_pct": "0.11", "total_office_votes": "3189323",
    },
]

_CANDIDATE_ROWS = [
    {
        "candidate_id": "01020202", "candidate_name": "Amy Klobuchar",
        "office_id": "0102", "office_title": "U.S. Senator",
        "county_id": "88", "order_code": "02", "party": "DFL",
    },
    {
        # County candidate — must be filtered out (office_id 0102 not present for this row).
        "candidate_id": "99990101", "candidate_name": "County Commissioner Person",
        "office_id": "9999", "office_title": "County Commissioner",
        "county_id": "01", "order_code": "01", "party": "",
    },
]


@pytest.mark.django_db
def test_sync_mn_races_creates_election_race_and_in_scope_candidate_only():
    with patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_file_index",
        return_value=_FILE_INDEX_HTML,
    ), patch(
        "integrations.mn_sos.tasks.parse_file_index",
        return_value=_IN_SCOPE_FILES + _OUT_OF_SCOPE_FILES,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_file",
        side_effect=lambda url: "fake text for " + url,
    ), patch(
        "integrations.mn_sos.tasks.parse_result_file",
        return_value=_SENATE_RESULT_ROWS,
    ), patch(
        "integrations.mn_sos.tasks.parse_candidate_table",
        return_value=_CANDIDATE_ROWS,
    ):
        result = sync_mn_races()

    assert result["created"] >= 2  # 1 race + 1 candidate at minimum
    election = Election.objects.get(source_id="mn_sos_2024_general")
    assert election.state == "MN"

    race = Race.objects.get(election=election, office_title="U.S. Senator")
    assert race.source == "mn_sos"

    candidate_names = set(Candidate.objects.filter(race=race).values_list("name", flat=True))
    assert candidate_names == {"Amy Klobuchar"}  # county candidate excluded, write-in row excluded


@pytest.mark.django_db
def test_sync_mn_races_marks_disappeared_candidate_withdrawn():
    with patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_file_index",
        return_value=_FILE_INDEX_HTML,
    ), patch(
        "integrations.mn_sos.tasks.parse_file_index",
        return_value=_IN_SCOPE_FILES,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_file",
        side_effect=lambda url: "fake text for " + url,
    ), patch(
        "integrations.mn_sos.tasks.parse_result_file",
        return_value=_SENATE_RESULT_ROWS,
    ), patch(
        "integrations.mn_sos.tasks.parse_candidate_table",
        return_value=_CANDIDATE_ROWS,
    ):
        sync_mn_races()

    race = Race.objects.get(office_title="U.S. Senator")
    Candidate.objects.create(race=race, name="Someone Who Withdrew", party="DFL")

    with patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_file_index",
        return_value=_FILE_INDEX_HTML,
    ), patch(
        "integrations.mn_sos.tasks.parse_file_index",
        return_value=_IN_SCOPE_FILES,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_file",
        side_effect=lambda url: "fake text for " + url,
    ), patch(
        "integrations.mn_sos.tasks.parse_result_file",
        return_value=_SENATE_RESULT_ROWS,
    ), patch(
        "integrations.mn_sos.tasks.parse_candidate_table",
        return_value=_CANDIDATE_ROWS,
    ):
        sync_mn_races()

    withdrawn = Candidate.objects.get(name="Someone Who Withdrew")
    assert withdrawn.candidate_status == Candidate.CandidateStatus.WITHDRAWN
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest --no-migrations integrations/mn_sos/tests/test_tasks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.mn_sos.tasks'`

- [ ] **Step 3: Implement the task**

```python
# backend/integrations/mn_sos/tasks.py
"""
Minnesota SOS Celery tasks.

sync_mn_races (single Stage 1 task, no-arg):
  1. Upsert the hardcoded Nov 2024 general POC Election row.
  2. Fetch the file index, filter to Federal+State in-scope files.
  3. Parse each in-scope result file to collect the in-scope (office_id,
     office_name) set — this is the office-level scope filter, since
     cand.txt itself mixes federal/state/county candidates together.
  4. Fetch + parse cand.txt, filter to in-scope office_ids, upsert Race +
     Candidate rows via the aggregation ingest service.
  5. Mark any previously-RUNNING candidate for this election not seen this
     run as WITHDRAWN (MN's own documented candidate lifecycle — see
     docs/superpowers/specs/2026-07-13-mn-adapter-design.md).
"""
import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Candidate
from ops.models import SyncLog

from .client import MnSosClient
from .exceptions import MnSosRetryableError
from .mappers import is_in_scope_file, map_candidate, map_election, map_race
from .parsers import parse_candidate_table, parse_file_index, parse_result_file

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_mn_races(self):
    sync_log = SyncLog.objects.create(
        source="mn_sos",
        task_name="sync_mn_races",
        status=SyncLog.Status.STARTED,
    )
    client = MnSosClient()
    created_count = updated_count = withdrawn_count = 0

    try:
        from aggregation import ingest

        mapped_election = map_election()
        source_id = mapped_election.pop("source_id")
        identity = {
            "state": mapped_election["state"],
            "election_type": mapped_election["election_type"],
            "election_date": mapped_election["election_date"],
            "jurisdiction_level": mapped_election["jurisdiction_level"],
        }
        fields = {k: v for k, v in mapped_election.items() if k not in identity}
        election_obj, election_was_created = ingest.ingest_election(
            source="mn_sos", source_id=source_id, identity=identity, fields=fields,
        )

        meta = election_obj.source_metadata or {}
        ers_election_id = meta.get("mn_ers_election_id")

        index_html = client.fetch_file_index(ers_election_id)
        all_files = parse_file_index(index_html)
        in_scope_files = [f for f in all_files if is_in_scope_file(f["label"])]

        in_scope_office_ids: set[str] = set()
        office_titles_by_id: dict[str, str] = {}
        for file_entry in in_scope_files:
            try:
                text = client.fetch_file(file_entry["url"])
            except Exception as exc:
                logger.warning(
                    "mn_sos.sync_races.result_file_fetch_failed url=%s err=%s",
                    file_entry["url"], exc,
                )
                continue
            for row in parse_result_file(text):
                in_scope_office_ids.add(row["office_id"])
                office_titles_by_id.setdefault(row["office_id"], row["office_name"])

        if not in_scope_office_ids:
            sync_log.notes = "No in-scope offices found in result files"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": 0, "updated": 0}

        cand_url = f"https://electionresultsfiles.sos.mn.gov/{meta['mn_date_path']}/cand.txt"
        cand_text = client.fetch_file(cand_url)
        candidate_rows = [
            row for row in parse_candidate_table(cand_text)
            if row["office_id"] in in_scope_office_ids
        ]

        seen_candidate_pks: set[int] = set()

        for office_id in in_scope_office_ids:
            office_title = office_titles_by_id[office_id]
            race_defaults = map_race(office_id, office_title)
            race_identity = {
                "office_title": race_defaults.pop("office_title"),
                "ocd_division_id": race_defaults.pop("ocd_division_id", "") or "",
                "race_type": race_defaults.pop("race_type"),
            }
            race_defaults.pop("source", None)

            race_obj, race_was_new = ingest.ingest_race(
                election=election_obj, source="mn_sos",
                identity=race_identity, fields=race_defaults,
            )
            if race_was_new:
                created_count += 1
            else:
                updated_count += 1

            for row in candidate_rows:
                if row["office_id"] != office_id:
                    continue
                name = row["candidate_name"].strip()
                if not name:
                    continue
                cand_fields = map_candidate(row)
                party = cand_fields.pop("party", "")
                cand_obj, cand_was_new = ingest.ingest_candidate(
                    race=race_obj, source="mn_sos", name=name, party=party, fields=cand_fields,
                )
                seen_candidate_pks.add(cand_obj.pk)
                if cand_was_new:
                    created_count += 1
                else:
                    updated_count += 1

        withdrawn_qs = (
            Candidate.objects
            .filter(race__election=election_obj, race__source="mn_sos")
            .exclude(pk__in=seen_candidate_pks)
            .filter(candidate_status=Candidate.CandidateStatus.RUNNING)
        )
        withdrawn_count = withdrawn_qs.update(candidate_status=Candidate.CandidateStatus.WITHDRAWN)

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.notes = f"withdrawn={withdrawn_count}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created_count, "updated": updated_count, "withdrawn": withdrawn_count}

    except MnSosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("mn_sos.sync_races.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest --no-migrations integrations/mn_sos/tests/test_tasks.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/mn_sos/tasks.py backend/integrations/mn_sos/tests/test_tasks.py
git commit -m "feat(mn): add sync_mn_races Stage 1 task"
```

---

### Task 9: Wire the internal trigger endpoint

**Files:**
- Modify: `backend/internal/views.py`
- Modify: `backend/internal/urls.py`
- Modify: `backend/internal/task_locks.py`

**Interfaces:**
- Consumes: `sync_mn_races` (Task 8).
- Produces: `POST /internal/tasks/sync-mn-sos/` → enqueues `sync_mn_races`.

- [ ] **Step 1: Add the TASK_LOCKS entry**

In `backend/internal/task_locks.py`, find:

```python
    "sync_il_sbe":          (WINDOW_DAILY,      23 * _HOUR),
```

Replace with:

```python
    "sync_il_sbe":          (WINDOW_DAILY,      23 * _HOUR),
    "sync_mn_sos":          (WINDOW_DAILY,      23 * _HOUR),
```

- [ ] **Step 2: Add the view**

In `backend/internal/views.py`, find the import block:

```python
from integrations.il_sbe.tasks import sync_il_elections
```

Replace with:

```python
from integrations.il_sbe.tasks import sync_il_elections
from integrations.mn_sos.tasks import sync_mn_races
```

Then find:

```python
@csrf_exempt
@require_POST
@require_internal_task_token
def sync_il_sbe_trigger(request):
    return _trigger("sync_il_sbe", sync_il_elections, request)
```

Add immediately after:

```python


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_mn_sos_trigger(request):
    return _trigger("sync_mn_sos", sync_mn_races, request)
```

- [ ] **Step 3: Add the URL route**

In `backend/internal/urls.py`, find:

```python
    path("tasks/sync-il-sbe/", views.sync_il_sbe_trigger, name="internal-sync-il-sbe"),
```

Replace with:

```python
    path("tasks/sync-il-sbe/", views.sync_il_sbe_trigger, name="internal-sync-il-sbe"),
    path("tasks/sync-mn-sos/", views.sync_mn_sos_trigger, name="internal-sync-mn-sos"),
```

- [ ] **Step 4: Verify the registry regression test catches drift correctly**

Run: `cd backend && pytest --no-migrations internal/tests/test_clear_task_locks.py -v`
Expected: `test_registry_covers_every_triggered_task` PASSES (this is the exact test that would have caught IL's missing-registry-entry bug — confirming it now also covers MN).

- [ ] **Step 5: Verify Django check and full internal test suite**

Run: `cd backend && python manage.py check && pytest --no-migrations internal/ -v`
Expected: no errors, all internal tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/internal/views.py backend/internal/urls.py backend/internal/task_locks.py
git commit -m "feat(mn): wire sync-mn-sos internal trigger endpoint"
```

---

### Task 10: Stage 2 results adapter — `MinnesotaAdapter`

**Files:**
- Create: `backend/results/adapters/mn.py`
- Create: `backend/results/tests/fixtures/mn_ussenate.txt`
- Create: `backend/results/tests/fixtures/mn_file_index.html`
- Create: `backend/results/tests/test_mn_adapter.py`
- Modify: `backend/results/apps.py`

**Interfaces:**
- Consumes: `MnSosClient`, `parse_file_index`, `parse_result_file`, `is_in_scope_file`, `is_write_in` (all from `integrations.mn_sos`), `AdapterResult`/`ResultRow`/`StateResultsAdapter` (`results.adapters.base`), `register` (`results.adapters.registry`).
- Produces: `MinnesotaAdapter` registered for state `"MN"`.

- [ ] **Step 1: Capture fixtures (reuse the same live files, placed under `results/tests/fixtures`)**

```bash
curl -s -A "Mozilla/5.0" \
  "https://electionresults.sos.mn.gov/Select/MediaFiles/Index?ersElectionId=170" \
  -o backend/results/tests/fixtures/mn_file_index.html
curl -s -A "Mozilla/5.0" \
  "https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt" \
  -o backend/results/tests/fixtures/mn_ussenate.txt
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/results/tests/test_mn_adapter.py
import os
from unittest.mock import patch

import pytest
from django.core.cache import cache

from elections.models import Election
from results.adapters.mn import MinnesotaAdapter

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_fetch_results_returns_none_confidence_when_metadata_missing():
    election = Election.objects.create(
        name="2024 Minnesota General Election", election_date="2024-11-05",
        election_type="general", jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MN", source_id="mn_sos_2024_general",
    )
    adapter = MinnesotaAdapter()
    result = adapter.fetch_results(election.election_date, election.pk)
    assert result.mapping_confidence == "none"
    assert result.rows == []


@pytest.mark.django_db
def test_fetch_results_parses_in_scope_files_only():
    election = Election.objects.create(
        name="2024 Minnesota General Election", election_date="2024-11-05",
        election_type="general", jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MN", source_id="mn_sos_2024_general",
        source_metadata={"mn_ers_election_id": 170, "mn_date_path": "20241105"},
    )
    adapter = MinnesotaAdapter()

    index_html = _load_fixture("mn_file_index.html")
    ussenate_text = _load_fixture("mn_ussenate.txt")

    def fake_fetch_file(url):
        if url.endswith("ussenate.txt"):
            return ussenate_text
        return ""

    with patch(
        "results.adapters.mn.MnSosClient.fetch_file_index", return_value=index_html,
    ), patch(
        "results.adapters.mn.MnSosClient.fetch_file", side_effect=fake_fetch_file,
    ):
        result = adapter.fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "full"
    klobuchar = next(r for r in result.rows if r.candidate_name == "Amy Klobuchar")
    assert klobuchar.vote_count == 1792441
    assert klobuchar.office_title == "U.S. Senator"
    write_in = next(r for r in result.rows if r.is_write_in_aggregate)
    assert write_in.candidate_name == "WRITE-IN"
    assert result.source_version  # checksum computed


@pytest.mark.django_db
def test_fetch_results_reports_unchanged_when_checksum_matches_cache():
    election = Election.objects.create(
        name="2024 Minnesota General Election", election_date="2024-11-05",
        election_type="general", jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MN", source_id="mn_sos_2024_general",
        source_metadata={"mn_ers_election_id": 170, "mn_date_path": "20241105"},
    )
    adapter = MinnesotaAdapter()
    index_html = _load_fixture("mn_file_index.html")
    ussenate_text = _load_fixture("mn_ussenate.txt")

    def fake_fetch_file(url):
        return ussenate_text if url.endswith("ussenate.txt") else ""

    with patch(
        "results.adapters.mn.MnSosClient.fetch_file_index", return_value=index_html,
    ), patch(
        "results.adapters.mn.MnSosClient.fetch_file", side_effect=fake_fetch_file,
    ):
        first = adapter.fetch_results(election.election_date, election.pk)
        cache.set(adapter.version_cache_key(election.pk), first.source_version, 86400)
        second = adapter.fetch_results(election.election_date, election.pk)

    assert second.unchanged is True
    assert second.rows == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest --no-migrations results/tests/test_mn_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'results.adapters.mn'`

- [ ] **Step 4: Implement the adapter**

```python
# backend/results/adapters/mn.py
"""
Minnesota (MN) results adapter — Minnesota Secretary of State.

Source: electionresultsfiles.sos.mn.gov (positional semicolon-delimited
flat files, hosted separately from the bot-protected electionresults.sos.mn.gov
human-facing pages — see integrations/mn_sos/client.py).

Data notes:
    - Federal + State offices only this build (see
      docs/superpowers/specs/2026-07-13-mn-adapter-design.md).
    - Confirmed live: MN's statewide/by-district files are already
      pre-aggregated to their stated granularity — no precinct-summing pass
      is needed here, unlike Illinois's il_aggregate.py.
    - No version endpoint exists; change detection uses a checksum of the
      concatenated bytes of all in-scope files fetched this run.
"""
from __future__ import annotations

import hashlib
import logging

from django.core.cache import cache

from integrations.mn_sos.client import MnSosClient
from integrations.mn_sos.mappers import is_in_scope_file, is_write_in
from integrations.mn_sos.parsers import parse_file_index, parse_result_file

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days


def _safe_float(value: str):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@register
class MinnesotaAdapter(StateResultsAdapter):
    state = "MN"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"mn_sos:checksum:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("mn_sos.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        meta = election.source_metadata or {}
        ers_election_id = meta.get("mn_ers_election_id")
        if not ers_election_id:
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"No mn_ers_election_id metadata for election {election.source_id}",
            )

        client = MnSosClient()
        index_html = client.fetch_file_index(ers_election_id)
        in_scope_files = [f for f in parse_file_index(index_html) if is_in_scope_file(f["label"])]

        if not in_scope_files:
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"No in-scope MN SOS files found for election {election.source_id}",
            )

        all_rows: list[ResultRow] = []
        file_bytes_for_checksum = bytearray()
        source_url = ""

        for file_entry in in_scope_files:
            url = file_entry["url"]
            try:
                text = client.fetch_file(url)
            except Exception as exc:
                logger.warning("mn_sos.adapter.file_fetch_failed url=%s err=%s", url, exc)
                continue
            file_bytes_for_checksum.extend(text.encode("utf-8", errors="ignore"))
            source_url = url
            for row in parse_result_file(text):
                all_rows.append(ResultRow(
                    candidate_name=row["candidate_name"] or None,
                    option_label=None,
                    vote_count=int(row["candidate_votes"] or 0),
                    vote_pct=_safe_float(row["candidate_pct"]),
                    is_winner=None,
                    result_type="unofficial",
                    office_title=row["office_name"],
                    is_write_in_aggregate=is_write_in(row["candidate_order_code"]),
                    raw=row,
                ))

        if not all_rows:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="none",
                notes=f"No result rows parsed for election {election.source_id}",
            )

        checksum = hashlib.md5(bytes(file_bytes_for_checksum)).hexdigest()
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == checksum:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="full",
                unchanged=True, source_version=checksum,
            )

        return AdapterResult(
            rows=all_rows, source_url=source_url,
            mapping_confidence="full", source_version=checksum,
        )
```

- [ ] **Step 5: Register the adapter**

In `backend/results/apps.py`, find:

```python
            il,
```

Replace with:

```python
            il,
            mn,
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest --no-migrations results/tests/test_mn_adapter.py -v`
Expected: `3 passed`

- [ ] **Step 7: Commit**

```bash
git add backend/results/adapters/mn.py backend/results/apps.py backend/results/tests/
git commit -m "feat(mn): add MinnesotaAdapter Stage 2 results adapter"
```

---

### Task 11: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && pytest --no-migrations -v`
Expected: all tests pass, including every `integrations/mn_sos/` and `results/tests/test_mn_adapter.py` test from Tasks 1-10.

- [ ] **Step 2: Run Django system checks**

Run: `cd backend && python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: End-to-end smoke test — Stage 1 then Stage 2 against the same election**

Run this as a one-off script to confirm Stage 1's created races/candidates and Stage 2's parsed rows are internally consistent (both read the same live MN files independently — this is the closest this plan gets to the research doc's "validate imported totals against the public SOS portal" without a live network call in CI):

```bash
cd backend && python manage.py shell -c "
from unittest.mock import patch
from integrations.mn_sos.tasks import sync_mn_races
from results.adapters.mn import MinnesotaAdapter
from elections.models import Election, Race, Candidate

result = sync_mn_races()
print('Stage 1:', result)

election = Election.objects.get(source_id='mn_sos_2024_general')
adapter = MinnesotaAdapter()
adapter_result = adapter.fetch_results(election.election_date, election.pk)
print('Stage 2 rows:', len(adapter_result.rows))

senate_race = Race.objects.get(election=election, office_title='U.S. Senator')
senate_candidates = set(Candidate.objects.filter(race=senate_race).values_list('name', flat=True))
senate_result_names = {r.candidate_name for r in adapter_result.rows if r.office_title == 'U.S. Senator' and not r.is_write_in_aggregate}
print('Stage 1 candidates:', senate_candidates)
print('Stage 2 candidate names:', senate_result_names)
assert senate_candidates == senate_result_names, 'Stage 1/Stage 2 candidate sets diverge for U.S. Senator'
print('OK: Stage 1 and Stage 2 agree on U.S. Senator candidates')
"
```
Expected: no assertion error, `OK: Stage 1 and Stage 2 agree on U.S. Senator candidates` printed. This makes a real live network call (not run in CI) — run it locally against a scratch/dev database, not production.

- [ ] **Step 4: Confirm no uncommitted changes remain**

Run: `git status --short`
Expected: clean (only the fixture files already committed in earlier tasks).

---

## Deferred / Follow-up Work (not part of this plan)

- Live discovery of `ersElectionId` for elections other than the Nov 2024 POC (requires a `sync_mn_elections`-style task once a 2026 election ID is confirmed live).
- County/municipal/school/hospital-district races, ballot questions, district court races.
- Official certification (State Canvassing Board / county canvassing records).
- GIS/precinct geography, ranked-choice voting municipal adapters.
- GCP Cloud Scheduler job creation for `POST /internal/tasks/sync-mn-sos/` (infra, not in this repo — see `civicmirror-gcp-tasks` skill).
