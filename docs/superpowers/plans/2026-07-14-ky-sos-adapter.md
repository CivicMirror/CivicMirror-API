# Kentucky SOS Stage 1 Adapter (KY-Elections + KY-Candidates) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Kentucky Stage-1 adapter (`backend/integrations/ky_sos/`) that ingests one Election record and Candidate Filings-sourced Race/Candidate records for the four in-scope federal + state-legislative office groups, including withdrawn/deceased/disqualified reconciliation.

**Architecture:** A single Celery task (`sync_ky_sos`, mirroring `oh_sos`'s one-task pattern) does everything in one run: derive the election from a statutory-date formula + the live election label, fetch the Candidate Filings directory page, sweep the four in-scope office-group pages plus the withdrawn group, and call `aggregation.ingest_election` / `ingest_race` / `ingest_candidate` for each record. No calendar-PDF client and no "Upcoming Election Summary" page are used — that URL from the original research doc returned HTTP 404 on live verification (see "Design deviation from spec" below).

**Tech Stack:** Django 5.2 / Python 3.14, `requests` + `beautifulsoup4` for HTML, Celery for the task, `pytest` + `pytest-django` for tests (run with `--no-migrations`).

## Global Constraints

- Follow the existing adapter shape used by `backend/integrations/il_sbe/` and `backend/integrations/oh_sos/`: `client.py`, `parsers.py`, `mappers.py`, `exceptions.py`, `apps.py`, `tasks.py`, `tests/`.
- All writes go through `aggregation.ingest.ingest_election` / `ingest_race` / `ingest_candidate` — no direct `Election.objects.create()` / `bulk_create()` in adapter code.
- Scope is federal + state-legislative offices only: US Senator (office id 3), US Representative (id 4), State Senator (id 11), State Representative (id 12). No judicial offices, no Constitutional Amendment group, no county filings.
- No PDF parsing (annual calendar / 2026-2036 schedule PDFs are out of scope for this PR).
- No live-results (`vrsws.sos.ky.gov`) automation — not in scope, not to be prototyped.
- Tests run via `pytest --no-migrations` (project convention — local test-DB creation breaks on a bad migration).
- New source choice: `Race.Source.KY_SOS = 'ky_sos', 'Kentucky SOS'`.

## Design deviation from the approved spec

The approved spec (`docs/superpowers/specs/2026-07-14-ky-sos-adapter-design.md`) assumed a
separate "Upcoming Election Summary" HTML page at
`elect.ky.gov/calendar/Pages/Upcoming-Elections.aspx` for Stage-1a election creation. Live
verification during planning found that URL returns **HTTP 404** — `elect.ky.gov`'s calendar
section is a static SharePoint page linking only to PDF calendars (out of scope per the spec).

Two things replace it, confirmed live 2026-07-14:

1. **Election date**: computed via the standard KY general-election statutory formula (first
   Tuesday after first Monday in November — Ky. Const. §148, KRS 118.025(4)), matching the
   dates already independently compiled by the user's research doc
   `docs/state-research/KY/2026_Kentucky_Election_Calendar.md` (General Election Day: November 3,
   2026). This mirrors how `oh_sos/mappers.py::oh_general_election_date` computes Ohio's date —
   no HTTP call needed for the date itself.
2. **Election label**: read directly off the Candidate Filings pages themselves. Every page
   (confirmed on both the office directory home page and every office-group page) includes:
   ```html
   <select id="ctl00_MainContent_ddlElection" ...>
   <option selected="selected" value="87">2026 General Election</option>
   </select>
   ```
   No separate calendar client is needed — `sync_ky_sos` fetches the Candidate Filings directory
   page once and gets both the office-group directory *and* the current election label from that
   one response.

This also simplifies the task structure from the spec's two-task (`sync_ky_elections` +
`sync_ky_candidates`) design to a single task, matching `oh_sos`'s proven single-task pattern
(there is no separate election-discovery step that runs on its own schedule — the election and
candidates come from the same site in the same run).

Real fixture HTML for all four in-scope office groups plus the withdrawn group was captured live
2026-07-14 and is checked in at `backend/integrations/ky_sos/tests/fixtures/` (already present in
the working tree before this plan's tasks begin — see Task 2).

## Withdrawn/Deceased/Disqualified handling

Live verification also found the withdrawn group page does **not** distinguish withdrawn vs.
deceased vs. disqualified per row — it's one merged list under a single "Withdrawn / Deceased /
Disqualified" heading with no per-row status column (confirmed against
`tests/fixtures/withdrawn.html`). All rows in that sweep are mapped to
`Candidate.CandidateStatus.WITHDRAWN` uniformly. Since the withdrawn group is disjoint from the
active office-group listings (a withdrawn candidate's `<a>` gets the `withdrawal` CSS class and is
never repeated in the `notwithdrawn` office links), the withdrawn sweep and the active sweep never
collide — no need for a second "mark existing rows inactive" pass. Each row (active or withdrawn)
goes straight through `ingest_candidate` with the appropriate `candidate_status` in `fields`.

---

