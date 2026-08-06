# Utah (UT) Stage 1 Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build native Stage 1 (election discovery + race/candidate creation) for Utah, adding a new `integrations/ut_elections` package, so UT moves from Results Coverage Only to Full Core Coverage per GitHub issue #87. Stage 2 (`results/adapters/ut.py`, `UtahAdapter`) already exists and needs no changes — it reads Utah's Enhanced Voting ENR JSON API directly and cross-source race matching (normalized office-title keying, already live in production) reconciles its races against whatever Stage 1 creates without any UT-specific wiring.

**Architecture:** Two Celery tasks mirroring the MD/NC two-task split — `sync_ut_elections` (election discovery from a maintained statutory calendar table, since Utah's primary date is set by the legislature per cycle, not a fixed formula) and `sync_ut_races` (candidate/race creation from Utah's official Candidate Filing Excel workbook). Both live in `integrations/ut_elections/`. Scope is federal + state legislative + state executive offices only — same convention as MD/NC/VT.

**Tech Stack:** Python 3.13, Django 5.2, Celery, pytest, `requests`, `openpyxl` (already a project dependency, `requirements/base.txt`).

## Global Constraints

- Scope is federal + state legislative + state executive races only. In the source workbook this means the `Federal Offices`, `State Offices` (Governor/Lt. Governor, Attorney General, State Auditor, State Treasurer — not on the ballot in 2026 but present in gubernatorial-cycle years), `State Senate`, and `State House` sections. The `State School Board` and `State Judicial` (judicial retention questions) sections are explicitly OUT of scope for this wave — do not build parsing for them even though they're structurally present in the same workbook. Judicial retention in particular is not office/district/party/candidate-shaped (it's a yes/no retention question per judge) and would need the measure pipeline, not the candidate pipeline.
- Follow this repo's TDD convention: write the failing test first, watch it fail, then implement. Run tests with `pytest --no-migrations` (local test-DB creation breaks on an unrelated bad migration in this repo).
- Preserve every candidate's raw filing status in `source_metadata` even when it's mapped to a coarser `CandidateStatus` enum value — never discard the source's own wording.
- All new Django migrations go through the same two-file pattern already established: one `elections` migration adding the `Race.Source` enum value, one `aggregation` migration seeding `SourcePrecedence` rows.
- Register the new app in `config/settings/base.py`'s `INSTALLED_APPS`, same as every other `integrations.*_sos`/`*_sbe`/`*_elections` package.

---

## Live-Verified Source Facts (2026-08-05)

These are not assumptions — confirmed today via a direct HTTPS fetch of the real live file, cited here so the plan's code isn't guessing:

