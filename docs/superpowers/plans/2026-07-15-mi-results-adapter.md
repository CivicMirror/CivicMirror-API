# Michigan (MI) Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Michigan Stage 1 race/candidate ingestion from the official BOE entellitrak candidate-listing report and Stage 2 results ingestion from official MVIC VoteHistory results.

**Architecture:** Add a new `integrations.mi_sos` Django app for Michigan election discovery, BOE candidate-list parsing, MVIC client helpers, mappers, and Celery race sync. Add `results/adapters/mi.py` as the `StateResultsAdapter` that fetches MVIC bulk tab-delimited results through the existing Cloudflare solver and falls back to the unchallenged MVIC HTML endpoint when the bulk file is unavailable. Keep optional county TotalVote/KNOWiNK ENR out of the first implementation; it is a later supplement, not the official statewide source.

**Tech Stack:** Django, Celery, `requests`, `beautifulsoup4`, existing `core.cf_solver.CfSolverClient`, existing `aggregation.ingest`, existing `results.adapters.base.ResultRow`.

## Global Constraints

- State code is `MI`; new app package is `backend/integrations/mi_sos`; results adapter is `backend/results/adapters/mi.py`.
- Primary Stage 2 source is official MVIC VoteHistory bulk file: `https://mvic.sos.state.mi.us/VoteHistory/GetElectionResultFile?electionId=<id>`.
- Stage 2 fallback is official MVIC HTML: `https://mvic.sos.state.mi.us/VoteHistory/GetCountyVoteRecords?electionId=<id>`.
- MVIC bulk-file endpoints are Cloudflare managed-challenge protected; use `CfSolverClient.fetch_through_cf()`, not an in-process Playwright dependency.
- MVIC HTML fallback endpoints are curl-friendly; use normal `requests` with a browser user agent.
- Primary Stage 1 source is official BOE entellitrak report endpoint: `https://mi-boe.entellitrak.com/etk-mi-boe-prod/page.request.do?page=page.miboePublicReport&electionType=<PRI|GEN>&electionYear=<YYYY>`.
- Candidate rows with status `DISQ` or `WITHD` must not create running candidates. Preserve their raw status in `source_metadata`.
- `michiganelections.io` and county TotalVote are out of scope for this adapter build.
- Keep compact, reviewed fixtures in git; do not commit full HAR archives or bulky raw exports.
- The completed research source for this plan is `docs/state-research/MI/MI-Election_Research.md`.

---

## File Structure

- `backend/integrations/mi_sos/apps.py`: Django app config.
- `backend/integrations/mi_sos/exceptions.py`: Michigan-specific exception types.
- `backend/integrations/mi_sos/client.py`: HTTP client for MVIC and BOE entellitrak, including CF-solver bulk fetch.
- `backend/integrations/mi_sos/parsers.py`: Pure parsers for MVIC election select HTML, MVIC bulk TSV, MVIC county HTML, and BOE Jasper-style candidate report HTML.
- `backend/integrations/mi_sos/mappers.py`: Map parsed elections, contests, candidates, result rows, write-ins, parties, and office scopes into CivicMirror naming.
- `backend/integrations/mi_sos/tasks.py`: Celery Stage 1 sync task for BOE candidate listings and MVIC election-id metadata.
- `backend/results/adapters/mi.py`: Stage 2 results adapter that emits `AdapterResult` and `ResultRow`.
- `backend/integrations/mi_sos/tests/`: Unit tests and compact fixtures for parser/client/task behavior.
- `backend/results/tests/test_mi_adapter.py`: Adapter tests for metadata, bulk parsing, fallback parsing, version caching, registration, and malformed rows.
- `backend/results/apps.py`: Import `mi` so the adapter registers at startup.
- `backend/config/settings/base.py`: Add `integrations.mi_sos`.
- `backend/internal/views.py`, `backend/internal/urls.py`, `backend/internal/task_locks.py`: Wire manual/scheduler trigger only after task tests exist.

---

### Task 1: Scaffold `integrations.mi_sos`

**Files:**
- Create: `backend/integrations/mi_sos/__init__.py`
- Create: `backend/integrations/mi_sos/apps.py`
- Create: `backend/integrations/mi_sos/exceptions.py`
- Create: `backend/integrations/mi_sos/tests/__init__.py`
- Modify: `backend/config/settings/base.py`

**Interfaces:**
- Produces: `MiSosError`, `MiSosRetryableError`.
- Produces: installed Django app label `mi_sos`.

- [ ] **Step 1: Write the app config**

```python
# backend/integrations/mi_sos/apps.py
from django.apps import AppConfig


class MichiganSosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.mi_sos"
    label = "mi_sos"
    verbose_name = "Michigan SOS Integration"
```

- [ ] **Step 2: Write exceptions**

```python
# backend/integrations/mi_sos/exceptions.py
class MiSosError(Exception):
    """Non-retryable Michigan SOS integration error."""


class MiSosRetryableError(MiSosError):
    """Transient Michigan SOS integration error that should retry."""
```

- [ ] **Step 3: Create empty package files**

```bash
mkdir -p backend/integrations/mi_sos/tests
touch backend/integrations/mi_sos/__init__.py
touch backend/integrations/mi_sos/tests/__init__.py
```

- [ ] **Step 4: Register the app**

In `backend/config/settings/base.py`, add the app near the other state integrations:

```python
    'integrations.mn_sos',
    'integrations.mi_sos',
    'internal',
```

- [ ] **Step 5: Verify Django loads**

Run:

```bash
cd backend
python3 manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/mi_sos backend/config/settings/base.py
git commit -m "feat(mi): scaffold Michigan SOS integration"
```