### Task 1: App scaffold + Race.Source.KY_SOS migration

**Files:**
- Create: `backend/integrations/ky_sos/__init__.py` (empty)
- Create: `backend/integrations/ky_sos/apps.py`
- Create: `backend/integrations/ky_sos/exceptions.py`
- Create: `backend/integrations/ky_sos/tests/__init__.py` (empty)
- Modify: `backend/config/settings/base.py:167` (after `'integrations.mn_sos',`)
- Modify: `backend/elections/models.py:112` (after `OR_SOS = 'or_sos', 'Oregon SOS'`)
- Create: `backend/elections/migrations/0024_add_ky_sos_race_source.py`

**Interfaces:**
- Produces: `Race.Source.KY_SOS` usable by later tasks; `KySosError`, `KySosRetryableError`
  exception classes importable from `integrations.ky_sos.exceptions`.

- [ ] **Step 1: Create the app package**

`backend/integrations/ky_sos/__init__.py` — empty file.

`backend/integrations/ky_sos/apps.py`:
```python
from django.apps import AppConfig


class KentuckySosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.ky_sos"
    label = "ky_sos"
    verbose_name = "Kentucky SOS Integration"
```

`backend/integrations/ky_sos/exceptions.py`:
```python
class KySosError(Exception):
    """Non-retryable Kentucky SOS integration error."""


class KySosRetryableError(KySosError):
    """Transient error that warrants a Celery retry."""
```

`backend/integrations/ky_sos/tests/__init__.py` — empty file.

- [ ] **Step 2: Register the app**

In `backend/config/settings/base.py`, add a line after `'integrations.mn_sos',` (currently line
167):

```python
    'integrations.mn_sos',
    'integrations.ky_sos',
```

- [ ] **Step 3: Add the Race.Source choice**

In `backend/elections/models.py`, in `Race.Source` (the `class Source(models.TextChoices):` block
starting at line 92), add after the `OR_SOS` line:

```python
        OR_SOS = 'or_sos', 'Oregon SOS'
        KY_SOS = 'ky_sos', 'Kentucky SOS'
```

- [ ] **Step 4: Generate and check the migration**

Run:
```bash
cd backend && python manage.py makemigrations elections --name add_ky_sos_race_source
```
Expected: creates `backend/elections/migrations/0024_add_ky_sos_race_source.py` with dependency
on `0023_add_mn_or_sos_race_sources` and an `AlterField` on `Race.source` adding `('ky_sos',
'Kentucky SOS')` to the choices list. Open the generated file and confirm it matches that shape
(compare against `elections/migrations/0023_add_mn_or_sos_race_sources.py` for the expected
format) — no manual edits needed if `makemigrations` produced the expected `AlterField`.

- [ ] **Step 5: Verify the app loads**

Run:
```bash
cd backend && python manage.py check
```
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/ky_sos/__init__.py backend/integrations/ky_sos/apps.py \
  backend/integrations/ky_sos/exceptions.py backend/integrations/ky_sos/tests/__init__.py \
  backend/config/settings/base.py backend/elections/models.py \
  backend/elections/migrations/0024_add_ky_sos_race_source.py
git commit -m "feat(ky): scaffold ky_sos integration app and KY_SOS race source"
```

---

### Task 2: Verify test fixtures are in place

The four fixture files below were already captured live from `web.sos.ky.gov/CandidateFilings/`
during planning (2026-07-14) and copied into the repo. This task just confirms they're present
and gives their exact provenance so a fresh worker doesn't need to re-fetch them.

**Files:**
- Verify exists: `backend/integrations/ky_sos/tests/fixtures/office_directory.html` (from
  `GET https://web.sos.ky.gov/CandidateFilings/` — the directory/home page, contains the office
  links, the withdrawn link, and the `ddlElection` dropdown)
- Verify exists: `backend/integrations/ky_sos/tests/fixtures/office_us_senator.html` (from
  `GET https://web.sos.ky.gov/CandidateFilings/Default.aspx?id=3` — statewide office, empty
  District/Division cells, 4 candidate rows)
- Verify exists: `backend/integrations/ky_sos/tests/fixtures/office_us_representative.html`
  (from `GET https://web.sos.ky.gov/CandidateFilings/Default.aspx?id=4` — district office, 21
  candidate rows across districts 1-6)
- Verify exists: `backend/integrations/ky_sos/tests/fixtures/withdrawn.html` (from
  `GET https://web.sos.ky.gov/CandidateFilings/Default.aspx?withdrawn=1` — 1 row at capture time,
  grouped by office, no per-row status/date-filed column)

- [ ] **Step 1: Confirm the fixtures exist and are non-empty**

Run:
```bash
cd backend && for f in office_directory office_us_senator office_us_representative withdrawn; do
  wc -l integrations/ky_sos/tests/fixtures/$f.html
done
```
Expected: four non-zero line counts (roughly: office_directory ~450 lines, office_us_senator
~550 lines, office_us_representative ~1050 lines, withdrawn ~470 lines — exact counts aren't
important, just confirm none are empty/missing).

