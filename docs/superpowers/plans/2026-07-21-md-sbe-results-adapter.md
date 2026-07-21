# Maryland (MD) SBE Certified Results Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship MD's Stage 2 (certified results) adapter for statewide offices, validated entirely against the historical Nov 5, 2024 general election, so MD reaches "Results Coverage Only" tier (same tier as NC/NY/CA) with races sourced from the Google Civic API.

**Architecture:** A new `integrations.md_sbe` Django app fetches Maryland SBE's per-county certified-results CSVs (`https://elections.maryland.gov/elections/archive/{year}/election_data/{cycle}{yy}_{county}CountyResults.csv`, one file per of the 24 jurisdictions) and parses each into candidate/office/vote-total rows. A new `results/adapters/md.py` `StateResultsAdapter` sums `Total Votes` for each `(office, candidate)` pair across all 24 county files — no precinct-level summing needed, since MD's county files are already county-aggregated — and emits `ResultRow`s via the existing generic `results.tasks.ingest_official_results` → `results.adapters.registry.get_adapter("MD")` flow. No new Celery task, internal endpoint, or `TASK_LOCKS` entry is needed for this scope: Stage 2-only adapters (like NC/CA/NY) are picked up automatically once `Race.source` covers this state's races (Civic API) and `Election.state == "MD"`.

**Tech Stack:** Django, `requests`, Python's stdlib `csv` module (same stack as the `il_sbe`/`nc_sbe` adapters this plan mirrors).

## Global Constraints

- **Statewide offices only, this build:** `President - Vice Pres` and `U.S. Senator` — the two statewide contests present in the Nov 5, 2024 general election data used for validation. Governor/Comptroller/Attorney General are on the gubernatorial-year cycle (2022/2026), not the presidential cycle used for this POC; adding them is a trivial follow-up once a gubernatorial-year fixture is available (2026 general, after certification). U.S. House (by congressional district), State Senate/House of Delegates (by legislative district), judicial retention, and ballot questions are explicitly out of scope for this plan — they need the separate `{cycle}{yy}_CongressionalBreakDown.csv` / `LegislativeBreakDown.csv` files and district-to-race mapping, which is follow-up work.
- **Historical POC only:** validate against the Nov 5, 2024 general election (`PG24` cycle prefix, files under `elections/archive/2024/election_data/`). Live discovery of the current cycle's prefix/year for future elections is out of scope — see "Follow-up work" below.
- **All CSV fixtures in this plan are real, live-captured data** from `https://elections.maryland.gov/elections/archive/2024/election_data/PG24_01CountyResults.csv` and `.../PG24_02CountyResults.csv`, fetched 2026-07-21. No synthetic/invented data.
- No live network calls in the test suite itself — all HTTP is mocked using the captured fixtures.
- Run tests with `pytest --no-migrations` (local test-DB creation breaks on an unrelated bad migration in this environment).
- Full research context: `docs/state-research/MD/MD-Election_Research.md`.

---

### Task 1: Scaffold the `integrations.md_sbe` Django app

**Files:**
- Create: `backend/integrations/md_sbe/__init__.py` (empty)
- Create: `backend/integrations/md_sbe/apps.py`
- Create: `backend/integrations/md_sbe/exceptions.py`
- Create: `backend/integrations/md_sbe/tests/__init__.py` (empty)
- Modify: `backend/config/settings/base.py`

**Interfaces:**
- Produces: `MdSbeError`, `MdSbeRetryableError` exception classes used by later tasks in this app.

- [ ] **Step 1: Create the app config**

```python
# backend/integrations/md_sbe/apps.py
from django.apps import AppConfig


class MarylandSbeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.md_sbe"
    label = "md_sbe"
    verbose_name = "Maryland SBE Integration"
```

- [ ] **Step 2: Create the exceptions module**

```python
# backend/integrations/md_sbe/exceptions.py
class MdSbeError(Exception):
    """Non-retryable Maryland SBE integration error."""


class MdSbeRetryableError(MdSbeError):
    """Transient error that warrants a retry (network/5xx)."""
```

- [ ] **Step 3: Create empty `__init__.py` files**

```bash
touch backend/integrations/md_sbe/__init__.py
mkdir -p backend/integrations/md_sbe/tests
touch backend/integrations/md_sbe/tests/__init__.py
```

- [ ] **Step 4: Register the app in settings**

In `backend/config/settings/base.py`, find this line in the `INSTALLED_APPS +=` block (line 172):

```python
    'integrations.al_sos',
    'internal',
```

Replace with:

```python
    'integrations.al_sos',
    'integrations.md_sbe',
    'internal',
```