---

### Task 2: Parse MVIC Election Discovery

**Files:**
- Create: `backend/integrations/mi_sos/parsers.py`
- Create: `backend/integrations/mi_sos/client.py`
- Create: `backend/integrations/mi_sos/tests/fixtures/mvic_votehistory.html`
- Create: `backend/integrations/mi_sos/tests/test_parsers.py`
- Create: `backend/integrations/mi_sos/tests/test_client.py`

**Interfaces:**
- Produces: `parse_mvic_elections(html: str) -> list[dict[str, str]]`, each dict has `election_id`, `date`, `name`, `type`.
- Produces: `MiSosClient.fetch_votehistory_page() -> str`.

- [ ] **Step 1: Capture compact fixture from MVIC**

```bash
mkdir -p backend/integrations/mi_sos/tests/fixtures
curl -fsS -A "Mozilla/5.0" \
  "https://mvic.sos.state.mi.us/votehistory/" \
  -o backend/integrations/mi_sos/tests/fixtures/mvic_votehistory.html
grep -E "ElectionDateId|705|699" backend/integrations/mi_sos/tests/fixtures/mvic_votehistory.html | head
```

Expected: the output includes an `ElectionDateId` select or option values such as `705` or `699`.

- [ ] **Step 2: Write failing parser tests**

```python
# backend/integrations/mi_sos/tests/test_parsers.py
from pathlib import Path

from integrations.mi_sos.parsers import parse_mvic_elections

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_mvic_elections_extracts_ids_dates_and_types():
    elections = parse_mvic_elections(_fixture("mvic_votehistory.html"))
    by_id = {e["election_id"]: e for e in elections}

    assert "705" in by_id
    assert by_id["705"]["date"] == "5/5/2026"
    assert "MAY CONSOLIDATED" in by_id["705"]["name"].upper()


def test_parse_mvic_elections_returns_empty_for_missing_select():
    assert parse_mvic_elections("<html><body>No elections</body></html>") == []
```

- [ ] **Step 3: Run parser tests and verify RED**

Run:

```bash
cd backend
python3 -m pytest integrations/mi_sos/tests/test_parsers.py -q
```

Expected: failure because `integrations.mi_sos.parsers` does not exist.

- [ ] **Step 4: Implement election parser**

```python
# backend/integrations/mi_sos/parsers.py
from __future__ import annotations

import re

from bs4 import BeautifulSoup


_DATE_RE = re.compile(r"(?P<date>\d{1,2}/\d{1,2}/\d{4})")


def parse_mvic_elections(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    select = soup.find("select", id=lambda value: value and "ElectionDateId" in value)
    if select is None:
        select = soup.find("select", attrs={"name": lambda value: value and "ElectionDateId" in value})
    if select is None:
        return []

    elections: list[dict[str, str]] = []
    for option in select.find_all("option"):
        election_id = (option.get("value") or "").strip()
        label = option.get_text(" ", strip=True)
        if not election_id or not label:
            continue
        match = _DATE_RE.search(label)
        date_text = match.group("date") if match else ""
        name = label.replace(date_text, "").strip(" -") if date_text else label
        elections.append({
            "election_id": election_id,
            "date": date_text,
            "name": name,
            "type": name,
        })
    return elections
```

- [ ] **Step 5: Add client and client test**

```python
# backend/integrations/mi_sos/client.py
from __future__ import annotations

import requests

from .exceptions import MiSosRetryableError

_MVIC_BASE = "https://mvic.sos.state.mi.us"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


class MiSosClient:
    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def fetch_votehistory_page(self) -> str:
        try:
            resp = self.session.get(f"{_MVIC_BASE}/votehistory/", timeout=self.timeout)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            raise MiSosRetryableError(f"MVIC votehistory page fetch failed: {exc}") from exc
```

```python
# backend/integrations/mi_sos/tests/test_client.py
from unittest.mock import MagicMock, patch

from integrations.mi_sos.client import MiSosClient


def test_fetch_votehistory_page_uses_mvic_url():
    response = MagicMock()
    response.text = "<html>ok</html>"
    response.raise_for_status.return_value = None

    with patch("integrations.mi_sos.client.requests.Session") as session_cls:
        session_cls.return_value.get.return_value = response
        text = MiSosClient().fetch_votehistory_page()

    assert text == "<html>ok</html>"
    session_cls.return_value.get.assert_called_once()
    assert "mvic.sos.state.mi.us/votehistory" in session_cls.return_value.get.call_args.args[0]
```

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```bash
cd backend
python3 -m pytest integrations/mi_sos/tests/test_parsers.py integrations/mi_sos/tests/test_client.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/integrations/mi_sos
git commit -m "feat(mi): parse MVIC election registry"
```

---

### Task 3: Parse BOE Entellitrak Candidate Listings

**Files:**
- Modify: `backend/integrations/mi_sos/parsers.py`
- Create: `backend/integrations/mi_sos/mappers.py`
- Create: `backend/integrations/mi_sos/tests/fixtures/boe_candidate_listing_2026_primary.html`
- Modify: `backend/integrations/mi_sos/tests/test_parsers.py`
- Create: `backend/integrations/mi_sos/tests/test_mappers.py`

**Interfaces:**
- Produces: `parse_boe_candidate_listing(html: str) -> list[dict[str, str]]`.
- Produces: `normalize_office_title(raw_office: str) -> str`.
- Produces: `candidate_status(raw_status: str) -> str`.

- [ ] **Step 1: Capture compact BOE fixture**

