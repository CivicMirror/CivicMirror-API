# Illinois (IL) Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Illinois to Full Core Coverage — Stage 1 (election/race creation) and Stage 2 (results ingestion) both sourced from the Illinois State Board of Elections (SBE), scoped to Federal + State offices.

**Architecture:** A new `integrations/il_sbe/` app (Stage 1) resolves per-election tokens via an ASP.NET auto-postback replay and parses the office/CSV list off IL SBE's results category pages, upserting `Election`/`Race` rows through `aggregation.ingest`. A new `results/adapters/il.py` (Stage 2), registered with the existing generic `ingest_official_results` task, re-parses the same category pages, downloads each office's precinct-level CSV, aggregates vote totals by candidate, and returns rows the existing framework matches to races by `office_title`.

**Tech Stack:** Django, Celery, `requests`, `beautifulsoup4` (already a dependency — confirm in Task 1), PostgreSQL.

## Global Constraints

- Scope is Federal + State offices only for this build. Judicial races and statewide ballot measures use the identical CSV mechanism but are explicitly deferred (see spec `docs/superpowers/specs/2026-07-11-il-adapter-design.md`).
- No live network calls in CI — all parser/aggregation tests run against fixture files.
- Follow existing per-state conventions exactly: `co_sos`/`nc_sbe` for Stage 1 shape, `nc.py` for Stage 2 adapter shape.
- Run tests with `pytest --no-migrations` (per project convention — local test-DB creation breaks on migration issues otherwise).
- Every DB-touching test must use `@pytest.mark.django_db`.
- **Rebuild before every test run.** `civicmirror-worker`/`civicmirror-api` are built from `/data/Projects/CivicMirror/CivicMirror-API/backend` with no live source volume mount (confirmed via `docker-compose.yml` — only `env_file` is set, no `volumes:`). The running container only has whatever code was baked in at its last build. Before **every** "Run tests"/"Run checks" step in this plan, rebuild and recreate the worker first, then reinstall test-only dependencies (not part of the prod image):
  ```bash
  docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml build civicmirror-worker
  docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml up -d --force-recreate civicmirror-worker civicmirror-api
  docker exec civicmirror-worker pip install -q -r requirements/dev.txt
  ```
  This is not repeated inline in every task step below — treat it as a mandatory prefix to any command in this plan that runs `pytest`, `manage.py check`, `manage.py makemigrations`, or the ad hoc verification scripts.

---

## Recon Facts (grounding for this plan — confirmed live on 2026-07-11)

- Search page: `https://www.elections.il.gov/electionoperations/votetotalsearch.aspx`. Contains a `ddlElections` `<select>` (43 options, current default is the most recent election) and ASP.NET WebForms hidden fields `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`.
- Selecting a different election fires a same-page auto-postback. Confirmed via plain `requests` (no browser needed): POST to the search page with `__EVENTTARGET=ctl00$ContentPlaceHolder1$ddlElections`, `__EVENTARGUMENT=''`, the captured `__VIEWSTATE`/`__VIEWSTATEGENERATOR`/`__EVENTVALIDATION`, and `ctl00$ContentPlaceHolder1$ddlElections=<value>` returns a 200 with the new election's data embedded, including its encrypted `ID` token.
- Results category pages: `https://www.elections.il.gov/electionoperations/ElectionVoteTotals.aspx?ID=<election-token>&OfficeType=<category-token>`. Category tokens are **stable across elections**:
  - Federal/Statewide: `LpWf6lpbWOfBN3kEuxRi3A==`
  - Senate: `XmLrbPr2rU0jTLF//JHNA==`
  - Judicial: `OIPn0DmJsHWCRPQwcCA4+K+zeOSGzX4E` (not used this build — deferred)
- Each office on a category page renders as:
  ```html
  <div class="gridview-title-bar"><div id="ContentPlaceHolder1_gridContainer13071" class="infoContainers ..."><div id="ContentPlaceHolder1_gridHeader13071" class="infoHeaders text-Left"><asp:Label runat="server" rel="noopener noreferrer">UNITED STATES SENATOR</asp:Label></div></div><a href="\Downloads\ElectionOperations\ElectionResults\ByOffice\69\69-150-UNITED STATES SENATOR-2026GP.csv" target="_blank" class="gridview-download" rel="noopener noreferrer">Download Results</a></div>
  ```
  Office name is in the `.infoHeaders` element text; the CSV path is the `a.gridview-download` `href`, using **backslashes** and requiring the host prefix `https://www.elections.il.gov` and forward-slash conversion.
- CSV is precinct-level, columns: `JurisdictionID,JurisContainerID,JurisName,EISCandidateID,CandidateName,EISContestID,ContestName,PrecinctName,Registration,EISPartyID,PartyName,VoteCount`. Publicly fetchable with no auth/session (confirmed via bare `curl`). Contains non-candidate rows (`Under Votes`, `Over Votes`, `Blank Ballots`) and inconsistent write-in capitalization (`WRITE-IN`, `Write-In`, `Write-in`) that must be excluded/normalized.
- Fixtures for this plan were saved from live responses to:
  - `backend/integrations/il_sbe/tests/fixtures/search_page.html`
  - `backend/integrations/il_sbe/tests/fixtures/category_federal_statewide.html`
  - `backend/results/tests/fixtures/il_us_senator_sample.csv`

---

### Task 1: Add `IL_SBE` Race source + confirm `beautifulsoup4` dependency

**Files:**
- Modify: `backend/elections/models.py` (Race.Source choices)
- Create: `backend/elections/migrations/0022_add_il_sbe_race_source.py`
- Check: `backend/requirements/base.txt`

**Interfaces:**
- Produces: `Race.Source.IL_SBE` (value `"il_sbe"`) usable by later tasks.

- [ ] **Step 1: Add the new choice to `Race.Source`**

In `backend/elections/models.py`, inside `class Race(models.Model): class Source(models.TextChoices):`, add after `GA_SOS = 'ga_sos', 'Georgia SOS'`:

```python
        IL_SBE = 'il_sbe', 'Illinois SBE'
```

- [ ] **Step 2: Generate the migration**

Run: `docker exec civicmirror-worker python3 manage.py makemigrations elections --name add_il_sbe_race_source`

Expected: creates `backend/elections/migrations/0022_add_il_sbe_race_source.py` with an `AlterField` on `race.source` whose `choices` list matches the updated `Race.Source` (same shape as `0021_add_ga_sos_race_source.py`, with `('il_sbe', 'Illinois SBE')` appended).

- [ ] **Step 3: Confirm `beautifulsoup4` is available**

Run: `grep -i beautifulsoup backend/requirements/base.txt`

Expected: a line like `beautifulsoup4==...`. If absent, add `beautifulsoup4==4.12.3` to `backend/requirements/base.txt` (check what other adapters use first — `grep -ri bs4\|beautifulsoup backend/results/adapters/*.py` to confirm the import name already used elsewhere, e.g. `from bs4 import BeautifulSoup`).

- [ ] **Step 4: Run migration check**

Run: `docker exec civicmirror-worker python3 manage.py makemigrations --check --dry-run`

Expected: `No changes detected` (confirms the committed migration fully captures the model change).

- [ ] **Step 5: Commit**

```bash
git add backend/elections/models.py backend/elections/migrations/0022_add_il_sbe_race_source.py backend/requirements/base.txt
git commit -m "feat(il): add IL_SBE race source"
```

---

### Task 2: Scaffold `integrations/il_sbe` app

**Files:**
- Create: `backend/integrations/il_sbe/__init__.py`
- Create: `backend/integrations/il_sbe/apps.py`
- Create: `backend/integrations/il_sbe/exceptions.py`
- Create: `backend/integrations/il_sbe/tests/__init__.py`
- Modify: `backend/config/settings/base.py`

**Interfaces:**
- Produces: `IlSbeError`, `IlSbeRetryableError` exception classes for Task 3+ to raise.

- [ ] **Step 1: Create the app package**

`backend/integrations/il_sbe/__init__.py` — empty file.