If any file is missing, re-fetch it with `curl -s -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64)
AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36" <url> -o <fixture path>`
using the URLs listed above — this is a plain public GET, no auth or bot-bypass needed (confirmed
live 2026-07-14; only the separate `vrsws.sos.ky.gov` live-results system has bot protection, not
`web.sos.ky.gov`).

- [ ] **Step 2: No commit needed**

These files are not yet tracked by git (they were copied into the working tree during planning).
They'll be committed together with Task 3's parser code, since a fixture with no test exercising
it is dead weight in its own commit.

---

### Task 3: parsers.py — HTML extraction

**Files:**
- Create: `backend/integrations/ky_sos/parsers.py`
- Create: `backend/integrations/ky_sos/tests/test_parsers.py`
- (fixtures from Task 2, now committed alongside this task)

**Interfaces:**
- Produces:
  - `parse_current_election(html: str) -> dict` → `{"value": str, "label": str}`
  - `parse_office_directory(html: str) -> list[dict]` → each
    `{"office_id": int, "label": str, "count": int}`
  - `parse_candidate_rows(html: str) -> list[dict]` → each
    `{"name": str, "office": str, "district": str, "party": str, "date_filed": str}`
    (`date_filed` is `""` for withdrawn-group fixtures, which have no Date Filed column)

- [ ] **Step 1: Write the failing tests**

`backend/integrations/ky_sos/tests/test_parsers.py`:
```python
import os

from integrations.ky_sos.parsers import (
    parse_candidate_rows,
    parse_current_election,
    parse_office_directory,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_current_election_reads_selected_option():
    html = _load_fixture("office_directory.html")
    result = parse_current_election(html)
    assert result == {"value": "87", "label": "2026 General Election"}


def test_parse_office_directory_extracts_ids_labels_counts():
    html = _load_fixture("office_directory.html")
    offices = parse_office_directory(html)
    by_id = {o["office_id"]: o for o in offices}
    assert by_id[3]["label"] == "US Senator"
    assert by_id[3]["count"] == 4
    assert by_id[4]["label"] == "US Representative"
    assert by_id[4]["count"] == 21
    assert by_id[11]["label"] == "State Senator"
    assert by_id[11]["count"] == 30
    assert by_id[12]["label"] == "State Representative"
    assert by_id[12]["count"] == 150
    # Out-of-scope groups are still parsed (filtering happens in mappers/tasks) —
    # this parser is a faithful extraction, not a scope filter.
    assert 14 in by_id  # Justice of the Supreme Court


def test_parse_candidate_rows_statewide_office_has_empty_district():
    html = _load_fixture("office_us_senator.html")
    rows = parse_candidate_rows(html)
    assert len(rows) == 4
    andy_barr = next(r for r in rows if r["name"] == "Andy Barr")
    assert andy_barr["office"] == "US Senator"
    assert andy_barr["district"] == ""
    assert andy_barr["party"] == "Republican Party"
    assert andy_barr["date_filed"] == "11/7/2025"


def test_parse_candidate_rows_district_office_extracts_district_text():
    html = _load_fixture("office_us_representative.html")
    rows = parse_candidate_rows(html)
    assert len(rows) == 21
    comer = next(r for r in rows if r["name"] == "James R. Comer")
    assert comer["office"] == "US Representative"
    assert comer["district"] == "1st"
    assert comer["party"] == "Republican Party"


def test_parse_candidate_rows_withdrawn_group_has_no_date_filed():
    html = _load_fixture("withdrawn.html")
    rows = parse_candidate_rows(html)
    assert len(rows) == 1
    chaffin = rows[0]
    assert chaffin["name"] == "Alisha Dawn Chaffin"
    assert chaffin["office"] == "State Representative"
    assert chaffin["district"] == "88th"
    assert chaffin["party"] == "Democratic Party"
    assert chaffin["date_filed"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest --no-migrations integrations/ky_sos/tests/test_parsers.py -v`
Expected: `ModuleNotFoundError: No module named 'integrations.ky_sos.parsers'`

- [ ] **Step 3: Write parsers.py**