```bash
curl -fsS -A "Mozilla/5.0" \
  "https://mi-boe.entellitrak.com/etk-mi-boe-prod/page.request.do?page=page.miboePublicReport&electionType=PRI&electionYear=2026" \
  -o backend/integrations/mi_sos/tests/fixtures/boe_candidate_listing_2026_primary.html
grep -E "Official Candidate Listing|Candidate Name|DISQ|WITHD" \
  backend/integrations/mi_sos/tests/fixtures/boe_candidate_listing_2026_primary.html | head
```

Expected: output includes `Official Candidate Listing` or candidate table markers.

- [ ] **Step 2: Write failing parser tests**

```python
# append to backend/integrations/mi_sos/tests/test_parsers.py
from integrations.mi_sos.parsers import parse_boe_candidate_listing


def test_parse_boe_candidate_listing_extracts_contests_and_candidates():
    rows = parse_boe_candidate_listing(_fixture("boe_candidate_listing_2026_primary.html"))

    assert rows
    sample = rows[0]
    assert set(sample) == {
        "office_title",
        "party",
        "incumbent",
        "filing_method",
        "status",
        "candidate_name",
        "candidate_address",
        "filed_on",
    }
    assert any("GOVERNOR" in row["office_title"].upper() for row in rows)


def test_parse_boe_candidate_listing_preserves_withdrawn_and_disqualified_statuses():
    rows = parse_boe_candidate_listing(_fixture("boe_candidate_listing_2026_primary.html"))
    statuses = {row["status"] for row in rows}
    assert {"DISQ", "WITHD"} & statuses
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
cd backend
python3 -m pytest integrations/mi_sos/tests/test_parsers.py::test_parse_boe_candidate_listing_extracts_contests_and_candidates -q
```

Expected: failure because `parse_boe_candidate_listing` is missing.

- [ ] **Step 4: Implement a schema-guarded parser**

Add this to `backend/integrations/mi_sos/parsers.py`:

```python
_STATUS_CODES = {"", "DISQ", "WITHD"}


def parse_boe_candidate_listing(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    text_rows = []
    for tr in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
        cells = [cell for cell in cells if cell]
        if cells:
            text_rows.append(cells)

    current_office = ""
    candidates: list[dict[str, str]] = []
    for cells in text_rows:
        joined = " ".join(cells)
        if len(cells) == 1 and "candidate" not in joined.lower():
            current_office = cells[0]
            continue
        if "Candidate Name" in joined and "Filed On" in joined:
            continue
        if len(cells) < 6 or not current_office:
            continue

        status = ""
        status_index = None
        for idx, cell in enumerate(cells):
            if cell in _STATUS_CODES:
                status = cell
                status_index = idx
                break
        if status_index is None or status_index + 1 >= len(cells):
            continue

        candidates.append({
            "office_title": current_office,
            "party": cells[0],
            "incumbent": cells[1] if len(cells) > 1 else "",
            "filing_method": cells[2] if len(cells) > 2 else "",
            "status": status,
            "candidate_name": cells[status_index + 1],
            "candidate_address": cells[status_index + 2] if status_index + 2 < len(cells) else "",
            "filed_on": cells[-1],
        })
    return candidates
```

- [ ] **Step 5: Write mapper tests**

```python
# backend/integrations/mi_sos/tests/test_mappers.py
from elections.models import Candidate
from integrations.mi_sos.mappers import candidate_status, normalize_office_title, party_abbrev


def test_normalize_office_title_handles_state_and_district_offices():
    assert normalize_office_title("GOVERNOR 4 Year Term (1) Position") == "Governor"
    assert normalize_office_title("UNITED STATES REPRESENTATIVE 7th District") == "U.S. House - District 7"
    assert normalize_office_title("STATE REPRESENTATIVE 55th District") == "State House - District 55"


def test_candidate_status_maps_withdrawn_and_disqualified():
    assert candidate_status("") == Candidate.CandidateStatus.RUNNING
    assert candidate_status("WITHD") == Candidate.CandidateStatus.WITHDRAWN
    assert candidate_status("DISQ") == Candidate.CandidateStatus.DISQUALIFIED


def test_party_abbrev_maps_common_michigan_parties():
    assert party_abbrev("Democratic") == "DEM"
    assert party_abbrev("Republican") == "REP"
    assert party_abbrev("Libertarian") == "LIB"
```

- [ ] **Step 6: Implement mappers**

```python
# backend/integrations/mi_sos/mappers.py
from __future__ import annotations

import re

from elections.models import Candidate

_PARTY_MAP = {
    "democratic": "DEM",
    "democrat": "DEM",
    "republican": "REP",
    "libertarian": "LIB",
    "green": "GRN",
    "working class": "WCP",
    "natural law": "NLP",
    "us taxpayers": "UST",
}


def party_abbrev(raw_party: str) -> str:
    normalized = (raw_party or "").strip().lower()
    return _PARTY_MAP.get(normalized, normalized.upper()[:3])


def candidate_status(raw_status: str) -> str:
    status = (raw_status or "").strip().upper()
    if status == "WITHD":
        return Candidate.CandidateStatus.WITHDRAWN
    if status == "DISQ":
        return Candidate.CandidateStatus.DISQUALIFIED
    return Candidate.CandidateStatus.RUNNING


def normalize_office_title(raw_office: str) -> str:
    office = " ".join((raw_office or "").split())
    upper = office.upper()
    district_match = re.search(r"(\d+)(?:ST|ND|RD|TH)?\s+DISTRICT", upper)
    district = district_match.group(1) if district_match else ""
    if "GOVERNOR" in upper and "LIEUTENANT" not in upper:
        return "Governor"
    if "UNITED STATES SENATOR" in upper or "U.S. SENATOR" in upper:
        return "U.S. Senate"
    if "UNITED STATES REPRESENTATIVE" in upper or "U.S. REPRESENTATIVE" in upper:
        return f"U.S. House - District {district}" if district else "U.S. House"
    if "STATE SENATOR" in upper:
        return f"State Senate - District {district}" if district else "State Senate"
    if "STATE REPRESENTATIVE" in upper:
        return f"State House - District {district}" if district else "State House"
    return office
```