- [ ] **Step 5: Verify Django can load the app**

Run: `cd backend && python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/md_sbe backend/config/settings/base.py
git commit -m "feat(md_sbe): scaffold integrations.md_sbe app"
```

---

### Task 2: `MdSbeClient` — fetch per-county certified results CSVs

**Files:**
- Create: `backend/integrations/md_sbe/client.py`
- Test: `backend/integrations/md_sbe/tests/test_client.py`

**Interfaces:**
- Consumes: `integrations.md_sbe.exceptions.MdSbeRetryableError` (Task 1).
- Produces: `MdSbeClient.fetch_county_results(year: int, cycle_prefix: str, county_code: str) -> str` — returns decoded CSV text. `MdSbeClient.COUNTY_CODES` — tuple of `"01"`..`"24"`, used by Task 4's aggregator to know how many files to fetch.

- [ ] **Step 1: Write the failing test**

```python
# backend/integrations/md_sbe/tests/test_client.py
from unittest.mock import MagicMock, patch

import pytest
import requests

from integrations.md_sbe.client import MdSbeClient
from integrations.md_sbe.exceptions import MdSbeRetryableError


def test_county_codes_span_01_through_24():
    assert MdSbeClient.COUNTY_CODES[0] == "01"
    assert MdSbeClient.COUNTY_CODES[-1] == "24"
    assert len(MdSbeClient.COUNTY_CODES) == 24


@patch("integrations.md_sbe.client.requests.Session.get")
def test_fetch_county_results_builds_expected_url_and_decodes_utf8_sig(mock_get):
    response = MagicMock(status_code=200)
    # utf-8-sig decoding must strip a BOM if present, and be a no-op if absent.
    response.content = "﻿Office Name,Total Votes\r\nU.S. Senator,100\r\n".encode("utf-8-sig")
    mock_get.return_value = response

    text = MdSbeClient().fetch_county_results(year=2024, cycle_prefix="PG", county_code="01")

    assert text == "Office Name,Total Votes\r\nU.S. Senator,100\r\n"
    called_url = mock_get.call_args[0][0]
    assert called_url == (
        "https://elections.maryland.gov/elections/archive/2024/election_data/"
        "PG24_01CountyResults.csv"
    )


@patch("integrations.md_sbe.client.requests.Session.get")
def test_fetch_county_results_treats_soft_404_as_retryable(mock_get):
    """MD SBE returns HTTP 200 with a ~14KB 'Page Not Found' HTML body for missing
    pages instead of a real 404 — must be detected by content, not status code."""
    response = MagicMock(status_code=200)
    response.content = ("<html><body>Page Not Found</body></html>" + "x" * 14400).encode("utf-8")
    mock_get.return_value = response

    with pytest.raises(MdSbeRetryableError):
        MdSbeClient().fetch_county_results(year=2024, cycle_prefix="PG", county_code="99")


@patch("integrations.md_sbe.client.requests.Session.get")
def test_fetch_county_results_raises_on_connection_error(mock_get):
    mock_get.side_effect = requests.ConnectionError("boom")

    with pytest.raises(MdSbeRetryableError):
        MdSbeClient().fetch_county_results(year=2024, cycle_prefix="PG", county_code="01")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest integrations/md_sbe/tests/test_client.py --no-migrations -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.md_sbe.client'`

- [ ] **Step 3: Write the implementation**

```python
# backend/integrations/md_sbe/client.py
from __future__ import annotations

import requests

from .exceptions import MdSbeRetryableError

_BASE_URL = "https://elections.maryland.gov"
_PAGE_NOT_FOUND_MARKER = "Page Not Found"


class MdSbeClient:
    """Fetches Maryland SBE's certified per-county results CSVs.

    MD SBE returns HTTP 200 with a "Page Not Found" HTML body (~14,424 bytes)
    for missing pages instead of a real 404 — every fetch here checks the
    response body for that marker rather than trusting the status code.
    """

    COUNTY_CODES: tuple[str, ...] = tuple(f"{i:02d}" for i in range(1, 25))

    def __init__(self):
        self.session = requests.Session()
        self.timeout = 15

    def fetch_county_results(self, year: int, cycle_prefix: str, county_code: str) -> str:
        url = (
            f"{_BASE_URL}/elections/archive/{year}/election_data/"
            f"{cycle_prefix}{year % 100:02d}_{county_code}CountyResults.csv"
        )
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise MdSbeRetryableError(f"MD SBE GET failed: {exc}") from exc

        # utf-8-sig strips a leading BOM if present, and is a no-op otherwise —
        # some MD SBE CSVs (candidate lists) are BOM-prefixed, county results
        # currently are not, so decode defensively either way.
        text = response.content.decode("utf-8-sig", errors="replace")

        if response.status_code != 200 or _PAGE_NOT_FOUND_MARKER in text:
            raise MdSbeRetryableError(
                f"MD SBE soft-404 or error for county={county_code} url={url}"
            )

        return text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest integrations/md_sbe/tests/test_client.py --no-migrations -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/md_sbe/client.py backend/integrations/md_sbe/tests/test_client.py
git commit -m "feat(md_sbe): add MdSbeClient for fetching county results CSVs"
```