- **URL:** `https://vote.utah.gov/wp-content/uploads/2026/06/Candidate-Filing-2026.xlsx` — fetched live, HTTP 200, 419-row single-sheet (`Sheet1`) workbook, 4 columns wide (`A1:D419`).
- **The workbook is NOT a flat table.** It is a hand-formatted sectioned layout: a section-title row (single non-empty cell in column A, e.g. `"Federal Offices"`), a blank row, a sub-header row (`Candidate | Office | Party | Status`), then data rows, then a blank row before the next section. Confirmed section titles present in the live 2026 file, in order: `Federal Offices`, `State Senate`, `State House`, `State School Board`, `State Judicial`. (`State Offices` — the section for Governor/Lt. Governor/Attorney General/Auditor/Treasurer — is not present in the live file because Utah elects those offices only in presidential-cycle years, 2024/2028, not 2026; it must still be treated as in-scope in the parser for forward-compatibility with the next cycle that includes it.)
- **No separate district column.** The `Office` column embeds the district as free text within the same cell, e.g. `"U.S. House District 1"`, `"State Senate District 1 (Multi-County)"`, `"State House District 10"`, `"State School Board Distrct 11 (Multi-County)"` (source's own typo, "Distrct" — expect this section excluded from scope anyway per the constraint above, but do not "fix" source typos elsewhere in this workbook if any turn up in in-scope sections). Store the `Office` cell verbatim as `office_title` — no split into office-type + district is needed, unlike Maryland.
- **Candidate names are ALL CAPS** in the source (`"BEN MCADAMS"`, `"JASON O'DELL"`). Python's `str.title()` gets ordinary names and `O'Dell`-style apostrophe names right, but not `Mc`/`Mac` surnames (`"BEN MCADAMS".title()` → `"Ben Mcadams"`, not `"Ben McAdams"`) — accepted as a known display-quality limitation, not fixed in this plan (no name dictionary available; flagged in code as a comment, not silently "solved").
- **Status vocabulary observed** (column D): `Election Candidate`, `Out in Convention`, `Out in Primary`, `Withdrew`, `Disqualified`. (`Filed` and `Primary` are documented as possible earlier-stage statuses in `docs/state-research/UT/UT-Election_Research.md` but were not observed live today — the current snapshot is post-primary, since Utah's 2026 primary was June 23 and today is August 5.) Party (column C) is sometimes blank even for non-disqualified statuses' predecessors within the same office (e.g. one candidate row for `State Senate District 1 (Multi-County)` has `party=None`, `status="Disqualified"`) — never assume party is always populated.
- **Party values observed:** `Democratic`, `Republican`, `Libertarian`, `Unaffiliated`, `Forward`, `Constitution`, `Independent American` — pass through verbatim to `ingest_candidate`; `aggregation.identity.normalize_party` already canonicalizes these downstream, no local mapping needed.
- **2026 calendar dates** (confirmed in `docs/state-research/UT/UT-Election_Research.md`, "Election Calendar and Notice of Election" section): primary June 23, 2026; general November 3, 2026.
- **`openpyxl` is already in `requirements/base.txt`** — no new dependency needed. Fetch the `.xlsx` as raw bytes (`response.content`), do not attempt to decode it as text (unlike every CSV-based adapter in this codebase).

---

## File Structure

- `backend/integrations/ut_elections/__init__.py` — **new file.**
- `backend/integrations/ut_elections/apps.py` — **new file.** `AppConfig` for Django app registration, mirrors `integrations/md_sbe/apps.py`.
- `backend/integrations/ut_elections/exceptions.py` — **new file.** `UtElectionsError` / `UtElectionsRetryableError`, same shape as `integrations/md_sbe/exceptions.py`.
- `backend/integrations/ut_elections/calendar.py` — **new file.** Maintained table of Utah's statutory primary/general dates and the exact Candidate Filing workbook URL per year (both are hand-set per cycle, not computable — see Task 1).
- `backend/integrations/ut_elections/client.py` — **new file.** `UtElectionsClient.fetch_candidate_filing_workbook(url: str) -> bytes`.
- `backend/integrations/ut_elections/mappers.py` — **new file.** Section scoping, sectioned-workbook parsing, name title-casing, race identity mapping, candidate status mapping.
- `backend/integrations/ut_elections/tasks.py` — **new file.** `sync_ut_elections` (Stage 1a) and `sync_ut_races` (Stage 1b) Celery tasks.
- `backend/integrations/ut_elections/tests/__init__.py`, `test_apps.py`, `test_calendar.py`, `test_client.py`, `test_mappers.py`, `test_tasks.py` — **new files.**
- `backend/config/settings/base.py` — **modify.** Register `integrations.ut_elections` in `INSTALLED_APPS`.
- `backend/elections/models.py` — **modify.** Add `Race.Source.UT_ELECTIONS`.
- `backend/elections/migrations/0035_add_ut_elections_race_source.py` — **new file.**
- `backend/aggregation/migrations/0017_seed_ut_elections_precedence.py` — **new file.**
- `backend/internal/task_locks.py` — **modify.** Register both new task locks.
- `backend/internal/views.py` — **modify.** Add trigger view functions.
- `backend/internal/urls.py` — **modify.** Add trigger routes.
- `backend/internal/tests/test_views.py` — **modify.** Extend with lock-registration assertions.
- `docs/state-research/00-MASTER-INDEX.md` — **modify (Task 10, deferred to post-verification).** Promote UT's row once verified live.

---

### Task 1: Utah election calendar table

**Files:**
- Create: `backend/integrations/ut_elections/calendar.py`
- Test: `backend/integrations/ut_elections/tests/test_calendar.py`

**Interfaces:**
- Produces: `get_active_cycle(today: datetime.date) -> UtElectionCycle | None`, where `UtElectionCycle` is a frozen `dataclass` with fields `year: int`, `primary_date: datetime.date`, `general_date: datetime.date`, `candidate_filing_url: str`. Also produces `UT_ELECTION_CYCLES: dict[int, UtElectionCycle]`, the maintained table, for `tasks.py` to iterate.

Utah's primary date is set by statute but is not on a fixed formula (verified in `docs/state-research/UT/UT-Election_Research.md`'s "Election Calendar and Notice of Election" section — 2026's primary is June 23). The Candidate Filing workbook's URL also can't be derived from a pattern: its path segment (`/2026/06/`) is a WordPress upload date, not a fixed per-cycle rule — the research doc explicitly warns "WordPress upload URLs... may change independently." Both fields must therefore be a maintained table, hand-updated each cycle, following the same precedent already accepted in this codebase for Maryland's `MD_ELECTION_CYCLES` table.

- [ ] **Step 1: Write the failing test**

```python
# backend/integrations/ut_elections/tests/test_calendar.py
from __future__ import annotations

import datetime


def test_get_active_cycle_returns_2026_cycle_before_general():
    from integrations.ut_elections.calendar import get_active_cycle
    cycle = get_active_cycle(datetime.date(2026, 8, 5))
    assert cycle is not None
    assert cycle.year == 2026
    assert cycle.primary_date == datetime.date(2026, 6, 23)
    assert cycle.general_date == datetime.date(2026, 11, 3)
    assert cycle.candidate_filing_url == (
        "https://vote.utah.gov/wp-content/uploads/2026/06/Candidate-Filing-2026.xlsx"
    )


def test_get_active_cycle_returns_none_when_no_cycle_configured():
    from integrations.ut_elections.calendar import get_active_cycle
    assert get_active_cycle(datetime.date(2099, 1, 1)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest integrations/ut_elections/tests/test_calendar.py -v --no-migrations`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.ut_elections'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/integrations/ut_elections/__init__.py
```
(empty file)

```python
# backend/integrations/ut_elections/calendar.py
"""
Maintained table of Utah's statutory primary/general election dates and the
Candidate Filing Excel workbook URL for each cycle.

Neither field is computable: the primary date is set by the legislature per
cycle (2026: June 23, per docs/state-research/UT/UT-Election_Research.md),
and the workbook URL's path segment is a WordPress upload date, not a fixed
pattern — confirmed live 2026-08-05 at
https://vote.utah.gov/wp-content/uploads/2026/06/Candidate-Filing-2026.xlsx.
This table must be updated by hand each cycle from
https://vote.utah.gov/2026-candidate-filings/ (or the equivalent year's page).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class UtElectionCycle:
    year: int
    primary_date: datetime.date
    general_date: datetime.date
    candidate_filing_url: str


UT_ELECTION_CYCLES: dict[int, UtElectionCycle] = {
    2026: UtElectionCycle(
        year=2026,
        primary_date=datetime.date(2026, 6, 23),
        general_date=datetime.date(2026, 11, 3),
        candidate_filing_url=(
            "https://vote.utah.gov/wp-content/uploads/2026/06/Candidate-Filing-2026.xlsx"
        ),
    ),
}


def get_active_cycle(today: datetime.date) -> UtElectionCycle | None:
    """Return the cycle whose general election hasn't yet passed, or None."""
    candidates = sorted(
        (c for c in UT_ELECTION_CYCLES.values() if c.general_date >= today),
        key=lambda c: c.general_date,
    )
    return candidates[0] if candidates else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest integrations/ut_elections/tests/test_calendar.py -v --no-migrations`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ut_elections/__init__.py backend/integrations/ut_elections/calendar.py backend/integrations/ut_elections/tests/__init__.py backend/integrations/ut_elections/tests/test_calendar.py
git commit -m "feat(ut_elections): add maintained election-cycle calendar table"
```

(create `backend/integrations/ut_elections/tests/__init__.py` as an empty file alongside this commit — required for pytest package discovery, same as every other `integrations/*/tests/` directory in this repo.)

---

### Task 2: App registration and exceptions

**Files:**
- Create: `backend/integrations/ut_elections/apps.py`
- Create: `backend/integrations/ut_elections/exceptions.py`
- Modify: `backend/config/settings/base.py`
- Test: `backend/integrations/ut_elections/tests/test_apps.py`

**Interfaces:**
- Produces: `UtElectionsError(Exception)`, `UtElectionsRetryableError(UtElectionsError)` for `client.py` (Task 3) to raise.

- [ ] **Step 1: Write the failing test**

```python
# backend/integrations/ut_elections/tests/test_apps.py
from django.apps import apps


def test_ut_elections_app_is_installed():
    config = apps.get_app_config("ut_elections")
    assert config.name == "integrations.ut_elections"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest integrations/ut_elections/tests/test_apps.py -v --no-migrations`
Expected: FAIL with `LookupError: No installed app with label 'ut_elections'.`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/integrations/ut_elections/apps.py
from django.apps import AppConfig


class UtahElectionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.ut_elections"
    label = "ut_elections"
    verbose_name = "Utah Elections Integration"
```

```python
# backend/integrations/ut_elections/exceptions.py
class UtElectionsError(Exception):
    """Non-retryable Utah elections integration error."""


class UtElectionsRetryableError(UtElectionsError):
    """Transient error that warrants a retry (network/5xx/soft-404)."""
```

```python
# backend/config/settings/base.py — add inside INSTALLED_APPS, alongside 'integrations.md_sbe'
    'integrations.ut_elections',
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest integrations/ut_elections/tests/test_apps.py -v --no-migrations`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ut_elections/apps.py backend/integrations/ut_elections/exceptions.py backend/integrations/ut_elections/tests/test_apps.py backend/config/settings/base.py
git commit -m "feat(ut_elections): register app and add exception types"
```

---

### Task 3: Candidate Filing workbook client fetch

**Files:**
- Create: `backend/integrations/ut_elections/client.py`
- Test: `backend/integrations/ut_elections/tests/test_client.py`

**Interfaces:**
- Consumes: `UtElectionsRetryableError` from Task 2.
- Produces: `UtElectionsClient.fetch_candidate_filing_workbook(url: str) -> bytes`. Raises `UtElectionsRetryableError` on network failure or non-200 status. Unlike every CSV-based adapter in this codebase, this returns raw `bytes`, not decoded text — the response is a binary `.xlsx` file.

- [ ] **Step 1: Write the failing test**

```python
# backend/integrations/ut_elections/tests/test_client.py
from __future__ import annotations

import pytest
import responses

from integrations.ut_elections.client import UtElectionsClient
from integrations.ut_elections.exceptions import UtElectionsRetryableError

_URL = "https://vote.utah.gov/wp-content/uploads/2026/06/Candidate-Filing-2026.xlsx"


@responses.activate
def test_fetch_candidate_filing_workbook_returns_bytes():
    responses.add(responses.GET, _URL, body=b"PK\x03\x04fake-xlsx-bytes", status=200)
    client = UtElectionsClient()
    content = client.fetch_candidate_filing_workbook(_URL)
    assert content == b"PK\x03\x04fake-xlsx-bytes"


@responses.activate
def test_fetch_candidate_filing_workbook_raises_on_non_200():
    responses.add(responses.GET, _URL, body=b"Not Found", status=404)
    client = UtElectionsClient()
    with pytest.raises(UtElectionsRetryableError):
        client.fetch_candidate_filing_workbook(_URL)
```

Check `responses` is already a test dependency before writing this (`grep responses backend/requirements/dev.txt`) — every other `integrations/*/tests/test_client.py` in this repo already uses it for the same soft-404/network-mocking pattern.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest integrations/ut_elections/tests/test_client.py -v --no-migrations`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.ut_elections.client'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/integrations/ut_elections/client.py
from __future__ import annotations

import requests

from .exceptions import UtElectionsRetryableError


class UtElectionsClient:
    """Fetches Utah's Candidate Filing Excel workbook.

    Returns raw bytes — the file is a binary .xlsx, parsed separately by
    mappers.parse_candidate_filing_workbook via openpyxl.
    """

    def __init__(self):
        self.session = requests.Session()
        self.timeout = 20

    def fetch_candidate_filing_workbook(self, url: str) -> bytes:
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise UtElectionsRetryableError(f"UT candidate filing GET failed: {exc}") from exc

        if response.status_code != 200:
            raise UtElectionsRetryableError(
                f"UT candidate filing fetch failed status={response.status_code} url={url}"
            )

        return response.content
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest integrations/ut_elections/tests/test_client.py -v --no-migrations`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ut_elections/client.py backend/integrations/ut_elections/tests/test_client.py
git commit -m "feat(ut_elections): add candidate filing workbook client fetch"
```

---

### Task 4: Sectioned-workbook parsing and section scoping

**Files:**
- Create: `backend/integrations/ut_elections/mappers.py`
- Test: `backend/integrations/ut_elections/tests/test_mappers.py`

**Interfaces:**
- Produces:
  - `IN_SCOPE_SECTIONS: frozenset[str]` — exact section-title strings in scope.
  - `is_in_scope_section(section: str) -> bool`
  - `parse_candidate_filing_workbook(content: bytes) -> list[dict]` — returns one dict per candidate row: `{"section": str, "name": str, "office": str, "party": str, "status": str}`, already filtered to in-scope sections only.

- [ ] **Step 1: Write the failing test**

```python
# backend/integrations/ut_elections/tests/test_mappers.py
from __future__ import annotations

import io

import openpyxl
import pytest


def _build_workbook(rows: list[tuple]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.parametrize("section", ["Federal Offices", "State Offices", "State Senate", "State House"])
def test_is_in_scope_section_true_for_federal_and_state(section):
    from integrations.ut_elections.mappers import is_in_scope_section
    assert is_in_scope_section(section) is True


@pytest.mark.parametrize("section", ["State School Board", "State Judicial", "", "Unknown Section"])
def test_is_in_scope_section_false_for_school_board_and_judicial(section):
    from integrations.ut_elections.mappers import is_in_scope_section
    assert is_in_scope_section(section) is False


def test_parse_candidate_filing_workbook_extracts_in_scope_rows_only():
    from integrations.ut_elections.mappers import parse_candidate_filing_workbook

    content = _build_workbook([
        (None, None, None, None),
        ("Federal Offices | State Offices | Utah Senate | Utah House | State School Board | Judicial Retention", None, None, None),
        (None, None, None, None),
        ("Federal Offices", None, None, None),
        (None, None, None, None),
        ("Candidate", "Office", "Party", "Status"),
        ("BEN MCADAMS", "U.S. House District 1", "Democratic", "Election Candidate"),
        ("RILEY OWEN", "U.S. House District 1", "Republican", "Election Candidate"),
        (None, None, None, None),
        ("State School Board", None, None, None),
        (None, None, None, None),
        ("Candidate", "Office", "Party", "Status"),
        ("TRACY J. NUTTALL", "State School Board Distrct 11 (Multi-County)", "Republican", "Election Candidate"),
        (None, None, None, None),
        ("State Judicial", None, None, None),
        (None, None, None, None),
        ("Judicial Retention", "Status", None, None),
        ("Shall AARON FLATER be retained...?", "Election Candidate", None, None),
    ])

    rows = parse_candidate_filing_workbook(content)

    assert len(rows) == 2
    assert rows[0] == {
        "section": "Federal Offices", "name": "BEN MCADAMS",
        "office": "U.S. House District 1", "party": "Democratic",
        "status": "Election Candidate",
    }
    assert rows[1]["name"] == "RILEY OWEN"
    assert all(r["section"] != "State School Board" for r in rows)
    assert all(r["section"] != "State Judicial" for r in rows)


def test_parse_candidate_filing_workbook_handles_blank_party():
    from integrations.ut_elections.mappers import parse_candidate_filing_workbook

    content = _build_workbook([
        ("State Senate", None, None, None),
        (None, None, None, None),
        ("Candidate", "Office", "Party", "Status"),
        ("FRED HAYES", "State Senate District 1 (Multi-County)", None, "Disqualified"),
    ])

    rows = parse_candidate_filing_workbook(content)
    assert rows[0]["party"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest integrations/ut_elections/tests/test_mappers.py -v --no-migrations`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.ut_elections.mappers'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/integrations/ut_elections/mappers.py (part 1 of 3 — remaining functions added in Tasks 5-6)
"""
Stage 1 mappers for the UT elections integration.

Source: the Candidate Filing Excel workbook (single sheet, hand-formatted
into sections — see docs/state-research/UT/UT-Election_Research.md and the
plan's "Live-Verified Source Facts" section). Each section is: a title row
(single non-empty cell in column A), a blank row, a
"Candidate | Office | Party | Status" sub-header row, then data rows, then a
blank row before the next section.

Full Core scope for this wave (per ADR-005/COVERAGE-CLARIFICATION, same
convention as MD/NC/VT): federal + state legislative + state executive
offices only. State School Board and State Judicial (judicial retention
questions — not office/district/party/candidate-shaped) are out of scope.
"""
from __future__ import annotations

import io

import openpyxl

IN_SCOPE_SECTIONS: frozenset[str] = frozenset({
    "Federal Offices",
    "State Offices",
    "State Senate",
    "State House",
})


def is_in_scope_section(section: str) -> bool:
    return (section or "").strip() in IN_SCOPE_SECTIONS


def parse_candidate_filing_workbook(content: bytes) -> list[dict]:
    """
    Parse the sectioned Candidate Filing workbook into row dicts, already
    filtered to in-scope sections (is_in_scope_section). Section headers and
    sub-header rows are consumed as parser state, not emitted as data.
    """
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    ws = wb.active

    section: str | None = None
    rows: list[dict] = []

    for raw_row in ws.iter_rows(values_only=True):
        cells = list(raw_row[:4]) + [None] * max(0, 4 - len(raw_row))
        a, b, c, d = cells[:4]
        a = a.strip() if isinstance(a, str) else a

        if a and not b and not c and not d:
            # Section-title row, e.g. "Federal Offices". The very first
            # non-empty-A-only row is the workbook's own top banner
            # ("Federal Offices | State Offices | ..."), which never matches
            # a real section title and is harmlessly overwritten by the next
            # real section row before any data row is seen.
            section = a
            continue

        if a == "Candidate" and b == "Office":
            continue  # sub-header row within an office section
        if a == "Judicial Retention" and b == "Status":
            continue  # sub-header row within the judicial section (out of scope anyway)

        if not a or section is None:
            continue  # blank row

        if not is_in_scope_section(section):
            continue

        rows.append({
            "section": section,
            "name": a,
            "office": (b or "").strip() if isinstance(b, str) else (b or ""),
            "party": (c or "").strip() if isinstance(c, str) else (c or ""),
            "status": (d or "").strip() if isinstance(d, str) else (d or ""),
        })

    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest integrations/ut_elections/tests/test_mappers.py -v --no-migrations`
Expected: PASS (all tests in file)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ut_elections/mappers.py backend/integrations/ut_elections/tests/test_mappers.py
git commit -m "feat(ut_elections): add sectioned-workbook parsing and section scoping"
```

---

### Task 5: Name title-casing and candidate status mapping

**Files:**
- Modify: `backend/integrations/ut_elections/mappers.py` (append)
- Test: `backend/integrations/ut_elections/tests/test_mappers.py` (append)

**Interfaces:**
- Produces:
  - `titlecase_name(raw: str) -> str` — best-effort display-name casing; does not special-case `Mc`/`Mac` surnames (documented limitation).
  - `candidate_status_for(status_raw: str) -> str | None` — maps a raw filing status to a `Candidate.CandidateStatus` value, or `None` to signal "skip this row" (used only for `"Filed"`, an early pre-viability stage with no durable ballot standing).

- [ ] **Step 1: Write the failing test**

```python
# append to backend/integrations/ut_elections/tests/test_mappers.py

def test_titlecase_name_ordinary_names():
    from integrations.ut_elections.mappers import titlecase_name
    assert titlecase_name("RILEY OWEN") == "Riley Owen"


def test_titlecase_name_apostrophe_name():
    from integrations.ut_elections.mappers import titlecase_name
    assert titlecase_name("JASON O'DELL") == "Jason O'Dell"


def test_titlecase_name_does_not_special_case_mc_surnames():
    # Known, documented limitation: no name dictionary available.
    from integrations.ut_elections.mappers import titlecase_name
    assert titlecase_name("BEN MCADAMS") == "Ben Mcadams"


@pytest.mark.parametrize("status_raw,expected", [
    ("Election Candidate", "running"),
    ("Primary", "running"),
    ("Withdrew", "withdrawn"),
    ("Out in Convention", "withdrawn"),
    ("Out in Primary", "withdrawn"),
    ("Disqualified", "disqualified"),
])
def test_candidate_status_for_maps_known_statuses(status_raw, expected):
    from integrations.ut_elections.mappers import candidate_status_for
    assert candidate_status_for(status_raw) == expected


def test_candidate_status_for_filed_returns_none_to_skip():
    from integrations.ut_elections.mappers import candidate_status_for
    assert candidate_status_for("Filed") is None


def test_candidate_status_for_unknown_status_defaults_to_running():
    from integrations.ut_elections.mappers import candidate_status_for
    assert candidate_status_for("Some New Status UT Adds Later") == "running"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest integrations/ut_elections/tests/test_mappers.py -v --no-migrations`
Expected: FAIL with `ImportError: cannot import name 'titlecase_name'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/integrations/ut_elections/mappers.py

def titlecase_name(raw: str) -> str:
    """
    Best-effort display-name casing for the source's ALL-CAPS candidate
    names. Python's str.title() handles ordinary names and apostrophe names
    ("O'Dell") correctly but does not special-case Mc/Mac surnames
    ("MCADAMS" -> "Mcadams", not "McAdams") — accepted as a known
    display-quality limitation; no name dictionary is available to fix it.
    """
    return (raw or "").strip().title()


# Statuses observed live 2026-08-05 (post-primary): "Election Candidate",
# "Out in Convention", "Out in Primary", "Withdrew", "Disqualified".
# "Primary" and "Filed" are documented in the research doc as earlier-stage
# statuses (pre-primary) not observed in this snapshot; mapped here from the
# state's own documented status vocabulary. "Out in Convention"/"Out in
# Primary" mean the candidate lost a party process and never reached any
# public ballot — modeled as WITHDRAWN (closest fit in the 4-value
# CandidateStatus enum; there is no distinct "eliminated" status).
_CANDIDATE_STATUS_MAP: dict[str, str] = {
    "election candidate": "running",
    "primary": "running",
    "withdrew": "withdrawn",
    "out in convention": "withdrawn",
    "out in primary": "withdrawn",
    "disqualified": "disqualified",
}
# "Filed" is the earliest pre-viability stage (declared but not yet advanced
# past any qualification step) — skip these rows entirely rather than
# creating a Candidate record for someone who never reached a ballot.
_SKIP_STATUSES: frozenset[str] = frozenset({"filed"})


def candidate_status_for(status_raw: str) -> str | None:
    """
    Map a raw filing status to a Candidate.CandidateStatus value.
    Returns None to signal the row should be skipped entirely (Filed only).
    Unknown/future statuses default to "running" (least-destructive default,
    same convention used by every other state adapter's status mapping).
    """
    key = (status_raw or "").strip().lower()
    if key in _SKIP_STATUSES:
        return None
    return _CANDIDATE_STATUS_MAP.get(key, "running")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest integrations/ut_elections/tests/test_mappers.py -v --no-migrations`
Expected: PASS (all tests in file)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ut_elections/mappers.py backend/integrations/ut_elections/tests/test_mappers.py
git commit -m "feat(ut_elections): add name title-casing and candidate status mapping"
```

---

### Task 6: Race identity and candidate field mapping

**Files:**
- Modify: `backend/integrations/ut_elections/mappers.py` (append)
- Test: `backend/integrations/ut_elections/tests/test_mappers.py` (append)

**Interfaces:**
- Consumes: `Race.Source.UT_ELECTIONS` (Task 7 must land before this is usable against a real DB; the mapper unit tests below don't hit the DB, so ordering here is for whole-suite correctness only, same note as MD's plan).
- Produces:
  - `map_race_identity(office: str) -> tuple[dict, dict]` — returns `(identity, fields)` for `aggregation.ingest.ingest_race`. `identity` has `office_title`, `ocd_division_id`, `race_type`, `contest_variant`; `fields` has `office_title`, `jurisdiction`, `geography_scope`, `vote_method`, `max_selections`, `source`, `source_metadata`.
  - `map_candidate(row: dict) -> dict` — returns the `fields` kwarg for `aggregation.ingest.ingest_candidate` (`candidate_status`, `source_metadata`), or `None` if the row's status maps to a skip (see Task 5).

- [ ] **Step 1: Write the failing test**

```python
# append to backend/integrations/ut_elections/tests/test_mappers.py

def test_map_race_identity_district_office():
    from integrations.ut_elections.mappers import map_race_identity
    identity, fields = map_race_identity("U.S. House District 1")
    assert identity["office_title"] == "U.S. House District 1"
    assert identity["contest_variant"] == "ut:U.S. House District 1"
    assert fields["geography_scope"] == "district"
    assert fields["source"] == "ut_elections"


def test_map_race_identity_statewide_office():
    from integrations.ut_elections.mappers import map_race_identity
    identity, fields = map_race_identity("Governor / Lieutenant Governor")
    assert identity["office_title"] == "Governor / Lieutenant Governor"
    assert fields["geography_scope"] == "statewide"


def test_map_candidate_running_status():
    from integrations.ut_elections.mappers import map_candidate
    row = {"name": "BEN MCADAMS", "status": "Election Candidate"}
    fields = map_candidate(row)
    assert fields is not None
    assert fields["candidate_status"] == "running"
    assert fields["source_metadata"]["ut_status"] == "Election Candidate"


def test_map_candidate_filed_returns_none():
    from integrations.ut_elections.mappers import map_candidate
    row = {"name": "SOMEONE NEW", "status": "Filed"}
    assert map_candidate(row) is None


def test_map_candidate_withdrawn_status():
    from integrations.ut_elections.mappers import map_candidate
    row = {"name": "KATHLEEN A. RIEBE", "status": "Withdrew"}
    fields = map_candidate(row)
    assert fields["candidate_status"] == "withdrawn"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest integrations/ut_elections/tests/test_mappers.py -v --no-migrations`
Expected: FAIL with `ImportError: cannot import name 'map_race_identity'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/integrations/ut_elections/mappers.py

def map_race_identity(office: str) -> tuple[dict, dict]:
    """
    Return (identity, fields) for aggregation.ingest.ingest_race, from one
    Office cell value. Utah's workbook already stores the full contest name
    (office + district, when applicable) in a single cell — no split is
    needed, unlike Maryland's separate office/district columns.
    """
    from elections.models import Race

    office_title = (office or "").strip()
    is_district = "district" in office_title.lower()
    variant = f"ut:{office_title}"

    identity = {
        "office_title": office_title,
        "ocd_division_id": "",
        "race_type": Race.RaceType.CANDIDATE,
        "contest_variant": variant,
    }
    fields = {
        "office_title": office_title,
        "jurisdiction": "Utah",
        "geography_scope": "district" if is_district else "statewide",
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "source": Race.Source.UT_ELECTIONS,
        "source_metadata": {
            "provider": "ut_elections",
            "office": office_title,
            "contest_variant": variant,
        },
    }
    return identity, fields


def map_candidate(row: dict) -> dict | None:
    """
    Map a parsed candidate-filing row to Candidate model fields, or None if
    the row's status means "never reached a ballot" (see candidate_status_for).
    """
    status_raw = (row.get("status") or "").strip()
    candidate_status = candidate_status_for(status_raw)
    if candidate_status is None:
        return None

    return {
        "candidate_status": candidate_status,
        "source_metadata": {
            "provider": "ut_elections",
            "ut_status": status_raw,
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest integrations/ut_elections/tests/test_mappers.py -v --no-migrations`
Expected: PASS (all tests in file — note this requires Task 7's `Race.Source.UT_ELECTIONS` to exist; if running this task's tests standalone before Task 7, expect an `AttributeError` on `Race.Source.UT_ELECTIONS` instead, which is expected per the ordering note above)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ut_elections/mappers.py backend/integrations/ut_elections/tests/test_mappers.py
git commit -m "feat(ut_elections): add race identity and candidate field mapping"
```

---

### Task 7: `Race.Source.UT_ELECTIONS` migration

**Files:**
- Modify: `backend/elections/models.py`
- Create: `backend/elections/migrations/0035_add_ut_elections_race_source.py`

**Interfaces:**
- Produces: `Race.Source.UT_ELECTIONS = 'ut_elections'` usable by `mappers.py` (Task 6).

- [ ] **Step 1: Modify the model**

```python
# backend/elections/models.py — inside class Race, class Source(models.TextChoices):
        MD_SBE = 'md_sbe', 'Maryland SBE'
        UT_ELECTIONS = 'ut_elections', 'Utah Elections'
```

Check `elections/migrations/` for the actual latest migration filename before running `makemigrations` — `0034_add_md_sbe_race_source.py` was the latest at plan-writing time; if a newer one landed since, this task's migration number shifts accordingly (Django names it automatically either way).

- [ ] **Step 2: Generate the migration**

Run: `cd backend && python manage.py makemigrations elections --name add_ut_elections_race_source`
Expected output file: `elections/migrations/0035_add_ut_elections_race_source.py` containing an `AlterField` on `Race.source` with `UT_ELECTIONS` added to the choices list (same shape as `0034_add_md_sbe_race_source.py`).

- [ ] **Step 3: Verify migration applies cleanly**

Run: `cd backend && python manage.py migrate elections --plan | grep add_ut_elections_race_source`
Expected: the migration appears in the plan, no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/elections/models.py backend/elections/migrations/0035_add_ut_elections_race_source.py
git commit -m "feat(elections): add UT_ELECTIONS to Race.Source"
```

---

### Task 8: `SourcePrecedence` seed migration

**Files:**
- Create: `backend/aggregation/migrations/0017_seed_ut_elections_precedence.py`

**Interfaces:**
- Consumes: the `SourcePrecedence` model (already exists, used identically by `0016_seed_md_sbe_precedence.py`).
- Produces: UT rows in `SourcePrecedence` ranking `ut_elections` above `civic_api` for `date`, `identity`, and `results`; `civic_api` above `ut_elections` for `contacts` (the Candidate Filing workbook doesn't carry the rich contact data Civic API does) — same pattern as MD/NC.

- [ ] **Step 1: Write the migration**

```python
# backend/aggregation/migrations/0017_seed_ut_elections_precedence.py
from django.db import migrations

_UT_ROWS = [
    ("UT", "date",     "ut_elections", 0),
    ("UT", "date",     "civic_api",    1),
    ("UT", "contacts", "civic_api",    0),
    ("UT", "contacts", "ut_elections", 1),
    ("UT", "identity",  "ut_elections", 0),
    ("UT", "identity",  "civic_api",    1),
    ("UT", "results",  "ut_elections", 0),
    ("UT", "results",  "civic_api",    1),
]


def seed_ut_elections_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _UT_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_ut_elections_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="UT").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0016_seed_md_sbe_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_ut_elections_precedence, remove_ut_elections_precedence),
    ]
```

Check `aggregation/migrations/` for the actual latest migration filename before setting `dependencies` — `0016_seed_md_sbe_precedence.py` was the latest at plan-writing time; if a newer one landed since, depend on that instead. Note: `SourcePrecedence.objects.filter(state="UT").delete()` in the reverse migration will also delete any pre-existing UT rows seeded for the Stage-2-only `ut.py` results adapter, if any exist — check `SourcePrecedence.objects.filter(state="UT")` before writing this task for real and merge with `update_or_create` rather than blind-inserting if rows already exist.

- [ ] **Step 2: Verify migration applies cleanly**

Run: `cd backend && python manage.py migrate aggregation --plan | grep seed_ut_elections_precedence`
Expected: appears in the plan, no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/aggregation/migrations/0017_seed_ut_elections_precedence.py
git commit -m "feat(aggregation): seed UT elections source precedence"
```

---

### Task 9: `sync_ut_elections` and `sync_ut_races` Celery tasks

**Files:**
- Create: `backend/integrations/ut_elections/tasks.py`
- Test: `backend/integrations/ut_elections/tests/test_tasks.py`

**Interfaces:**
- Consumes: `integrations.ut_elections.calendar.get_active_cycle`, `integrations.ut_elections.client.UtElectionsClient.fetch_candidate_filing_workbook`, `integrations.ut_elections.mappers.{parse_candidate_filing_workbook, titlecase_name, map_race_identity, map_candidate}`, `aggregation.ingest.{ingest_election, ingest_race, ingest_candidate}`, `ops.models.SyncLog`, `elections.models.Election`.
- Produces: `sync_ut_elections()` and `sync_ut_races()` — both `@shared_task(bind=True, max_retries=3, default_retry_delay=300)`, same `SyncLog` bookkeeping pattern as `integrations/md_sbe/tasks.py`'s two tasks (`STARTED` → `COMPLETED`/`FAILED`/`COMPLETED_WITH_WARNINGS`, `records_created`/`records_updated`/`error_count`/`last_error`/`notes`).

- [ ] **Step 1: Write the failing test**

```python
# backend/integrations/ut_elections/tests/test_tasks.py
from __future__ import annotations

import datetime
import io
from unittest.mock import patch

import openpyxl
import pytest

pytestmark = pytest.mark.django_db


def _build_workbook_bytes(rows: list[tuple]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_sync_ut_elections_creates_primary_and_general():
    from integrations.ut_elections.tasks import sync_ut_elections
    from elections.models import Election

    with patch("integrations.ut_elections.tasks.timezone") as mock_tz:
        mock_tz.localdate.return_value = datetime.date(2026, 8, 5)
        mock_tz.now.return_value = datetime.datetime(2026, 8, 5, tzinfo=datetime.timezone.utc)
        result = sync_ut_elections()

    assert result["created"] >= 1
    assert Election.objects.filter(state="UT", election_date=datetime.date(2026, 6, 23)).exists()
    assert Election.objects.filter(state="UT", election_date=datetime.date(2026, 11, 3)).exists()


def test_sync_ut_races_creates_races_and_candidates_for_in_scope_sections():
    from integrations.ut_elections.tasks import sync_ut_elections, sync_ut_races
    from elections.models import Election, Race, Candidate

    workbook_bytes = _build_workbook_bytes([
        ("Federal Offices", None, None, None),
        (None, None, None, None),
        ("Candidate", "Office", "Party", "Status"),
        ("BEN MCADAMS", "U.S. House District 1", "Democratic", "Election Candidate"),
        ("RILEY OWEN", "U.S. House District 1", "Republican", "Election Candidate"),
        (None, None, None, None),
        ("State School Board", None, None, None),
        (None, None, None, None),
        ("Candidate", "Office", "Party", "Status"),
        ("TRACY J. NUTTALL", "State School Board Distrct 11 (Multi-County)", "Republican", "Election Candidate"),
    ])

    with patch("integrations.ut_elections.tasks.timezone") as mock_tz:
        mock_tz.localdate.return_value = datetime.date(2026, 8, 5)
        mock_tz.now.return_value = datetime.datetime(2026, 8, 5, tzinfo=datetime.timezone.utc)
        sync_ut_elections()

        with patch(
            "integrations.ut_elections.tasks.UtElectionsClient.fetch_candidate_filing_workbook",
            return_value=workbook_bytes,
        ):
            result = sync_ut_races()

    assert result["created"] == 1  # only the in-scope U.S. House District 1 race
    race = Race.objects.get(election__state="UT", office_title="U.S. House District 1")
    assert Candidate.objects.filter(race=race, name="Ben Mcadams").exists()
    assert Candidate.objects.filter(race=race, name="Riley Owen").exists()
    assert not Race.objects.filter(office_title__icontains="School Board").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest integrations/ut_elections/tests/test_tasks.py -v --no-migrations`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.ut_elections.tasks'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/integrations/ut_elections/tasks.py
"""
Utah elections Celery tasks.

sync_ut_elections (Stage 1a): seed Election records for UT's active cycle
    from the maintained calendar.py table.

sync_ut_races (Stage 1b): fetch the active cycle's Candidate Filing Excel
    workbook and upsert Race + Candidate records for in-scope (federal +
    state legislative + state executive) sections. See mappers.py for scope,
    status mapping, and name-casing.
"""
from __future__ import annotations

import logging

from celery import shared_task
from celery.exceptions import Retry
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog

from .calendar import get_active_cycle
from .client import UtElectionsClient
from .exceptions import UtElectionsRetryableError
from .mappers import (
    map_candidate,
    map_race_identity,
    parse_candidate_filing_workbook,
    titlecase_name,
)

logger = logging.getLogger(__name__)

_SOURCE = "ut_elections"


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_ut_elections(self):
    """Stage 1a: seed UT's primary and general Election rows from the calendar table."""
    sync_log = SyncLog.objects.create(
        source=_SOURCE, task_name="sync_ut_elections", status=SyncLog.Status.STARTED,
    )
    try:
        from aggregation import ingest

        today = timezone.localdate()
        cycle = get_active_cycle(today)
        created = updated = 0

        if cycle is not None:
            for phase, election_date in (("primary", cycle.primary_date), ("general", cycle.general_date)):
                status = (
                    Election.Status.RESULTS_PENDING if election_date <= today
                    else Election.Status.UPCOMING
                )
                election, was_created = ingest.ingest_election(
                    source=_SOURCE,
                    source_id=f"ut_elections_{cycle.year}_{phase}",
                    identity={
                        "state": "UT",
                        "election_type": phase,
                        "election_date": election_date,
                        "jurisdiction_level": Election.JurisdictionLevel.STATE,
                    },
                    fields={
                        "name": f"{cycle.year} Utah {phase.title()} Election",
                        "status": status,
                        "source_metadata": {"phase": phase},
                    },
                )
                created += int(was_created)
                updated += int(not was_created)

        sync_log.records_created = created
        sync_log.notes = f"updated={updated}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "notes", "status", "completed_at"])
        return {"created": created, "updated": updated}

    except Exception as exc:
        logger.exception("ut_elections.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_ut_races(self):
    """Stage 1b: upsert Race + Candidate records from the active cycle's Candidate Filing workbook."""
    from aggregation import ingest

    sync_log = SyncLog.objects.create(
        source=_SOURCE, task_name="sync_ut_races", status=SyncLog.Status.STARTED,
    )
    try:
        today = timezone.localdate()
        cycle = get_active_cycle(today)
        if cycle is None:
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.notes = "no active UT cycle configured"
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["status", "notes", "completed_at"])
            return {"created": 0, "updated": 0, "skipped_no_election": 0}

        phase = "primary" if today <= cycle.primary_date else "general"
        election = Election.objects.filter(
            state="UT", election_type=phase, election_date=(
                cycle.primary_date if phase == "primary" else cycle.general_date
            ),
        ).first()
        if election is None:
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.notes = "sync_ut_elections has not run yet for this cycle"
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["status", "notes", "completed_at"])
            return {"created": 0, "updated": 0, "skipped_no_election": 0}

        client = UtElectionsClient()
        workbook_bytes = client.fetch_candidate_filing_workbook(cycle.candidate_filing_url)
        rows = parse_candidate_filing_workbook(workbook_bytes)

        # Group already-in-scope rows by Office; parse_candidate_filing_workbook
        # filters out-of-scope sections before this point.
        offices: dict[str, list[dict]] = {}
        for row in rows:
            offices.setdefault(row["office"], []).append(row)

        created = updated = candidates_skipped = 0

        for office, office_rows in offices.items():
            identity, fields = map_race_identity(office)
            race, race_created = ingest.ingest_race(
                election=election, source=_SOURCE, identity=identity, fields=fields,
            )
            created += int(race_created)
            updated += int(not race_created)

            for row in office_rows:
                candidate_fields = map_candidate(row)
                if candidate_fields is None:
                    candidates_skipped += 1
                    continue
                ingest.ingest_candidate(
                    race=race, source=_SOURCE, name=titlecase_name(row["name"]),
                    party=row["party"], fields=candidate_fields,
                )

        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.notes = f"candidates_skipped={candidates_skipped}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created, "updated": updated, "candidates_skipped": candidates_skipped}

    except UtElectionsRetryableError as exc:
        logger.warning("ut_elections.sync_races.retryable_error: %s", exc)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        try:
            raise self.retry(exc=exc)
        except Retry:
            raise
    except Exception as exc:
        logger.exception("ut_elections.sync_races.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

Check `SyncLog.Status.COMPLETED_WITH_WARNINGS` exists (confirmed in `ops/models.py` during plan-writing — it's the same enum every other state's `tasks.py` already uses).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest integrations/ut_elections/tests/test_tasks.py -v --no-migrations`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ut_elections/tasks.py backend/integrations/ut_elections/tests/test_tasks.py
git commit -m "feat(ut_elections): add sync_ut_elections and sync_ut_races Stage 1 tasks"
```

---

### Task 10: Wire tasks into the internal trigger API and task-lock registry

**Files:**
- Modify: `backend/internal/task_locks.py`
- Modify: `backend/internal/views.py`
- Modify: `backend/internal/urls.py`
- Test: `backend/internal/tests/test_views.py` (extend)

**Interfaces:**
- Consumes: `sync_ut_elections`, `sync_ut_races` from Task 9; the existing `_trigger`, `require_internal_task_token` helpers in `views.py`.
- Produces: `POST /internal/tasks/sync-ut-elections/` and `POST /internal/tasks/sync-ut-races/`, each Bearer-token-gated the same way every other endpoint in `urls.py` already is.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/internal/tests/test_views.py
def test_ut_elections_task_lock_registered():
    from internal.task_locks import TASK_LOCKS
    assert TASK_LOCKS["sync_ut_elections"] == ("daily", 23 * 60 * 60)


def test_ut_races_task_lock_registered():
    from internal.task_locks import TASK_LOCKS
    assert TASK_LOCKS["sync_ut_races"] == ("daily", 23 * 60 * 60)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest internal/tests/test_views.py -k ut -v --no-migrations`
Expected: FAIL with `KeyError: 'sync_ut_elections'`

- [ ] **Step 3: Write minimal implementation**

```python
# internal/task_locks.py — add inside TASK_LOCKS dict, alongside the sync_md_* rows
    "sync_ut_elections":    (WINDOW_DAILY,      23 * _HOUR),
    "sync_ut_races":        (WINDOW_DAILY,      23 * _HOUR),
```

```python
# internal/views.py — add to the import block, alongside the md_sbe import
from integrations.ut_elections.tasks import sync_ut_elections, sync_ut_races
```

```python
# internal/views.py — add trigger view functions, following the sync_md_elections_trigger pattern exactly (copy its decorator stack verbatim)
@csrf_exempt
@require_POST
@require_internal_task_token
def sync_ut_elections_trigger(request):
    return _trigger("sync_ut_elections", sync_ut_elections, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_ut_races_trigger(request):
    return _trigger("sync_ut_races", sync_ut_races, request)
```

```python
# internal/urls.py — add routes, alongside the sync-md-elections routes
    path("tasks/sync-ut-elections/", views.sync_ut_elections_trigger, name="internal-sync-ut-elections"),
    path("tasks/sync-ut-races/", views.sync_ut_races_trigger, name="internal-sync-ut-races"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest internal/tests/test_views.py -k ut -v --no-migrations`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/internal/task_locks.py backend/internal/views.py backend/internal/urls.py backend/internal/tests/test_views.py
git commit -m "feat(internal): wire UT elections Stage 1 tasks into trigger API"
```

- [ ] **Step 6: Add to production crontab (manual, post-merge)**

After this PR merges and is deployed, add both lines to `/data/DockerConfigs/CivicMirror/scheduler/crontab` (same file MD/NC/NY use), in order (elections before races):

```
10 12 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-ut-elections/
15 12 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-ut-races/
```

Then `docker restart civicmirror-scheduler` and confirm both lines are live with `docker exec civicmirror-scheduler crontab -l`. This step is not part of the code PR — it's a manual production step, same as every prior state's Stage 1 rollout.

---

### Task 11: Full backend test suite and ruff check

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && pytest --no-migrations`
Expected: all tests pass, including every pre-existing `ut_elections`/`ut` (Stage 2) test, and no regressions in any other state's suite.

- [ ] **Step 2: Run ruff**

Run: `cd backend && ruff check .`
Expected: no errors introduced by this plan's new/modified files.

- [ ] **Step 3: Commit if either step required fixes**

```bash
git add -A
git commit -m "fix: address test/lint findings from UT Stage 1 build"
```

---

### Task 12: Live verification and Full Core promotion

**Files:**
- Modify: `docs/state-research/00-MASTER-INDEX.md`
- Comment on: GitHub issue #87

Do not do this task until Task 10's Step 6 (crontab wiring) has been live in production and `ops_synclog` shows clean unattended runs — apply the same bar NY/MD were held to: several consecutive days of `status=completed`, `error_count=0` for both `sync_ut_elections` and `sync_ut_races`, plus at least one confirmed `OfficialResult` row attaching to a Stage-1-created UT race (the existing Stage 2 `UtahAdapter` already ingests results independently — this step only confirms the two sides actually reconcile onto the same `Race` rows via cross-source normalized-title matching, not a new code path).

**Known risk to verify:** Utah's ENR results feed uses a party-**PREFIX** naming convention (e.g. "REP U.S. House District 2" — see `results/adapters/ut.py`'s module docstring), but the existing cross-source title-matching fallback in `results/tasks.py` (`_PARTY_SUFFIX_RE`) only strips a party **suffix** (e.g. "Governor - Rep"), not a prefix. This means Stage 1 races for primary-phase UT contests may fail to reconcile with Stage 2 results until a party-prefix stripping fallback is added to `results/tasks.py` — that fallback is shared infrastructure used by every state's title-matching, not UT-specific, and is a separate piece of work from this plan. General-election titles are likely unprefixed, so this risk may look fully resolved from general-election data alone even if it isn't. Step 2 below (`official_results` counts for primary-phase UT races) must therefore be treated as a real gate for this risk, not a formality — if it comes back empty for primary-phase UT races once Utah's 2028 primary season is reachable, this is the reason to check first.

- [ ] **Step 1: Query production `ops_synclog` for UT**

```bash
docker exec civicmirror-postgres psql -U civicmirror -d civicmirror_api -c "
SELECT started_at, task_name, status, records_created, records_updated, error_count
FROM ops_synclog WHERE source = 'ut_elections' ORDER BY started_at DESC LIMIT 20;"
```

- [ ] **Step 2: Confirm results reconciliation onto Stage-1-created races**

```bash
docker exec civicmirror-postgres psql -U civicmirror -d civicmirror_api -c "
SELECT r.office_title, r.source, COUNT(orr.id) AS official_results
FROM elections_race r
JOIN elections_election e ON e.id = r.election_id
LEFT JOIN results_officialresult orr ON orr.race_id = r.id
WHERE e.state = 'UT' AND 'ut_elections' = ANY(r.contributing_sources)
GROUP BY r.office_title, r.source;"
```

- [ ] **Step 3: Update the master index**

Move UT's row in `docs/state-research/00-MASTER-INDEX.md` from "Results Coverage Only" to "Full Core Coverage" (both the table row at line 94 and the prose bullet at line 143), following the exact same edit shape used for MD/NY.

- [ ] **Step 4: Comment on and check off issue #87**

```bash
gh issue comment 87 --repo CivicMirror/CivicMirror-API --body "UT promoted to Full Core — [evidence]"
```

Check off UT's line in the issue body via `gh issue edit 87 --body-file ...`, same process used for MD/NY.

- [ ] **Step 5: Commit the doc update**

```bash
git add docs/state-research/00-MASTER-INDEX.md
git commit -m "docs(state-research): promote UT to Full Core Coverage"
```

---

## Explicitly Out of Scope (do not build in this plan)

- **State School Board races** — structurally present in the same workbook, same section-parsing mechanism would work, but deferred per the "federal + state legislative + state executive" scope convention (matches MD/NC/VT precedent).
- **State Judicial (judicial retention)** — not office/district/party/candidate-shaped; would need the measure pipeline (yes/no per judge), not the candidate pipeline. Confirmed available per the research doc, deferred per user direction.
- **Ballot measures / initiatives and referenda** (Rank 9 in the research doc) — confirmed available, deferred per user direction.
- **Municipal elections** — the research doc explicitly notes municipal candidates generally file with local officials, not this statewide workbook; county/city elections are a documented out-of-scope area for this codebase generally.
- **Campaign finance (Utah Financial Disclosures), precinct-level results by request, GIS/precinct boundary ingestion, State Archives historical backfill** — all confirmed available in the research doc, all deferred, none required for Full Core.
- **Stage 2 changes** — `results/adapters/ut.py` needs no changes for this plan; it already ingests results generically via the Enhanced Voting ENR JSON API and relies on cross-source race-title normalization to reconcile onto whichever races exist (Stage 1 or Civic API), the same mechanism already live in production for every other state.