- [ ] **Step 7: Run tests**

Run:

```bash
cd backend
python3 -m pytest integrations/mi_sos/tests/test_parsers.py integrations/mi_sos/tests/test_mappers.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/integrations/mi_sos
git commit -m "feat(mi): parse BOE candidate listings"
```

---

### Task 4: Build Stage 1 Race/Candidate Sync

**Files:**
- Modify: `backend/integrations/mi_sos/client.py`
- Modify: `backend/integrations/mi_sos/mappers.py`
- Create: `backend/integrations/mi_sos/tasks.py`
- Create: `backend/integrations/mi_sos/tests/test_tasks.py`

**Interfaces:**
- Produces: `sync_mi_elections()` Celery task.
- Produces: `MiSosClient.fetch_candidate_listing(election_type: str, election_year: int) -> str`.

- [ ] **Step 1: Add client method test**

```python
# append to backend/integrations/mi_sos/tests/test_client.py
def test_fetch_candidate_listing_uses_entellitrak_report_endpoint():
    response = MagicMock()
    response.text = "<html>candidate report</html>"
    response.raise_for_status.return_value = None

    with patch("integrations.mi_sos.client.requests.Session") as session_cls:
        session_cls.return_value.get.return_value = response
        text = MiSosClient().fetch_candidate_listing("PRI", 2026)

    assert text == "<html>candidate report</html>"
    url = session_cls.return_value.get.call_args.args[0]
    params = session_cls.return_value.get.call_args.kwargs["params"]
    assert "mi-boe.entellitrak.com" in url
    assert params == {
        "page": "page.miboePublicReport",
        "electionType": "PRI",
        "electionYear": 2026,
    }
```

- [ ] **Step 2: Implement client method**

```python
# add to MiSosClient in backend/integrations/mi_sos/client.py
def fetch_candidate_listing(self, election_type: str, election_year: int) -> str:
    url = "https://mi-boe.entellitrak.com/etk-mi-boe-prod/page.request.do"
    try:
        resp = self.session.get(
            url,
            params={
                "page": "page.miboePublicReport",
                "electionType": election_type,
                "electionYear": election_year,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        raise MiSosRetryableError(f"BOE candidate listing fetch failed: {exc}") from exc
```

- [ ] **Step 3: Write task test**

```python
# backend/integrations/mi_sos/tests/test_tasks.py
from unittest.mock import patch

import pytest

from elections.models import Candidate, Election, Race
from integrations.mi_sos.tasks import sync_mi_elections


@pytest.mark.django_db
def test_sync_mi_elections_creates_election_race_and_running_candidate():
    html = "<html>fixture</html>"
    parsed = [{
        "office_title": "GOVERNOR 4 Year Term (1) Position",
        "party": "Democratic",
        "incumbent": "",
        "filing_method": "Petitions",
        "status": "",
        "candidate_name": "Jane Candidate",
        "candidate_address": "1 Main St",
        "filed_on": "4/21/2026",
    }]

    with patch("integrations.mi_sos.tasks.MiSosClient") as client_cls, \
         patch("integrations.mi_sos.tasks.parse_boe_candidate_listing", return_value=parsed):
        client_cls.return_value.fetch_candidate_listing.return_value = html
        result = sync_mi_elections()

    assert result["created"] >= 2
    election = Election.objects.get(state="MI", election_type="primary", election_date="2026-08-04")
    race = Race.objects.get(election=election, office_title="Governor")
    candidate = Candidate.objects.get(race=race, name="Jane Candidate")
    assert candidate.party == "DEM"
    assert candidate.candidate_status == Candidate.CandidateStatus.RUNNING
```

- [ ] **Step 4: Implement task**

