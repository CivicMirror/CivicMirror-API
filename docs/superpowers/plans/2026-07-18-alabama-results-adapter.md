# Alabama Results Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Alabama Stage 2 official-results ingestion from the Alabama Votes ENR WebForms Excel export so AL moves from Elections Only to Results Adapter coverage.

**Architecture:** Build a small `integrations.al_sos` package for HTTP/WebForms export fetching and pure workbook parsing, then add `results.adapters.al` as the registered `StateResultsAdapter`. The adapter reads `Election.source_metadata["al_ecode"]` or `Election.source_metadata["results_url"]`, fetches `sosEnrExport.xlsx`, aggregates county rows to contest/candidate totals, preserves county reporting statistics in `raw`, and returns bootstrappable `ResultRow` objects. Stage 1 state election/race/candidate ingestion is intentionally out of scope until Alabama state-source candidate/race evidence is found; this plan relies on the existing Google Civic/manual election setup plus results bootstrap behavior.

**Tech Stack:** Django, Celery, `requests`, `beautifulsoup4`, `openpyxl`, existing `results.adapters.base.AdapterResult`, existing `results.adapters.base.ResultRow`, existing `results.tasks.ingest_official_results`.

## Global Constraints

- State code is `AL`; integration package is `backend/integrations/al_sos`; results adapter is `backend/results/adapters/al.py`.
- Primary live source is `https://www2.alabamavotes.gov/electionNight/statewideResultsByContest.aspx?ecode=<ecode>`.
- Adapter configuration must support `Election.source_metadata["al_ecode"]` and `Election.source_metadata["results_url"]`.
- The WebForms export postback uses `__EVENTTARGET=hlnkExportData`, empty `__EVENTARGUMENT`, and hidden fields `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`.
- Do not use Playwright for AL; the verified export path works with `requests` and a browser user agent.
- Parse `AllResults` and `Statistics` with `openpyxl`; do not introduce pandas.
- Aggregate `AllResults` by contest code, normalized contest title, candidate name, and party code, summing votes across all counties.
- Strip party suffixes such as ` (REP)` and ` (DEM)` from `office_title`, but preserve the party code in `ResultRow.raw`.
- Mark `Write-In` / `Write-In (Miscellaneous)` rows as `is_write_in_aggregate=True` and set `candidate_name=None`.
- Use `result_type="unofficial"` when any county has `Precincts Reported < Total Precincts`; otherwise use `result_type="official"`.
- Use the highest `Last Updated` timestamp from `Statistics` plus workbook row counts as the source version cache key material.
- Keep compact xlsx fixtures in git; do not commit HAR files or bulky raw archives.
- Completed AL research source is `docs/state-research/AL/AL-Election_Research.md`.

---

## File Structure

- `backend/integrations/al_sos/__init__.py`: package marker.
- `backend/integrations/al_sos/apps.py`: Django app config.
- `backend/integrations/al_sos/exceptions.py`: AL-specific retryable and non-retryable exceptions.
- `backend/integrations/al_sos/client.py`: `AlSosClient` with WebForms hidden-field extraction and Excel export download.
- `backend/integrations/al_sos/parsers.py`: pure workbook parser and aggregation helpers.
- `backend/integrations/al_sos/tests/fixtures/al_sos_enr_export.xlsx`: compact copy of the verified ENR sample workbook.
- `backend/integrations/al_sos/tests/test_client.py`: mocked WebForms client tests.
- `backend/integrations/al_sos/tests/test_parsers.py`: workbook parsing and aggregation tests.
- `backend/results/adapters/al.py`: `AlabamaAdapter` implementing `StateResultsAdapter`.
- `backend/results/tests/test_al_adapter.py`: adapter metadata, caching, registration, missing metadata, and fetch behavior tests.
- `backend/results/apps.py`: add `"al"` to the startup adapter import list.
- `backend/config/settings/base.py`: add `integrations.al_sos`.
- `backend/ops/tests/test_views.py`: assert AL becomes `results`, not absent, after adapter registration.
- `docs/state-research/00-MASTER-INDEX.md` and `README.md`: update AL Stage 2/results adapter status after implementation.

---

### Task 1: Scaffold `integrations.al_sos`