`backend/integrations/ky_sos/parsers.py`:
```python
"""
HTML parsers for the Kentucky SOS Candidate Filings application
(web.sos.ky.gov/CandidateFilings/).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

_OFFICE_LINK_RE = re.compile(r"^Default\.aspx\?id=(\d+)$")
_COUNT_RE = re.compile(r"\((\d+)\)\s*$")


def parse_current_election(html: str) -> dict:
    """Extract {value, label} for the currently-selected election dropdown option."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find(id="ctl00_MainContent_ddlElection")
    if not select:
        return {}
    option = select.find("option", selected=True) or select.find("option")
    if not option:
        return {}
    return {"value": option.get("value", ""), "label": option.get_text(strip=True)}


def parse_office_directory(html: str) -> list[dict]:
    """Extract {office_id, label, count} for every office group in the directory."""
    soup = BeautifulSoup(html, "html.parser")
    offices = []
    for a in soup.find_all("a", href=_OFFICE_LINK_RE):
        match = _OFFICE_LINK_RE.match(a["href"])
        office_id = int(match.group(1))
        text = a.get_text(strip=True)
        count_match = _COUNT_RE.search(text)
        count = int(count_match.group(1)) if count_match else 0
        label = _COUNT_RE.sub("", text).strip()
        offices.append({"office_id": office_id, "label": label, "count": count})
    return offices


def parse_candidate_rows(html: str) -> list[dict]:
    """
    Extract candidate rows from an office-group results table (active office
    pages have 6 columns ending in Date Filed; the withdrawn group has 5
    columns with no Date Filed).
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for body in soup.select("div.cf-office-body"):
        table = body.find("table")
        if not table:
            continue
        trs = table.find_all("tr")[1:]  # skip header row
        for tr in trs:
            cells = tr.find_all("td")
            if len(cells) < 5:
                continue
            name_link = cells[0].find("a")
            name = name_link.get_text(strip=True) if name_link else cells[0].get_text(strip=True)
            office = cells[2].get_text(strip=True)
            district_link = cells[3].find("a")
            district = district_link.get_text(strip=True) if district_link else ""
            party = cells[4].get_text(strip=True)
            date_filed = cells[5].get_text(strip=True) if len(cells) >= 6 else ""
            rows.append({
                "name": name,
                "office": office,
                "district": district,
                "party": party,
                "date_filed": date_filed,
            })
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest --no-migrations integrations/ky_sos/tests/test_parsers.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ky_sos/parsers.py backend/integrations/ky_sos/tests/test_parsers.py \
  backend/integrations/ky_sos/tests/fixtures/
git commit -m "feat(ky): add Candidate Filings HTML parsers"
```

---

### Task 4: mappers.py — normalize to CivicMirror fields

**Files:**
- Create: `backend/integrations/ky_sos/mappers.py`
- Create: `backend/integrations/ky_sos/tests/test_mappers.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (works on plain dicts shaped like
  `parse_candidate_rows`/`parse_current_election`/`parse_office_directory` output).
- Produces:
  - `IN_SCOPE_OFFICE_IDS: frozenset[int]` = `{3, 4, 11, 12}`
  - `ky_general_election_date(year: int) -> datetime.date`
  - `map_election(election_label: str) -> dict` → dict for `ingest_election` (includes
    `source_id`, identity fields, `name`, `state`, `status`)
  - `map_race(office_name: str, district: str) -> dict` → dict for `ingest_race`
  - `map_candidate(row: dict, candidate_status: str) -> dict` → `(name, party, fields)` tuple
    ready for `ingest_candidate`'s `name=`/`party=`/`fields=` kwargs

- [ ] **Step 1: Write the failing tests**

`backend/integrations/ky_sos/tests/test_mappers.py`:
```python
import datetime

from elections.models import Candidate, Election, Race

from integrations.ky_sos.mappers import (
    IN_SCOPE_OFFICE_IDS,
    ky_general_election_date,
    map_candidate,
    map_election,
    map_race,
)


def test_in_scope_office_ids_are_federal_and_state_legislative_only():
    assert IN_SCOPE_OFFICE_IDS == {3, 4, 11, 12}


def test_ky_general_election_date_2026():
    # Ky. Const. §148 / KRS 118.025(4): first Tuesday after first Monday in
    # November. Confirmed against docs/state-research/KY/2026_Kentucky_Election_Calendar.md
    # ("GENERAL ELECTION DAY: Tuesday, November 3, 2026").
    assert ky_general_election_date(2026) == datetime.date(2026, 11, 3)


def test_map_election_general_election():
    result = map_election("2026 General Election")
    assert result["source_id"] == "ky_sos_2026_general"
    assert result["name"] == "2026 Kentucky General Election"
    assert result["election_date"] == datetime.date(2026, 11, 3)
    assert result["election_type"] == "general"
    assert result["jurisdiction_level"] == Election.JurisdictionLevel.STATE
    assert result["state"] == "KY"


def test_map_race_statewide_office_no_district():
    result = map_race("US Senator", "")
    assert result["office_title"] == "US Senator"
    assert result["geography_scope"] == "statewide"
    assert result["jurisdiction"] == "Kentucky"
    assert result["race_type"] == Race.RaceType.CANDIDATE
    assert result["source"] == Race.Source.KY_SOS
    assert result["ocd_division_id"] == ""


def test_map_race_district_office_includes_district_in_title():
    result = map_race("US Representative", "1st")
    assert result["office_title"] == "US Representative District 1st"
    assert result["geography_scope"] == "district"
    assert result["jurisdiction"] == "Kentucky District 1st"


def test_map_candidate_active_row():
    row = {
        "name": "Andy Barr", "office": "US Senator", "district": "",
        "party": "Republican Party", "date_filed": "11/7/2025",
    }
    name, party, fields = map_candidate(row, Candidate.CandidateStatus.RUNNING)
    assert name == "Andy Barr"
    assert party == "Republican Party"
    assert fields["candidate_status"] == Candidate.CandidateStatus.RUNNING
    assert fields["source_metadata"]["ky_sos_date_filed"] == "11/7/2025"