```python
# backend/integrations/mi_sos/tasks.py
from __future__ import annotations

from datetime import date

from celery import shared_task
from django.utils import timezone

from elections.models import Candidate, Election, Race
from ops.models import SyncLog

from .client import MiSosClient
from .exceptions import MiSosRetryableError
from .mappers import candidate_status, normalize_office_title, party_abbrev
from .parsers import parse_boe_candidate_listing

_MI_ELECTION_SPECS = [
    {
        "name": "2026 Michigan Primary Election",
        "election_type": "primary",
        "election_date": date(2026, 8, 4),
        "boe_type": "PRI",
        "boe_year": 2026,
        "source_id": "mi_sos_2026_primary",
    },
    {
        "name": "2026 Michigan General Election",
        "election_type": "general",
        "election_date": date(2026, 11, 3),
        "boe_type": "GEN",
        "boe_year": 2026,
        "source_id": "mi_sos_2026_general",
    },
]


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_mi_elections(self):
    from aggregation import ingest

    sync_log = SyncLog.objects.create(
        source="mi_sos",
        task_name="sync_mi_elections",
        status=SyncLog.Status.STARTED,
    )
    created = updated = 0
    client = MiSosClient()
    try:
        for spec in _MI_ELECTION_SPECS:
            election, _ = ingest.ingest_election(
                source="mi_sos",
                source_id=spec["source_id"],
                identity={
                    "state": "MI",
                    "election_type": spec["election_type"],
                    "election_date": spec["election_date"],
                    "jurisdiction_level": Election.JurisdictionLevel.STATE,
                },
                fields={
                    "name": spec["name"],
                    "status": (
                        Election.Status.UPCOMING
                        if spec["election_date"] > timezone.localdate()
                        else Election.Status.RESULTS_PENDING
                    ),
                },
            )
            rows = parse_boe_candidate_listing(
                client.fetch_candidate_listing(spec["boe_type"], spec["boe_year"])
            )
            seen: set[int] = set()
            for row in rows:
                office_title = normalize_office_title(row["office_title"])
                race, race_created = ingest.ingest_race(
                    election=election,
                    source="mi_sos",
                    identity={
                        "office_title": office_title,
                        "ocd_division_id": "",
                        "race_type": Race.RaceType.CANDIDATE,
                    },
                    fields={
                        "jurisdiction": "Michigan",
                        "source_metadata": {"mi_office_raw": row["office_title"]},
                    },
                )
                created += int(race_created)
                cand, cand_created = ingest.ingest_candidate(
                    race=race,
                    source="mi_sos",
                    name=row["candidate_name"],
                    party=party_abbrev(row["party"]),
                    fields={
                        "candidate_status": candidate_status(row["status"]),
                        "source_metadata": {
                            "mi_candidate_status_raw": row["status"],
                            "mi_filing_method": row["filing_method"],
                            "mi_candidate_address": row["candidate_address"],
                            "mi_filed_on": row["filed_on"],
                        },
                    },
                )
                seen.add(cand.pk)
                created += int(cand_created)
                updated += int(not cand_created)

            Candidate.objects.filter(
                race__election=election,
                race__source="mi_sos",
                candidate_status=Candidate.CandidateStatus.RUNNING,
            ).exclude(pk__in=seen).update(candidate_status=Candidate.CandidateStatus.WITHDRAWN)
            election.last_synced_at = timezone.now()
            election.save(update_fields=["last_synced_at"])

        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "status", "completed_at"])
        return {"created": created, "updated": updated}
    except MiSosRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

- [ ] **Step 5: Run task tests**

Run:

```bash
cd backend
python3 -m pytest integrations/mi_sos/tests/test_tasks.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/mi_sos
git commit -m "feat(mi): sync BOE races and candidates"
```

---

### Task 5: Parse MVIC Bulk Results and HTML Fallback

**Files:**
- Modify: `backend/integrations/mi_sos/parsers.py`
- Modify: `backend/integrations/mi_sos/mappers.py`
- Create: `backend/integrations/mi_sos/tests/fixtures/mvic_result_file_705.tsv`
- Create: `backend/integrations/mi_sos/tests/fixtures/mvic_county_records_705.html`
- Modify: `backend/integrations/mi_sos/tests/test_parsers.py`

**Interfaces:**
- Produces: `parse_mvic_result_file(text: str) -> list[dict[str, str]]`.
- Produces: `parse_mvic_county_results_html(html: str) -> list[dict[str, str]]`.
- Produces: `result_office_title(raw_contest: str) -> str`.
- Produces: `is_write_in(candidate_name: str) -> bool`.

- [ ] **Step 1: Capture compact MVIC fixtures**

Use browser/CF solver output for the bulk file when available. Keep the fixture compact by saving the first contest block and a few candidate rows, not the full statewide export:

```bash
mkdir -p backend/integrations/mi_sos/tests/fixtures
curl -fsS -A "Mozilla/5.0" \
  "https://mvic.sos.state.mi.us/VoteHistory/GetCountyVoteRecords?electionId=705" \
  -o backend/integrations/mi_sos/tests/fixtures/mvic_county_records_705.html
```

If a CF-solved full `GetElectionResultFile?electionId=705` sample is available, trim it to a compact fixture:

```bash
head -n 40 /tmp/mi_mvic_result_file_705.tsv > backend/integrations/mi_sos/tests/fixtures/mvic_result_file_705.tsv
```

- [ ] **Step 2: Write parser tests**

```python
# append to backend/integrations/mi_sos/tests/test_parsers.py
from integrations.mi_sos.parsers import parse_mvic_county_results_html, parse_mvic_result_file


def test_parse_mvic_result_file_returns_candidate_rows():
    rows = parse_mvic_result_file(_fixture("mvic_result_file_705.tsv"))
    assert rows
    sample = rows[0]
    assert {"contest", "party", "candidate_name", "votes", "vote_pct", "county"} <= set(sample)


def test_parse_mvic_county_results_html_returns_candidate_rows():
    rows = parse_mvic_county_results_html(_fixture("mvic_county_records_705.html"))
    assert rows
    names = {row["candidate_name"] for row in rows}
    assert "GREENE, CHEDRICK" in names
    greene = next(row for row in rows if row["candidate_name"] == "GREENE, CHEDRICK")
    assert greene["votes"] == "36583"
    assert greene["vote_pct"] == "58.88"
```

- [ ] **Step 3: Implement parser functions**

```python
# add to backend/integrations/mi_sos/parsers.py
import csv
import io