**Files:**
- Create: `backend/integrations/al_sos/__init__.py`
- Create: `backend/integrations/al_sos/apps.py`
- Create: `backend/integrations/al_sos/exceptions.py`
- Create: `backend/integrations/al_sos/tests/__init__.py`
- Modify: `backend/config/settings/base.py`

**Interfaces:**
- Produces: installed Django app `integrations.al_sos`.
- Produces: `AlSosError` and `AlSosRetryableError`.

- [ ] **Step 1: Write the failing Django app-load test**

Add this test to `backend/integrations/al_sos/tests/test_apps.py`:

```python
from django.apps import apps


def test_al_sos_app_is_installed():
    config = apps.get_app_config("al_sos")

    assert config.name == "integrations.al_sos"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
./.venv/bin/python -m pytest integrations/al_sos/tests/test_apps.py -q
```

Expected: fail because `integrations/al_sos` does not exist or app config is not installed.

- [ ] **Step 3: Create the app files**

Create `backend/integrations/al_sos/apps.py`:

```python
from django.apps import AppConfig


class AlabamaSosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.al_sos"
    label = "al_sos"
    verbose_name = "Alabama SOS Integration"
```

Create `backend/integrations/al_sos/exceptions.py`:

```python
class AlSosError(Exception):
    """Non-retryable Alabama SOS integration error."""


class AlSosRetryableError(AlSosError):
    """Transient Alabama SOS integration error that should be retried."""
```

Create empty package files:

```bash
mkdir -p backend/integrations/al_sos/tests
touch backend/integrations/al_sos/__init__.py
touch backend/integrations/al_sos/tests/__init__.py
```

- [ ] **Step 4: Register the app**

In `backend/config/settings/base.py`, add the app near other state integrations:

```python
    'integrations.tn_sos',
    'integrations.mi_sos',
    'integrations.al_sos',
    'internal',
```

- [ ] **Step 5: Verify**

Run:

```bash
cd backend
./.venv/bin/python -m pytest integrations/al_sos/tests/test_apps.py -q
./.venv/bin/python manage.py check
```

Expected: pytest passes and Django reports `System check identified no issues`.

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/al_sos backend/config/settings/base.py
git commit -m "feat(al): scaffold Alabama SOS integration"
```

---

### Task 2: Implement ENR WebForms Client

**Files:**
- Create: `backend/integrations/al_sos/client.py`
- Create: `backend/integrations/al_sos/tests/test_client.py`

**Interfaces:**
- Produces: `AlSosClient.fetch_enr_export(ecode: str) -> bytes`.
- Produces: `AlSosClient.fetch_enr_export_from_url(url: str) -> bytes`.
- Produces: `extract_webforms_fields(html: str) -> dict[str, str]`.

- [ ] **Step 1: Write failing client tests**

Create `backend/integrations/al_sos/tests/test_client.py`:

```python
from unittest.mock import MagicMock

import pytest

from integrations.al_sos.client import AlSosClient, extract_webforms_fields
from integrations.al_sos.exceptions import AlSosError


def test_extract_webforms_fields_reads_required_fields():
    html = """
    <input type="hidden" id="__VIEWSTATE" value="view-state" />
    <input type="hidden" id="__VIEWSTATEGENERATOR" value="generator" />
    <input type="hidden" id="__EVENTVALIDATION" value="validation" />
    """

    assert extract_webforms_fields(html) == {
        "__VIEWSTATE": "view-state",
        "__VIEWSTATEGENERATOR": "generator",
        "__EVENTVALIDATION": "validation",
    }


def test_extract_webforms_fields_raises_when_missing():
    with pytest.raises(AlSosError, match="missing __EVENTVALIDATION"):
        extract_webforms_fields('<input id="__VIEWSTATE" value="x" />')