---

### Task 3: Parser — `parse_county_results_csv`

**Files:**
- Create: `backend/integrations/md_sbe/parsers.py`
- Create: `backend/results/tests/fixtures/md_county01_us_senator.csv` (already captured — see below)
- Create: `backend/results/tests/fixtures/md_county02_us_senator.csv` (already captured — see below)
- Test: `backend/integrations/md_sbe/tests/test_parsers.py`

**Interfaces:**
- Produces: `parse_county_results_csv(csv_text: str) -> list[dict]`, where each dict has keys `office_name: str`, `candidate_name: str`, `party: str`, `is_winner: bool`, `is_write_in: bool`, `total_votes: int`. Consumed by Task 4's aggregator.

The two fixture files below are **already saved** at `backend/results/tests/fixtures/md_county01_us_senator.csv` and `md_county02_us_senator.csv` — real data captured live from `https://elections.maryland.gov/elections/archive/2024/election_data/PG24_01CountyResults.csv` and `PG24_02CountyResults.csv` on 2026-07-21 (trimmed to the `U.S. Senator` contest rows only). Their contents, for reference:

`md_county01_us_senator.csv`:
```csv
"Office Name","Office District","Candidate Name","Party","Winner","Write-In?","Early Votes","Early Votes Against","Election Night Votes","Election Night Votes Against","Mail-In Ballot 1 Votes","Mail-In Ballot 1 Votes Against","Provisional Votes","Provisional Votes Against","Mail-In Ballot 2 Votes","Mail-In Ballot 2 Votes Against","Total Votes","Total Votes Against"
"U.S. Senator","","Angela Alsobrooks","DEM","Y","","1486","","3089","","2251","","510","","60","","7396",""
"U.S. Senator","","Larry Hogan","REP","","","5040","","13222","","2671","","839","","39","","21811",""
"U.S. Senator","","Mike Scott","LIB","","","431","","1362","","217","","88","","2","","2100",""
"U.S. Senator","","Patrick J. Burke","OTC","","Y","5","","12","","0","","0","","0","","17",""
"U.S. Senator","","Billy Bridges","UNA","","Y","0","","1","","0","","0","","0","","1",""
"U.S. Senator","","Irwin William Gibbs","UNA","","Y","0","","0","","0","","0","","0","","0",""
"U.S. Senator","","Christy Renee Helmondollar","UNA","","Y","0","","0","","0","","0","","0","","0",""
"U.S. Senator","","Robin Rowe","UNA","","Y","0","","0","","0","","0","","0","","0",""
"U.S. Senator","","Other Write-Ins","","","Y","27","","42","","14","","2","","1","","86",""
```

`md_county02_us_senator.csv`:
```csv
"Office Name","Office District","Candidate Name","Party","Winner","Write-In?","Early Votes","Early Votes Against","Election Night Votes","Election Night Votes Against","Mail-In Ballot 1 Votes","Mail-In Ballot 1 Votes Against","Provisional Votes","Provisional Votes Against","Mail-In Ballot 2 Votes","Mail-In Ballot 2 Votes Against","Total Votes","Total Votes Against"
"U.S. Senator","","Angela Alsobrooks","DEM","Y","","42690","","39930","","41166","","6438","","7421","","137645",""
"U.S. Senator","","Larry Hogan","REP","","","56319","","70174","","26371","","6376","","5458","","164698",""
"U.S. Senator","","Mike Scott","LIB","","","2224","","3540","","810","","421","","278","","7273",""
"U.S. Senator","","Patrick J. Burke","OTC","","Y","80","","49","","8","","0","","6","","143",""
"U.S. Senator","","Billy Bridges","UNA","","Y","0","","6","","0","","0","","0","","6",""
"U.S. Senator","","Irwin William Gibbs","UNA","","Y","0","","0","","0","","0","","0","","0",""
"U.S. Senator","","Christy Renee Helmondollar","UNA","","Y","0","","0","","0","","0","","0","","0",""
"U.S. Senator","","Robin Rowe","UNA","","Y","1","","0","","0","","0","","0","","1",""
"U.S. Senator","","Other Write-Ins","","","Y","246","","238","","95","","18","","24","","621",""
```