def test_map_candidate_withdrawn_row_has_withdrawn_status():
    row = {
        "name": "Alisha Dawn Chaffin", "office": "State Representative",
        "district": "88th", "party": "Democratic Party", "date_filed": "",
    }
    name, party, fields = map_candidate(row, Candidate.CandidateStatus.WITHDRAWN)
    assert fields["candidate_status"] == Candidate.CandidateStatus.WITHDRAWN
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest --no-migrations integrations/ky_sos/tests/test_mappers.py -v`
Expected: `ModuleNotFoundError: No module named 'integrations.ky_sos.mappers'`

- [ ] **Step 3: Write mappers.py**

`backend/integrations/ky_sos/mappers.py`:
```python
"""
Mappers for Kentucky SOS Candidate Filings data -> CivicMirror model fields.
"""
from __future__ import annotations

import calendar
import datetime

from elections.models import Election, Race

IN_SCOPE_OFFICE_IDS = frozenset({3, 4, 11, 12})

# office_id -> expected office label text (sanity/lookup only; office_title
# itself always comes from the parsed row text, not this table).
OFFICE_LABELS = {
    3: "US Senator",
    4: "US Representative",
    11: "State Senator",
    12: "State Representative",
}

_STATEWIDE_OFFICES = frozenset({"US Senator"})


def ky_general_election_date(year: int) -> datetime.date:
    """First Tuesday after first Monday in November (Ky. Const. §148, KRS 118.025(4))."""
    first = datetime.date(year, 11, 1)
    days_to_monday = (calendar.MONDAY - first.weekday()) % 7
    first_monday = first + datetime.timedelta(days=days_to_monday)
    return first_monday + datetime.timedelta(days=1)


def infer_election_status(election_date: datetime.date) -> str:
    from django.utils import timezone
    today = timezone.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def map_election(election_label: str) -> dict:
    """
    Map the Candidate Filings election dropdown label (e.g. "2026 General
    Election") to Election model field values. Only "General Election" labels
    are supported — this adapter doesn't sweep primary-cycle filings.
    """
    year = int(election_label.split()[0])
    election_date = ky_general_election_date(year)
    return {
        "source_id": f"ky_sos_{year}_general",
        "name": f"{year} Kentucky General Election",
        "election_date": election_date,
        "election_type": "general",
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "KY",
        "status": infer_election_status(election_date),
    }


def map_race(office_name: str, district: str) -> dict:
    is_statewide = office_name in _STATEWIDE_OFFICES
    office_title = office_name if is_statewide else f"{office_name} District {district}"
    jurisdiction = "Kentucky" if is_statewide else f"Kentucky District {district}"

    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office_title,
        "jurisdiction": jurisdiction,
        "geography_scope": "statewide" if is_statewide else "district",
        "certification_status": Race.CertificationStatus.UPCOMING,
        "source": Race.Source.KY_SOS,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "normalized_office_title": " ".join(office_title.lower().split()),
        "source_metadata": {"ky_sos_office": office_name, "ky_sos_district": district},
    }


def map_candidate(row: dict, candidate_status: str) -> tuple[str, str, dict]:
    fields = {
        "candidate_status": candidate_status,
        "source_metadata": {
            "ky_sos_date_filed": row.get("date_filed", ""),
            "ky_sos_office": row.get("office", ""),
            "ky_sos_district": row.get("district", ""),
        },
    }
    return row["name"], row.get("party", ""), fields
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest --no-migrations integrations/ky_sos/tests/test_mappers.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ky_sos/mappers.py backend/integrations/ky_sos/tests/test_mappers.py
git commit -m "feat(ky): add Candidate Filings field mappers"
```

---

### Task 5: client.py — HTTP client

**Files:**
- Create: `backend/integrations/ky_sos/client.py`
- Create: `backend/integrations/ky_sos/tests/test_client.py`

**Interfaces:**
- Consumes: `KySosRetryableError` from `integrations.ky_sos.exceptions` (Task 1).
- Produces:
  - `class KentuckySosClient` with `fetch_directory() -> str` and
    `fetch_office(office_id: int) -> str` and `fetch_withdrawn() -> str`

- [ ] **Step 1: Write the failing tests**

`backend/integrations/ky_sos/tests/test_client.py`:
```python
from unittest.mock import Mock, patch

import pytest
import requests

from integrations.ky_sos.client import KentuckySosClient
from integrations.ky_sos.exceptions import KySosRetryableError


def _mock_response(status_code=200, text="<html></html>"):
    resp = Mock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = Mock()
    return resp


def test_fetch_directory_gets_root_url():
    client = KentuckySosClient()
    with patch.object(client._session, "get", return_value=_mock_response(text="<html>dir</html>")) as mock_get:
        html = client.fetch_directory()
    assert html == "<html>dir</html>"
    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == "https://web.sos.ky.gov/CandidateFilings/"