def test_fetch_enr_export_posts_hidden_fields():
    session = MagicMock()
    get_response = MagicMock()
    get_response.text = """
    <input type="hidden" id="__VIEWSTATE" value="view-state" />
    <input type="hidden" id="__VIEWSTATEGENERATOR" value="generator" />
    <input type="hidden" id="__EVENTVALIDATION" value="validation" />
    """
    get_response.raise_for_status.return_value = None
    post_response = MagicMock()
    post_response.content = b"xlsx-bytes"
    post_response.headers = {
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": "attachment; filename=sosEnrExport.xlsx",
    }
    post_response.raise_for_status.return_value = None
    session.get.return_value = get_response
    session.post.return_value = post_response

    content = AlSosClient(session=session).fetch_enr_export("1001295")

    assert content == b"xlsx-bytes"
    session.get.assert_called_once_with(
        "https://www2.alabamavotes.gov/electionNight/statewideResultsByContest.aspx?ecode=1001295",
        timeout=30,
    )
    session.post.assert_called_once()
    assert session.post.call_args.kwargs["data"]["__EVENTTARGET"] == "hlnkExportData"
    assert session.post.call_args.kwargs["data"]["__EVENTARGUMENT"] == ""
    assert session.post.call_args.kwargs["data"]["__VIEWSTATE"] == "view-state"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd backend
./.venv/bin/python -m pytest integrations/al_sos/tests/test_client.py -q
```

Expected: fail because `integrations.al_sos.client` does not exist.

- [ ] **Step 3: Implement the client**

Create `backend/integrations/al_sos/client.py`:

```python
from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .exceptions import AlSosError, AlSosRetryableError

_BASE_URL = "https://www2.alabamavotes.gov/electionNight/statewideResultsByContest.aspx"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
_REQUIRED_FIELDS = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")


def enr_url_for_ecode(ecode: str) -> str:
    return f"{_BASE_URL}?ecode={ecode.strip()}"


def extract_webforms_fields(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html or "", "html.parser")
    fields: dict[str, str] = {}
    for name in _REQUIRED_FIELDS:
        node = soup.find("input", id=name)
        value = (node.get("value") if node else None) or ""
        if not value:
            raise AlSosError(f"Alabama ENR page missing {name}")
        fields[name] = value
    return fields


def ecode_from_results_url(url: str) -> str:
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("ecode") or []
    return values[0].strip() if values else ""


class AlSosClient:
    def __init__(self, session=None, timeout: int = 30, export_timeout: int = 60):
        self.session = session or requests.Session()
        self.session.headers.update(_HEADERS)
        self.timeout = timeout
        self.export_timeout = export_timeout

    def fetch_enr_export(self, ecode: str) -> bytes:
        if not ecode or not ecode.strip():
            raise AlSosError("Alabama ENR ecode is required")
        return self.fetch_enr_export_from_url(enr_url_for_ecode(ecode))

    def fetch_enr_export_from_url(self, url: str) -> bytes:
        try:
            get_response = self.session.get(url, timeout=self.timeout)
            get_response.raise_for_status()
            fields = extract_webforms_fields(get_response.text)
            post_response = self.session.post(
                url,
                data={
                    "__EVENTTARGET": "hlnkExportData",
                    "__EVENTARGUMENT": "",
                    **fields,
                },
                timeout=self.export_timeout,
            )
            post_response.raise_for_status()
        except requests.RequestException as exc:
            raise AlSosRetryableError(f"Alabama ENR export request failed: {exc}") from exc

        content_type = post_response.headers.get("Content-Type", "")
        disposition = post_response.headers.get("Content-Disposition", "")
        if "spreadsheetml" not in content_type and "sosEnrExport.xlsx" not in disposition:
            raise AlSosError("Alabama ENR export did not return an Excel workbook")
        return post_response.content
```

- [ ] **Step 4: Verify**

Run:

```bash
cd backend
./.venv/bin/python -m pytest integrations/al_sos/tests/test_client.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/al_sos/client.py backend/integrations/al_sos/tests/test_client.py
git commit -m "feat(al): fetch Alabama ENR export"
```

---

### Task 3: Parse and Aggregate AL ENR Workbook

**Files:**
- Create: `backend/integrations/al_sos/parsers.py`
- Create: `backend/integrations/al_sos/tests/fixtures/al_sos_enr_export.xlsx`
- Create: `backend/integrations/al_sos/tests/test_parsers.py`

**Interfaces:**
- Produces: `AlEnrParsedResult(rows: list[ResultRow], source_version: str, is_complete: bool, county_stats: dict[str, dict])`.
- Produces: `parse_enr_workbook(content: bytes) -> AlEnrParsedResult`.
- Produces: `normalize_contest_title(title: str) -> tuple[str, str]`, returning `(office_title, party_code_from_title)`.

- [ ] **Step 1: Copy compact fixture**

Run:

```bash
mkdir -p backend/integrations/al_sos/tests/fixtures
cp docs/state-research/AL/AL-sosEnrExport-sample.xlsx \
  backend/integrations/al_sos/tests/fixtures/al_sos_enr_export.xlsx
