# CM2 MA Pilot — Plan 1: Election Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `cm2_ma` Django app and its first working slice — parsing Massachusetts's regular and special election calendars (both behind Incapsula) into `ElectionRecord` tuples, ready for a later plan to persist via `apply_pre_election_batch`.

**Architecture:** Mirrors `cm2_nc`'s module layout exactly (`constants.py`, `sources/`, `tests/fixtures/`). The one new piece NC didn't need is `sources/solver.py`, a `MaSolverBytesSource` base class wrapping the existing production `CfSolverClient.fetch_through_cf()` (from `core/cf_solver.py`) instead of a plain `requests.get()`, since every `sec.state.ma.us` page is Incapsula-blocked. Two independent parsers sit on top of it: one for the flat regular-election calendar, one for the special-elections two-hop crawl (index page → per-special calendar page). This plan does not touch persistence — it stops at producing typed, tested `ElectionRecord` tuples, matching how NC's own `parse_upcoming_elections()` is a pure function with no DB writes. Wiring these into `apply_pre_election_batch` alongside candidates happens in Plan 3.

**Tech Stack:** Django 5 / Python 3.13, `beautifulsoup4` (already a project dependency, used by `cm2_nc`), pytest, the existing `core.cf_solver.CfSolverClient`.

**Spec:** `docs/superpowers/specs/2026-08-17-cm2-ma-pilot-design.md`

## Global Constraints

- Python 3.13 runtime only (project requires `>=3.13,<3.14`; do not add code that only works under a different interpreter).
- `core/cf_solver.py` (the `CfSolverClient` class) must not be modified — it is live CM1 production infrastructure shared with `oh_sos`/`ny_boe`/`mi_sos`. Only *use* it from `cm2_ma`.
- No changes to `cloudflare/cf-solver/app.py`, `docker-compose.yml`, or any `CF_SOLVER_*` env var — that generalization work is already done and committed (`31ee044`) and is out of scope for this plan.
- Follow the existing `cm2_nc` app's structure and naming conventions exactly where MA's shape matches NC's (app config, constants module, `sources/` package, `tests/fixtures/` for HTML fixtures) — this is a second implementation of an established pattern, not a place to invent a new one.
- Contracts (`cm2_ingestion.contracts.ElectionRecord`, etc.) are shared and must not be modified by this plan.
- All new tests must run under `pytest --no-migrations` (per project convention for the isolated CM2 test DB).

---

## File Structure

```
backend/cm2_ma/
  __init__.py
  apps.py
  constants.py
  sources/
    __init__.py
    solver.py                    # MaSolverBytesSource base class
    upcoming_elections.py        # regular-election parser + source class
    special_elections.py         # special-election index + calendar parsers + source classes
  tests/
    __init__.py
    fixtures/
      upcoming_elections_2026.html
      special_elections_index.html
      special_election_calendar.html
    test_solver.py
    test_upcoming_elections.py
    test_special_elections.py

backend/config/settings/v2.py    # register "cm2_ma" app + add "MA" to enabled states
```

---

### Task 1: `cm2_ma` app scaffolding

**Files:**
- Create: `backend/cm2_ma/__init__.py`
- Create: `backend/cm2_ma/apps.py`
- Create: `backend/cm2_ma/constants.py`
- Modify: `backend/config/settings/v2.py`

**Interfaces:**
- Produces: `cm2_ma.constants.{SOURCE_SYSTEM, SEC_BASE_URL, UPCOMING_ELECTIONS_URL, SPECIAL_ELECTIONS_INDEX_URL, SOURCE_TIMEOUT_SECONDS, SOLVER_WAIT_SECONDS, UPCOMING_PARSER_VERSION, SPECIAL_INDEX_PARSER_VERSION, SPECIAL_CALENDAR_PARSER_VERSION}` — consumed by every later task in this plan and by Plans 2-4.