def test_fetch_office_builds_id_query_param():
    client = KentuckySosClient()
    with patch.object(client._session, "get", return_value=_mock_response(text="<html>office</html>")) as mock_get:
        html = client.fetch_office(4)
    assert html == "<html>office</html>"
    assert mock_get.call_args[0][0] == "https://web.sos.ky.gov/CandidateFilings/Default.aspx?id=4"


def test_fetch_withdrawn_builds_withdrawn_query_param():
    client = KentuckySosClient()
    with patch.object(client._session, "get", return_value=_mock_response(text="<html>wdd</html>")) as mock_get:
        html = client.fetch_withdrawn()
    assert html == "<html>wdd</html>"
    assert mock_get.call_args[0][0] == "https://web.sos.ky.gov/CandidateFilings/Default.aspx?withdrawn=1"


def test_retries_then_raises_on_persistent_5xx():
    client = KentuckySosClient(max_retries=1)
    with patch.object(client._session, "get", return_value=_mock_response(status_code=500)):
        with pytest.raises(KySosRetryableError):
            client.fetch_directory()


def test_retries_then_raises_on_connection_error():
    client = KentuckySosClient(max_retries=1)
    with patch.object(client._session, "get", side_effect=requests.ConnectionError("boom")):
        with pytest.raises(KySosRetryableError):
            client.fetch_directory()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest --no-migrations integrations/ky_sos/tests/test_client.py -v`
Expected: `ModuleNotFoundError: No module named 'integrations.ky_sos.client'`

- [ ] **Step 3: Write client.py**

`backend/integrations/ky_sos/client.py`:
```python
"""
Kentucky SOS Candidate Filings HTTP client (web.sos.ky.gov/CandidateFilings/).

Plain GET requests, no authentication, no ASP.NET postback needed — office
groups and the withdrawn list are addressable by query string
(Default.aspx?id=N / Default.aspx?withdrawn=1). Confirmed live 2026-07-14; no
bot protection observed on this host (unlike vrsws.sos.ky.gov's live-results
system, which is explicitly out of scope for this adapter).
"""
from __future__ import annotations

import logging

import requests

from .exceptions import KySosRetryableError

logger = logging.getLogger(__name__)

BASE_URL = "https://web.sos.ky.gov/CandidateFilings"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_RETRYABLE_STATUSES = {403, 429, 500, 502, 503, 504}


class KentuckySosClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _get(self, url: str) -> str:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise KySosRetryableError(f"KY SOS GET failed: {exc}") from exc
                logger.warning("ky_sos.client.retry attempt=%d url=%s err=%s", attempt, url, exc)
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise KySosRetryableError(f"KY SOS returned {resp.status_code} for {url}")
                logger.warning(
                    "ky_sos.client.retry attempt=%d url=%s status=%d",
                    attempt, url, resp.status_code,
                )
                continue
            resp.raise_for_status()
            return resp.text
        raise KySosRetryableError("KY SOS request retries exhausted")

    def fetch_directory(self) -> str:
        return self._get(f"{BASE_URL}/")

    def fetch_office(self, office_id: int) -> str:
        return self._get(f"{BASE_URL}/Default.aspx?id={office_id}")

    def fetch_withdrawn(self) -> str:
        return self._get(f"{BASE_URL}/Default.aspx?withdrawn=1")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest --no-migrations integrations/ky_sos/tests/test_client.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ky_sos/client.py backend/integrations/ky_sos/tests/test_client.py
git commit -m "feat(ky): add Candidate Filings HTTP client"
```

---

### Task 6: tasks.py — sync_ky_sos Celery task

**Files:**
- Create: `backend/integrations/ky_sos/tasks.py`
- Create: `backend/integrations/ky_sos/tests/test_tasks.py`

**Interfaces:**
- Consumes: `KentuckySosClient` (Task 5), `parse_current_election` / `parse_office_directory` /
  `parse_candidate_rows` (Task 3), `IN_SCOPE_OFFICE_IDS` / `map_election` / `map_race` /
  `map_candidate` (Task 4), `KySosRetryableError` (Task 1), `aggregation.ingest.ingest_election` /
  `ingest_race` / `ingest_candidate` (existing).
- Produces: `sync_ky_sos` — a `@shared_task`, importable as
  `integrations.ky_sos.tasks.sync_ky_sos`, callable with no arguments, returns
  `{"created": int, "updated": int}`.

- [ ] **Step 1: Write the failing tests**

`backend/integrations/ky_sos/tests/test_tasks.py`:
```python
import os
from unittest.mock import patch

import pytest

from elections.models import Candidate, Election, Race
from integrations.ky_sos.tasks import sync_ky_sos

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