```

Expected: fixture file is about 48 KB and contains sheets `AllResults` and `Statistics`.

- [ ] **Step 2: Write failing parser tests**

Create `backend/integrations/al_sos/tests/test_parsers.py`:

```python
from pathlib import Path

from integrations.al_sos.parsers import normalize_contest_title, parse_enr_workbook

FIXTURES = Path(__file__).parent / "fixtures"


def test_normalize_contest_title_strips_party_suffix():
    assert normalize_contest_title("LIEUTENANT GOVERNOR (REP)") == ("LIEUTENANT GOVERNOR", "REP")
    assert normalize_contest_title("STATE REPRESENTATIVE, DISTRICT 63") == (
        "STATE REPRESENTATIVE, DISTRICT 63",
        "",
    )


def test_parse_enr_workbook_aggregates_county_rows():
    content = (FIXTURES / "al_sos_enr_export.xlsx").read_bytes()

    parsed = parse_enr_workbook(content)

    lieutenant_governor = [
        row for row in parsed.rows
        if row.office_title == "LIEUTENANT GOVERNOR" and row.raw["party_code"] == "REP"
    ]
    by_candidate = {row.candidate_name: row for row in lieutenant_governor}

    assert "Wes Allen" in by_candidate
    assert "John Wahl" in by_candidate
    assert by_candidate["Wes Allen"].vote_count > 13036
    assert by_candidate["John Wahl"].vote_count > 15588
    assert all(row.result_type == "official" for row in parsed.rows)
    assert parsed.is_complete is True
    assert parsed.source_version.startswith("1001295:")
    assert parsed.county_stats["01"]["precincts_reported"] == 177


def test_parse_enr_workbook_preserves_party_from_column_when_title_has_suffix():
    content = (FIXTURES / "al_sos_enr_export.xlsx").read_bytes()

    parsed = parse_enr_workbook(content)
    row = next(row for row in parsed.rows if row.candidate_name == "Wes Allen")

    assert row.raw["party_code"] == "REP"
    assert row.raw["contest_code"] == "00100892"
    assert row.raw["source"] == "al_sos_enr"
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
cd backend
./.venv/bin/python -m pytest integrations/al_sos/tests/test_parsers.py -q
```

Expected: fail because `integrations.al_sos.parsers` does not exist.

- [ ] **Step 4: Implement parser**

Create `backend/integrations/al_sos/parsers.py`:

```python
from __future__ import annotations

import datetime as dt
import io
import re
from collections import defaultdict
from dataclasses import dataclass

from openpyxl import load_workbook
from results.adapters.base import ResultRow

from .exceptions import AlSosError

_PARTY_SUFFIX_RE = re.compile(r"\s+\(([A-Z]{2,5})\)\s*$")


@dataclass(frozen=True)
class AlEnrParsedResult:
    rows: list[ResultRow]
    source_version: str
    is_complete: bool
    county_stats: dict[str, dict]


def normalize_contest_title(title: str) -> tuple[str, str]:
    normalized = " ".join(str(title or "").split())
    match = _PARTY_SUFFIX_RE.search(normalized)
    if not match:
        return normalized, ""
    return _PARTY_SUFFIX_RE.sub("", normalized).strip(), match.group(1)