Note the `Winner` column is `"Y"` for Angela Alsobrooks (position 5) and the `Write-In?` column is `"Y"` for the minor-party/write-in rows (position 6) — these are two distinct columns, don't conflate them.

- [ ] **Step 1: Write the failing test**

```python
# backend/integrations/md_sbe/tests/test_parsers.py
import os

from integrations.md_sbe.parsers import parse_county_results_csv

FIXTURES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "results", "tests", "fixtures"
)


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_county_results_csv_extracts_all_candidate_rows():
    rows = parse_county_results_csv(_load_fixture("md_county01_us_senator.csv"))
    assert len(rows) == 9
    by_name = {r["candidate_name"]: r for r in rows}
    assert "Angela Alsobrooks" in by_name
    assert "Other Write-Ins" in by_name


def test_parse_county_results_csv_extracts_expected_fields():
    rows = parse_county_results_csv(_load_fixture("md_county01_us_senator.csv"))
    alsobrooks = next(r for r in rows if r["candidate_name"] == "Angela Alsobrooks")

    assert alsobrooks["office_name"] == "U.S. Senator"
    assert alsobrooks["party"] == "DEM"
    assert alsobrooks["is_winner"] is True
    assert alsobrooks["is_write_in"] is False
    assert alsobrooks["total_votes"] == 7396


def test_parse_county_results_csv_distinguishes_winner_from_write_in_column():
    rows = parse_county_results_csv(_load_fixture("md_county01_us_senator.csv"))
    burke = next(r for r in rows if r["candidate_name"] == "Patrick J. Burke")

    # Burke is a write-in, not the contest winner — Winner and Write-In? are
    # different columns and must not be conflated.
    assert burke["is_winner"] is False
    assert burke["is_write_in"] is True
    assert burke["total_votes"] == 17


def test_parse_county_results_csv_handles_comma_thousands_and_blank_against_columns():
    csv_text = (
        '"Office Name","Office District","Candidate Name","Party","Winner","Write-In?",'
        '"Early Votes","Early Votes Against","Election Night Votes","Election Night Votes Against",'
        '"Mail-In Ballot 1 Votes","Mail-In Ballot 1 Votes Against","Provisional Votes",'
        '"Provisional Votes Against","Mail-In Ballot 2 Votes","Mail-In Ballot 2 Votes Against",'
        '"Total Votes","Total Votes Against"\n'
        '"President - Vice Pres","","Kamala D. Harris and Tim Walz","DEM","Y","","1,752","",'
        '"4,032","","2,740","","641","","66","","9,231",""\n'
    )
    rows = parse_county_results_csv(csv_text)
    assert rows[0]["total_votes"] == 9231


def test_parse_county_results_csv_skips_rows_with_no_office_name():
    csv_text = (
        '"Office Name","Candidate Name","Party","Winner","Write-In?","Total Votes"\n'
        '"","","","","",""\n'
    )
    assert parse_county_results_csv(csv_text) == []
```

- [ ] **Step 2: Save the fixture files**