@pytest.mark.django_db
def test_sync_ky_sos_creates_election_races_and_candidates():
    directory_html = _load_fixture("office_directory.html")
    senator_html = _load_fixture("office_us_senator.html")
    rep_html = _load_fixture("office_us_representative.html")
    withdrawn_html = _load_fixture("withdrawn.html")

    def fake_fetch_office(office_id):
        return {3: senator_html, 4: rep_html}.get(office_id, "<html></html>")

    with patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_directory",
        return_value=directory_html,
    ), patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_office",
        side_effect=fake_fetch_office,
    ), patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_withdrawn",
        return_value=withdrawn_html,
    ):
        result = sync_ky_sos()

    election = Election.objects.get(state="KY")
    assert election.election_type == "general"
    assert election.election_date.isoformat() == "2026-11-03"

    # US Senator: statewide race, 4 candidates (from fixture)
    senator_race = Race.objects.get(election=election, office_title="US Senator")
    assert senator_race.candidates.count() == 4
    assert senator_race.source == Race.Source.KY_SOS

    # US Representative: 6 district races from the 21-row fixture
    rep_races = Race.objects.filter(election=election, office_title__startswith="US Representative")
    assert rep_races.count() == 6

    # State Senator / State Representative office ids (11, 12) weren't mocked
    # with real fixtures above, so they fetch "<html></html>" and parse to
    # zero rows/races — that's fine, this test only asserts the two mocked
    # groups landed correctly.

    # Withdrawn candidate ingested with WITHDRAWN status on its own race.
    withdrawn_candidate = Candidate.objects.get(name="Alisha Dawn Chaffin")
    assert withdrawn_candidate.candidate_status == Candidate.CandidateStatus.WITHDRAWN
    assert withdrawn_candidate.race.office_title == "State Representative District 88th"

    assert result["created"] > 0