def parse_enr_workbook(content: bytes) -> AlEnrParsedResult:
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    if "AllResults" not in workbook.sheetnames:
        raise AlSosError("Alabama ENR workbook missing AllResults sheet")
    if "Statistics" not in workbook.sheetnames:
        raise AlSosError("Alabama ENR workbook missing Statistics sheet")

    county_stats = _parse_statistics(workbook["Statistics"])
    is_complete = all(
        stat["total_precincts"] == stat["precincts_reported"]
        for stat in county_stats.values()
        if stat["total_precincts"] is not None
    )
    result_type = "official" if is_complete else "unofficial"

    totals: dict[tuple[str, str, str, str], int] = defaultdict(int)
    metadata: dict[tuple[str, str, str, str], dict] = {}
    election_codes: set[str] = set()

    for raw in _iter_dict_rows(workbook["AllResults"]):
        contest_code = _clean(raw.get("Contest Code"))
        contest_title = _clean(raw.get("Contest Title"))
        candidate_name = _clean(raw.get("Candidate Name"))
        party_code = _clean(raw.get("Party Code"))
        votes = _safe_int(raw.get("Votes"))
        election_code = _clean(raw.get("Election Code"))
        county_code = _clean(raw.get("County Code"))
        if not contest_code or not contest_title or not candidate_name:
            continue

        office_title, party_from_title = normalize_contest_title(contest_title)
        party = party_code or party_from_title
        key = (contest_code, office_title, candidate_name, party)
        totals[key] += votes
        election_codes.add(election_code)
        metadata.setdefault(key, {
            "contest_code": contest_code,
            "contest_title": contest_title,
            "party_code": party,
            "source": "al_sos_enr",
            "county_codes": [],
        })
        metadata[key]["county_codes"].append(county_code)

    rows = [
        ResultRow(
            office_title=office_title,
            candidate_name=None if _is_write_in(candidate_name) else candidate_name,
            option_label=None,
            vote_count=vote_count,
            vote_pct=None,
            is_winner=None,
            result_type=result_type,
            is_write_in_aggregate=_is_write_in(candidate_name),
            raw=metadata[key],
        )
        for key, vote_count in sorted(totals.items(), key=lambda item: item[0])
        for _contest_code, office_title, candidate_name, _party in [key]
    ]

    return AlEnrParsedResult(
        rows=rows,
        source_version=_source_version(election_codes, county_stats, len(rows)),
        is_complete=is_complete,
        county_stats=county_stats,
    )


def _parse_statistics(sheet) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for raw in _iter_dict_rows(sheet):
        county_code = _clean(raw.get("County Code"))
        if not county_code:
            continue
        last_updated = raw.get("Last Updated")
        if isinstance(last_updated, dt.datetime):
            last_updated_value = last_updated.isoformat()
        else:
            last_updated_value = _clean(last_updated)
        stats[county_code] = {
            "ballots_cast": _safe_int(raw.get("Ballots Cast")),
            "total_precincts": _safe_int(raw.get("Total Precincts")),
            "precincts_reported": _safe_int(raw.get("Precincts Reported")),
            "last_updated": last_updated_value,
        }
    return stats


def _iter_dict_rows(sheet):
    rows = sheet.iter_rows(values_only=True)
    headers = [_clean(value) for value in next(rows, [])]
    for row in rows:
        yield dict(zip(headers, row))


def _source_version(election_codes: set[str], county_stats: dict[str, dict], row_count: int) -> str:
    code = ",".join(sorted(election_codes))
    latest = max((stat["last_updated"] for stat in county_stats.values()), default="")
    return f"{code}:{latest}:{row_count}"


def _safe_int(value) -> int:
    if value in (None, ""):
        return 0
    return int(str(value).replace(",", "").strip())


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _is_write_in(value: str) -> bool:
    return "write-in" in value.lower() or "write in" in value.lower()
```

- [ ] **Step 5: Verify**

Run:

```bash
cd backend
./.venv/bin/python -m pytest integrations/al_sos/tests/test_parsers.py -q
```

Expected: all parser tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/al_sos/parsers.py backend/integrations/al_sos/tests
git commit -m "feat(al): parse Alabama ENR workbook"
```

---

### Task 4: Add `results.adapters.al`

**Files:**
- Create: `backend/results/adapters/al.py`
- Create: `backend/results/tests/test_al_adapter.py`
- Modify: `backend/results/apps.py`
- Modify: `backend/ops/tests/test_views.py`