This task has no unit-testable behavior of its own (it's Django app registration), so it's verified with `manage.py check` instead of pytest, per Django app-scaffolding convention already used by `cm2_nc`.

- [ ] **Step 1: Create the app package**

`backend/cm2_ma/__init__.py`:
```python
```
(empty, matching `cm2_nc/__init__.py`)

`backend/cm2_ma/apps.py`:
```python
from django.apps import AppConfig


class Cm2MaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cm2_ma"
    verbose_name = "CivicMirror 2.0 Massachusetts"
```

- [ ] **Step 2: Write constants**

`backend/cm2_ma/constants.py`:
```python
SOURCE_SYSTEM = "ma_sos"
SEC_BASE_URL = "https://www.sec.state.ma.us"
UPCOMING_ELECTIONS_URL = (
    f"{SEC_BASE_URL}/divisions/elections/recent-updates/upcoming-elections.htm"
)
SPECIAL_ELECTIONS_INDEX_URL = (
    f"{SEC_BASE_URL}/divisions/elections/recent-updates/special-elections.htm"
)

# sec.state.ma.us is Incapsula-blocked; every fetch of it goes through the
# shared cloudflare/cf-solver/ nodriver service (core.cf_solver.CfSolverClient),
# which needs a longer timeout than a plain HTTP GET — solves typically take
# ~25-30s. See docs/superpowers/specs/2026-08-17-cm2-ma-pilot-design.md.
SOURCE_TIMEOUT_SECONDS = 90
SOLVER_WAIT_SECONDS = 25

UPCOMING_PARSER_VERSION = "ma-upcoming-v1"
SPECIAL_INDEX_PARSER_VERSION = "ma-special-index-v1"
SPECIAL_CALENDAR_PARSER_VERSION = "ma-special-calendar-v1"
```

- [ ] **Step 3: Register the app and enabled state**

In `backend/config/settings/v2.py`, after the existing `INSTALLED_APPS.append("cm2_nc")` line (line 34):
```python
INSTALLED_APPS.append("cm2_nc")
INSTALLED_APPS.append("cm2_ma")
```

And change line 190 from:
```python
CIVICMIRROR_V2_ENABLED_STATES = ("NC",)
```
to:
```python
CIVICMIRROR_V2_ENABLED_STATES = ("NC", "MA")
```

- [ ] **Step 4: Verify with Django's system check**

Run: `cd backend && python manage.py check --settings=config.settings.v2`
Expected: `System check identified no issues (0 silenced).`

If this fails with a Python version error, confirm you're using the project's `.venv` (Python 3.13), not a system Python — see Global Constraints.

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ma/__init__.py backend/cm2_ma/apps.py backend/cm2_ma/constants.py backend/config/settings/v2.py
git commit -m "feat(cm2_ma): scaffold app and register in v2 settings"
```

---

### Task 2: Solver-backed source base class

**Files:**
- Create: `backend/cm2_ma/sources/__init__.py`
- Create: `backend/cm2_ma/sources/solver.py`
- Test: `backend/cm2_ma/tests/__init__.py`
- Test: `backend/cm2_ma/tests/test_solver.py`

**Interfaces:**
- Consumes: `core.cf_solver.CfSolverClient` — specifically `fetch_through_cf(self, solve_url: str, payload_url: str, payload_referer: str | None = None) -> str` (already exists, unmodified — see `backend/core/cf_solver.py`).
- Produces: `cm2_ma.sources.solver.MaSolverBytesSource` — a base class with class attribute `url: str = ""`, constructor `__init__(self, *, client=None)`, and method `acquire(self) -> bytes`. Later tasks in this plan subclass it and set `url`.

- [ ] **Step 1: Write the failing test**

`backend/cm2_ma/tests/__init__.py`:
```python
```
(empty, matching `cm2_nc/tests/__init__.py`)

`backend/cm2_ma/tests/test_solver.py`:
```python
from cm2_ma.constants import SOLVER_WAIT_SECONDS
from cm2_ma.sources.solver import MaSolverBytesSource


class FakeSolverClient:
    def __init__(self, text: str):
        self.text = text
        self.calls = []

    def fetch_through_cf(self, solve_url, payload_url, payload_referer=None):
        self.calls.append((solve_url, payload_url, payload_referer))
        return self.text


def test_acquire_solves_and_fetches_same_url_and_encodes_to_bytes():
    client = FakeSolverClient("<html>hello</html>")
    source = MaSolverBytesSource(client=client)
    source.url = "https://www.sec.state.ma.us/example.htm"

    result = source.acquire()

    assert result == b"<html>hello</html>"
    assert client.calls == [
        ("https://www.sec.state.ma.us/example.htm", "https://www.sec.state.ma.us/example.htm", None)
    ]


def test_default_client_uses_configured_wait_seconds(monkeypatch):
    captured = {}

    class RecordingCfSolverClient:
        def __init__(self, wait_seconds):
            captured["wait_seconds"] = wait_seconds

    monkeypatch.setattr("cm2_ma.sources.solver.CfSolverClient", RecordingCfSolverClient)

    MaSolverBytesSource()

    assert captured["wait_seconds"] == SOLVER_WAIT_SECONDS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest cm2_ma/tests/test_solver.py -v --no-migrations`
Expected: FAIL — `ModuleNotFoundError: No module named 'cm2_ma.sources'`

- [ ] **Step 3: Write minimal implementation**

`backend/cm2_ma/sources/__init__.py`:
```python
```
(empty, matching `cm2_nc/sources/__init__.py`)

`backend/cm2_ma/sources/solver.py`:
```python
from core.cf_solver import CfSolverClient

from cm2_ma.constants import SOLVER_WAIT_SECONDS, SOURCE_SYSTEM


class MaSolverBytesSource:
    """
    Base class for cm2_ma sources that must go through the shared cf-solver
    microservice because sec.state.ma.us is Incapsula-blocked. Mirrors
    cm2_nc.sources.http.NcPublicBytesSource's role (plain-HTTP fetch), but
    solves the challenge and fetches the payload in-browser via
    CfSolverClient.fetch_through_cf() instead of a direct requests.get().
    """

    source_system = SOURCE_SYSTEM
    url = ""

    def __init__(self, *, client=None):
        self._client = client or CfSolverClient(wait_seconds=SOLVER_WAIT_SECONDS)

    def acquire(self) -> bytes:
        text = self._client.fetch_through_cf(solve_url=self.url, payload_url=self.url)
        return text.encode("utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest cm2_ma/tests/test_solver.py -v --no-migrations`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ma/sources/__init__.py backend/cm2_ma/sources/solver.py backend/cm2_ma/tests/__init__.py backend/cm2_ma/tests/test_solver.py
git commit -m "feat(cm2_ma): add solver-backed source base class"
```

---

### Task 3: Regular election calendar parser

**Files:**
- Create: `backend/cm2_ma/sources/upcoming_elections.py`
- Create: `backend/cm2_ma/tests/fixtures/upcoming_elections_2026.html`
- Test: `backend/cm2_ma/tests/test_upcoming_elections.py`

**Interfaces:**
- Consumes: `cm2_ma.sources.solver.MaSolverBytesSource`, `cm2_ma.constants.{UPCOMING_ELECTIONS_URL, UPCOMING_PARSER_VERSION}`, `cm2_ingestion.contracts.ElectionRecord`.
- Produces: `cm2_ma.sources.upcoming_elections.parse_upcoming_elections(content: bytes, *, source_artifact_public_id: str | None = None) -> tuple[ElectionRecord, ...]` and `cm2_ma.sources.upcoming_elections.NcUpcomingElectionsSource`... — named `MaUpcomingElectionsSource(MaSolverBytesSource)` with `url = UPCOMING_ELECTIONS_URL` and a `.parse(content) -> tuple[ElectionRecord, ...]` method. Consumed by Plan 3's batch builder.

**Important divergence from NC's parser** (confirmed against live-fetched markup, see spec's Solver verification section): NC's heading date lives in *sibling* text after the `<h2>` (e.g. `<h2>Statewide Primary Election</h2><p>...March 3, 2026...</p>`). MA's date is *inside* the heading text itself, separated from the label by an en dash: `<h2>September 1, 2026 – State Primaries</h2>`. This parser therefore searches the heading text itself for the date and splits off the label after the dash, rather than walking sibling elements.

- [ ] **Step 1: Write the failing test**

`backend/cm2_ma/tests/fixtures/upcoming_elections_2026.html`:
```html
<!doctype html>
<html lang="en">
  <body>
    <main id="main-content">
      <h1>Upcoming Elections</h1>
      <article>
        <h2>September 1, 2026 – State Primaries</h2>
        <p style="margin-top:15px;"><b>District:</b><br>
        Statewide</p>
        <p style="margin-top:-5px;"><b>Offices on Ballot:</b></p>
        <ul style="margin-top:-10px;">
          <li>U.S. Senator</li>
          <li>Governor</li>
        </ul>
        <p style="margin-top:-5px;"><b>Voter Registration Deadline:</b><br>
        August 22</p>

        <h2>November 3, 2026 – State Election</h2>
        <p style="margin-top:15px;"><b>District:</b><br>
        Statewide</p>
        <p style="margin-top:-5px;"><b>Offices on Ballot:</b></p>
        <ul style="margin-top:-10px;">
          <li>U.S. Senator</li>
          <li>Governor</li>
        </ul>
      </article>
    </main>
  </body>
</html>
```

`backend/cm2_ma/tests/test_upcoming_elections.py`:
```python
from datetime import date
from pathlib import Path

from cm2_ma.constants import UPCOMING_ELECTIONS_URL
from cm2_ma.sources.upcoming_elections import MaUpcomingElectionsSource, parse_upcoming_elections

FIXTURES = Path(__file__).parent / "fixtures"


def test_parses_date_embedded_in_heading_and_splits_label():
    records = parse_upcoming_elections(
        (FIXTURES / "upcoming_elections_2026.html").read_bytes(),
        source_artifact_public_id="artifact/ma-upcoming-2026",
    )

    assert [(record.name, record.election_date, record.election_type) for record in records] == [
        ("State Primaries", date(2026, 9, 1), "primary"),
        ("State Election", date(2026, 11, 3), "general"),
    ]
    assert {record.source_artifact_public_id for record in records} == {"artifact/ma-upcoming-2026"}
    assert all(record.lifecycle_status == "upcoming" for record in records)


def test_headings_without_a_recognized_type_default_to_other():
    content = b"<h2>March 3, 2026 \xe2\x80\x93 Municipal Preliminary</h2><p>text</p>"

    records = parse_upcoming_elections(content)

    assert len(records) == 1
    assert records[0].election_type == "other"


def test_headings_without_a_parseable_date_are_skipped():
    content = b"<h2>Voter Dates and Deadlines</h2><ul><li>No date here</li></ul>"

    records = parse_upcoming_elections(content)

    assert records == ()


def test_source_url_and_parse_delegate_correctly():
    source = MaUpcomingElectionsSource()
    assert source.url == UPCOMING_ELECTIONS_URL

    records = source.parse((FIXTURES / "upcoming_elections_2026.html").read_bytes())
    assert len(records) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest cm2_ma/tests/test_upcoming_elections.py -v --no-migrations`
Expected: FAIL — `ModuleNotFoundError: No module named 'cm2_ma.sources.upcoming_elections'`

- [ ] **Step 3: Write minimal implementation**

`backend/cm2_ma/sources/upcoming_elections.py`:
```python
import hashlib
import re
from datetime import date

from bs4 import BeautifulSoup

from cm2_ingestion.contracts import ElectionRecord
from cm2_ma.constants import UPCOMING_ELECTIONS_URL

from .solver import MaSolverBytesSource

_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Sept\.?|Oct\.?|Nov\.?|Dec\.?)"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?,\s+(\d{4})\b",
    re.IGNORECASE,
)
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
# The separator between the date and the label in a MA upcoming-elections
# heading, e.g. "September 1, 2026 – State Primaries". Handles both the
# en dash the live site uses and a plain hyphen, defensively.
_LABEL_SEPARATOR_RE = re.compile(r"[–—-]")