@pytest.mark.django_db
def test_sync_ky_sos_is_idempotent_on_rerun():
    directory_html = _load_fixture("office_directory.html")
    senator_html = _load_fixture("office_us_senator.html")

    with patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_directory",
        return_value=directory_html,
    ), patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_office",
        return_value=senator_html,
    ), patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_withdrawn",
        return_value="<html></html>",
    ):
        sync_ky_sos()
        second_result = sync_ky_sos()

    # Second run should update existing rows, not duplicate them.
    assert Election.objects.filter(state="KY").count() == 1
    assert second_result["created"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest --no-migrations integrations/ky_sos/tests/test_tasks.py -v`
Expected: `ModuleNotFoundError: No module named 'integrations.ky_sos.tasks'`

- [ ] **Step 3: Write tasks.py**

`backend/integrations/ky_sos/tasks.py`:
```python
"""
Kentucky SOS Candidate Filings Celery task.

Stage 1 — sync_ky_sos:
  Fetch the Candidate Filings directory page (gets both the current election
  label and the office-group directory in one request). Derive the Election
  record from the statutory general-election date formula + that label. Sweep
  the four in-scope office-group pages (US Senator, US Representative, State
  Senator, State Representative) plus the Withdrawn/Deceased/Disqualified
  group, upserting Race + Candidate rows for each.

See docs/superpowers/plans/2026-07-14-ky-sos-adapter.md for why this is a
single task rather than split election/candidate tasks like il_sbe, and why
there's no separate "Upcoming Election Summary" client call.
"""
import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Candidate
from ops.models import SyncLog

from .client import KentuckySosClient
from .exceptions import KySosRetryableError
from .mappers import IN_SCOPE_OFFICE_IDS, map_candidate, map_election, map_race
from .parsers import parse_candidate_rows, parse_current_election, parse_office_directory

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ky_sos(self):
    sync_log = SyncLog.objects.create(
        source="ky_sos",
        task_name="sync_ky_sos",
        status=SyncLog.Status.STARTED,
    )
    client = KentuckySosClient()
    created_count = updated_count = 0

    try:
        from aggregation import ingest

        directory_html = client.fetch_directory()
        current_election = parse_current_election(directory_html)
        offices = parse_office_directory(directory_html)

        mapped_election = map_election(current_election["label"])
        source_id = mapped_election.pop("source_id")
        identity = {
            "state": mapped_election["state"],
            "election_type": mapped_election["election_type"],
            "election_date": mapped_election["election_date"],
            "jurisdiction_level": mapped_election["jurisdiction_level"],
        }
        fields = {k: v for k, v in mapped_election.items() if k not in identity}
        election_obj, _ = ingest.ingest_election(
            source="ky_sos", source_id=source_id, identity=identity, fields=fields,
        )

        for office in offices:
            if office["office_id"] not in IN_SCOPE_OFFICE_IDS:
                continue

            office_html = client.fetch_office(office["office_id"])
            rows = parse_candidate_rows(office_html)

            for row in rows:
                race_defaults = map_race(row["office"], row["district"])
                race_identity = {
                    "office_title": race_defaults.pop("office_title"),
                    "ocd_division_id": race_defaults.pop("ocd_division_id", "") or "",
                    "race_type": race_defaults.pop("race_type"),
                }
                race_defaults.pop("source", None)
                race_obj, race_created = ingest.ingest_race(
                    election=election_obj, source="ky_sos",
                    identity=race_identity, fields=race_defaults,
                )
                created_count += int(race_created)
                updated_count += int(not race_created)

                name, party, cand_fields = map_candidate(row, Candidate.CandidateStatus.RUNNING)
                _, cand_created = ingest.ingest_candidate(
                    race=race_obj, source="ky_sos", name=name, party=party, fields=cand_fields,
                )
                created_count += int(cand_created)
                updated_count += int(not cand_created)

        withdrawn_html = client.fetch_withdrawn()
        for row in parse_candidate_rows(withdrawn_html):
            race_defaults = map_race(row["office"], row["district"])
            race_identity = {
                "office_title": race_defaults.pop("office_title"),
                "ocd_division_id": race_defaults.pop("ocd_division_id", "") or "",
                "race_type": race_defaults.pop("race_type"),
            }
            race_defaults.pop("source", None)
            race_obj, race_created = ingest.ingest_race(
                election=election_obj, source="ky_sos",
                identity=race_identity, fields=race_defaults,
            )
            created_count += int(race_created)
            updated_count += int(not race_created)

            name, party, cand_fields = map_candidate(row, Candidate.CandidateStatus.WITHDRAWN)
            _, cand_created = ingest.ingest_candidate(
                race=race_obj, source="ky_sos", name=name, party=party, fields=cand_fields,
            )
            created_count += int(cand_created)
            updated_count += int(not cand_created)

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "status", "completed_at",
        ])
        return {"created": created_count, "updated": updated_count}

    except KySosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("ky_sos.sync_ky_sos.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest --no-migrations integrations/ky_sos/tests/test_tasks.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ky_sos/tasks.py backend/integrations/ky_sos/tests/test_tasks.py
git commit -m "feat(ky): add sync_ky_sos Celery task"
```

---

### Task 7: Internal scheduler wiring

**Files:**
- Modify: `backend/internal/task_locks.py` (add `"sync_ky_sos"` to `TASK_LOCKS`)
- Modify: `backend/internal/views.py` (import + `sync_ky_sos_trigger`)
- Modify: `backend/internal/urls.py` (add the route)

**Interfaces:**
- Consumes: `sync_ky_sos` (Task 6).
- Produces: `POST /internal/tasks/sync-ky-sos/` endpoint, name `internal-sync-ky-sos`.

- [ ] **Step 1: Register the lock**

In `backend/internal/task_locks.py`, add to `TASK_LOCKS` (after the `sync_or_sos` line):
```python
    "sync_or_sos":          (WINDOW_DAILY,      23 * _HOUR),
    "sync_ky_sos":          (WINDOW_DAILY,      23 * _HOUR),
```

- [ ] **Step 2: Add the trigger view**

In `backend/internal/views.py`, add the import (alphabetically among the existing
`from integrations....tasks import ...` block, after the `il_sbe` import):
```python
from integrations.ky_sos.tasks import sync_ky_sos
```

Add the view function after `sync_or_sos_trigger` (end of file):
```python
@csrf_exempt
@require_POST
@require_internal_task_token
def sync_ky_sos_trigger(request):
    return _trigger("sync_ky_sos", sync_ky_sos, request)
```

- [ ] **Step 3: Add the URL route**

In `backend/internal/urls.py`, add after the `sync-or-sos` line:
```python
    path("tasks/sync-ky-sos/", views.sync_ky_sos_trigger, name="internal-sync-ky-sos"),
```

- [ ] **Step 4: Run the self-enforcing registry test**

Run: `cd backend && pytest --no-migrations internal/tests/test_clear_task_locks.py -v`
Expected: all pass, including `test_registry_covers_every_triggered_task` (this test fails if
`TASK_LOCKS` and the `_trigger(...)` calls in `views.py` ever drift apart — it's the regression
guard for exactly the kind of wiring done in this task).

- [ ] **Step 5: Run Django system checks**

Run: `cd backend && python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 6: Commit**

```bash
git add backend/internal/task_locks.py backend/internal/views.py backend/internal/urls.py
git commit -m "feat(ky): wire sync_ky_sos into the internal scheduler trigger"
```

---

### Task 8: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full ky_sos test suite**

Run: `cd backend && pytest --no-migrations integrations/ky_sos/ -v`
Expected: all tests pass (parsers, mappers, client, tasks — ~19 tests total across Tasks 3-6).

- [ ] **Step 2: Run the full backend test suite to check for regressions**

Run: `cd backend && pytest --no-migrations -q`
Expected: no new failures relative to the pre-branch baseline (existing failures, if any, are
pre-existing and out of scope for this PR).

- [ ] **Step 3: Update the phase-3 progress memory**

This isn't a code step — after this plan lands, update the
`phase-3-state-expansion-progress` memory file
(`/home/midnight/.claude/projects/-data-Projects-CivicMirror-CivicMirror-API/memory/phase-3-state-expansion-progress.md`)
to record that KY Stage 1 (KY-Elections + KY-Candidates, federal + state-legislative scope) has
shipped, and that KY-Ballots / KY-Measures / KY-ResultsCertified / KY-ResultsLive remain
follow-up work per the design spec's "Follow-up work" section.

- [ ] **Step 4: Final commit check**

Run: `git log --oneline main..ky-sos-adapter` and `git status` to confirm all planned commits
landed cleanly and the working tree is clean.