**Interfaces:**
- Produces: `AlabamaAdapter.fetch_results(election_date: date, election_id: int) -> AdapterResult`.
- Produces: `AlabamaAdapter.version_cache_key(election_id: int) -> str`.
- Consumes: `AlSosClient.fetch_enr_export()` and `parse_enr_workbook()`.

- [ ] **Step 1: Write failing adapter tests**

Create `backend/results/tests/test_al_adapter.py`:

```python
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from results.adapters.al import AlabamaAdapter
from results.adapters.registry import get_adapter

FIXTURES = Path(__file__).parents[2] / "integrations" / "al_sos" / "tests" / "fixtures"


@pytest.mark.django_db
def test_alabama_adapter_fetches_by_ecode_metadata():
    from elections.models import Election

    election = Election.objects.create(
        source_id="al_2026_runoff",
        name="2026 Alabama Primary Runoff",
        state="AL",
        election_type="primary",
        election_date=date(2026, 6, 16),
        status="RESULTS_PENDING",
        jurisdiction_level="STATE",
        source_metadata={"al_ecode": "1001295"},
    )
    content = (FIXTURES / "al_sos_enr_export.xlsx").read_bytes()

    with patch("results.adapters.al.cache") as mock_cache, \
         patch("results.adapters.al.AlSosClient") as MockClient:
        mock_cache.get.return_value = None
        MockClient.return_value.fetch_enr_export.return_value = content

        result = AlabamaAdapter().fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "full"
    assert result.source_url.endswith("ecode=1001295")
    assert result.source_version.startswith("1001295:")
    assert len(result.rows) > 0
    MockClient.return_value.fetch_enr_export.assert_called_once_with("1001295")


@pytest.mark.django_db
def test_alabama_adapter_returns_unchanged_when_source_version_matches():
    from elections.models import Election

    election = Election.objects.create(
        source_id="al_2026_runoff_cached",
        name="2026 Alabama Primary Runoff",
        state="AL",
        election_type="primary",
        election_date=date(2026, 6, 16),
        status="RESULTS_PENDING",
        jurisdiction_level="STATE",
        source_metadata={"al_ecode": "1001295"},
    )
    content = (FIXTURES / "al_sos_enr_export.xlsx").read_bytes()

    with patch("results.adapters.al.cache") as mock_cache, \
         patch("results.adapters.al.AlSosClient") as MockClient:
        MockClient.return_value.fetch_enr_export.return_value = content
        first = AlabamaAdapter().fetch_results(election.election_date, election.pk)
        mock_cache.get.return_value = first.source_version

        second = AlabamaAdapter().fetch_results(election.election_date, election.pk)

    assert second.unchanged is True
    assert second.rows == []
    assert second.source_version == first.source_version


@pytest.mark.django_db
def test_alabama_adapter_requires_ecode_or_results_url():
    from elections.models import Election

    election = Election.objects.create(
        source_id="al_missing_metadata",
        name="2026 Alabama Primary Runoff",
        state="AL",
        election_type="primary",
        election_date=date(2026, 6, 16),
        status="RESULTS_PENDING",
        jurisdiction_level="STATE",
        source_metadata={},
    )

    result = AlabamaAdapter().fetch_results(election.election_date, election.pk)

    assert result.rows == []
    assert result.mapping_confidence == "none"
    assert "al_ecode" in result.notes


def test_alabama_adapter_registered_at_startup():
    assert get_adapter("AL") is AlabamaAdapter
```

Update `backend/ops/tests/test_views.py`:

```python
def test_coverage_tiers_reflect_full_core_definition(client):
    response = client.get("/api/coverage/sync-status/")
    tiers = response.json()["coverage_tiers"]

    assert tiers["AZ"] == "full"
    assert tiers["AK"] == "results"
    assert tiers["AL"] == "results"
    assert tiers["DE"] == "results"
    assert tiers["FL"] == "full"
    assert tiers["IL"] == "full"
    assert tiers["TX"] == "full"
    assert tiers["WA"] == "full"
    assert tiers["NC"] == "results"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd backend
./.venv/bin/python -m pytest results/tests/test_al_adapter.py ops/tests/test_views.py::test_coverage_tiers_reflect_full_core_definition -q
```