_LABEL_TYPE_MAP = (
    ("state primaries", "primary"),
    ("state primary", "primary"),
    ("state election", "general"),
    ("special primary", "special_primary"),
    ("special election", "special_general"),
)


def _parse_date(text: str) -> date | None:
    match = _DATE_RE.search(text)
    if not match:
        return None
    month_label, day, year = match.groups()
    month = _MONTHS[month_label.casefold().rstrip(".")]
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def _election_type(label: str) -> str:
    normalized = " ".join(label.casefold().split())
    for key, value in _LABEL_TYPE_MAP:
        if key in normalized:
            return value
    return "other"


def _split_heading(heading_text: str) -> tuple[date | None, str]:
    """
    MA upcoming-elections headings embed the date in the heading text itself
    (unlike NC, where the date is in sibling content) e.g.
    "September 1, 2026 – State Primaries". Returns (date, label) with the
    label being whatever follows the date/separator, or the full heading text
    if no date was found.
    """
    match = _DATE_RE.search(heading_text)
    if not match:
        return None, heading_text
    election_date = _parse_date(heading_text)
    remainder = heading_text[match.end():]
    remainder = _LABEL_SEPARATOR_RE.sub("", remainder, count=1).strip()
    return election_date, remainder or heading_text


def _election_public_id(*, election_date: date, election_type: str, label: str) -> str:
    normalized_label = " ".join(label.casefold().split())
    digest = hashlib.sha256(normalized_label.encode()).hexdigest()[:12]
    return f"ma/election/{election_date.isoformat()}/{election_type}/{digest}"