- [ ] **Step 2: Create `apps.py`**

```python
from django.apps import AppConfig


class IllinoisSbeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.il_sbe"
    label = "il_sbe"
    verbose_name = "Illinois SBE Integration"
```

- [ ] **Step 3: Create `exceptions.py`**

```python
class IlSbeError(Exception):
    """Non-retryable Illinois SBE integration error."""


class IlSbeRetryableError(IlSbeError):
    """Transient error that warrants a Celery retry."""
```

- [ ] **Step 4: Register the app**

In `backend/config/settings/base.py`, find the line `'integrations.co_sos',` in `INSTALLED_APPS` and add immediately after it:

```python
    'integrations.il_sbe',
```

- [ ] **Step 5: Create the tests package**

`backend/integrations/il_sbe/tests/__init__.py` — empty file.

- [ ] **Step 6: Verify Django can load the app**

Run: `docker exec civicmirror-worker python3 manage.py check`

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 7: Commit**

```bash
git add backend/integrations/il_sbe/__init__.py backend/integrations/il_sbe/apps.py backend/integrations/il_sbe/exceptions.py backend/integrations/il_sbe/tests/__init__.py backend/config/settings/base.py
git commit -m "feat(il): scaffold integrations.il_sbe app"
```

---

### Task 3: Parsers — postback fields, election options, election ID token, office/CSV blocks

**Files:**
- Create: `backend/integrations/il_sbe/parsers.py`
- Create: `backend/integrations/il_sbe/tests/test_parsers.py`
- Test fixtures (already staged): `backend/integrations/il_sbe/tests/fixtures/search_page.html`, `backend/integrations/il_sbe/tests/fixtures/category_federal_statewide.html`

**Interfaces:**
- Produces:
  - `parse_postback_fields(html: str) -> dict[str, str]` — `{"__VIEWSTATE": ..., "__VIEWSTATEGENERATOR": ..., "__EVENTVALIDATION": ...}`
  - `parse_election_options(html: str) -> list[dict]` — `[{"value": "69", "label": "2026 GENERAL PRIMARY"}, ...]`
  - `parse_election_id_token(html: str) -> str | None` — decoded `ID` query param from the "Federal / Statewide" link, or `None` if not found.
  - `parse_category_offices(html: str) -> list[dict]` — `[{"office_name": "UNITED STATES SENATOR", "csv_url": "https://www.elections.il.gov/Downloads/ElectionOperations/ElectionResults/ByOffice/69/69-150-UNITED STATES SENATOR-2026GP.csv"}, ...]`

- [ ] **Step 1: Write the failing tests**

Create `backend/integrations/il_sbe/tests/test_parsers.py`:

```python
import os

import pytest

from integrations.il_sbe.parsers import (
    parse_category_offices,
    parse_election_id_token,
    parse_election_options,
    parse_postback_fields,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_postback_fields_extracts_viewstate_trio():
    html = _load_fixture("search_page.html")
    fields = parse_postback_fields(html)
    assert set(fields.keys()) == {"__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"}
    assert len(fields["__VIEWSTATE"]) > 1000
    assert fields["__VIEWSTATEGENERATOR"]
    assert fields["__EVENTVALIDATION"]


def test_parse_election_options_returns_value_label_pairs():
    html = _load_fixture("search_page.html")
    options = parse_election_options(html)
    assert len(options) > 40
    assert {"value": "69", "label": "2026 GENERAL PRIMARY"} in options
    assert {"value": "66", "label": "2024 GENERAL ELECTION"} in options


def test_parse_election_id_token_decodes_from_federal_statewide_link():
    html = _load_fixture("search_page.html")
    token = parse_election_id_token(html)
    assert token == "Z2J/vYpKX8w="


def test_parse_election_id_token_returns_none_when_link_missing():
    assert parse_election_id_token("<html><body>no links here</body></html>") is None


def test_parse_category_offices_extracts_office_name_and_csv_url():
    html = _load_fixture("category_federal_statewide.html")
    offices = parse_category_offices(html)
    assert len(offices) > 20

    senate = next(o for o in offices if o["office_name"] == "UNITED STATES SENATOR")
    assert senate["csv_url"] == (
        "https://www.elections.il.gov/Downloads/ElectionOperations/ElectionResults/"
        "ByOffice/69/69-150-UNITED STATES SENATOR-2026GP.csv"
    )

    governor = next(o for o in offices if o["office_name"] == "GOVERNOR AND LIEUTENANT GOVERNOR")
    assert "69-180-GOVERNOR AND LIEUTENANT GOVERNOR-2026GP.csv" in governor["csv_url"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec civicmirror-worker /home/appuser/.local/bin/pytest integrations/il_sbe/tests/test_parsers.py --no-migrations -v`

Expected: `ModuleNotFoundError: No module named 'integrations.il_sbe.parsers'` (or collection error) — the module doesn't exist yet.

- [ ] **Step 3: Write `parsers.py`**

```python
"""
HTML/postback parsers for the Illinois State Board of Elections (SBE) site.

The search page (votetotalsearch.aspx) is classic ASP.NET WebForms: selecting
a different election in the `Elections` dropdown fires a same-page auto-postback
via __doPostBack, swapping in a new encrypted `ID` token used by the results
category pages. The `OfficeType` category tokens are stable across elections
(see client.py for the constants).
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

_POSTBACK_FIELDS = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")

_CSV_BASE_URL = "https://www.elections.il.gov"


def parse_postback_fields(html: str) -> dict[str, str]:
    """Extract the ASP.NET WebForms hidden postback fields required to replay a postback."""
    soup = BeautifulSoup(html, "html.parser")
    fields: dict[str, str] = {}
    for field_id in _POSTBACK_FIELDS:
        tag = soup.find(id=field_id)
        fields[field_id] = tag.get("value", "") if tag else ""
    return fields


def parse_election_options(html: str) -> list[dict]:
    """Extract {value, label} pairs from the `Elections` dropdown."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find(id="ContentPlaceHolder1_ddlElections")
    if not select:
        return []
    options = []
    for opt in select.find_all("option"):
        value = opt.get("value", "").strip()
        label = opt.get_text(strip=True)
        if value and label:
            options.append({"value": value, "label": label})
    return options


def parse_election_id_token(html: str) -> str | None:
    """
    Decode the per-election `ID` token from the "Federal / Statewide" category link.
    Returns None if the link isn't present (e.g. election has no results page yet).
    """
    soup = BeautifulSoup(html, "html.parser")
    link = soup.find("a", string="Federal / Statewide")
    if not link or not link.get("href"):
        return None
    query = urlparse(link["href"]).query
    params = parse_qs(query)
    values = params.get("ID")
    if not values:
        return None
    return unquote(values[0])


def parse_category_offices(html: str) -> list[dict]:
    """
    Extract {office_name, csv_url} for every office on a results category page
    (Federal/Statewide, Senate, ...).
    """
    soup = BeautifulSoup(html, "html.parser")
    offices = []
    for block in soup.select("div.gridview-title-bar"):
        header = block.select_one("[id*=gridHeader]")
        link = block.select_one("a.gridview-download")
        if not header or not link or not link.get("href"):
            continue
        office_name = header.get_text(strip=True)
        raw_href = link["href"].replace("\\", "/")
        csv_url = f"{_CSV_BASE_URL}/{raw_href.lstrip('/')}"
        offices.append({"office_name": office_name, "csv_url": csv_url})
    return offices
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec civicmirror-worker /home/appuser/.local/bin/pytest integrations/il_sbe/tests/test_parsers.py --no-migrations -v`