Expected: fail because `results.adapters.al` is missing and AL is not registered.

- [ ] **Step 3: Implement adapter**

Create `backend/results/adapters/al.py`:

```python
"""
Alabama (AL) results adapter - Alabama Votes ENR WebForms export.

Required Election.source_metadata:
    al_ecode       str  Alabama ENR election code, e.g. "1001295"

Optional Election.source_metadata:
    results_url    str  Full statewideResultsByContest.aspx?ecode=<ecode> URL
"""
from __future__ import annotations

import logging

from django.core.cache import cache

from integrations.al_sos.client import AlSosClient, ecode_from_results_url, enr_url_for_ecode
from integrations.al_sos.parsers import parse_enr_workbook

from .base import AdapterResult, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30


@register
class AlabamaAdapter(StateResultsAdapter):
    state = "AL"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"al_sos:enr:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("al_sos.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        meta = election.source_metadata or {}
        results_url = (meta.get("results_url") or "").strip()
        ecode = (meta.get("al_ecode") or ecode_from_results_url(results_url)).strip()
        if not ecode and not results_url:
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes='Alabama adapter requires Election.source_metadata["al_ecode"] or ["results_url"]',
            )

        source_url = results_url or enr_url_for_ecode(ecode)
        client = AlSosClient()
        content = (
            client.fetch_enr_export_from_url(source_url)
            if results_url
            else client.fetch_enr_export(ecode)
        )
        parsed = parse_enr_workbook(content)
        if cache.get(self.version_cache_key(election_id)) == parsed.source_version:
            return AdapterResult(
                rows=[],
                source_url=source_url,
                mapping_confidence="full",
                unchanged=True,
                source_version=parsed.source_version,
            )

        return AdapterResult(
            rows=parsed.rows,
            source_url=source_url,
            mapping_confidence="full",
            source_version=parsed.source_version,
            notes=f"counties={len(parsed.county_stats)} complete={parsed.is_complete}",
        )
```

- [ ] **Step 4: Register adapter startup import**

In `backend/results/apps.py`, add `"al"` as the first module in `adapter_modules`:

```python
        adapter_modules = [
            "al", "ak", "ar", "az", "ca", "co", "ct", "de", "fl", "ga", "hi",
```

- [ ] **Step 5: Verify**

Run:

```bash
cd backend
./.venv/bin/python -m pytest results/tests/test_al_adapter.py ops/tests/test_views.py -q
./.venv/bin/ruff check results/adapters/al.py results/apps.py results/tests/test_al_adapter.py ops/tests/test_views.py
```

Expected: adapter tests pass, ops view tests pass, and ruff passes.

- [ ] **Step 6: Commit**

```bash
git add backend/results/adapters/al.py backend/results/apps.py backend/results/tests/test_al_adapter.py backend/ops/tests/test_views.py
git commit -m "feat(al): add Alabama ENR results adapter"
```

---

### Task 5: Document Coverage and Runtime Use

**Files:**
- Modify: `docs/state-research/00-MASTER-INDEX.md`
- Modify: `README.md`
- Modify: `docs/state-research/AL/AL-Election_Research.md`

**Interfaces:**
- Produces: updated docs showing AL as Results Adapter coverage, not Full Core.
- Produces: explicit operator note that AL elections need `source_metadata["al_ecode"]` until ecode discovery is built.

- [ ] **Step 1: Update master index**

In `docs/state-research/00-MASTER-INDEX.md`, change AL from Elections Only/no adapter to Results Adapter. The AL row should communicate:

```markdown
| AL | Results Adapter | Stage 2 ENR Excel export adapter; Stage 1 still Google Civic/manual until state candidate/race source is implemented |
```

Use the actual table columns in the file; preserve its existing formatting.

- [ ] **Step 2: Update README coverage table**

In `README.md`, change the AL Stage 2/results adapter indicator from not implemented to implemented while leaving Stage 1 state-source indicators incomplete. Preserve the table's existing checkmark/cross style.

- [ ] **Step 3: Add implementation note to AL research**

Append this section to `docs/state-research/AL/AL-Election_Research.md`:

```markdown
## Implementation Notes

- Results adapter: `backend/results/adapters/al.py`
- Integration helpers: `backend/integrations/al_sos/`
- Required election metadata: `source_metadata["al_ecode"]`, for example `"1001295"`
- Optional override: `source_metadata["results_url"]`
- Coverage tier after this adapter: Results Adapter. AL is not Full Core until a state-source Stage 1 election/race/candidate ingestion pipeline exists.
```

- [ ] **Step 4: Verify docs references**

Run:

```bash
rg -n "AL|Alabama|al_ecode|Results Adapter" README.md docs/state-research/00-MASTER-INDEX.md docs/state-research/AL/AL-Election_Research.md
```

Expected: AL appears as Results Adapter and `al_ecode` is documented.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/state-research/00-MASTER-INDEX.md docs/state-research/AL/AL-Election_Research.md
git commit -m "docs(al): document Alabama results adapter coverage"
```

---

### Task 6: End-to-End Verification and Deployment Prep

**Files:**
- No new files.
- Verify all files changed by Tasks 1-5.

**Interfaces:**
- Confirms: AL adapter registers in Django startup.
- Confirms: coverage API classifies AL as `results`.
- Confirms: parser and adapter tests are deterministic and network-free.

- [ ] **Step 1: Run focused tests**

Run:

```bash
cd backend
./.venv/bin/python -m pytest integrations/al_sos/tests results/tests/test_al_adapter.py ops/tests/test_views.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run lint and system check**

Run:

```bash
cd backend
./.venv/bin/ruff check integrations/al_sos results/adapters/al.py results/apps.py results/tests/test_al_adapter.py ops/tests/test_views.py
./.venv/bin/python manage.py check
```

Expected: ruff passes and Django reports no system-check issues.

- [ ] **Step 3: Verify registry and tier classification in shell**

Run:

```bash
cd backend
./.venv/bin/python manage.py shell -c "from results.adapters import list_supported_states; from ops.views import _coverage_tiers; states=list_supported_states(); tiers=_coverage_tiers(states); print('AL registered', 'AL' in states); print('AL tier', tiers.get('AL')); print('elections_only', sorted(set('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split())-set(tiers)))"
```

Expected output includes:

```text
AL registered True
AL tier results
elections_only ['MD', 'MO', 'NM', 'UT']
```

- [ ] **Step 4: Review commit scope**

Run:

```bash
git status --short
git log --oneline -6
```

Expected: only intentional uncommitted research artifacts remain, or the working tree is clean if the AL research files were intentionally committed in Task 5.

- [ ] **Step 5: Deployment handoff**

If implementation is approved and merged to `main`, deploy through the active local production stack:

```bash
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml build civicmirror-api civicmirror-worker
docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml up -d --force-recreate civicmirror-api civicmirror-worker
curl -fsS https://civicmirror.app/api/coverage/sync-status/ | jq '.coverage_tiers.AL'
```

Expected: `curl` prints `"results"` after the new backend is live.

---

## Follow-Up Work Not Included

- Stage 1 Alabama state-source ingestion for elections/races/candidates. Current AL research confirms Google Civic availability but does not identify an official Alabama candidate/race feed suitable for a state integration.
- Automatic `ecode` discovery. The ENR site has no verified election index; keep `al_ecode` as election metadata until a reliable link source is identified.
- Certified/historical Drupal workbook ingestion. The ENR adapter is the first production path; certified workbook and precinct ZIP parsing can be added after the live adapter lands.
- Scheduler changes. AL results can initially use `poll_pending_results` once elections have `source_metadata["al_ecode"]`; add a dedicated scheduler trigger only if operational cadence requires one.

## Self-Review

- Spec coverage: The plan implements the confirmed AL Stage 2 ENR export path, documents `al_ecode`, registers the adapter, updates coverage classification, and leaves unsupported Stage 1/source-discovery work as explicit follow-up.
- Placeholder scan: The plan contains no deferred-detail markers, no empty "add tests" steps, and every code-changing task includes concrete code or exact file edits.
- Type consistency: `AlSosClient`, `parse_enr_workbook`, `AlEnrParsedResult`, `AlabamaAdapter`, and `source_metadata["al_ecode"]` are named consistently across tasks.
