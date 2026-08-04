# Maryland (MD) Stage 1 Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build native Stage 1 (election discovery + race/candidate creation) for Maryland, extending the existing `integrations/md_sbe` package, so MD moves from Results Coverage Only to Full Core Coverage per GitHub issue #87.

**Architecture:** Two Celery tasks mirroring the NC/NY two-task split — `sync_md_elections` (election discovery from a maintained statutory calendar table) and `sync_md_races` (candidate/race creation from MD SBE's consolidated statewide candidate CSV). Both live in `integrations/md_sbe/`, reusing the package's existing `MdSbeClient` soft-404 detection pattern. Scope is federal + state legislative + state executive offices only — same convention as NC/KY/VT. The existing Stage 2 adapter (`results/adapters/md.py`) is separately extended in Task 8 so results actually attach to the races Stage 1 creates (today it only covers President/US Senator on a hardcoded historical 2024 election, which would leave every Stage-1-created 2026 race with no results path).

**Tech Stack:** Python 3.13, Django 5.2, Celery, pytest, `requests`.

## Global Constraints

- Scope is federal + state legislative + state executive races only (US House, US Senate when up, Governor/Lt. Governor, Attorney General, Comptroller, State Senate, House of Delegates). Judicial (Judge of the Circuit Court, appellate retention), county/local offices, ballot measures, and municipal elections are explicitly OUT of scope for this wave — do not build adapters for them even though the research doc confirms sources exist for all of them.
- Follow this repo's TDD convention: write the failing test first, watch it fail, then implement. Run tests with `pytest --no-migrations` (local test-DB creation breaks on an unrelated bad migration in this repo).
- Map CSV columns by header name, never by position — MD's candidate-list schema has drifted between cycles before (documented in `docs/state-research/MD/MD-Election_Research.md` §6).
- Never delete withdrawn/disqualified candidate rows — preserve `Candidate Status` as-is, matching the NC/VT normalization convention already in this codebase.
- All new Django migrations go through the same two-file pattern already established: one `elections` migration adding the `Race.Source` enum value, one `aggregation` migration seeding `SourcePrecedence` rows.

---

## Live-Verified Source Facts (2026-08-04)

These are not assumptions — confirmed today via direct HTTPS fetch, cited here so the plan's code isn't guessing:

- **Single consolidated CSV covers every in-scope office.** `https://elections.maryland.gov/elections/2026/primary_candidates/2026_GP_statewide_candidatelist.csv` (585 rows) contains `Office Name` values: `Attorney General`, `Comptroller`, `Governor / Lt. Governor`, `House of Delegates`, `Judge of the Circuit Court` (excluded — judicial), `Representative in Congress`, `State Senator`. No separate per-office fetch is needed; per-office CSVs exist too but the consolidated one is sufficient and simpler.
- **Exact header row** (BOM-prefixed, decode with `utf-8-sig`):
  `Office Name, Contest Run By District Name and Number, Candidate Ballot Last Name and Suffix, Candidate First Name and Middle Name, Additional Information, Office Political Party, Candidate Residential Jurisdiction, Candidate Gender, Candidate Status, Filing Type and Date, Campaign Mailing Address, Campaign Mailing City State and Zip, Public Phone, Email, Website, Facebook, X, Other, Committee Name, Has Related Candidate, Related Candidate Last Name and Suffix, Related Candidate First Name and Middle Name, Related Office Political Party, Related Candidate County of Residence, Related Candidate Gender, Related Candidate Status, Related Candidate Filing Type and Date, Related Candidate Campaign Mailing Address, Related Candidate Campaign Mailing City State and Zip, Related Candidate Email, Related Candidate Website, Related Candidate Facebook, Related Candidate X, Related Candidate Other Social`
- **District field example values:** `State Of Maryland` (statewide offices), `Congressional District 1`..`8`, `Legislative District 1`..`47` (State Senate), `Legislative District 1A`/`11B`/etc. (House of Delegates — some districts split A/B/C).
- **Governor/Lt. Governor ticket:** one row per ticket under `Office Name == "Governor / Lt. Governor"`. The Governor candidate is in the primary columns; the running mate is in the `Related Candidate *` columns, with `Has Related Candidate == "Yes"`. There is no `running_mate`/`ticket` field on the `Candidate` model (confirmed in `elections/models.py`) — model the ticket as **one `Candidate` row per race** with a combined `name` (`"{Gov Last, Suffix} {Gov First/Middle} / {LtGov Last, Suffix} {LtGov First/Middle}"`), matching how a single ballot line reads. Store both individuals' raw names separately in `source_metadata` for provenance, per the research doc's "model as a ticket with two people, not one concatenated candidate" guidance — concatenating the display name is fine, discarding the underlying two names is not.
- **URL pattern generalizes across phase:** `/elections/{year}/primary_candidates/{PREFIX}{yy}_statewide_candidatelist.csv` during the primary filing period, `/elections/{year}/general_candidates/{PREFIX}{yy}_statewide_candidatelist.csv` after the primary (confirmed both `2026/general_candidates/index.html` and a `2026_GG_statewide_candidatelist.csv`-shaped URL 200 today, even though the general ballot isn't finalized yet — soft-404 body-check still required per `MdSbeClient`'s existing pattern).
- **No stable candidate ID exists in the source** (confirmed in the research doc) — use a compound key.

---

## File Structure

- `backend/integrations/md_sbe/mappers.py` — **new file.** Office-scope filtering, candidate-list row → Race/Candidate identity mapping, ticket-name construction, compound candidate key.
- `backend/integrations/md_sbe/client.py` — **modify.** Add `fetch_statewide_candidate_csv()` alongside the existing `fetch_county_results()`. Reuses the existing soft-404 detection.
- `backend/integrations/md_sbe/calendar.py` — **new file.** Small maintained table of MD's statutory primary/general dates and cycle prefixes per year (see Task 1 — MD primary dates are not on a fixed formula, unlike the federal general-election formula, so this must be a maintained table, not a computed one).
- `backend/integrations/md_sbe/tasks.py` — **new file.** `sync_md_elections` (Stage 1a) and `sync_md_races` (Stage 1b) Celery tasks, mirroring `integrations/nc_sbe/tasks.py`'s structure.
- `backend/integrations/md_sbe/tests/test_calendar.py`, `test_mappers.py`, `test_client.py` (extend), `test_tasks.py` — **new files.**
- `backend/internal/views.py` — **modify.** Add `sync_md_elections_trigger` / `sync_md_races_trigger` view functions.
- `backend/internal/urls.py` — **modify.** Add the two new trigger routes.
- `backend/internal/task_locks.py` — **modify.** Add `sync_md_elections` and `sync_md_races` to `TASK_LOCKS`.
- `backend/elections/migrations/0034_add_md_sbe_race_source.py` — **new file.** Adds `MD_SBE` to `Race.Source`.
- `backend/aggregation/migrations/0016_seed_md_sbe_precedence.py` — **new file.** Seeds `SourcePrecedence` rows for MD.
- `backend/results/adapters/md.py`, `backend/results/adapters/md_aggregate.py` — **modify (Task 8).** Widen from the hardcoded 2024/President+Senator POC to a live-cycle, full-office-scope adapter that reconciles against Stage-1-created races.
- `docs/state-research/00-MASTER-INDEX.md` — **modify (Task 9).** Promote MD's row once verified live.

---

### Task 1: MD election calendar table

**Files:**
- Create: `backend/integrations/md_sbe/calendar.py`
- Test: `backend/integrations/md_sbe/tests/test_calendar.py`

**Interfaces:**
- Produces: `get_active_cycle(today: datetime.date) -> MdElectionCycle | None`, where `MdElectionCycle` is a `dataclass` with fields `year: int`, `primary_date: datetime.date`, `general_date: datetime.date`, `cycle_prefix: str` (e.g. `"GP"` for a gubernatorial cycle). Also produces `MD_ELECTION_CYCLES: dict[int, MdElectionCycle]`, the maintained table, for `tasks.py` to iterate.

MD's primary election date is set by statute but has been moved by the legislature multiple times across recent cycles (2022 was July 19, 2024 was May 14, 2026 is June 23) — there is no reliable formula to compute it. Follow the same precedent this codebase already accepts for AL (`source_metadata["al_ecode"]` requires manual entry) rather than inventing an unverifiable formula. This table is maintained by hand each cycle from the calendar PDF at `https://elections.maryland.gov/elections/{year}/{year}_Election_Calendar.pdf` (Rank 6 source, `docs/state-research/MD/MD-Election_Research.md`).

- [ ] **Step 1: Write the failing test**

```python
# backend/integrations/md_sbe/tests/test_calendar.py
from __future__ import annotations

import datetime


def test_get_active_cycle_returns_2026_cycle_before_primary():
    from integrations.md_sbe.calendar import get_active_cycle
    cycle = get_active_cycle(datetime.date(2026, 3, 1))
    assert cycle is not None
    assert cycle.year == 2026
    assert cycle.primary_date == datetime.date(2026, 6, 23)
    assert cycle.general_date == datetime.date(2026, 11, 3)
    assert cycle.cycle_prefix == "GP"


def test_get_active_cycle_returns_none_when_no_cycle_configured():
    from integrations.md_sbe.calendar import get_active_cycle
    assert get_active_cycle(datetime.date(2099, 1, 1)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest integrations/md_sbe/tests/test_calendar.py -v --no-migrations`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.md_sbe.calendar'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/integrations/md_sbe/calendar.py
"""
Maintained table of Maryland's statutory primary/general election dates.

MD's primary date is set by statute but has been moved by the legislature
across recent cycles (2022: July 19, 2024: May 14, 2026: June 23) — there is
no computable formula. This table must be updated by hand each cycle from
the official calendar PDF (Rank 6 in docs/state-research/MD/MD-Election_Research.md):
https://elections.maryland.gov/elections/{year}/{year}_Election_Calendar.pdf

cycle_prefix mirrors the prefix MD SBE embeds in its candidate-list and
results-CSV filenames (e.g. "GP" = Gubernatorial cycle, "PG" = Presidential
cycle — confirmed against the live 2026_GP_statewide_candidatelist.csv and
the existing results/adapters/md.py which already uses "PG" for 2024).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class MdElectionCycle:
    year: int
    primary_date: datetime.date
    general_date: datetime.date
    cycle_prefix: str


MD_ELECTION_CYCLES: dict[int, MdElectionCycle] = {
    2026: MdElectionCycle(
        year=2026,
        primary_date=datetime.date(2026, 6, 23),
        general_date=datetime.date(2026, 11, 3),
        cycle_prefix="GP",
    ),
}


def get_active_cycle(today: datetime.date) -> MdElectionCycle | None:
    """Return the cycle whose general election hasn't yet passed, or None."""
    candidates = sorted(
        (c for c in MD_ELECTION_CYCLES.values() if c.general_date >= today),
        key=lambda c: c.general_date,
    )
    return candidates[0] if candidates else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest integrations/md_sbe/tests/test_calendar.py -v --no-migrations`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/md_sbe/calendar.py backend/integrations/md_sbe/tests/test_calendar.py
git commit -m "feat(md_sbe): add maintained election-cycle calendar table"
```

---

### Task 2: Candidate CSV client method

**Files:**
- Modify: `backend/integrations/md_sbe/client.py`
- Test: `backend/integrations/md_sbe/tests/test_client.py` (extend existing file)

**Interfaces:**
- Consumes: `MdSbeClient` class, existing `_PAGE_NOT_FOUND_MARKER`, `_BASE_URL` constants already in `client.py`.
- Produces: `MdSbeClient.fetch_statewide_candidate_csv(year: int, cycle_prefix: str, phase: str) -> str`, where `phase` is `"primary"` or `"general"` and selects between the `primary_candidates/` and `general_candidates/` URL paths. Raises `MdSbeRetryableError` on soft-404 or network failure, same contract as the existing `fetch_county_results`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/integrations/md_sbe/tests/test_client.py
import pytest
import responses

from integrations.md_sbe.client import MdSbeClient
from integrations.md_sbe.exceptions import MdSbeRetryableError


@responses.activate
def test_fetch_statewide_candidate_csv_primary_phase():
    responses.add(
        responses.GET,
        "https://elections.maryland.gov/elections/2026/primary_candidates/2026_GP_statewide_candidatelist.csv",
        body="﻿Office Name,Candidate Ballot Last Name and Suffix\r\nGovernor / Lt. Governor,Moore\r\n",
        status=200,
    )
    client = MdSbeClient()
    text = client.fetch_statewide_candidate_csv(year=2026, cycle_prefix="GP", phase="primary")
    assert "Governor / Lt. Governor" in text


@responses.activate
def test_fetch_statewide_candidate_csv_general_phase_uses_general_path():
    responses.add(
        responses.GET,
        "https://elections.maryland.gov/elections/2026/general_candidates/2026_GG_statewide_candidatelist.csv",
        body="﻿Office Name\r\nGovernor / Lt. Governor\r\n",
        status=200,
    )
    client = MdSbeClient()
    text = client.fetch_statewide_candidate_csv(year=2026, cycle_prefix="GG", phase="general")
    assert "Governor" in text


@responses.activate
def test_fetch_statewide_candidate_csv_raises_on_soft_404():
    responses.add(
        responses.GET,
        "https://elections.maryland.gov/elections/2026/primary_candidates/2026_GP_statewide_candidatelist.csv",
        body="Page Not Found" + ("x" * 14400),
        status=200,
    )
    client = MdSbeClient()
    with pytest.raises(MdSbeRetryableError):
        client.fetch_statewide_candidate_csv(year=2026, cycle_prefix="GP", phase="primary")
```

Check `responses` is already a test dependency: `grep responses backend/requirements*.txt` — the existing `test_client.py` for `md_sbe` almost certainly already uses it (`fetch_county_results` has the same soft-404 contract); if not, use whatever HTTP-mocking approach the existing `test_client.py` file already uses instead (`unittest.mock.patch` on `requests.Session.get` is the fallback pattern — check the file before writing this step for real).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest integrations/md_sbe/tests/test_client.py -v --no-migrations`
Expected: FAIL with `AttributeError: 'MdSbeClient' object has no attribute 'fetch_statewide_candidate_csv'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to backend/integrations/md_sbe/client.py, inside class MdSbeClient

    @staticmethod
    def build_candidate_csv_url(year: int, cycle_prefix: str, phase: str) -> str:
        path = "primary_candidates" if phase == "primary" else "general_candidates"
        return (
            f"{_BASE_URL}/elections/{year}/{path}/"
            f"{cycle_prefix}{year % 100:02d}_statewide_candidatelist.csv"
        )

    def fetch_statewide_candidate_csv(self, year: int, cycle_prefix: str, phase: str) -> str:
        url = self.build_candidate_csv_url(year=year, cycle_prefix=cycle_prefix, phase=phase)
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise MdSbeRetryableError(f"MD SBE GET failed: {exc}") from exc

        text = response.content.decode("utf-8-sig", errors="replace")

        if response.status_code != 200 or _PAGE_NOT_FOUND_MARKER in text:
            raise MdSbeRetryableError(f"MD SBE soft-404 or error for candidate CSV url={url}")

        return text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest integrations/md_sbe/tests/test_client.py -v --no-migrations`
Expected: PASS (all `test_client.py` tests, including the 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/md_sbe/client.py backend/integrations/md_sbe/tests/test_client.py
git commit -m "feat(md_sbe): add statewide candidate-list CSV fetch"
```

---

### Task 3: Office-scope filter and candidate-row parsing

**Files:**
- Create: `backend/integrations/md_sbe/mappers.py`
- Test: `backend/integrations/md_sbe/tests/test_mappers.py`

**Interfaces:**
- Produces:
  - `IN_SCOPE_OFFICES: frozenset[str]` — exact `Office Name` values in scope.
  - `is_in_scope_office(office_name: str) -> bool`
  - `parse_statewide_candidate_csv(csv_text: str) -> list[dict]` — thin CSV→list[dict] wrapper (header-name based, via `csv.DictReader`).

- [ ] **Step 1: Write the failing test**

```python
# backend/integrations/md_sbe/tests/test_mappers.py
from __future__ import annotations

import pytest


@pytest.mark.parametrize("office_name", [
    "Governor / Lt. Governor",
    "Attorney General",
    "Comptroller",
    "Representative in Congress",
    "State Senator",
    "House of Delegates",
])
def test_is_in_scope_office_true_for_federal_and_state(office_name):
    from integrations.md_sbe.mappers import is_in_scope_office
    assert is_in_scope_office(office_name) is True


@pytest.mark.parametrize("office_name", [
    "Judge of the Circuit Court",
    "Board of Education",
    "County Council",
    "",
])
def test_is_in_scope_office_false_for_judicial_and_local(office_name):
    from integrations.md_sbe.mappers import is_in_scope_office
    assert is_in_scope_office(office_name) is False


def test_parse_statewide_candidate_csv_maps_by_header_name():
    from integrations.md_sbe.mappers import parse_statewide_candidate_csv
    csv_text = (
        "﻿Office Name,Contest Run By District Name and Number,"
        "Candidate Ballot Last Name and Suffix,Candidate First Name and Middle Name,"
        "Office Political Party,Candidate Status,Has Related Candidate\r\n"
        "Governor / Lt. Governor,State Of Maryland,Moore,Wes,Democratic,Active,Yes\r\n"
    )
    rows = parse_statewide_candidate_csv(csv_text)
    assert len(rows) == 1
    assert rows[0]["Office Name"] == "Governor / Lt. Governor"
    assert rows[0]["Candidate Ballot Last Name and Suffix"] == "Moore"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest integrations/md_sbe/tests/test_mappers.py -v --no-migrations`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.md_sbe.mappers'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/integrations/md_sbe/mappers.py (part 1 of 2 — remaining functions added in Task 4)
"""
Stage 1 mappers for the MD SBE integration.

Source: consolidated {PREFIX}{yy}_statewide_candidatelist.csv, confirmed
2026-08-04 to carry every in-scope office in one file (585 rows for the
2026 primary cycle) — see docs/state-research/MD/MD-Election_Research.md
Rank 2 and the plan's "Live-Verified Source Facts" section.

Full Core scope for this wave (per ADR-005/COVERAGE-CLARIFICATION, same
convention as NC/KY/VT): federal + state legislative + state executive
offices only. Judicial (Judge of the Circuit Court, appellate retention)
and all county/local/municipal offices are out of scope.
"""
from __future__ import annotations

import csv
import io

IN_SCOPE_OFFICES: frozenset[str] = frozenset({
    "Governor / Lt. Governor",
    "Attorney General",
    "Comptroller",
    "U.S. Senator",
    "Representative in Congress",
    "State Senator",
    "House of Delegates",
})


def is_in_scope_office(office_name: str) -> bool:
    return (office_name or "").strip() in IN_SCOPE_OFFICES


def parse_statewide_candidate_csv(csv_text: str) -> list[dict]:
    """Parse the consolidated statewide candidate-list CSV into row dicts.

    Maps by header name (csv.DictReader), never by column position — MD's
    schema has drifted between cycles before.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    return [dict(row) for row in reader]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest integrations/md_sbe/tests/test_mappers.py -v --no-migrations`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/md_sbe/mappers.py backend/integrations/md_sbe/tests/test_mappers.py
git commit -m "feat(md_sbe): add office-scope filter and candidate CSV parsing"
```

---

### Task 4: Race identity, candidate key, and ticket-name mapping

**Files:**
- Modify: `backend/integrations/md_sbe/mappers.py` (append)
- Test: `backend/integrations/md_sbe/tests/test_mappers.py` (append)

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces:
  - `group_candidate_rows(rows: list[dict]) -> dict[tuple[str, str], list[dict]]` — groups by `(Office Name, Contest Run By District Name and Number)`.
  - `map_race_identity(office_name: str, district: str) -> tuple[dict, dict]` — returns `(identity, fields)` for `aggregation.ingest.ingest_race`, matching the exact shape `integrations/nc_sbe/mappers.py::map_race_identity` produces (`identity` has `office_title`, `ocd_division_id`, `race_type`, `contest_variant`; `fields` has `office_title`, `jurisdiction`, `geography_scope`, `vote_method`, `max_selections`, `source`, `source_metadata`).
  - `candidate_display_name(row: dict) -> str` — builds the single-line ballot name, joining the ticket for `"Governor / Lt. Governor"` rows.
  - `map_candidate(row: dict) -> dict` — returns fields for `aggregation.ingest.ingest_candidate`'s `fields` kwarg (`candidate_status`, `source_metadata`), matching `integrations/nc_sbe/mappers.py::map_candidate`'s shape.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/integrations/md_sbe/tests/test_mappers.py

def test_group_candidate_rows_groups_by_office_and_district():
    from integrations.md_sbe.mappers import group_candidate_rows
    rows = [
        {"Office Name": "House of Delegates", "Contest Run By District Name and Number": "Legislative District 1A"},
        {"Office Name": "House of Delegates", "Contest Run By District Name and Number": "Legislative District 1A"},
        {"Office Name": "House of Delegates", "Contest Run By District Name and Number": "Legislative District 1B"},
    ]
    groups = group_candidate_rows(rows)
    assert len(groups) == 2
    assert len(groups[("House of Delegates", "Legislative District 1A")]) == 2


def test_map_race_identity_district_office():
    from integrations.md_sbe.mappers import map_race_identity
    identity, fields = map_race_identity("House of Delegates", "Legislative District 1A")
    assert identity["office_title"] == "House of Delegates - Legislative District 1A"
    assert identity["contest_variant"] == "md:House of Delegates:Legislative District 1A"
    assert fields["geography_scope"] == "district"
    assert fields["source"] == "md_sbe"


def test_map_race_identity_statewide_office():
    from integrations.md_sbe.mappers import map_race_identity
    identity, fields = map_race_identity("Governor / Lt. Governor", "State Of Maryland")
    assert identity["office_title"] == "Governor / Lt. Governor"
    assert fields["geography_scope"] == "statewide"


def test_candidate_display_name_builds_ticket_for_governor():
    from integrations.md_sbe.mappers import candidate_display_name
    row = {
        "Office Name": "Governor / Lt. Governor",
        "Candidate Ballot Last Name and Suffix": "Moore",
        "Candidate First Name and Middle Name": "Wes",
        "Has Related Candidate": "Yes",
        "Related Candidate Last Name and Suffix": "Miller",
        "Related Candidate First Name and Middle Name": "Aruna",
    }
    assert candidate_display_name(row) == "Wes Moore / Aruna Miller"


def test_candidate_display_name_single_candidate_office():
    from integrations.md_sbe.mappers import candidate_display_name
    row = {
        "Office Name": "Attorney General",
        "Candidate Ballot Last Name and Suffix": "Brown",
        "Candidate First Name and Middle Name": "Anthony",
        "Has Related Candidate": "",
    }
    assert candidate_display_name(row) == "Anthony Brown"


def test_map_candidate_preserves_status():
    from integrations.md_sbe.mappers import map_candidate
    row = {"Candidate Status": "Active", "Filing Type and Date": "Regular - 02/13/2026"}
    fields = map_candidate(row)
    assert fields["candidate_status"] == "running"
    assert fields["source_metadata"]["md_status"] == "Active"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest integrations/md_sbe/tests/test_mappers.py -v --no-migrations`
Expected: FAIL with `ImportError: cannot import name 'group_candidate_rows'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/integrations/md_sbe/mappers.py

def group_candidate_rows(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Group candidate rows by (Office Name, district). One group = one race."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        key = (
            (row.get("Office Name") or "").strip(),
            (row.get("Contest Run By District Name and Number") or "").strip(),
        )
        groups.setdefault(key, []).append(row)
    return groups


def map_race_identity(office_name: str, district: str) -> tuple[dict, dict]:
    """
    Return (identity, fields) for aggregation.ingest.ingest_race, from one
    (office_name, district) group of statewide candidate-list rows.
    """
    from elections.models import Race

    office_name = (office_name or "").strip()
    district = (district or "").strip()
    is_statewide = district == "State Of Maryland" or district == ""
    office_title = office_name if is_statewide else f"{office_name} - {district}"
    variant = f"md:{office_name}:{district}"

    identity = {
        "office_title": office_title,
        "ocd_division_id": "",
        "race_type": Race.RaceType.CANDIDATE,
        "contest_variant": variant,
    }
    fields = {
        "office_title": office_title,
        "jurisdiction": "Maryland",
        "geography_scope": "statewide" if is_statewide else "district",
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "source": Race.Source.MD_SBE,
        "source_metadata": {
            "provider": "md_sbe",
            "office_name": office_name,
            "district": district,
            "contest_variant": variant,
        },
    }
    return identity, fields


def candidate_display_name(row: dict) -> str:
    """
    Build the ballot display name. Governor/Lt. Governor rows combine the
    primary candidate and their running mate into one "A / B" line — there
    is no ticket/running_mate field on the Candidate model, so this is the
    single Candidate row's name for that race. Both individual names are
    preserved separately in map_candidate's source_metadata for provenance.
    """
    last = (row.get("Candidate Ballot Last Name and Suffix") or "").strip()
    first = (row.get("Candidate First Name and Middle Name") or "").strip()
    primary_name = f"{first} {last}".strip()

    has_related = (row.get("Has Related Candidate") or "").strip().lower() == "yes"
    if not has_related:
        return primary_name

    related_last = (row.get("Related Candidate Last Name and Suffix") or "").strip()
    related_first = (row.get("Related Candidate First Name and Middle Name") or "").strip()
    related_name = f"{related_first} {related_last}".strip()
    if not related_name:
        return primary_name
    return f"{primary_name} / {related_name}"


def map_candidate(row: dict) -> dict:
    """Map a statewide candidate-list CSV row to Candidate model fields."""
    from elections.models import Candidate

    status_raw = (row.get("Candidate Status") or "").strip()
    status_map = {
        "active": Candidate.CandidateStatus.RUNNING,
        "withdrawn": Candidate.CandidateStatus.WITHDRAWN,
        "disqualified": Candidate.CandidateStatus.DISQUALIFIED,
    }
    candidate_status = status_map.get(status_raw.lower(), Candidate.CandidateStatus.RUNNING)

    return {
        "candidate_status": candidate_status,
        "source_metadata": {
            "provider": "md_sbe",
            "md_status": status_raw,
            "filing": (row.get("Filing Type and Date") or "").strip(),
            "related_candidate_last_name": (row.get("Related Candidate Last Name and Suffix") or "").strip(),
            "related_candidate_first_name": (row.get("Related Candidate First Name and Middle Name") or "").strip(),
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest integrations/md_sbe/tests/test_mappers.py -v --no-migrations`
Expected: PASS (all tests in file)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/md_sbe/mappers.py backend/integrations/md_sbe/tests/test_mappers.py
git commit -m "feat(md_sbe): add race identity, ticket-name, and candidate mapping"
```

---

### Task 5: `Race.Source.MD_SBE` migration

**Files:**
- Modify: `backend/elections/models.py`
- Create: `backend/elections/migrations/0034_add_md_sbe_race_source.py`

**Interfaces:**
- Produces: `Race.Source.MD_SBE = 'md_sbe'` usable by `mappers.py` (Task 4 already references `Race.Source.MD_SBE`, so this task must land before Task 4's tests can pass against a real DB — for a strict TDD run, do this task's migration first if running any DB-backed test; the mapper unit tests above don't hit the DB so ordering here is for whole-suite correctness, not test-by-test blocking).

- [ ] **Step 1: Modify the model**

```python
# backend/elections/models.py — inside class Race, class Source(models.TextChoices):
        NY_BOE = 'ny_boe', 'New York BOE'
        MD_SBE = 'md_sbe', 'Maryland SBE'
```

- [ ] **Step 2: Generate the migration**

Run: `cd backend && python manage.py makemigrations elections --name add_md_sbe_race_source`
Expected output file: `elections/migrations/0034_add_md_sbe_race_source.py` containing an `AlterField` on `Race.source` with `MD_SBE` added to the choices list (same shape as `0028_add_nc_sbe_race_source.py`).

- [ ] **Step 3: Verify migration applies cleanly**

Run: `cd backend && python manage.py migrate elections --plan | grep add_md_sbe_race_source`
Expected: the migration appears in the plan, no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/elections/models.py backend/elections/migrations/0034_add_md_sbe_race_source.py
git commit -m "feat(elections): add MD_SBE to Race.Source"
```

---

### Task 6: `SourcePrecedence` seed migration

**Files:**
- Create: `backend/aggregation/migrations/0016_seed_md_sbe_precedence.py`

**Interfaces:**
- Consumes: the `SourcePrecedence` model (already exists, used identically by `0013_seed_nc_sbe_precedence.py`).
- Produces: MD rows in `SourcePrecedence` ranking `md_sbe` above `civic_api` for `date`, `identity`, and `results`; `civic_api` above `md_sbe` for `contacts` (MD SBE candidate CSVs don't carry the rich contact/office data Civic API does) — same pattern as NC.

- [ ] **Step 1: Write the migration**

```python
# backend/aggregation/migrations/0016_seed_md_sbe_precedence.py
from django.db import migrations

_MD_ROWS = [
    ("MD", "date",     "md_sbe",    0),
    ("MD", "date",     "civic_api", 1),
    ("MD", "contacts", "civic_api", 0),
    ("MD", "contacts", "md_sbe",    1),
    ("MD", "identity", "md_sbe",    0),
    ("MD", "identity", "civic_api", 1),
    ("MD", "results",  "md_sbe",    0),
    ("MD", "results",  "civic_api", 1),
]


def seed_md_sbe_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _MD_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_md_sbe_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="MD").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0015_remove_unreachable_openstates_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_md_sbe_precedence, remove_md_sbe_precedence),
    ]
```

Check `aggregation/migrations/` for the actual latest migration filename before setting `dependencies` — `0015_remove_unreachable_openstates_precedence` was the latest at plan-writing time; if a newer one landed since, depend on that instead.

- [ ] **Step 2: Verify migration applies cleanly**

Run: `cd backend && python manage.py migrate aggregation --plan | grep seed_md_sbe_precedence`
Expected: appears in the plan, no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/aggregation/migrations/0016_seed_md_sbe_precedence.py
git commit -m "feat(aggregation): seed MD SBE source precedence"
```

---

### Task 7: `sync_md_elections` and `sync_md_races` Celery tasks

**Files:**
- Create: `backend/integrations/md_sbe/tasks.py`
- Test: `backend/integrations/md_sbe/tests/test_tasks.py`

**Interfaces:**
- Consumes: `integrations.md_sbe.calendar.get_active_cycle`, `integrations.md_sbe.client.MdSbeClient.fetch_statewide_candidate_csv`, `integrations.md_sbe.mappers.{is_in_scope_office, parse_statewide_candidate_csv, group_candidate_rows, map_race_identity, candidate_display_name, map_candidate}`, `aggregation.ingest.{ingest_election, ingest_race, ingest_candidate}`, `ops.models.SyncLog`, `elections.models.Election`.
- Produces: `sync_md_elections()` and `sync_md_races()` — both `@shared_task(bind=True, max_retries=3, default_retry_delay=300)`, same signature shape as `integrations/nc_sbe/tasks.py`'s two tasks, same `SyncLog` bookkeeping pattern (`STARTED` → `COMPLETED`/`FAILED`, `records_created`/`records_updated`/`error_count`/`last_error`/`notes`).

- [ ] **Step 1: Write the failing test**

```python
# backend/integrations/md_sbe/tests/test_tasks.py
from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db


def test_sync_md_elections_creates_election_for_active_cycle():
    from integrations.md_sbe.tasks import sync_md_elections
    from elections.models import Election

    with patch("integrations.md_sbe.tasks.timezone") as mock_tz:
        mock_tz.localdate.return_value = datetime.date(2026, 3, 1)
        mock_tz.now.return_value = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc)
        result = sync_md_elections()

    assert result["created"] >= 1
    assert Election.objects.filter(state="MD", election_date=datetime.date(2026, 6, 23)).exists()
    assert Election.objects.filter(state="MD", election_date=datetime.date(2026, 11, 3)).exists()


def test_sync_md_races_creates_races_and_candidates_for_in_scope_offices():
    from integrations.md_sbe.tasks import sync_md_elections, sync_md_races
    from elections.models import Election, Race, Candidate

    csv_text = (
        "﻿Office Name,Contest Run By District Name and Number,"
        "Candidate Ballot Last Name and Suffix,Candidate First Name and Middle Name,"
        "Office Political Party,Candidate Status,Has Related Candidate,"
        "Related Candidate Last Name and Suffix,Related Candidate First Name and Middle Name\r\n"
        "Governor / Lt. Governor,State Of Maryland,Moore,Wes,Democratic,Active,Yes,Miller,Aruna\r\n"
        "Judge of the Circuit Court,Judicial Circuit 1,Smith,Pat,,Active,\r\n"
    )

    with patch("integrations.md_sbe.tasks.timezone") as mock_tz:
        mock_tz.localdate.return_value = datetime.date(2026, 3, 1)
        mock_tz.now.return_value = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc)
        sync_md_elections()

        with patch(
            "integrations.md_sbe.tasks.MdSbeClient.fetch_statewide_candidate_csv",
            return_value=csv_text,
        ):
            result = sync_md_races()

    assert result["created"] == 1  # only the in-scope Governor/Lt.Gov race
    race = Race.objects.get(election__state="MD", office_title="Governor / Lt. Governor")
    assert Candidate.objects.filter(race=race, name="Wes Moore / Aruna Miller").exists()
    assert not Race.objects.filter(office_title__icontains="Circuit Court").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest integrations/md_sbe/tests/test_tasks.py -v --no-migrations`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.md_sbe.tasks'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/integrations/md_sbe/tasks.py
"""
Maryland SBE Celery tasks.

sync_md_elections (Stage 1a): seed Election records for MD's active cycle
    from the maintained calendar.py table.

sync_md_races (Stage 1b): fetch the active cycle's consolidated statewide
    candidate-list CSV and upsert Race + Candidate records for in-scope
    (federal + state legislative + state executive) offices. See mappers.py
    for scope and ticket-name handling.
"""
from __future__ import annotations

import logging

from celery import shared_task
from celery.exceptions import Retry
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog

from .calendar import get_active_cycle
from .client import MdSbeClient
from .exceptions import MdSbeRetryableError
from .mappers import (
    candidate_display_name,
    group_candidate_rows,
    is_in_scope_office,
    map_candidate,
    map_race_identity,
    parse_statewide_candidate_csv,
)

logger = logging.getLogger(__name__)

_SOURCE = "md_sbe"


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_md_elections(self):
    """Stage 1a: seed MD's primary and general Election rows from the calendar table."""
    sync_log = SyncLog.objects.create(
        source=_SOURCE, task_name="sync_md_elections", status=SyncLog.Status.STARTED,
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
                    source_id=f"md_sbe_{cycle.year}_{phase}",
                    identity={
                        "state": "MD",
                        "election_type": phase,
                        "election_date": election_date,
                        "jurisdiction_level": Election.JurisdictionLevel.STATE,
                    },
                    fields={
                        "name": f"{cycle.year} Maryland {phase.title()} Election",
                        "status": status,
                        "source_metadata": {"cycle_prefix": cycle.cycle_prefix, "phase": phase},
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
        logger.exception("md_sbe.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_md_races(self):
    """Stage 1b: upsert Race + Candidate records from the active cycle's candidate CSV."""
    from aggregation import ingest

    sync_log = SyncLog.objects.create(
        source=_SOURCE, task_name="sync_md_races", status=SyncLog.Status.STARTED,
    )
    try:
        today = timezone.localdate()
        cycle = get_active_cycle(today)
        if cycle is None:
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.notes = "no active MD cycle configured"
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["status", "notes", "completed_at"])
            return {"created": 0, "updated": 0, "skipped_out_of_scope": 0}

        phase = "primary" if today <= cycle.primary_date else "general"
        election_type = phase
        election = Election.objects.filter(
            state="MD", election_type=election_type, election_date=(
                cycle.primary_date if phase == "primary" else cycle.general_date
            ),
        ).first()
        if election is None:
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.notes = "sync_md_elections has not run yet for this cycle"
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["status", "notes", "completed_at"])
            return {"created": 0, "updated": 0, "skipped_out_of_scope": 0}

        client = MdSbeClient()
        csv_text = client.fetch_statewide_candidate_csv(
            year=cycle.year, cycle_prefix=cycle.cycle_prefix, phase=phase,
        )
        rows = parse_statewide_candidate_csv(csv_text)
        groups = group_candidate_rows(rows)

        created = updated = skipped_out_of_scope = 0

        for (office_name, district), group_rows in groups.items():
            if not is_in_scope_office(office_name):
                skipped_out_of_scope += 1
                continue

            identity, fields = map_race_identity(office_name, district)
            race, race_created = ingest.ingest_race(
                election=election, source=_SOURCE, identity=identity, fields=fields,
            )
            created += int(race_created)
            updated += int(not race_created)

            for row in group_rows:
                name = candidate_display_name(row)
                if not name:
                    continue
                ingest.ingest_candidate(
                    race=race, source=_SOURCE, name=name,
                    party=(row.get("Office Political Party") or "").strip(),
                    fields=map_candidate(row),
                )

        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.notes = f"skipped_out_of_scope={skipped_out_of_scope}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created, "updated": updated, "skipped_out_of_scope": skipped_out_of_scope}

    except MdSbeRetryableError as exc:
        logger.warning("md_sbe.sync_races.retryable_error: %s", exc)
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
        logger.exception("md_sbe.sync_races.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

Check `SyncLog.Status.COMPLETED_WITH_WARNINGS` exists (it's used in `nc_sbe/tasks.py`); if the enum name differs, match whatever `ops/models.py` actually defines.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest integrations/md_sbe/tests/test_tasks.py -v --no-migrations`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/md_sbe/tasks.py backend/integrations/md_sbe/tests/test_tasks.py
git commit -m "feat(md_sbe): add sync_md_elections and sync_md_races Stage 1 tasks"
```

---

### Task 8: Wire tasks into the internal trigger API, task-lock registry, and Cloud Scheduler

**Files:**
- Modify: `backend/internal/task_locks.py`
- Modify: `backend/internal/views.py`
- Modify: `backend/internal/urls.py`
- Test: `backend/internal/tests/test_views.py` (extend)

**Interfaces:**
- Consumes: `sync_md_elections`, `sync_md_races` from Task 7; the existing `_trigger`, `_acquire_lock` helpers in `views.py`.
- Produces: `POST /internal/tasks/sync-md-elections/` and `POST /internal/tasks/sync-md-races/`, each Bearer-token-gated the same way every other endpoint in `urls.py` already is.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/internal/tests/test_views.py
def test_md_elections_task_lock_registered():
    from internal.task_locks import TASK_LOCKS
    assert TASK_LOCKS["sync_md_elections"] == ("daily", 23 * 60 * 60)


def test_md_races_task_lock_registered():
    from internal.task_locks import TASK_LOCKS
    assert TASK_LOCKS["sync_md_races"] == ("daily", 23 * 60 * 60)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest internal/tests/test_views.py -k md -v --no-migrations`
Expected: FAIL with `KeyError: 'sync_md_elections'`

- [ ] **Step 3: Write minimal implementation**

```python
# internal/task_locks.py — add inside TASK_LOCKS dict, alongside the sync_ny_* rows
    "sync_md_elections":    (WINDOW_DAILY,      23 * _HOUR),
    "sync_md_races":        (WINDOW_DAILY,      23 * _HOUR),
```

```python
# internal/views.py — add to the import block, alongside the nc_sbe import
from integrations.md_sbe.tasks import sync_md_elections, sync_md_races
```

```python
# internal/views.py — add trigger view functions, following the sync_nc_sbe_trigger pattern
@csrf_exempt
@require_POST
@require_internal_task_token
def sync_md_elections_trigger(request):
    return _trigger("sync_md_elections", sync_md_elections, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_md_races_trigger(request):
    return _trigger("sync_md_races", sync_md_races, request)
```

Check the exact decorator stack on `sync_nc_sbe_trigger` in `views.py` before writing this — copy it verbatim rather than guessing at decorator order.

```python
# internal/urls.py — add routes, alongside the sync-nc-sbe routes
    path("tasks/sync-md-elections/", views.sync_md_elections_trigger, name="internal-sync-md-elections"),
    path("tasks/sync-md-races/", views.sync_md_races_trigger, name="internal-sync-md-races"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest internal/tests/test_views.py -k md -v --no-migrations`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/internal/task_locks.py backend/internal/views.py backend/internal/urls.py backend/internal/tests/test_views.py
git commit -m "feat(internal): wire MD SBE Stage 1 tasks into trigger API"
```

- [ ] **Step 6: Add to production crontab (manual, post-merge)**

After this PR merges and is deployed, add both lines to `/data/DockerConfigs/CivicMirror/scheduler/crontab` (same file NC/NY use), in order (elections before races, same as NC):

```
0 12 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-md-elections/
5 12 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-md-races/
```

Then `docker restart civicmirror-scheduler` and confirm both lines are live with `docker exec civicmirror-scheduler crontab -l`. This step is not part of the code PR — it's a manual production step, same as NC's issue #57 fix required.

---

### Task 9: Extend Stage 2 (`results/adapters/md.py`) to reconcile with Stage-1-created races

**Files:**
- Modify: `backend/results/adapters/md.py`
- Modify: `backend/results/adapters/md_aggregate.py`
- Test: `backend/results/tests/test_md_adapter.py` (extend existing file)

**Interfaces:**
- Consumes: `MdSbeClient` (unchanged), the office-name strings from Task 4 (`IN_SCOPE_OFFICES` values must match the `Office Name` strings this adapter's `_OFFICE_ALLOWLIST` filters on, since Stage 1 races are keyed by the same office titles).
- Produces: `MarylandAdapter.fetch_results` widened to accept a live cycle year/prefix (via `integrations.md_sbe.calendar.get_active_cycle`, same table Task 1 built) instead of the hardcoded `_YEAR = 2024` / `_CYCLE_PREFIX = "PG"` constants, and `_OFFICE_ALLOWLIST` widened from `{"President - Vice Pres", "U.S. Senator"}` to match `integrations.md_sbe.mappers.IN_SCOPE_OFFICES`.

This is the task that actually closes the Full Core gap: without it, Stage 1 will create Governor/Lt. Governor, Attorney General, Comptroller, US House, State Senate, and House of Delegates races, but the results adapter will keep ignoring all of them (it currently only recognizes `"President - Vice Pres"` and `"U.S. Senator"` from a single hardcoded 2024 election). MD cannot be called Full Core until this is fixed — election/race creation alone is only half of ADR-005's definition.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/results/tests/test_md_adapter.py
import datetime
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db


def test_fetch_results_uses_active_cycle_not_hardcoded_2024(db):
    from elections.models import Election
    from results.adapters.md import MarylandAdapter

    election = Election.objects.create(
        name="2026 Maryland General Election", state="MD",
        election_date=datetime.date(2026, 11, 3), election_type="general",
        jurisdiction_level="state",
    )

    with patch("results.adapters.md.get_active_cycle") as mock_cycle:
        from integrations.md_sbe.calendar import MdElectionCycle
        mock_cycle.return_value = MdElectionCycle(
            year=2026, primary_date=datetime.date(2026, 6, 23),
            general_date=datetime.date(2026, 11, 3), cycle_prefix="GG",
        )
        with patch("results.adapters.md.MdSbeClient.fetch_county_results", return_value=""):
            adapter = MarylandAdapter()
            result = adapter.fetch_results(election.election_date, election.pk)

    # No rows expected from an empty fixture, but the call must not raise
    # and must not silently fall back to the 2024/PG constants.
    assert result.source_url == "" or "2026" in result.source_url


def test_office_allowlist_includes_state_legislative_offices():
    from results.adapters.md import _OFFICE_ALLOWLIST
    assert "Governor / Lt. Governor" in _OFFICE_ALLOWLIST
    assert "State Senator" in _OFFICE_ALLOWLIST
    assert "House of Delegates" in _OFFICE_ALLOWLIST
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest results/tests/test_md_adapter.py -k "active_cycle or allowlist_includes" -v --no-migrations`
Expected: FAIL — `_OFFICE_ALLOWLIST` doesn't contain the new offices yet, and `get_active_cycle` isn't imported into `results/adapters/md.py` yet.

- [ ] **Step 3: Write minimal implementation**

```python
# results/adapters/md.py — replace the module-level constants and fetch_results body
from integrations.md_sbe.calendar import get_active_cycle
from integrations.md_sbe.mappers import IN_SCOPE_OFFICES

_OFFICE_ALLOWLIST = IN_SCOPE_OFFICES  # replaces the old frozenset({"President - Vice Pres", "U.S. Senator"})
```

Then in `fetch_results`, replace the two hardcoded module constants `_YEAR` / `_CYCLE_PREFIX` used in the `client.build_url(...)` call with values derived from `get_active_cycle(election_date)` (falling back to the existing 2024/PG constants only when no cycle table entry covers `election_date`, so the historical 2024 test fixtures in `results/tests/fixtures/md_county*.csv` keep passing unmodified). Keep the per-county fetch loop and checksum logic in `fetch_results` exactly as-is — only the year/cycle-prefix source and the office allowlist change.

Note for whoever implements this task: `md_aggregate.py`'s `aggregate_county_rows` function itself needs no changes — it already takes `office_allowlist` as a parameter and has no office-specific logic. Also note: results CSVs are per-county (`{prefix}{yy}_{county}CountyResults.csv`) and cover *all* offices on that county's ballot in one file — confirm during implementation whether `Office Name` values in the results CSV exactly match the candidate-list CSV's `Office Name` values (e.g. does the results file also say `"House of Delegates"` or something like `"Delegate District 1A"` — the plan's Live-Verified Source Facts section only checked the candidate-list CSV, not a results CSV, because no 2026 results exist yet to check against). If they don't match exactly, add a small alias map in `md_aggregate.py` rather than changing `IN_SCOPE_OFFICES` (which must stay in sync with Stage 1's race `office_title`s).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest results/tests/test_md_adapter.py -v --no-migrations`
Expected: PASS (all tests, including the pre-existing 2024 fixture-based tests — verify those still pass since they exercise the fallback path)

- [ ] **Step 5: Commit**

```bash
git add backend/results/adapters/md.py backend/results/adapters/md_aggregate.py backend/results/tests/test_md_adapter.py
git commit -m "feat(results): widen MD adapter to live cycle + full office scope"
```

---

### Task 10: Full backend test suite and ruff check

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && pytest --no-migrations`
Expected: all tests pass, including every pre-existing `md_sbe`/`md` test.