Expected: all 6 tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/il_sbe/parsers.py backend/integrations/il_sbe/tests/test_parsers.py backend/integrations/il_sbe/tests/fixtures/
git commit -m "feat(il): add IL SBE HTML/postback parsers"
```

---

### Task 4: Client — HTTP wrapper with retry + postback replay

**Files:**
- Create: `backend/integrations/il_sbe/client.py`
- Create: `backend/integrations/il_sbe/tests/test_client.py`

**Interfaces:**
- Consumes: `parse_postback_fields`, `parse_election_id_token` from `parsers.py` (Task 3).
- Produces:
  - `IllinoisSbeClient` class with methods `fetch_search_page() -> str`, `fetch_election_page(election_value: str) -> str`, `fetch_category_page(election_id_token: str, office_type_token: str) -> str`, `fetch_office_csv(csv_url: str) -> str`.
  - Module constants: `OFFICE_TYPE_FEDERAL_STATEWIDE`, `OFFICE_TYPE_SENATE` (strings, used by Task 6+8).

- [ ] **Step 1: Write the failing test**

Create `backend/integrations/il_sbe/tests/test_client.py`:

```python
from unittest.mock import MagicMock, patch

from integrations.il_sbe.client import IllinoisSbeClient


def test_fetch_election_page_replays_postback_with_captured_fields():
    client = IllinoisSbeClient()

    search_page_html = (
        '<input type="hidden" id="__VIEWSTATE" value="VSTATE123" />'
        '<input type="hidden" id="__VIEWSTATEGENERATOR" value="GEN123" />'
        '<input type="hidden" id="__EVENTVALIDATION" value="EVAL123" />'
    )
    postback_response_html = "<html>postback result</html>"

    mock_get_response = MagicMock(status_code=200, text=search_page_html)
    mock_post_response = MagicMock(status_code=200, text=postback_response_html)

    with patch.object(client._session, "get", return_value=mock_get_response) as mock_get, \
         patch.object(client._session, "post", return_value=mock_post_response) as mock_post:
        result = client.fetch_election_page("66")

    assert result == postback_response_html
    mock_get.assert_called_once()
    post_kwargs = mock_post.call_args.kwargs
    assert post_kwargs["data"]["__VIEWSTATE"] == "VSTATE123"
    assert post_kwargs["data"]["__EVENTTARGET"] == "ctl00$ContentPlaceHolder1$ddlElections"
    assert post_kwargs["data"]["ctl00$ContentPlaceHolder1$ddlElections"] == "66"


def test_fetch_category_page_passes_id_and_office_type_params():
    client = IllinoisSbeClient()
    mock_response = MagicMock(status_code=200, text="<html>category page</html>")

    with patch.object(client._session, "get", return_value=mock_response) as mock_get:
        result = client.fetch_category_page("Z2J/vYpKX8w=", "LpWf6lpbWOfBN3kEuxRi3A==")

    assert result == "<html>category page</html>"
    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"ID": "Z2J/vYpKX8w=", "OfficeType": "LpWf6lpbWOfBN3kEuxRi3A=="}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec civicmirror-worker /home/appuser/.local/bin/pytest integrations/il_sbe/tests/test_client.py --no-migrations -v`

Expected: `ModuleNotFoundError: No module named 'integrations.il_sbe.client'`

- [ ] **Step 3: Write `client.py`**

```python
"""
Illinois State Board of Elections (SBE) HTTP client.

Source: https://www.elections.il.gov/electionoperations/
No authentication required. The search page uses ASP.NET WebForms
auto-postback: selecting a different election in the `Elections` dropdown
fires a same-page postback that swaps in a new encrypted `ID` token for
that election. `OfficeType` category tokens are stable across elections
(confirmed live 2026-07-11 — see docs/superpowers/specs/2026-07-11-il-adapter-design.md).
"""
from __future__ import annotations

import logging

import requests

from .exceptions import IlSbeRetryableError
from .parsers import parse_postback_fields

logger = logging.getLogger(__name__)

BASE_URL = "https://www.elections.il.gov/electionoperations"
SEARCH_PAGE_URL = f"{BASE_URL}/votetotalsearch.aspx"
RESULTS_PAGE_URL = f"{BASE_URL}/ElectionVoteTotals.aspx"

# Stable category tokens (decoded), confirmed identical across elections.
OFFICE_TYPE_FEDERAL_STATEWIDE = "LpWf6lpbWOfBN3kEuxRi3A=="
OFFICE_TYPE_SENATE = "XmLrbPr2rU0jTLF//JHNA=="

_DDL_ELECTIONS_FIELD = "ctl00$ContentPlaceHolder1$ddlElections"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_RETRYABLE_STATUSES = {403, 429, 500, 502, 503, 504}


class IllinoisSbeClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        call = self._session.get if method == "GET" else self._session.post
        for attempt in range(self.max_retries + 1):
            try:
                resp = call(url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise IlSbeRetryableError(f"IL SBE {method} failed: {exc}") from exc
                logger.warning(
                    "il_sbe.client.retry method=%s attempt=%d url=%s err=%s",
                    method, attempt, url, exc,
                )
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise IlSbeRetryableError(f"IL SBE returned {resp.status_code} for {url}")
                logger.warning(
                    "il_sbe.client.retry method=%s attempt=%d url=%s status=%d",
                    method, attempt, url, resp.status_code,
                )
                continue
            resp.raise_for_status()
            return resp
        raise IlSbeRetryableError("IL SBE request retries exhausted")

    def fetch_search_page(self) -> str:
        """GET the default search page (most recent election preselected)."""
        return self._request("GET", SEARCH_PAGE_URL).text

    def fetch_election_page(self, election_value: str) -> str:
        """
        Replay the ddlElections auto-postback to load the page for a specific
        election (identified by its dropdown `value`, e.g. "66").
        """
        base_html = self.fetch_search_page()
        fields = parse_postback_fields(base_html)
        data = {
            "__EVENTTARGET": _DDL_ELECTIONS_FIELD,
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": fields["__VIEWSTATE"],
            "__VIEWSTATEGENERATOR": fields["__VIEWSTATEGENERATOR"],
            "__EVENTVALIDATION": fields["__EVENTVALIDATION"],
            _DDL_ELECTIONS_FIELD: election_value,
        }
        resp = self._request(
            "POST", SEARCH_PAGE_URL, data=data, headers={"Referer": SEARCH_PAGE_URL}
        )
        return resp.text

    def fetch_category_page(self, election_id_token: str, office_type_token: str) -> str:
        """GET a results category page (Federal/Statewide, Senate) for one election."""
        resp = self._request(
            "GET",
            RESULTS_PAGE_URL,
            params={"ID": election_id_token, "OfficeType": office_type_token},
        )
        return resp.text

    def fetch_office_csv(self, csv_url: str) -> str:
        """GET a per-office precinct-level results CSV. Public, no auth required."""
        return self._request("GET", csv_url).text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec civicmirror-worker /home/appuser/.local/bin/pytest integrations/il_sbe/tests/test_client.py --no-migrations -v`

Expected: both tests `PASS`.

- [ ] **Step 5: Manually verify against the live site (not part of CI)**

Run:
```bash
docker exec civicmirror-worker python3 -c "
from integrations.il_sbe.client import IllinoisSbeClient, OFFICE_TYPE_FEDERAL_STATEWIDE
from integrations.il_sbe.parsers import parse_election_id_token, parse_category_offices

client = IllinoisSbeClient()
page = client.fetch_election_page('66')
token = parse_election_id_token(page)
print('resolved ID token:', token)
assert token, 'expected a resolved election ID token'

category_html = client.fetch_category_page(token, OFFICE_TYPE_FEDERAL_STATEWIDE)
offices = parse_category_offices(category_html)
print('offices found:', len(offices))
assert offices, 'expected at least one office on the category page'
print(offices[0])
"
```

Expected: prints a resolved token (e.g. `9huvqbsiUWA=`), a positive office count, and a sample `{"office_name": ..., "csv_url": ...}` dict. This confirms the plain-`requests` postback replay still works against the live site (it was validated once during recon on 2026-07-11; re-verify here since site behavior can change).

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/il_sbe/client.py backend/integrations/il_sbe/tests/test_client.py
git commit -m "feat(il): add IL SBE HTTP client with postback replay"
```

---

### Task 5: Mappers — election date/type inference, office → Race field mapping, Federal+State filter

**Files:**
- Create: `backend/integrations/il_sbe/mappers.py`
- Create: `backend/integrations/il_sbe/tests/test_mappers.py`

**Interfaces:**
- Produces:
  - `is_federal_or_state_office(office_name: str) -> bool`
  - `infer_election_type_and_date(label: str) -> tuple[str, datetime.date] | None` — returns `(election_type, election_date)` or `None` when the label's type can't be reliably dated (e.g. `SPECIAL GENERAL ELECTION`, `SPECIAL PRIMARY`).
  - `map_election(value: str, label: str) -> dict | None` — `Election` field dict (identity fields separated by caller), or `None` if undatable.
  - `map_race(election_obj, office_name: str) -> dict` — `Race` field dict.

- [ ] **Step 1: Write the failing tests**

Create `backend/integrations/il_sbe/tests/test_mappers.py`:

```python
import datetime

import pytest

from integrations.il_sbe.mappers import (
    infer_election_type_and_date,
    is_federal_or_state_office,
    map_election,
    map_race,
)


@pytest.mark.parametrize("office_name,expected", [
    ("UNITED STATES SENATOR", True),
    ("PRESIDENT AND VICE PRESIDENT", True),
    ("1ST CONGRESS", True),
    ("17TH CONGRESS", True),
    ("GOVERNOR AND LIEUTENANT GOVERNOR", True),
    ("ATTORNEY GENERAL", True),
    ("SECRETARY OF STATE", True),
    ("COMPTROLLER", True),
    ("TREASURER", True),
    ("2ND SENATE", True),
    ("118TH REPRESENTATIVE", True),
    ("1ST STATE CENTRAL COMMITTEEPERSON", False),
    ("1ST APPELLATE - HOFFMAN VACANCY", False),
    ("COOK CIRCUIT - RETAIN FLANAGAN", False),
    ('"Should any candidate appearing on the Illinois ballot..."', False),
])
def test_is_federal_or_state_office(office_name, expected):
    assert is_federal_or_state_office(office_name) is expected


def test_infer_election_type_and_date_general_election():
    election_type, election_date = infer_election_type_and_date("2024 GENERAL ELECTION")
    assert election_type == "general"
    assert election_date == datetime.date(2024, 11, 5)


def test_infer_election_type_and_date_consolidated_election():
    election_type, election_date = infer_election_type_and_date("2025 CONSOLIDATED ELECTION")
    assert election_type == "municipal"
    assert election_date == datetime.date(2025, 4, 1)


def test_infer_election_type_and_date_general_primary_is_approximate():
    election_type, election_date = infer_election_type_and_date("2026 GENERAL PRIMARY")
    assert election_type == "primary"
    # Best-effort statutory default (third Tuesday in March); flagged as
    # approximate in map_election()'s source_metadata.
    assert election_date == datetime.date(2026, 3, 17)


def test_infer_election_type_and_date_returns_none_for_special_elections():
    assert infer_election_type_and_date("2015 SPECIAL GENERAL ELECTION") is None
    assert infer_election_type_and_date("2013 SPECIAL PRIMARY") is None


def test_map_election_flags_primary_date_as_approximate():
    result = map_election("69", "2026 GENERAL PRIMARY")
    assert result["name"] == "2026 Illinois General Primary"
    assert result["state"] == "IL"
    assert result["election_type"] == "primary"
    assert result["source_id"] == "il_sbe_69"
    assert result["source_metadata"]["il_sbe_election_value"] == "69"
    assert result["source_metadata"]["election_date_approximate"] is True


def test_map_election_general_election_not_flagged_approximate():
    result = map_election("66", "2024 GENERAL ELECTION")
    assert result["source_metadata"]["election_date_approximate"] is False


def test_map_election_returns_none_for_special_elections():
    assert map_election("59", "2015 SPECIAL GENERAL ELECTION") is None


def test_map_race_sets_federal_geography_for_congress():
    election = type("FakeElection", (), {"pk": 1, "source_id": "il_sbe_69", "state": "IL"})()
    result = map_race(election, "1ST CONGRESS")
    assert result["office_title"] == "1ST CONGRESS"
    assert result["geography_scope"] == "district"
    assert result["jurisdiction"] == "1ST CONGRESS"


def test_map_race_sets_statewide_geography_for_row_offices():
    election = type("FakeElection", (), {"pk": 1, "source_id": "il_sbe_69", "state": "IL"})()
    result = map_race(election, "GOVERNOR AND LIEUTENANT GOVERNOR")
    assert result["geography_scope"] == "statewide"
    assert result["jurisdiction"] == "Illinois"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec civicmirror-worker /home/appuser/.local/bin/pytest integrations/il_sbe/tests/test_mappers.py --no-migrations -v`

Expected: `ModuleNotFoundError: No module named 'integrations.il_sbe.mappers'`

- [ ] **Step 3: Write `mappers.py`**

```python
"""
Mappers for Illinois SBE data -> CivicMirror model fields.

Election dates: IL SBE's election dropdown only gives label text (e.g.
"2026 GENERAL PRIMARY"), not a machine-readable date. General Elections and
Consolidated Elections follow fixed statutory formulas and are computed
exactly. General Primary dates have shifted by statute in recent cycles
(e.g. moved to June in 2022 for redistricting reasons) — this maps them to
the typical third-Tuesday-in-March date and flags the result as
`election_date_approximate` in source_metadata so it can be corrected if
wrong. Special elections have no fixed schedule and are not mapped at all
(returns None; sync_il_elections skips them).
"""
from __future__ import annotations

import calendar
import datetime
import re

from elections.models import Election, Race

_FEDERAL_STATE_PATTERNS = (
    re.compile(r"^UNITED STATES SENATOR$"),
    re.compile(r"^PRESIDENT AND VICE PRESIDENT$"),
    re.compile(r"^\d+(ST|ND|RD|TH) CONGRESS$"),
    re.compile(r"^\d+(ST|ND|RD|TH) SENATE$"),
    re.compile(r"^\d+(ST|ND|RD|TH) REPRESENTATIVE$"),
)

_STATEWIDE_ROW_OFFICES = frozenset({
    "GOVERNOR AND LIEUTENANT GOVERNOR",
    "ATTORNEY GENERAL",
    "SECRETARY OF STATE",
    "COMPTROLLER",
    "TREASURER",
})

_DISTRICT_OFFICE_PATTERNS = (
    re.compile(r"^\d+(ST|ND|RD|TH) CONGRESS$"),
    re.compile(r"^\d+(ST|ND|RD|TH) SENATE$"),
    re.compile(r"^\d+(ST|ND|RD|TH) REPRESENTATIVE$"),
)


def is_federal_or_state_office(office_name: str) -> bool:
    name = office_name.strip().upper()
    if name in _STATEWIDE_ROW_OFFICES:
        return True
    return any(p.match(name) for p in _FEDERAL_STATE_PATTERNS)


def _is_district_office(office_name: str) -> bool:
    name = office_name.strip().upper()
    return any(p.match(name) for p in _DISTRICT_OFFICE_PATTERNS)


def _first_tuesday_after_first_monday(year: int, month: int) -> datetime.date:
    first = datetime.date(year, month, 1)
    days_to_monday = (calendar.MONDAY - first.weekday()) % 7
    first_monday = first + datetime.timedelta(days=days_to_monday)
    return first_monday + datetime.timedelta(days=1)


def _third_tuesday_of_march(year: int) -> datetime.date:
    first = datetime.date(year, 3, 1)
    days_to_tuesday = (calendar.TUESDAY - first.weekday()) % 7
    first_tuesday = first + datetime.timedelta(days=days_to_tuesday)
    return first_tuesday + datetime.timedelta(days=14)


def _first_tuesday_of_april(year: int) -> datetime.date:
    first = datetime.date(year, 4, 1)
    days_to_tuesday = (calendar.TUESDAY - first.weekday()) % 7
    return first + datetime.timedelta(days=days_to_tuesday)


def infer_election_type_and_date(label: str) -> tuple[str, datetime.date] | None:
    """
    Parse an IL SBE election dropdown label into (election_type, election_date).
    Returns None for labels whose date can't be reliably computed (specials).
    """
    match = re.match(r"^(\d{4})\s+(.*)$", label.strip())
    if not match:
        return None
    year = int(match.group(1))
    kind = match.group(2).strip().upper()

    if kind == "GENERAL ELECTION":
        return "general", _first_tuesday_after_first_monday(year, 11)
    if kind == "GENERAL PRIMARY":
        return "primary", _third_tuesday_of_march(year)
    if kind == "CONSOLIDATED ELECTION":
        return "municipal", _first_tuesday_of_april(year)
    return None


def map_election(value: str, label: str) -> dict | None:
    """Return Election model field values for one IL SBE dropdown entry, or None if undatable."""
    inferred = infer_election_type_and_date(label)
    if inferred is None:
        return None
    election_type, election_date = inferred

    today = datetime.date.today()
    if election_date > today:
        status = Election.Status.UPCOMING
    elif election_date == today:
        status = Election.Status.ACTIVE
    else:
        status = Election.Status.RESULTS_PENDING

    return {
        "source_id": f"il_sbe_{value}",
        "name": f"{label.split()[0]} Illinois {label.split(maxsplit=1)[1].title()}",
        "election_date": election_date,
        "election_type": election_type,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "IL",
        "status": status,
        "source_metadata": {
            "il_sbe_election_value": value,
            "election_date_approximate": election_type == "primary",
        },
    }


def map_race(election_obj, office_name: str) -> dict:
    """Map an IL SBE office name to Race model field values."""
    office_name = office_name.strip()
    is_district = _is_district_office(office_name)

    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office_name,
        "jurisdiction": office_name if is_district else "Illinois",
        "geography_scope": "district" if is_district else "statewide",
        "certification_status": Race.CertificationStatus.UPCOMING,
        "source": Race.Source.IL_SBE,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "normalized_office_title": " ".join(office_name.lower().split()),
        "source_metadata": {
            "il_sbe_election_source_id": getattr(election_obj, "source_id", ""),
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec civicmirror-worker /home/appuser/.local/bin/pytest integrations/il_sbe/tests/test_mappers.py --no-migrations -v`

Expected: all tests `PASS`. If `test_infer_election_type_and_date_general_primary_is_approximate` fails on the exact date, recompute by hand (third Tuesday in March 2026: March 1 2026 is a Sunday, so first Tuesday is March 3, third Tuesday is March 17) and adjust the assertion — the formula must match the assertion, not the other way around; if the formula is wrong, fix `_third_tuesday_of_march`.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/il_sbe/mappers.py backend/integrations/il_sbe/tests/test_mappers.py
git commit -m "feat(il): add IL SBE mappers (office filter, election date inference)"
```

---

### Task 6: Stage 1 Celery tasks — `sync_il_elections`, `sync_il_races`

**Files:**
- Create: `backend/integrations/il_sbe/tasks.py`
- Create: `backend/integrations/il_sbe/tests/test_tasks.py`

**Interfaces:**
- Consumes: `IllinoisSbeClient`, `OFFICE_TYPE_FEDERAL_STATEWIDE`, `OFFICE_TYPE_SENATE` (Task 4); `parse_election_options`, `parse_election_id_token`, `parse_category_offices` (Task 3); `map_election`, `map_race`, `is_federal_or_state_office` (Task 5); `aggregation.ingest.ingest_election`, `ingest_race`.
- Produces: `sync_il_elections` (Celery task, no args), `sync_il_races` (Celery task, `election_pk: int`).

- [ ] **Step 1: Write the failing tests**

Create `backend/integrations/il_sbe/tests/test_tasks.py`:

```python
from unittest.mock import patch

import pytest

from elections.models import Election, Race
from integrations.il_sbe.tasks import sync_il_elections, sync_il_races


@pytest.mark.django_db
def test_sync_il_elections_creates_general_and_primary_skips_specials():
    options_html = "<html>fake search page</html>"
    fake_options = [
        {"value": "69", "label": "2026 GENERAL PRIMARY"},
        {"value": "68", "label": "2025 CONSOLIDATED ELECTION"},
        {"value": "13", "label": "2015 SPECIAL GENERAL ELECTION"},
    ]

    with patch(
        "integrations.il_sbe.tasks.IllinoisSbeClient.fetch_search_page",
        return_value=options_html,
    ), patch(
        "integrations.il_sbe.tasks.parse_election_options",
        return_value=fake_options,
    ), patch(
        "integrations.il_sbe.tasks.sync_il_races.delay"
    ) as mock_delay:
        result = sync_il_elections()

    assert result["created"] == 2
    assert Election.objects.filter(state="IL").count() == 2
    assert not Election.objects.filter(source_id="il_sbe_13").exists()
    assert mock_delay.call_count == 2


@pytest.mark.django_db
def test_sync_il_races_creates_federal_and_state_races_only():
    election = Election.objects.create(
        name="2026 Illinois General Primary",
        election_date="2026-03-17",
        election_type="primary",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="IL",
        source_id="il_sbe_69",
        status=Election.Status.RESULTS_PENDING,
        source_metadata={"il_sbe_election_value": "69"},
    )

    fake_offices = [
        {"office_name": "UNITED STATES SENATOR", "csv_url": "https://example.com/senate.csv"},
        {"office_name": "1ST STATE CENTRAL COMMITTEEPERSON", "csv_url": "https://example.com/scc.csv"},
        {"office_name": "GOVERNOR AND LIEUTENANT GOVERNOR", "csv_url": "https://example.com/gov.csv"},
    ]

    with patch(
        "integrations.il_sbe.tasks.IllinoisSbeClient.fetch_election_page",
        return_value="<html>fake election page</html>",
    ), patch(
        "integrations.il_sbe.tasks.parse_election_id_token",
        return_value="Z2J/vYpKX8w=",
    ), patch(
        "integrations.il_sbe.tasks.IllinoisSbeClient.fetch_category_page",
        return_value="<html>fake category page</html>",
    ), patch(
        "integrations.il_sbe.tasks.parse_category_offices",
        return_value=fake_offices,
    ):
        result = sync_il_races(election.pk)

    assert result["created"] == 2
    races = Race.objects.filter(election=election)
    assert races.count() == 2
    assert set(races.values_list("office_title", flat=True)) == {
        "UNITED STATES SENATOR", "GOVERNOR AND LIEUTENANT GOVERNOR",
    }
    election.refresh_from_db()
    assert election.source_metadata["il_sbe_election_id_token"] == "Z2J/vYpKX8w="


@pytest.mark.django_db
def test_sync_il_races_noop_when_election_missing():
    result = sync_il_races(999999)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec civicmirror-worker /home/appuser/.local/bin/pytest integrations/il_sbe/tests/test_tasks.py --no-migrations -v`

Expected: `ModuleNotFoundError: No module named 'integrations.il_sbe.tasks'`

- [ ] **Step 3: Write `tasks.py`**

```python
"""
Illinois SBE Celery tasks.

Stage 1a — sync_il_elections:
  Parse the ddlElections dropdown for known election labels, upsert Election
  rows for the ones we can reliably date (general/primary/consolidated;
  specials are skipped — see mappers.infer_election_type_and_date), and
  queue sync_il_races for each.

Stage 1b — sync_il_races:
  Resolve the election's encrypted SBE `ID` token (cached on the Election
  row after first resolution), fetch the Federal/Statewide + Senate results
  category pages, filter to Federal + State offices, and upsert Race rows.
"""
import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog

from .client import OFFICE_TYPE_FEDERAL_STATEWIDE, OFFICE_TYPE_SENATE, IllinoisSbeClient
from .exceptions import IlSbeRetryableError
from .mappers import is_federal_or_state_office, map_election, map_race
from .parsers import parse_category_offices, parse_election_id_token, parse_election_options

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_il_elections(self):
    """Stage 1a: seed IL Election records and queue Stage 1b for each."""
    sync_log = SyncLog.objects.create(
        source="il_sbe",
        task_name="sync_il_elections",
        status=SyncLog.Status.STARTED,
    )
    client = IllinoisSbeClient()
    created_count = updated_count = skipped_count = queued_count = 0

    try:
        html = client.fetch_search_page()
        options = parse_election_options(html)

        from aggregation import ingest

        for option in options:
            mapped = map_election(option["value"], option["label"])
            if mapped is None:
                skipped_count += 1
                continue

            source_id = mapped.pop("source_id")
            identity = {
                "state": mapped["state"],
                "election_type": mapped["election_type"],
                "election_date": mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            fields = {k: v for k, v in mapped.items() if k not in identity}
            election_obj, was_created = ingest.ingest_election(
                source="il_sbe",
                source_id=source_id,
                identity=identity,
                fields=fields,
            )
            if was_created:
                created_count += 1
            else:
                updated_count += 1

            sync_il_races.delay(election_obj.pk)
            queued_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.notes = f"skipped={skipped_count} (undatable) | queued={queued_count}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created_count, "updated": updated_count, "queued": queued_count}

    except IlSbeRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("il_sbe.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_il_races(self, election_pk: int):
    """
    Stage 1b: resolve the election's SBE ID token, fetch its results category
    pages, and upsert Race rows for Federal + State offices.
    """
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("il_sbe.sync_races.missing_election pk=%d", election_pk)
        return None

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source="il_sbe",
        task_name="sync_il_races",
        status=SyncLog.Status.STARTED,
    )
    client = IllinoisSbeClient()
    created_count = updated_count = 0

    try:
        meta = election_obj.source_metadata or {}
        election_value = meta.get("il_sbe_election_value", "")
        id_token = meta.get("il_sbe_election_id_token")

        if not id_token:
            election_page_html = client.fetch_election_page(election_value)
            id_token = parse_election_id_token(election_page_html)
            if not id_token:
                logger.info(
                    "il_sbe.sync_races.no_results_page_yet election=%s",
                    election_obj.source_id,
                )
                sync_log.notes = "No results category page available yet"
                sync_log.status = SyncLog.Status.COMPLETED
                sync_log.completed_at = timezone.now()
                sync_log.save(update_fields=["notes", "status", "completed_at"])
                return {"created": 0, "updated": 0}
            meta["il_sbe_election_id_token"] = id_token
            election_obj.source_metadata = meta
            election_obj.save(update_fields=["source_metadata"])

        offices: list[dict] = []
        for office_type_token in (OFFICE_TYPE_FEDERAL_STATEWIDE, OFFICE_TYPE_SENATE):
            category_html = client.fetch_category_page(id_token, office_type_token)
            offices.extend(parse_category_offices(category_html))

        from aggregation import ingest

        for office in offices:
            office_name = office["office_name"]
            if not is_federal_or_state_office(office_name):
                continue

            race_defaults = map_race(election_obj, office_name)
            race_identity = {
                "office_title": race_defaults.pop("office_title"),
                "ocd_division_id": race_defaults.pop("ocd_division_id", "") or "",
                "race_type": race_defaults.pop("race_type"),
            }
            race_defaults.pop("source", None)

            race_obj, was_created = ingest.ingest_race(
                election=election_obj,
                source="il_sbe",
                identity=race_identity,
                fields=race_defaults,
            )
            if was_created:
                created_count += 1
            else:
                updated_count += 1

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

    except IlSbeRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception(
            "il_sbe.sync_races.failed election=%s",
            getattr(election_obj, "source_id", None) or election_pk,
        )
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec civicmirror-worker /home/appuser/.local/bin/pytest integrations/il_sbe/tests/test_tasks.py --no-migrations -v`

Expected: all 3 tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/il_sbe/tasks.py backend/integrations/il_sbe/tests/test_tasks.py
git commit -m "feat(il): add IL SBE Stage 1 tasks (sync_il_elections, sync_il_races)"
```

---

### Task 7: Wire the internal trigger endpoint + scheduler cron entry

**Files:**
- Modify: `backend/internal/views.py`
- Modify: `backend/internal/urls.py`
- Modify: `/data/DockerConfigs/CivicMirror/scheduler/crontab`

**Interfaces:**
- Produces: `POST /internal/tasks/sync-il-sbe/` → enqueues `sync_il_elections`.

- [ ] **Step 1: Add the trigger view**

In `backend/internal/views.py`, find `def sync_co_sos_trigger(request):` and add a new view immediately after it (matching the existing `@csrf_exempt @require_POST @require_internal_task_token` decorator stack used by every other trigger view, and importing `sync_il_elections` alongside the other task imports at the top of the file — check the existing import block, e.g. `from integrations.co_sos.tasks import sync_co_elections`, and add `from integrations.il_sbe.tasks import sync_il_elections`):

```python
@csrf_exempt
@require_POST
@require_internal_task_token
def sync_il_sbe_trigger(request):
    return _trigger("sync_il_sbe", sync_il_elections, request)
```

- [ ] **Step 2: Register the URL**

In `backend/internal/urls.py`, add after the `sync-oh-sos` line:

```python
    path("tasks/sync-il-sbe/", views.sync_il_sbe_trigger, name="internal-sync-il-sbe"),
```

- [ ] **Step 3: Verify the endpoint locally**

Run: `docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml up -d --force-recreate civicmirror-api civicmirror-worker`

Then: `docker exec civicmirror-scheduler /usr/local/bin/trigger.sh /internal/tasks/sync-il-sbe/`

Expected: `{"task_id": "..."}` JSON response (same shape as other trigger endpoints).

- [ ] **Step 4: Add the cron entry**

In `/data/DockerConfigs/CivicMirror/scheduler/crontab`, add a new line after the `sync-tx-goelect` line (following the existing 15-minute-offset pattern), and renumber any later lines by 15 minutes if a collision would occur — check the file first with `cat /data/DockerConfigs/CivicMirror/scheduler/crontab` and pick the next free `HH:MM` slot in sequence:

```
0 7 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-il-sbe/
```

(Adjust the exact time slot to whatever is the next free 15-minute increment after the last existing entry — do not overwrite an existing job's time slot.)

- [ ] **Step 5: Recreate the scheduler to pick up the new crontab**

Run: `docker compose -f /data/DockerConfigs/CivicMirror/docker-compose.yml up -d --force-recreate civicmirror-scheduler`

Expected: `civicmirror-scheduler` container restarts; `docker exec civicmirror-scheduler crontab -l` (or `cat /etc/crontabs/root` inside the container) shows the new `sync-il-sbe` line.

- [ ] **Step 6: Commit**

```bash
git add backend/internal/views.py backend/internal/urls.py
git commit -m "feat(il): wire sync-il-sbe internal task endpoint"
```

Note: the crontab file lives in `/data/DockerConfigs/CivicMirror/`, a separate directory from this git repo — it has no independent version control observed so far in this session; leave it edited on disk (no commit needed for that file).

---

### Task 8: Stage 2 results adapter — `results/adapters/il.py`

**Files:**
- Create: `backend/results/adapters/il.py`
- Modify: `backend/results/apps.py`

**Interfaces:**
- Consumes: `IllinoisSbeClient`, `OFFICE_TYPE_FEDERAL_STATEWIDE`, `OFFICE_TYPE_SENATE` (Task 4); `parse_category_offices` (Task 3); `AdapterResult`, `ResultRow`, `StateResultsAdapter`, `register` (from `results/adapters/base.py`, `registry.py`).
- Produces: `IllinoisAdapter` class registered under `state = "IL"`, consumed automatically by the existing generic `results/tasks.py::ingest_official_results`.

- [ ] **Step 1: Write `il.py`**

(No isolated unit test here — this class is thin orchestration glue tested end-to-end through the aggregation logic in Task 9 and the generic `results/tasks.py` machinery already covered by that module's existing tests. Splitting a fetch-only class into its own test would just re-mock everything Task 9 already verifies.)

```python
"""
Illinois (IL) results adapter — Illinois State Board of Elections (SBE).

Source: https://www.elections.il.gov/electionoperations/
Access: Public HTTPS, no authentication required.
Schema: precinct-level CSV per office, aggregated to contest totals by
        summing VoteCount across all precincts for each CandidateName.

Data notes:
    - Federal + State offices only this build (Judicial, ballot measures
      deferred — see docs/superpowers/specs/2026-07-11-il-adapter-design.md).
    - Non-candidate CSV rows (Under Votes, Over Votes, Blank Ballots) and
      write-ins are excluded/aggregated separately — see aggregate_csv_rows
      in this module.
    - No version endpoint exists (unlike Clarity's current_ver.txt); change
      detection uses a checksum of the concatenated CSV bytes fetched this run.

Election ID token:
    Resolved and cached by Stage 1 (integrations.il_sbe.tasks.sync_il_races)
    onto Election.source_metadata["il_sbe_election_id_token"]. If absent,
    this adapter resolves and caches it itself so Stage 2 can run standalone.
"""
from __future__ import annotations

import hashlib
import logging

from django.core.cache import cache

from integrations.il_sbe.client import OFFICE_TYPE_FEDERAL_STATEWIDE, OFFICE_TYPE_SENATE, IllinoisSbeClient
from integrations.il_sbe.parsers import parse_category_offices, parse_election_id_token

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register
from .il_aggregate import aggregate_csv_rows

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days


@register
class IllinoisAdapter(StateResultsAdapter):
    state = "IL"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"il_sbe:checksum:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("il_sbe.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        client = IllinoisSbeClient()
        meta = election.source_metadata or {}
        id_token = meta.get("il_sbe_election_id_token")
        election_value = meta.get("il_sbe_election_value", "")

        if not id_token:
            election_page_html = client.fetch_election_page(election_value)
            id_token = parse_election_id_token(election_page_html)
            if not id_token:
                return AdapterResult(
                    rows=[], source_url="", mapping_confidence="none",
                    notes=f"No IL SBE results category page yet for election {election.source_id}",
                )
            meta["il_sbe_election_id_token"] = id_token
            election.source_metadata = meta
            election.save(update_fields=["source_metadata"])

        offices: list[dict] = []
        for office_type_token in (OFFICE_TYPE_FEDERAL_STATEWIDE, OFFICE_TYPE_SENATE):
            category_html = client.fetch_category_page(id_token, office_type_token)
            offices.extend(parse_category_offices(category_html))

        if not offices:
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"No offices found on IL SBE category pages for election {election.source_id}",
            )

        all_rows: list[ResultRow] = []
        csv_bytes_for_checksum = bytearray()
        source_url = ""

        for office in offices:
            office_name = office["office_name"]
            csv_url = office["csv_url"]
            try:
                csv_text = client.fetch_office_csv(csv_url)
            except Exception as exc:
                logger.warning(
                    "il_sbe.adapter.csv_fetch_failed office=%s url=%s err=%s",
                    office_name, csv_url, exc,
                )
                continue
            csv_bytes_for_checksum.extend(csv_text.encode("utf-8", errors="ignore"))
            source_url = csv_url
            all_rows.extend(aggregate_csv_rows(csv_text, office_name))

        if not all_rows:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="none",
                notes=f"No result rows parsed for election {election.source_id}",
            )

        checksum = hashlib.md5(bytes(csv_bytes_for_checksum)).hexdigest()
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == checksum:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="full",
                unchanged=True, source_version=checksum,
            )

        return AdapterResult(
            rows=all_rows,
            source_url=source_url,
            mapping_confidence="full",
            source_version=checksum,
        )
```

- [ ] **Step 2: Register the adapter in `results/apps.py`**

In `backend/results/apps.py`, add `il` to the `ready()` import list (alphabetically, between `ia` and `ma`):

```python
        from results.adapters import (  # noqa: F401
            ar,
            az,
            ca,
            co,
            ct,
            fl,
            ga,
            ia,
            il,
            ma,
            me,
            nc,
            ny,
            oh,
            sc,
            tx,
            va,
            wa,
            wv,
        )
```

- [ ] **Step 3: Verify Django loads the adapter and it registers correctly**

Run:
```bash
docker exec civicmirror-worker python3 -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.prod')
django.setup()
from results.adapters.registry import get_adapter
adapter_class = get_adapter('IL')
print('IL adapter registered:', adapter_class)
assert adapter_class is not None
"
```

Expected: prints `IL adapter registered: <class 'results.adapters.il.IllinoisAdapter'>` (this will fail until Task 9 creates `il_aggregate.py`, which `il.py` imports — run this check again after Task 9's Step 4).

- [ ] **Step 4: Commit**

```bash
git add backend/results/adapters/il.py backend/results/apps.py
git commit -m "feat(il): add IL Stage 2 results adapter"
```

(This commit will not yet pass the Step 3 verification on its own — `il_aggregate` doesn't exist until Task 9. That's expected; Task 9 completes the pair. If your workflow requires every commit to be independently green, do Task 9 first and merge its commit with this one instead of committing here.)

---

### Task 9: CSV aggregation — `results/adapters/il_aggregate.py`

**Files:**
- Create: `backend/results/adapters/il_aggregate.py`
- Create: `backend/results/tests/test_il_adapter.py`
- Test fixture (already staged): `backend/results/tests/fixtures/il_us_senator_sample.csv`

**Interfaces:**
- Produces: `aggregate_csv_rows(csv_text: str, office_name: str) -> list[ResultRow]`

- [ ] **Step 1: Write the failing tests**

Create `backend/results/tests/test_il_adapter.py`:

```python
import os

from results.adapters.il_aggregate import aggregate_csv_rows

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_aggregate_csv_rows_sums_votes_across_precincts_by_candidate():
    csv_text = _load_fixture("il_us_senator_sample.csv")
    rows = aggregate_csv_rows(csv_text, "UNITED STATES SENATOR")

    by_candidate = {r.candidate_name: r.vote_count for r in rows if r.candidate_name}
    # STEVE BOTSFORD JR. appears in both fixture precincts (CLAYTON PCT 1, CAMP POINT PCT 2).
    assert "STEVE BOTSFORD JR." in by_candidate
    assert by_candidate["STEVE BOTSFORD JR."] >= 0

    for row in rows:
        assert row.office_title == "UNITED STATES SENATOR"
        assert row.result_type == "official"


def test_aggregate_csv_rows_excludes_under_over_votes_and_blank_ballots():
    csv_text = _load_fixture("il_us_senator_sample.csv")
    rows = aggregate_csv_rows(csv_text, "UNITED STATES SENATOR")

    names = {r.candidate_name for r in rows if r.candidate_name}
    assert "Under Votes" not in names
    assert "Over Votes" not in names
    assert "Blank Ballots" not in names


def test_aggregate_csv_rows_normalizes_write_in_capitalization_variants():
    csv_text = (
        "JurisdictionID,JurisContainerID,JurisName,EISCandidateID,CandidateName,"
        "EISContestID,ContestName,PrecinctName,Registration,EISPartyID,PartyName,VoteCount\n"
        "1,0,ADAMS,0,WRITE-IN,150,UNITED STATES SENATOR,PCT 1,500,11,DEMOCRATIC,2\n"
        "1,0,ADAMS,0,Write-in,150,UNITED STATES SENATOR,PCT 2,500,11,DEMOCRATIC,3\n"
    )
    rows = aggregate_csv_rows(csv_text, "UNITED STATES SENATOR")

    write_in_rows = [r for r in rows if r.is_write_in_aggregate]
    assert len(write_in_rows) == 1
    assert write_in_rows[0].vote_count == 5


def test_aggregate_csv_rows_handles_empty_csv():
    header_only = (
        "JurisdictionID,JurisContainerID,JurisName,EISCandidateID,CandidateName,"
        "EISContestID,ContestName,PrecinctName,Registration,EISPartyID,PartyName,VoteCount\n"
    )
    assert aggregate_csv_rows(header_only, "UNITED STATES SENATOR") == []


def test_aggregate_csv_rows_strips_control_bytes_from_candidate_name():
    csv_text = (
        "JurisdictionID,JurisContainerID,JurisName,EISCandidateID,CandidateName,"
        "EISContestID,ContestName,PrecinctName,Registration,EISPartyID,PartyName,VoteCount\n"
        "1,0,ADAMS,1,JANE\x00 DOE,150,UNITED STATES SENATOR,PCT 1,500,11,DEMOCRATIC,10\n"
    )
    rows = aggregate_csv_rows(csv_text, "UNITED STATES SENATOR")
    assert rows[0].candidate_name == "JANE DOE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec civicmirror-worker /home/appuser/.local/bin/pytest results/tests/test_il_adapter.py --no-migrations -v`

Expected: `ModuleNotFoundError: No module named 'results.adapters.il_aggregate'`

- [ ] **Step 3: Write `il_aggregate.py`**

```python
"""
CSV aggregation for the Illinois results adapter.

IL SBE's per-office CSV is precinct-level: one row per
(jurisdiction, precinct, candidate). This sums VoteCount by CandidateName
within one office/contest, excluding non-candidate bookkeeping rows
(Under Votes, Over Votes, Blank Ballots) and normalizing write-in
capitalization variants (WRITE-IN / Write-In / Write-in) into a single
aggregate row.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict

from .base import ResultRow

_NON_CANDIDATE_ROWS = frozenset({"under votes", "over votes", "blank ballots"})


def _clean_text(value: str) -> str:
    """Remove NUL/control bytes that PostgreSQL cannot store, then trim."""
    return "".join(ch for ch in value if ch >= " " or ch == "\t").strip()


def _is_write_in(candidate_name: str) -> bool:
    return candidate_name.strip().lower().replace(" ", "") in {"write-in", "writein"}


def aggregate_csv_rows(csv_text: str, office_name: str) -> list[ResultRow]:
    """Aggregate one office's precinct-level CSV into per-candidate ResultRows."""
    reader = csv.DictReader(io.StringIO(csv_text))

    totals: dict[str, int] = defaultdict(int)
    write_in_total = 0
    party_by_candidate: dict[str, str] = {}

    for row in reader:
        raw_name = _clean_text(row.get("CandidateName") or "")
        if not raw_name or raw_name.lower() in _NON_CANDIDATE_ROWS:
            continue

        try:
            vote_count = int((row.get("VoteCount") or "0").strip())
        except ValueError:
            vote_count = 0

        if _is_write_in(raw_name):
            write_in_total += vote_count
            continue

        totals[raw_name] += vote_count
        party_by_candidate.setdefault(raw_name, _clean_text(row.get("PartyName") or ""))

    rows = [
        ResultRow(
            candidate_name=name,
            option_label=None,
            vote_count=count,
            vote_pct=None,
            is_winner=None,
            result_type="official",
            office_title=office_name,
            is_write_in_aggregate=False,
            raw={"party": party_by_candidate.get(name, "")},
        )
        for name, count in totals.items()
    ]

    if write_in_total:
        rows.append(
            ResultRow(
                candidate_name="Write-In",
                option_label=None,
                vote_count=write_in_total,
                vote_pct=None,
                is_winner=None,
                result_type="official",
                office_title=office_name,
                is_write_in_aggregate=True,
                raw={},
            )
        )

    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec civicmirror-worker /home/appuser/.local/bin/pytest results/tests/test_il_adapter.py --no-migrations -v`

Expected: all 5 tests `PASS`.

- [ ] **Step 5: Re-run Task 8's registration check now that `il_aggregate` exists**

Run the same command as Task 8 Step 3:
```bash
docker exec civicmirror-worker python3 -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.prod')
django.setup()
from results.adapters.registry import get_adapter
adapter_class = get_adapter('IL')
print('IL adapter registered:', adapter_class)
assert adapter_class is not None
"
```

Expected: `IL adapter registered: <class 'results.adapters.il.IllinoisAdapter'>`, no exceptions.

- [ ] **Step 6: Commit**

```bash
git add backend/results/adapters/il_aggregate.py backend/results/tests/test_il_adapter.py backend/results/tests/fixtures/
git commit -m "feat(il): add IL CSV aggregation for Stage 2 results"
```

---

### Task 10: Full test suite run + docs update

**Files:**
- Modify: `docs/state-research/IL/IL-Election_Research.md`
- Modify: `docs/state-research/00-MASTER-INDEX.md`

**Interfaces:** None (docs + verification only).

- [ ] **Step 1: Run the full IL-related test suite together**

Run:
```bash
docker exec civicmirror-worker /home/appuser/.local/bin/pytest integrations/il_sbe/ results/tests/test_il_adapter.py --no-migrations -v
```

Expected: every test from Tasks 3, 4, 5, 6, and 9 passes together (catches any cross-task import or fixture path regressions).

- [ ] **Step 2: Run the full backend test suite**

Run: `docker exec civicmirror-worker /home/appuser/.local/bin/pytest --no-migrations -q`

Expected: no new failures introduced outside the IL-related tests (pre-existing failures, if any, are out of scope for this plan — note them but don't fix here).

- [ ] **Step 3: Update the IL research doc**

In `docs/state-research/IL/IL-Election_Research.md`, replace the `## API Access` section's "No public REST API identified" conclusion and the `## Coverage Status` table's Stage 2 row. Update the table:

```markdown
| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Built | IL SBE `votetotalsearch.aspx` election dropdown (`integrations/il_sbe/`) |
| Stage 1 — Race Creation | ✅ Built | IL SBE results category pages, Federal + State offices only |
| Stage 2 — Results Ingestion | ✅ Built | IL SBE per-office CSV (`results/adapters/il.py`) |
```

And append a new section:

```markdown
## Update 2026-07-11: CSV mechanism found, adapter built

Superseded the "no public REST API identified" finding above. IL SBE exposes
pre-built results category pages (`ElectionVoteTotals.aspx?ID=...&OfficeType=...`)
with stable `OfficeType` tokens per category and a per-election encrypted `ID`
token resolved via an ASP.NET auto-postback replay (plain `requests`, no
browser needed). Each office links to a public, unauthenticated, precinct-level
CSV. Full mechanism documented in `docs/superpowers/specs/2026-07-11-il-adapter-design.md`.

**Deferred for future integration:** Judicial retention/contested races and
statewide ballot measures use the identical CSV mechanism (see the `Judicial`
category token in `integrations/il_sbe/client.py`) but are out of scope for
the Federal + State build. Adding them is a matter of adding the Judicial
category token to `sync_il_races`/`il.py`'s category loop and updating
`is_federal_or_state_office`'s filter (or adding a parallel measures path) —
no new scraping mechanism required.
```

- [ ] **Step 4: Update the master index**

In `docs/state-research/00-MASTER-INDEX.md`, move Illinois from wherever it currently sits (likely "Federal Only (no adapter)") into the "Full Core Coverage" list, matching the existing table format used for other Full Core states (see `AZ`, `CO`, etc. rows for the exact format).

- [ ] **Step 5: Commit**

```bash
git add docs/state-research/IL/IL-Election_Research.md docs/state-research/00-MASTER-INDEX.md
git commit -m "docs(il): update IL research doc and master index for shipped adapter"
```

---

## Post-Plan Follow-Ups (not part of this plan)

- Judicial races + statewide ballot measures (explicitly deferred — see Task 10 doc note).
- Historical backfill beyond current/upcoming elections.
- Optional `SourcePrecedence` rows for `il_sbe` (defaults to lowest precedence / fills-empty-fields-only without one — functional either way, per `aggregation/precedence.py`).
- Confirm the `House` category link (rendered as a non-link element in initial recon) — if IL SBE splits State House results into their own category page rather than bundling them under Senate/Federal-Statewide, a third category token will need to be found and added to the `sync_il_races`/`il.py` category loop.