```bash
mkdir -p backend/results/tests/fixtures
cat > backend/results/tests/fixtures/md_county01_us_senator.csv << 'EOF'
"Office Name","Office District","Candidate Name","Party","Winner","Write-In?","Early Votes","Early Votes Against","Election Night Votes","Election Night Votes Against","Mail-In Ballot 1 Votes","Mail-In Ballot 1 Votes Against","Provisional Votes","Provisional Votes Against","Mail-In Ballot 2 Votes","Mail-In Ballot 2 Votes Against","Total Votes","Total Votes Against"
"U.S. Senator","","Angela Alsobrooks","DEM","Y","","1486","","3089","","2251","","510","","60","","7396",""
"U.S. Senator","","Larry Hogan","REP","","","5040","","13222","","2671","","839","","39","","21811",""
"U.S. Senator","","Mike Scott","LIB","","","431","","1362","","217","","88","","2","","2100",""
"U.S. Senator","","Patrick J. Burke","OTC","","Y","5","","12","","0","","0","","0","","17",""
"U.S. Senator","","Billy Bridges","UNA","","Y","0","","1","","0","","0","","0","","1",""
"U.S. Senator","","Irwin William Gibbs","UNA","","Y","0","","0","","0","","0","","0","","0",""
"U.S. Senator","","Christy Renee Helmondollar","UNA","","Y","0","","0","","0","","0","","0","","0",""
"U.S. Senator","","Robin Rowe","UNA","","Y","0","","0","","0","","0","","0","","0",""
"U.S. Senator","","Other Write-Ins","","","Y","27","","42","","14","","2","","1","","86",""
EOF
cat > backend/results/tests/fixtures/md_county02_us_senator.csv << 'EOF'
"Office Name","Office District","Candidate Name","Party","Winner","Write-In?","Early Votes","Early Votes Against","Election Night Votes","Election Night Votes Against","Mail-In Ballot 1 Votes","Mail-In Ballot 1 Votes Against","Provisional Votes","Provisional Votes Against","Mail-In Ballot 2 Votes","Mail-In Ballot 2 Votes Against","Total Votes","Total Votes Against"
"U.S. Senator","","Angela Alsobrooks","DEM","Y","","42690","","39930","","41166","","6438","","7421","","137645",""
"U.S. Senator","","Larry Hogan","REP","","","56319","","70174","","26371","","6376","","5458","","164698",""
"U.S. Senator","","Mike Scott","LIB","","","2224","","3540","","810","","421","","278","","7273",""
"U.S. Senator","","Patrick J. Burke","OTC","","Y","80","","49","","8","","0","","6","","143",""
"U.S. Senator","","Billy Bridges","UNA","","Y","0","","6","","0","","0","","0","","6",""
"U.S. Senator","","Irwin William Gibbs","UNA","","Y","0","","0","","0","","0","","0","","0",""
"U.S. Senator","","Christy Renee Helmondollar","UNA","","Y","0","","0","","0","","0","","0","","0",""
"U.S. Senator","","Robin Rowe","UNA","","Y","1","","0","","0","","0","","0","","1",""
"U.S. Senator","","Other Write-Ins","","","Y","246","","238","","95","","18","","24","","621",""
EOF
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest integrations/md_sbe/tests/test_parsers.py --no-migrations -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.md_sbe.parsers'`

- [ ] **Step 4: Write the implementation**

```python
# backend/integrations/md_sbe/parsers.py
from __future__ import annotations

import csv
import io


def _clean(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch >= " " or ch == "\t").strip()


def _parse_int(value: str | None) -> int:
    cleaned = _clean(value).replace(",", "")
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        return 0


def parse_county_results_csv(csv_text: str) -> list[dict]:
    """Parse one MD SBE {cycle}{yy}_{county}CountyResults.csv into row dicts.

    Each row already represents a county-level total (no precinct summing
    needed) — see docs/state-research/MD/MD-Election_Research.md's
    "CountyResults schema" section.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []
    for raw_row in reader:
        office_name = _clean(raw_row.get("Office Name"))
        candidate_name = _clean(raw_row.get("Candidate Name"))
        if not office_name or not candidate_name:
            continue
        rows.append({
            "office_name": office_name,
            "candidate_name": candidate_name,
            "party": _clean(raw_row.get("Party")),
            "is_winner": _clean(raw_row.get("Winner")).upper() == "Y",
            "is_write_in": _clean(raw_row.get("Write-In?")).upper() == "Y",
            "total_votes": _parse_int(raw_row.get("Total Votes")),
        })
    return rows
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest integrations/md_sbe/tests/test_parsers.py --no-migrations -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/md_sbe/parsers.py backend/integrations/md_sbe/tests/test_parsers.py backend/results/tests/fixtures/md_county01_us_senator.csv backend/results/tests/fixtures/md_county02_us_senator.csv
git commit -m "feat(md_sbe): add county results CSV parser with real captured fixtures"
```

---

### Task 4: Aggregator — sum county rows into `ResultRow`s