- [ ] **Step 2: Run ruff**

Run: `cd backend && ruff check .`
Expected: no errors introduced by this plan's new/modified files.

- [ ] **Step 3: Commit if either step required fixes**

```bash
git add -A
git commit -m "fix: address test/lint findings from MD Stage 1 build"
```

---

### Task 11: Live verification and Full Core promotion

**Files:**
- Modify: `docs/state-research/00-MASTER-INDEX.md`
- Comment on: GitHub issue #87

Do not do this task until Task 8's Step 6 (crontab wiring) has been live in production and `ops_synclog` shows clean unattended runs — apply the same bar NY was just held to (see the NY promotion commit `84234ea` and issue #87 comment): several consecutive days of `status=completed`, `error_count=0` for both `sync_md_elections` and `sync_md_races`, plus at least one confirmed `OfficialResult` row attaching to a Stage-1-created MD race once results start flowing (won't be possible to fully verify until closer to the June 23, 2026 primary or Nov 3, 2026 general — check `ops_synclog` and `results_officialresult` joined to `elections_race`/`elections_election` the same way the NY verification did).

- [ ] **Step 1: Query production `ops_synclog` for MD**

```bash
docker exec civicmirror-postgres psql -U civicmirror -d civicmirror_api -c "
SELECT started_at, task_name, status, records_created, records_updated, error_count
FROM ops_synclog WHERE source = 'md_sbe' ORDER BY started_at DESC LIMIT 20;"
```