def parse_mvic_result_file(text: str) -> list[dict[str, str]]:
    if not (text or "").strip():
        return []
    sample = text[:2048]
    dialect = csv.Sniffer().sniff(sample, delimiters="\t,|")
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = []
    for record in reader:
        normalized = {str(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in record.items()}
        contest = normalized.get("contest") or normalized.get("office") or normalized.get("race")
        candidate = normalized.get("candidate") or normalized.get("candidate_name")
        votes = normalized.get("votes") or normalized.get("vote_total")
        if not contest or not candidate or votes is None:
            continue
        rows.append({
            "contest": contest,
            "party": normalized.get("party", ""),
            "candidate_name": candidate,
            "votes": votes.replace(",", ""),
            "vote_pct": (normalized.get("pct") or normalized.get("percent") or "").replace("%", ""),
            "county": normalized.get("county", ""),
            "raw": normalized,
        })
    return rows


def parse_mvic_county_results_html(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows = []
    current_contest = ""
    current_party = ""
    for line in lines:
        upper = line.upper()
        if " POSITION" in upper or " TERM " in upper:
            current_contest = line
            current_party = ""
            continue
        if upper in {"DEMOCRATIC", "REPUBLICAN", "LIBERTARIAN", "GREEN", "NONPARTISAN"}:
            current_party = line
            continue
        parts = [part.strip() for part in re.split(r"\s{2,}|\t", line) if part.strip()]
        if current_contest and len(parts) >= 3 and re.match(r"^[\d,]+$", parts[-2]):
            rows.append({
                "contest": current_contest,
                "party": current_party,
                "candidate_name": " ".join(parts[:-2]),
                "votes": parts[-2].replace(",", ""),
                "vote_pct": parts[-1].replace("%", ""),
                "county": "",
                "raw": {"source": "mvic_html", "line": line},
            })
    return rows
```

- [ ] **Step 4: Implement mapper helpers**

```python
# append to backend/integrations/mi_sos/mappers.py
def result_office_title(raw_contest: str) -> str:
    return normalize_office_title(raw_contest)


def is_write_in(candidate_name: str) -> bool:
    return "WRITE" in (candidate_name or "").upper()
```

- [ ] **Step 5: Run parser tests**

Run:

```bash
cd backend
python3 -m pytest integrations/mi_sos/tests/test_parsers.py integrations/mi_sos/tests/test_mappers.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/mi_sos
git commit -m "feat(mi): parse MVIC result payloads"
```

---

### Task 6: Build MVIC Client Bulk and Fallback Fetching

**Files:**
- Modify: `backend/integrations/mi_sos/client.py`
- Modify: `backend/integrations/mi_sos/tests/test_client.py`

**Interfaces:**
- Produces: `MiSosClient.fetch_result_file(election_id: int) -> str`.
- Produces: `MiSosClient.fetch_county_vote_records(election_id: int) -> str`.

- [ ] **Step 1: Write client tests**

```python
# append to backend/integrations/mi_sos/tests/test_client.py
def test_fetch_result_file_uses_cf_solver_payload_fetch():
    with patch("integrations.mi_sos.client.CfSolverClient") as solver_cls:
        solver_cls.return_value.fetch_through_cf.return_value = "bulk text"
        text = MiSosClient().fetch_result_file(705)

    assert text == "bulk text"
    solve_url, payload_url = solver_cls.return_value.fetch_through_cf.call_args.args[:2]
    assert solve_url == "https://mvic.sos.state.mi.us/votehistory/"
    assert payload_url.endswith("/VoteHistory/GetElectionResultFile?electionId=705")


def test_fetch_county_vote_records_uses_plain_requests():
    response = MagicMock()
    response.text = "<html>county records</html>"
    response.raise_for_status.return_value = None

    with patch("integrations.mi_sos.client.requests.Session") as session_cls:
        session_cls.return_value.get.return_value = response
        text = MiSosClient().fetch_county_vote_records(705)

    assert text == "<html>county records</html>"
    assert "GetCountyVoteRecords" in session_cls.return_value.get.call_args.args[0]
```

- [ ] **Step 2: Implement methods**

```python
# add imports to backend/integrations/mi_sos/client.py
from core.cf_solver import CfSolverClient, CfSolverError


# add methods to MiSosClient
def fetch_result_file(self, election_id: int) -> str:
    payload_url = f"{_MVIC_BASE}/VoteHistory/GetElectionResultFile?electionId={election_id}"
    try:
        return CfSolverClient().fetch_through_cf(
            f"{_MVIC_BASE}/votehistory/",
            payload_url,
            payload_referer=f"{_MVIC_BASE}/votehistory/",
        )
    except CfSolverError as exc:
        raise MiSosRetryableError(f"MVIC result file CF fetch failed: {exc}") from exc


def fetch_county_vote_records(self, election_id: int) -> str:
    try:
        resp = self.session.get(
            f"{_MVIC_BASE}/VoteHistory/GetCountyVoteRecords",
            params={"electionId": election_id},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        raise MiSosRetryableError(f"MVIC county vote records fetch failed: {exc}") from exc
```

- [ ] **Step 3: Run client tests**

Run:

```bash
cd backend
python3 -m pytest integrations/mi_sos/tests/test_client.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/integrations/mi_sos/client.py backend/integrations/mi_sos/tests/test_client.py
git commit -m "feat(mi): add MVIC result client"
```

---

### Task 7: Build `MichiganAdapter`

**Files:**
- Create: `backend/results/adapters/mi.py`
- Create: `backend/results/tests/test_mi_adapter.py`
- Modify: `backend/results/apps.py`

**Interfaces:**
- Produces: `MichiganAdapter(StateResultsAdapter)` registered under state `MI`.
- Consumes: `MiSosClient.fetch_result_file`, `MiSosClient.fetch_county_vote_records`, `parse_mvic_result_file`, `parse_mvic_county_results_html`, `result_office_title`, `is_write_in`.

- [ ] **Step 1: Write adapter tests**

```python
# backend/results/tests/test_mi_adapter.py
from unittest.mock import MagicMock, patch

import pytest

from elections.models import Election
from results.adapters.mi import MichiganAdapter


def test_mi_adapter_registered():
    import results.adapters.mi  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "MI" in list_supported_states()
    assert get_adapter("MI") is MichiganAdapter


@pytest.mark.django_db
def test_fetch_results_requires_mvic_election_id_metadata():
    election = Election.objects.create(
        name="MI Test",
        election_date="2026-05-05",
        election_type="special",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MI",
        source_id="mi_test",
    )

    result = MichiganAdapter().fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "none"
    assert "mi_mvic_election_id" in result.notes


@pytest.mark.django_db
@patch("results.adapters.mi.cache")
@patch("results.adapters.mi.MiSosClient")
def test_fetch_results_uses_bulk_file_first(client_cls, cache_mock):
    election = Election.objects.create(
        name="MI Test",
        election_date="2026-05-05",
        election_type="special",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MI",
        source_id="mi_test",
        source_metadata={"mi_mvic_election_id": 705},
    )
    cache_mock.get.return_value = None
    client_cls.return_value.fetch_result_file.return_value = (
        "contest\tcandidate\tvotes\tpct\tparty\tcounty\n"
        "35TH DISTRICT STATE SENATOR\tGREENE, CHEDRICK\t36583\t58.88\tDEMOCRATIC\tBAY\n"
    )

    result = MichiganAdapter().fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "full"
    assert result.rows[0].candidate_name == "GREENE, CHEDRICK"
    assert result.rows[0].vote_count == 36583
    assert result.rows[0].jurisdiction_fragment == "BAY"
    client_cls.return_value.fetch_county_vote_records.assert_not_called()


@pytest.mark.django_db
@patch("results.adapters.mi.cache")
@patch("results.adapters.mi.MiSosClient")
def test_fetch_results_falls_back_to_html_when_bulk_fetch_fails(client_cls, cache_mock):
    from integrations.mi_sos.exceptions import MiSosRetryableError

    election = Election.objects.create(
        name="MI Test",
        election_date="2026-05-05",
        election_type="special",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MI",
        source_id="mi_test",
        source_metadata={"mi_mvic_election_id": 705},
    )
    cache_mock.get.return_value = None
    client = client_cls.return_value
    client.fetch_result_file.side_effect = MiSosRetryableError("cf blocked")
    client.fetch_county_vote_records.return_value = """
    35TH DISTRICT STATE SENATOR PARTIAL TERM ENDING 1/1/2027 (1) POSITION
    DEMOCRATIC
    GREENE, CHEDRICK  36,583  58.88%
    """

    result = MichiganAdapter().fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "partial"
    assert result.rows[0].candidate_name == "GREENE, CHEDRICK"
    assert result.rows[0].vote_count == 36583
```

- [ ] **Step 2: Run adapter tests and verify RED**

Run:

```bash
cd backend
python3 -m pytest results/tests/test_mi_adapter.py -q
```

Expected: failure because `results.adapters.mi` does not exist.

- [ ] **Step 3: Implement adapter**

```python
# backend/results/adapters/mi.py
from __future__ import annotations

import hashlib
import logging

from django.core.cache import cache

from integrations.mi_sos.client import MiSosClient
from integrations.mi_sos.exceptions import MiSosRetryableError
from integrations.mi_sos.mappers import is_write_in, result_office_title
from integrations.mi_sos.parsers import parse_mvic_county_results_html, parse_mvic_result_file

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30


def _safe_int(value) -> int:
    try:
        return int(str(value or "0").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0


def _safe_float(value):
    try:
        return float(str(value or "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _to_result_rows(raw_rows: list[dict[str, str]], result_type: str) -> list[ResultRow]:
    rows = []
    for raw in raw_rows:
        name = raw.get("candidate_name", "").strip()
        write_in = is_write_in(name)
        rows.append(ResultRow(
            candidate_name=name if name else None,
            option_label=None,
            vote_count=_safe_int(raw.get("votes")),
            vote_pct=_safe_float(raw.get("vote_pct")),
            is_winner=None,
            result_type=result_type,
            office_title=result_office_title(raw.get("contest", "")),
            is_write_in_aggregate=write_in,
            jurisdiction_fragment=(raw.get("county") or "").strip(),
            raw=raw,
        ))
    return rows


@register
class MichiganAdapter(StateResultsAdapter):
    state = "MI"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"mi_mvic:checksum:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            return AdapterResult(rows=[], source_url="", mapping_confidence="none", notes=f"Election {election_id} not found")

        mvic_id = (election.source_metadata or {}).get("mi_mvic_election_id")
        if not mvic_id:
            return AdapterResult(rows=[], source_url="", mapping_confidence="none", notes="Missing mi_mvic_election_id in election.source_metadata")

        client = MiSosClient()
        source_url = f"https://mvic.sos.state.mi.us/VoteHistory/GetElectionResultFile?electionId={mvic_id}"
        mapping_confidence = "full"
        try:
            text = client.fetch_result_file(int(mvic_id))
            raw_rows = parse_mvic_result_file(text)
        except MiSosRetryableError as exc:
            logger.warning("mi_mvic.bulk_fetch_failed election=%s: %s", mvic_id, exc)
            source_url = f"https://mvic.sos.state.mi.us/VoteHistory/GetCountyVoteRecords?electionId={mvic_id}"
            text = client.fetch_county_vote_records(int(mvic_id))
            raw_rows = parse_mvic_county_results_html(text)
            mapping_confidence = "partial"

        checksum = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
        if cache.get(self.version_cache_key(election_id)) == checksum:
            return AdapterResult(
                rows=[],
                source_url=source_url,
                mapping_confidence=mapping_confidence,
                unchanged=True,
                source_version=checksum,
            )

        result_type = "official"
        rows = _to_result_rows(raw_rows, result_type)
        return AdapterResult(
            rows=rows,
            source_url=source_url,
            mapping_confidence=mapping_confidence,
            source_version=checksum,
        )
```

- [ ] **Step 4: Register adapter**

In `backend/results/apps.py`, add `mi` to the adapter import list near `mn`:

```python
            me,
            mi,
            mn,
```

- [ ] **Step 5: Run adapter tests**

Run:

```bash
cd backend
python3 -m pytest results/tests/test_mi_adapter.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/results/adapters/mi.py backend/results/tests/test_mi_adapter.py backend/results/apps.py
git commit -m "feat(results): add Michigan results adapter"
```

---

### Task 8: Wire Internal Trigger for Stage 1

**Files:**
- Modify: `backend/internal/views.py`
- Modify: `backend/internal/urls.py`
- Modify: `backend/internal/task_locks.py`
- Modify: `backend/internal/management/commands/trigger_internal_task.py`
- Modify: `backend/internal/tests/test_clear_task_locks.py`
- Modify: `backend/internal/tests/test_views.py`
- Modify: `backend/internal/tests/test_management_commands.py`

**Interfaces:**
- Produces: `POST /internal/tasks/sync-mi-sos/`.
- Produces: local management command support for `python manage.py trigger_internal_task sync_mi_sos`.

- [ ] **Step 1: Add lock registry entry**

In `backend/internal/task_locks.py`, add:

```python
    "sync_mi_sos":          (WINDOW_DAILY,      23 * _HOUR),
```

- [ ] **Step 2: Wire view**

In `backend/internal/views.py`, import the task:

```python
from integrations.mi_sos.tasks import sync_mi_elections
```

Add trigger:

```python
@csrf_exempt
@require_POST
@require_internal_task_token
def sync_mi_sos_trigger(request):
    return _trigger("sync_mi_sos", sync_mi_elections, request)
```

- [ ] **Step 3: Wire URL**

In `backend/internal/urls.py`, add:

```python
    path("tasks/sync-mi-sos/", views.sync_mi_sos_trigger, name="internal-sync-mi-sos"),
```

- [ ] **Step 4: Wire local management command**

In `backend/internal/management/commands/trigger_internal_task.py`, import and register:

```python
from integrations.mi_sos.tasks import sync_mi_elections

LOCAL_TASKS = {
    "sync_mi_sos": sync_mi_elections,
    ...
}
```

- [ ] **Step 5: Add view/lock/management tests**

Add a view test following the `sync_or_sos` pattern:

```python
def test_sync_mi_sos_valid_token(client, internal_token):
    with patch("internal.views.sync_mi_elections") as mock_task:
        mock_task.apply_async.return_value.id = "mi-task-123"
        response = client.post(
            "/internal/tasks/sync-mi-sos/",
            HTTP_X_INTERNAL_TASK_TOKEN=internal_token,
        )
    assert response.status_code == 202
    assert response.json()["task_id"] == "mi-task-123"
```

The existing `test_registry_covers_every_triggered_task` should fail until `TASK_LOCKS` is updated; keep it in the verification command.

- [ ] **Step 6: Run internal tests**

Run:

```bash
cd backend
python3 -m pytest internal/tests/test_clear_task_locks.py internal/tests/test_views.py internal/tests/test_management_commands.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/internal
git commit -m "feat(mi): expose Michigan sync trigger"
```

---

### Task 9: Full Verification and Documentation Sync

**Files:**
- Modify: `docs/state-research/MI/MI-Election_Research.md` only if implementation reveals changed details.
- No code creation unless a verification failure reveals a defect.

**Interfaces:**
- Consumes: all previous task outputs.
- Produces: verified branch ready for review/PR.

- [ ] **Step 1: Run targeted parser/task/adapter tests**

```bash
cd backend
python3 -m pytest \
  integrations/mi_sos/tests \
  results/tests/test_mi_adapter.py \
  internal/tests/test_clear_task_locks.py \
  internal/tests/test_views.py \
  internal/tests/test_management_commands.py \
  -q
```

Expected: all tests pass.

- [ ] **Step 2: Run lint**

```bash
cd backend
ruff check integrations/mi_sos results/adapters/mi.py results/tests/test_mi_adapter.py internal
```

Expected: `All checks passed!`

- [ ] **Step 3: Run Django system check**

```bash
cd backend
python3 manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Inspect branch scope**

```bash
git status --short
git diff --stat main...HEAD
```

Expected: only MI research, MI integration, MI adapter, MI trigger, and MI tests are changed.

- [ ] **Step 5: Commit any doc correction**

If implementation changed the research facts, commit only the doc correction:

```bash
git add docs/state-research/MI/MI-Election_Research.md
git commit -m "docs(mi): update Michigan adapter research notes"
```

If no correction is needed, do not create a docs-only commit.

---

## Self-Review

**Spec coverage:** The plan covers Stage 1 election/race/candidate creation through BOE entellitrak, Stage 2 results ingestion through MVIC bulk files, Cloudflare handling through the existing CF solver, HTML fallback through unchallenged MVIC endpoints, adapter registration, internal trigger wiring, and tests. County TotalVote and michiganelections.io are explicitly out of scope.

**Placeholder scan:** No `TBD`, `TODO`, or unspecified “add tests” steps remain. Each task includes concrete files, code snippets, commands, and expected outcomes.

**Type consistency:** `MiSosClient`, `parse_*`, mapper names, `sync_mi_elections`, and `MichiganAdapter` signatures are consistent across tasks.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-15-mi-results-adapter.md`. Two execution options:

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