**Files:**
- Create: `backend/results/adapters/md_aggregate.py`
- Test: `backend/results/tests/test_md_adapter.py` (this task's tests only — Task 5 adds more to the same file)

**Interfaces:**
- Consumes: `list[dict]` shape produced by Task 3's `parse_county_results_csv`. `ResultRow`/`from .base import ResultRow` (existing).
- Produces: `aggregate_county_rows(all_rows: list[dict], office_allowlist: frozenset[str]) -> list[ResultRow]`. Consumed by Task 5's `MarylandAdapter.fetch_results`.

- [ ] **Step 1: Write the failing test**

```python
# backend/results/tests/test_md_adapter.py
import os

from integrations.md_sbe.parsers import parse_county_results_csv
from results.adapters.md_aggregate import aggregate_county_rows

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def _county_rows():
    county01 = parse_county_results_csv(_load_fixture("md_county01_us_senator.csv"))
    county02 = parse_county_results_csv(_load_fixture("md_county02_us_senator.csv"))
    return county01 + county02


def test_aggregate_county_rows_sums_total_votes_across_counties():
    rows = aggregate_county_rows(_county_rows(), office_allowlist=frozenset({"U.S. Senator"}))

    by_name = {r.candidate_name: r.vote_count for r in rows}
    # 7396 (county 01) + 137645 (county 02) = 145041
    assert by_name["Angela Alsobrooks"] == 145041
    # 21811 + 164698 = 186509
    assert by_name["Larry Hogan"] == 186509


def test_aggregate_county_rows_marks_winner_true_if_any_county_row_says_so():
    rows = aggregate_county_rows(_county_rows(), office_allowlist=frozenset({"U.S. Senator"}))
    alsobrooks = next(r for r in rows if r.candidate_name == "Angela Alsobrooks")
    hogan = next(r for r in rows if r.candidate_name == "Larry Hogan")

    assert alsobrooks.is_winner is True
    assert hogan.is_winner is False


def test_aggregate_county_rows_flags_write_in_aggregate():
    rows = aggregate_county_rows(_county_rows(), office_allowlist=frozenset({"U.S. Senator"}))
    write_ins = next(r for r in rows if r.candidate_name == "Other Write-Ins")

    assert write_ins.is_write_in_aggregate is True
    # 86 (county 01) + 621 (county 02) = 707
    assert write_ins.vote_count == 707


def test_aggregate_county_rows_sets_office_title_and_result_type():
    rows = aggregate_county_rows(_county_rows(), office_allowlist=frozenset({"U.S. Senator"}))
    for row in rows:
        assert row.office_title == "U.S. Senator"
        assert row.result_type == "official"


def test_aggregate_county_rows_excludes_offices_not_in_allowlist():
    county_rows = parse_county_results_csv(_load_fixture("md_county01_us_senator.csv"))
    # Allowlist a different office than what's in the fixture.
    rows = aggregate_county_rows(county_rows, office_allowlist=frozenset({"Governor"}))
    assert rows == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest results/tests/test_md_adapter.py --no-migrations -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'results.adapters.md_aggregate'`

- [ ] **Step 3: Write the implementation**

```python
# backend/results/adapters/md_aggregate.py
"""
Aggregation for the Maryland SBE results adapter.

MD SBE's {cycle}{yy}_{county}CountyResults.csv files are already
county-aggregated (no precinct-level summing needed) — this module sums
each candidate's Total Votes across all 24 counties' files to get the
statewide total per (office, candidate).
"""
from __future__ import annotations

from collections import defaultdict

from .base import ResultRow


def aggregate_county_rows(all_rows: list[dict], office_allowlist: frozenset[str]) -> list[ResultRow]:
    totals: dict[tuple[str, str], int] = defaultdict(int)
    winner_seen: dict[tuple[str, str], bool] = defaultdict(bool)
    write_in_seen: dict[tuple[str, str], bool] = defaultdict(bool)
    party_by_key: dict[tuple[str, str], str] = {}

    for row in all_rows:
        office_name = row["office_name"]
        if office_name not in office_allowlist:
            continue
        key = (office_name, row["candidate_name"])
        totals[key] += row["total_votes"]
        winner_seen[key] = winner_seen[key] or row["is_winner"]
        write_in_seen[key] = write_in_seen[key] or row["is_write_in"]
        party_by_key.setdefault(key, row["party"])

    return [
        ResultRow(
            candidate_name=candidate_name,
            option_label=None,
            vote_count=vote_count,
            vote_pct=None,
            is_winner=winner_seen[(office_name, candidate_name)],
            result_type="official",
            office_title=office_name,
            is_write_in_aggregate=write_in_seen[(office_name, candidate_name)],
            raw={"party": party_by_key.get((office_name, candidate_name), "")},
        )
        for (office_name, candidate_name), vote_count in totals.items()
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest results/tests/test_md_adapter.py --no-migrations -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/results/adapters/md_aggregate.py backend/results/tests/test_md_adapter.py
git commit -m "feat(md): add cross-county vote aggregation for MD results"
```

---

### Task 5: `MarylandAdapter` — wire client + parser + aggregator into `StateResultsAdapter`

**Files:**
- Create: `backend/results/adapters/md.py`
- Modify: `backend/results/tests/test_md_adapter.py` (add adapter-level tests)

**Interfaces:**
- Consumes: `MdSbeClient` (Task 2), `parse_county_results_csv` (Task 3), `aggregate_county_rows` (Task 4), `AdapterResult`/`StateResultsAdapter`/`register` (existing, see `results/adapters/base.py` and `results/adapters/registry.py`).
- Produces: `MarylandAdapter` registered under state `"MD"` — consumed by `results.tasks.ingest_official_results` via `results.adapters.registry.get_adapter("MD")`. No other task needs to change.

- [ ] **Step 1: Write the failing test**

Append to `backend/results/tests/test_md_adapter.py`:

```python
from datetime import date
from unittest.mock import patch

import pytest

from results.adapters.md import MarylandAdapter


@pytest.mark.django_db
@patch("results.adapters.md.MdSbeClient")
def test_fetch_results_sums_across_all_24_counties(mock_client_cls, django_user_model):
    from elections.models import Election

    election = Election.objects.create(
        name="2024 Maryland General Election",
        election_date=date(2024, 11, 5),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MD",
        source_id="md-2024-general",
        status=Election.Status.RESULTS_CERTIFIED,
    )

    county01 = _load_fixture("md_county01_us_senator.csv")
    county02 = _load_fixture("md_county02_us_senator.csv")
    # Fixtures only cover 2 of the 24 counties; the other 22 return the same
    # county-02 text purely to exercise the full 24-file fetch loop.
    responses = [county01, county02] + [county02] * 22
    mock_client_cls.return_value.fetch_county_results.side_effect = responses

    result = MarylandAdapter().fetch_results(election_date=election.election_date, election_id=election.pk)

    assert result.mapping_confidence == "full"
    senator_rows = [r for r in result.rows if r.office_title == "U.S. Senator"]
    assert len(senator_rows) > 0
    assert mock_client_cls.return_value.fetch_county_results.call_count == 24


@pytest.mark.django_db
@patch("results.adapters.md.MdSbeClient")
def test_fetch_results_returns_unchanged_when_checksum_matches_cache(mock_client_cls):
    from django.core.cache import cache

    from elections.models import Election

    election = Election.objects.create(
        name="2024 Maryland General Election",
        election_date=date(2024, 11, 5),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MD",
        source_id="md-2024-general-2",
        status=Election.Status.RESULTS_CERTIFIED,
    )
    county02 = _load_fixture("md_county02_us_senator.csv")
    mock_client_cls.return_value.fetch_county_results.return_value = county02

    adapter = MarylandAdapter()
    first = adapter.fetch_results(election_date=election.election_date, election_id=election.pk)
    cache.set(adapter.version_cache_key(election.pk), first.source_version)

    second = adapter.fetch_results(election_date=election.election_date, election_id=election.pk)
    assert second.unchanged is True
    assert second.rows == []


@pytest.mark.django_db
def test_fetch_results_returns_empty_for_missing_election():
    result = MarylandAdapter().fetch_results(election_date=date(2024, 11, 5), election_id=999999)
    assert result.rows == []
    assert result.mapping_confidence == "none"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest results/tests/test_md_adapter.py --no-migrations -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'results.adapters.md'`

- [ ] **Step 3: Write the implementation**

```python
# backend/results/adapters/md.py
"""
Maryland (MD) results adapter — Maryland State Board of Elections (SBE).

Source: https://elections.maryland.gov/elections/archive/{year}/election_data/
Access: Public HTTPS, no authentication required. NOT Clarity — homegrown
        static CSVs (confirmed via HAR capture; see
        docs/state-research/MD/MD-Election_Research.md).
Schema: per-county CSV, already county-aggregated (no precinct summing) —
        this adapter sums Total Votes for each (office, candidate) pair
        across all 24 counties' files.

Scope (this build): statewide offices on the historical Nov 5, 2024 general
election only — "President - Vice Pres" and "U.S. Senator". U.S. House,
State Senate/House of Delegates, judicial, and ballot questions are
follow-up work (need the separate CongressionalBreakDown/LegislativeBreakDown
files and district-to-race mapping).

Cycle prefix resolution: hardcoded to "PG" (Presidential General) + year 2024
for this historical POC. Live discovery of the current cycle's prefix for
future elections is out of scope — see the plan's "Follow-up work" section.
"""
from __future__ import annotations

import hashlib
import logging

from django.core.cache import cache

from integrations.md_sbe.client import MdSbeClient
from integrations.md_sbe.exceptions import MdSbeRetryableError
from integrations.md_sbe.parsers import parse_county_results_csv

from .base import AdapterResult, StateResultsAdapter
from .md_aggregate import aggregate_county_rows
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days
_OFFICE_ALLOWLIST = frozenset({"President - Vice Pres", "U.S. Senator"})
_CYCLE_PREFIX = "PG"
_YEAR = 2024


@register
class MarylandAdapter(StateResultsAdapter):
    state = "MD"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"md_sbe:checksum:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("md_sbe.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        client = MdSbeClient()
        all_rows: list[dict] = []
        csv_bytes_for_checksum = bytearray()
        source_url = ""

        for county_code in client.COUNTY_CODES:
            try:
                csv_text = client.fetch_county_results(
                    year=_YEAR, cycle_prefix=_CYCLE_PREFIX, county_code=county_code,
                )
            except MdSbeRetryableError as exc:
                logger.warning(
                    "md_sbe.adapter.county_fetch_failed county=%s err=%s", county_code, exc,
                )
                continue
            csv_bytes_for_checksum.extend(csv_text.encode("utf-8", errors="ignore"))
            source_url = (
                f"https://elections.maryland.gov/elections/archive/{_YEAR}/election_data/"
                f"{_CYCLE_PREFIX}{_YEAR % 100:02d}_{county_code}CountyResults.csv"
            )
            all_rows.extend(parse_county_results_csv(csv_text))

        if not all_rows:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="none",
                notes=f"No county results parsed for election {election_id}",
            )

        checksum = hashlib.md5(bytes(csv_bytes_for_checksum)).hexdigest()
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == checksum:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="full",
                unchanged=True, source_version=checksum,
            )

        rows = aggregate_county_rows(all_rows, office_allowlist=_OFFICE_ALLOWLIST)

        return AdapterResult(
            rows=rows,
            source_url=source_url,
            mapping_confidence="full",
            source_version=checksum,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest results/tests/test_md_adapter.py --no-migrations -v`
Expected: 8 passed (5 from Task 4 + 3 new)

- [ ] **Step 5: Commit**

```bash
git add backend/results/adapters/md.py backend/results/tests/test_md_adapter.py
git commit -m "feat(md): add MarylandAdapter wiring client+parser+aggregator into StateResultsAdapter"
```

---

### Task 6: Register the adapter and verify end-to-end

**Files:**
- Modify: `backend/results/adapters/registry.py` — no code change needed (the `@register` decorator in Task 5 already registers it); this task just verifies the import wiring.

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: nothing new — this is a verification-only task.

- [ ] **Step 1: Verify the adapter is discoverable via the registry**

Run:
```bash
cd backend && python -c "
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')
django.setup()
from results.adapters.registry import list_supported_states
assert 'MD' in list_supported_states(), list_supported_states()
print('OK: MD registered')
"
```
Expected: `OK: MD registered`

(If this fails with `ImproperlyConfigured` about `SECRET_KEY`, run with `SECRET_KEY=test-only python -c "..."` instead — matches how other adapters are smoke-tested in this repo.)

- [ ] **Step 2: Run the full test suite to check for regressions**

Run: `cd backend && pytest --no-migrations -q`
Expected: all tests pass, no regressions in other adapters' tests.

- [ ] **Step 3: Run Django's system check**

Run: `cd backend && python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Commit** (only if any fixups were needed in prior steps; otherwise skip — nothing to commit)

---

## Follow-up work (explicitly out of scope for this plan)

- **U.S. House / State Senate / House of Delegates (district-level results):** needs `{cycle}{yy}_CongressionalBreakDown.csv` / `LegislativeBreakDown.csv` (already confirmed live and real — see the research doc) plus a district-to-`Race` mapping. Separate plan.
- **Governor / Comptroller / Attorney General:** on the gubernatorial cycle (2022/2026), not the 2024 presidential-cycle fixtures used here. Trivial to add to `_OFFICE_ALLOWLIST` once a 2026-general fixture is available post-certification — same file schema.
- **Ballot questions:** separate `*QuestionResults.csv` / `*QuestionbyPrecinctsResults.csv` files, different schema (see research doc). Separate plan.
- **Current-cycle discovery (cycle prefix + year):** this plan hardcodes `PG24`. A production adapter for the *current* cycle needs to resolve the cycle prefix (e.g. `GG26` for the 2026 general) from `Election.election_type`/`election_date`, and needs to handle the doc's soft-404 behavior for `.../{year}/election_data/` not existing until post-certification (the current cycle's data isn't published at that path until after canvass — confirmed in the research doc).
- **Stage 1 (candidate/race creation):** MD currently relies on the Google Civic API for race/election discovery (this plan's scope). A native `integrations.md_sbe` Stage 1 built on the per-office candidate CSVs (schema already documented in the research doc, including the 2025→2026 header drift gotcha) would add richer candidate profiles (committee name, filing date, socials) — separate plan.
- **Stage 2 live/election-night results:** static HTML scrape + `dashboarddata.json` heartbeat, per the research doc's "Stage 2 — Live / Election-Night Results" section. Per this repo's established convention (see TN's live-dashboard deferral), defer until closer to an active MD election so parsing can be validated against a live HAR capture rather than the historical-only archive data used here. Separate plan.