def parse_upcoming_elections(
    content: bytes,
    *,
    source_artifact_public_id: str | None = None,
) -> tuple[ElectionRecord, ...]:
    soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")
    records = []
    seen: set[tuple[date, str, str]] = set()
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        heading_text = " ".join(heading.get_text(" ", strip=True).split())
        election_date, label = _split_heading(heading_text)
        if election_date is None:
            continue
        election_type = _election_type(label)
        identity = (election_date, election_type, label.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        public_id = _election_public_id(
            election_date=election_date, election_type=election_type, label=label,
        )
        records.append(
            ElectionRecord(
                public_id=public_id,
                name=label,
                election_date=election_date,
                election_type=election_type,
                lifecycle_status="upcoming",
                source_key=f"upcoming:{election_date.isoformat()}:{public_id.rsplit('/', 1)[-1]}",
                source_artifact_public_id=source_artifact_public_id,
            )
        )
    return tuple(sorted(records, key=lambda record: (record.election_date, record.name)))


class MaUpcomingElectionsSource(MaSolverBytesSource):
    url = UPCOMING_ELECTIONS_URL

    def parse(self, content: bytes) -> tuple[ElectionRecord, ...]:
        return parse_upcoming_elections(content)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest cm2_ma/tests/test_upcoming_elections.py -v --no-migrations`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ma/sources/upcoming_elections.py backend/cm2_ma/tests/fixtures/upcoming_elections_2026.html backend/cm2_ma/tests/test_upcoming_elections.py
git commit -m "feat(cm2_ma): parse regular election calendar into ElectionRecords"
```

---

### Task 4: Special-elections index parser

**Files:**
- Create: `backend/cm2_ma/sources/special_elections.py`
- Create: `backend/cm2_ma/tests/fixtures/special_elections_index.html`
- Test: `backend/cm2_ma/tests/test_special_elections.py`

**Interfaces:**
- Consumes: `cm2_ma.sources.solver.MaSolverBytesSource`, `cm2_ma.constants.{SEC_BASE_URL, SPECIAL_ELECTIONS_INDEX_URL}`.
- Produces: `cm2_ma.sources.special_elections.parse_special_elections_index(content: bytes) -> tuple[str, ...]` (absolute calendar-page URLs, discovered dynamically — never hardcode a specific `current-special-electionN.htm` URL, since the live index showed these numbers shift as specials open/close) and `MaSpecialElectionsIndexSource(MaSolverBytesSource)` with `url = SPECIAL_ELECTIONS_INDEX_URL`. Consumed by Plan 3's orchestration to know which calendar pages to fetch next (Task 5 parses those).

- [ ] **Step 1: Write the failing test**

`backend/cm2_ma/tests/fixtures/special_elections_index.html`:
```html
<!doctype html>
<html lang="en">
  <body>
    <main id="main-content">
      <h1>Special Elections</h1>
      <p>
        5 - 6th Essex Representative District (to fill vacancy caused by the
        resignation of Representative Jerald A. Parisella)
        <a href="/divisions/elections/recent-updates/current-special-election7.htm">Election Calendar</a> |
        <a href="/divisions/elections/recent-updates/past-special-elections/2026-1st-middlesex-candidates.htm">Primary Candidates</a> |
        <a href="/divisions/elections/recent-updates/current-special-election7.htm">Special State Election Candidates</a>
      </p>
      <p>
        4 - 1st Middlesex Senate District (to fill vacancy caused by the
        resignation of Senator Someone Else)
        <a href="/divisions/elections/recent-updates/current-special-election6.htm">Election Calendar</a>
      </p>
      <h2>Past Special Elections Calendars and Results</h2>
      <p>
        <a href="/divisions/elections/recent-updates/past-special-elections/past-special-elections.htm">View past Special Elections calendars and results here</a>
      </p>
    </main>
  </body>
</html>
```

`backend/cm2_ma/tests/test_special_elections.py`:
```python
from pathlib import Path

from cm2_ma.constants import SPECIAL_ELECTIONS_INDEX_URL
from cm2_ma.sources.special_elections import (
    MaSpecialElectionsIndexSource,
    parse_special_elections_index,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_index_parser_returns_unique_absolute_calendar_urls_in_order():
    urls = parse_special_elections_index(
        (FIXTURES / "special_elections_index.html").read_bytes()
    )

    assert urls == (
        "https://www.sec.state.ma.us/divisions/elections/recent-updates/current-special-election6.htm",
        "https://www.sec.state.ma.us/divisions/elections/recent-updates/current-special-election7.htm",
    )


def test_index_parser_excludes_past_special_election_links():
    urls = parse_special_elections_index(
        (FIXTURES / "special_elections_index.html").read_bytes()
    )

    assert not any("past-special-elections" in url for url in urls)


def test_index_source_url_is_configured():
    assert MaSpecialElectionsIndexSource().url == SPECIAL_ELECTIONS_INDEX_URL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest cm2_ma/tests/test_special_elections.py -v --no-migrations`
Expected: FAIL — `ModuleNotFoundError: No module named 'cm2_ma.sources.special_elections'`

- [ ] **Step 3: Write minimal implementation**

`backend/cm2_ma/sources/special_elections.py`:
```python
import re

from bs4 import BeautifulSoup

from cm2_ma.constants import SEC_BASE_URL, SPECIAL_ELECTIONS_INDEX_URL

from .solver import MaSolverBytesSource

# Matches the Secretary's "current" special-election calendar pages, e.g.
# "/divisions/elections/recent-updates/current-special-election7.htm". These
# page numbers are not stable identifiers -- they shift as specials open and
# close (confirmed live: the same URL served a different special's calendar
# than the index page currently links to it under) -- so the index must
# always be crawled fresh rather than any specific URL being hardcoded.
_CURRENT_SPECIAL_HREF_RE = re.compile(
    r"^/divisions/elections/recent-updates/current-special-election\d+\.htm$"
)


def parse_special_elections_index(content: bytes) -> tuple[str, ...]:
    soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")
    seen: set[str] = set()
    hrefs: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if _CURRENT_SPECIAL_HREF_RE.match(href) and href not in seen:
            seen.add(href)
            hrefs.append(href)
    return tuple(f"{SEC_BASE_URL}{href}" for href in sorted(hrefs))


class MaSpecialElectionsIndexSource(MaSolverBytesSource):
    url = SPECIAL_ELECTIONS_INDEX_URL

    def parse(self, content: bytes) -> tuple[str, ...]:
        return parse_special_elections_index(content)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest cm2_ma/tests/test_special_elections.py -v --no-migrations`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ma/sources/special_elections.py backend/cm2_ma/tests/fixtures/special_elections_index.html backend/cm2_ma/tests/test_special_elections.py
git commit -m "feat(cm2_ma): parse special-elections index into calendar-page URLs"
```

---

### Task 5: Special-election calendar page parser

**Files:**
- Modify: `backend/cm2_ma/sources/special_elections.py`
- Create: `backend/cm2_ma/tests/fixtures/special_election_calendar.html`
- Modify: `backend/cm2_ma/tests/test_special_elections.py`

**Interfaces:**
- Consumes: `cm2_ma.sources.solver.MaSolverBytesSource`, `cm2_ingestion.contracts.ElectionRecord`.
- Produces: `cm2_ma.sources.special_elections.parse_special_election_calendar(content: bytes, *, source_artifact_public_id: str | None = None) -> tuple[ElectionRecord, ...]` and `MaSpecialElectionCalendarSource(MaSolverBytesSource)`, constructed with a specific `url` (from Task 4's discovered URLs) via `__init__(self, *, url: str, client=None)`. Consumed by Plan 3.

This is built directly against the real markup fetched live during design (see spec's Solver verification section): the office/district is in an `<h1>`, the vacancy reason is the first `<p>` *after* it (not a direct sibling — it's nested inside a following `<article>` wrapper, so the parser must search forward in document order, not just direct siblings), and the actual primary/general dates are `<tr><td>Month D, YYYY</td><td>State Primary</td></tr>` / `...<td>State Election</td></tr>` rows inside a `<table>` that also contains many other (irrelevant) deadline rows.

- [ ] **Step 1: Write the failing test**

`backend/cm2_ma/tests/fixtures/special_election_calendar.html`:
```html
<!doctype html>
<html lang="en">
  <body>
    <main id="main-content">
      <h1 style="border-bottom:none!important;">Special State Election<br>
      <strong>5th Essex Representative District</strong></h1>
      <article>
        <p style="margin-top:-20px;">(to fill vacancy caused by the death of Representative Ann-Margaret Ferrante)</p>

        <h2>Calendar</h2>
        <div class="table-scroll">
          <table>
            <tr>
              <td width="150"><p>October 28, 2025</p></td>
              <td><p>Last day for a person running in the State Primary to enroll in a party.</p></td>
            </tr>
            <tr>
              <td><p><strong>March 3, 2026</strong></p></td>
              <td><p><strong>State Primary</strong></p></td>
            </tr>
            <tr>
              <td><p>March 9, 2026</p></td>
              <td><p>Last day for filing withdrawals of nominations made at the State Primary.</p></td>
            </tr>
            <tr>
              <td><p><strong>March 31, 2026</strong></p></td>
              <td><p><strong>State Election</strong></p></td>
            </tr>
          </table>
        </div>
      </article>
    </main>
  </body>
</html>
```

Append to `backend/cm2_ma/tests/test_special_elections.py`:
```python
from datetime import date

from cm2_ma.sources.special_elections import (
    MaSpecialElectionCalendarSource,
    parse_special_election_calendar,
)


def test_calendar_parser_extracts_only_the_primary_and_general_rows():
    records = parse_special_election_calendar(
        (FIXTURES / "special_election_calendar.html").read_bytes(),
        source_artifact_public_id="artifact/ma-special-5th-essex",
    )

    assert [(record.election_date, record.election_type) for record in records] == [
        (date(2026, 3, 3), "special_primary"),
        (date(2026, 3, 31), "special_general"),
    ]
    assert all("5th Essex Representative District" in record.name for record in records)
    assert all(
        "death of Representative Ann-Margaret Ferrante" in record.name for record in records
    )
    assert {record.source_artifact_public_id for record in records} == {
        "artifact/ma-special-5th-essex"
    }


def test_calendar_parser_ignores_non_matching_deadline_rows():
    records = parse_special_election_calendar(
        (FIXTURES / "special_election_calendar.html").read_bytes()
    )

    assert len(records) == 2


def test_calendar_source_uses_constructor_provided_url():
    url = "https://www.sec.state.ma.us/divisions/elections/recent-updates/current-special-election7.htm"
    source = MaSpecialElectionCalendarSource(url=url)

    assert source.url == url

    records = source.parse((FIXTURES / "special_election_calendar.html").read_bytes())
    assert len(records) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest cm2_ma/tests/test_special_elections.py -v --no-migrations`
Expected: FAIL — `ImportError: cannot import name 'parse_special_election_calendar'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/cm2_ma/sources/special_elections.py` (add these imports to the top alongside the existing ones, then the new functions/classes at the bottom):

```python
import hashlib
from datetime import date

from cm2_ingestion.contracts import ElectionRecord

from .upcoming_elections import _parse_date
```

```python
_VACANCY_STRIP_RE = re.compile(r"^[()]+|[()]+$")


def _district_label(heading_text: str) -> str:
    stripped = re.sub(r"^Special State Election\s*", "", heading_text).strip()
    return stripped or heading_text


def _special_election_public_id(
    *, election_date: date, election_type: str, district_label: str
) -> str:
    normalized_label = " ".join(district_label.casefold().split())
    digest = hashlib.sha256(f"{election_type}|{normalized_label}".encode()).hexdigest()[:12]
    return f"ma/election/{election_date.isoformat()}/{election_type}/{digest}"


def parse_special_election_calendar(
    content: bytes,
    *,
    source_artifact_public_id: str | None = None,
) -> tuple[ElectionRecord, ...]:
    soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")
    heading = soup.find("h1")
    if heading is None:
        return ()

    heading_text = " ".join(heading.get_text(" ", strip=True).split())
    district_label = _district_label(heading_text)

    vacancy_paragraph = heading.find_next("p")
    vacancy_reason = ""
    if vacancy_paragraph is not None:
        vacancy_reason = _VACANCY_STRIP_RE.sub(
            "", vacancy_paragraph.get_text(" ", strip=True)
        ).strip()

    records = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != 2:
            continue
        date_text = cells[0].get_text(" ", strip=True)
        label_text = cells[1].get_text(" ", strip=True)
        election_date = _parse_date(date_text)
        if election_date is None:
            continue
        if label_text == "State Primary":
            election_type = "special_primary"
            type_label = "Special Primary"
        elif label_text == "State Election":
            election_type = "special_general"
            type_label = "Special Election"
        else:
            continue

        name = f"Massachusetts {type_label} — {district_label}"
        if vacancy_reason:
            name = f"{name} ({vacancy_reason})"

        public_id = _special_election_public_id(
            election_date=election_date,
            election_type=election_type,
            district_label=district_label,
        )
        records.append(
            ElectionRecord(
                public_id=public_id,
                name=name,
                election_date=election_date,
                election_type=election_type,
                lifecycle_status="upcoming",
                source_key=f"special:{election_date.isoformat()}:{public_id.rsplit('/', 1)[-1]}",
                source_artifact_public_id=source_artifact_public_id,
            )
        )
    return tuple(sorted(records, key=lambda record: (record.election_date, record.name)))


class MaSpecialElectionCalendarSource(MaSolverBytesSource):
    def __init__(self, *, url: str, client=None):
        super().__init__(client=client)
        self.url = url

    def parse(self, content: bytes) -> tuple[ElectionRecord, ...]:
        return parse_special_election_calendar(content)
```

Note: `_parse_date` is imported from `.upcoming_elections` rather than duplicated — both modules need the same "Month D, YYYY" text-to-`date` parsing, and `upcoming_elections.py` already defines it correctly (handles both full and abbreviated month names, optional ordinal suffixes).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest cm2_ma/tests/test_special_elections.py -v --no-migrations`
Expected: PASS (6 tests)

Then run the full plan's test suite together:
Run: `cd backend && pytest cm2_ma/ -v --no-migrations`
Expected: PASS (all tests from Tasks 2-5)

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ma/sources/special_elections.py backend/cm2_ma/tests/fixtures/special_election_calendar.html backend/cm2_ma/tests/test_special_elections.py
git commit -m "feat(cm2_ma): parse special-election calendar pages into ElectionRecords"
```

---

## Definition of done

- `python manage.py check --settings=config.settings.v2` passes.
- `pytest cm2_ma/ -v --no-migrations` passes (all tasks' tests, ~15 tests total).
- `ruff check backend/cm2_ma` passes (match `cm2_nc`'s lint-clean baseline).
- No changes outside `backend/cm2_ma/` and the single `INSTALLED_APPS`/`CIVICMIRROR_V2_ENABLED_STATES` edit in `backend/config/settings/v2.py`.
- `core/cf_solver.py` and `cloudflare/cf-solver/` are untouched (verify with `git diff --stat` before committing the final task).

## Next

Plan 2 (OCPF identity pool) and Plan 3 (Secretary candidate pages → `PreElectionBatch`, wiring in this plan's `ElectionRecord`s as `discovered_elections`) build on this plan's output but are not part of it.