- [ ] **Step 2: Update the master index**

Move MD's row in `docs/state-research/00-MASTER-INDEX.md` from "Results Coverage Only" to "Full Core Coverage" (both the table row and the prose bullet list), following the exact same edit shape used for NY in commit `84234ea`.

- [ ] **Step 3: Comment on and check off issue #87**

```bash
gh issue comment 87 --repo CivicMirror/CivicMirror-API --body "MD promoted to Full Core — [evidence]"
```

Check off MD's line in the issue body via `gh issue edit 87 --body-file ...`, same process used for NY.

- [ ] **Step 4: Commit the doc update**

```bash
git add docs/state-research/00-MASTER-INDEX.md
git commit -m "docs(state-research): promote MD to Full Core Coverage"
```

---

## Explicitly Out of Scope (do not build in this plan)

- Ballot-question / measure adapter (Rank 5 in the research doc) — confirmed available, deferred per user direction.
- Municipal document lane (Rank 8) — confirmed available, deferred per user direction.
- Campaign finance (MD CRIS, Rank 9), CVRs (Rank 11), GIS/precinct boundary verification (Rank 10), certification/audit-notice indexing — all deferred, not required for Full Core.
- US Senate is not up in MD in 2026 (Van Hollen's term runs through 2028) — `IN_SCOPE_OFFICES` includes `"U.S. Senator"` for forward-compatibility with future cycles, but no test fixture needs to cover it for 2026.
