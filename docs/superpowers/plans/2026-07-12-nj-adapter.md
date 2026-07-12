# New Jersey (NJ) Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add New Jersey to Near Core Coverage — Stage 2 (results ingestion) for the ~16 counties running Clarity-pattern infrastructure, with Stage 1 continuing to rely on the existing Google Civic API election sync, enriched with a per-election county-URL discovery task.

**Architecture:** A new `integrations/nj_elections/` app scrapes NJ's election-night-results page to discover which counties are on Clarity-pattern infrastructure and their per-election IDs, storing this on the existing Civic-API-created `Election.source_metadata`. A new `results/adapters/nj.py` (`NewJerseyAdapter(ClarityAdapter)`) fans out to each in-scope county's Clarity JSON API, normalizes office titles and candidate names through `results/adapters/nj_normalize.py` (office titles and candidate names are **not** consistent strings across counties — confirmed via live data, see the design spec), and aggregates into one canonical result set per election.

**Tech Stack:** Django, Celery, `requests`, `beautifulsoup4`, PostgreSQL.

## Global Constraints

- Scope is the ~16 Clarity-pattern counties only. The 5 off-platform counties (Bergen, Camden, Sussex, Warren, Hunterdon) are explicitly deferred — do not build scrapers for them in this plan.
- No live network calls in CI — all parser/normalization/aggregation tests run against fixture files.
- Follow existing per-state conventions: `ClarityAdapter` (`results/adapters/clarity.py`) for the Stage 2 base, `co_sos`'s `(office, district, party)` primary-race grouping precedent for how party fits into race identity.
- Run tests with `pytest --no-migrations`.
- **Every task that touches the internal trigger endpoint MUST include the `TASK_LOCKS` registry entry in the same commit** (`backend/internal/task_locks.py`). IL's adapter shipped without this and got a live 500 on first real invocation, caught only by manual post-merge testing — `manage.py check` does not catch a missing dict key used at runtime. The task wiring the endpoint (Task 5) must add the entry and include a live-trigger verification step before being considered done.
- No new `Race.Source` value is needed — NJ Stage 1 uses the existing `CIVIC_API` source; Stage 2-bootstrapped races use the existing `RESULTS_ADAPTER` source (both already exist in `elections/models.py`; no migration required).

---

## Recon Facts (grounding for this plan — confirmed live on 2026-07-12)

- County table source: `https://nj.gov/state/elections/election-night-results.shtml`. Table rows follow: `<td>{County} County<br />{optional HTML comment}<a href="{url}" class="elect_results">...</a></td>`. **Verified with a working BeautifulSoup parser against the real fixture — extracts all 21/21 counties correctly** (see Task 2).
- In-scope (Clarity-pattern) hostnames, confirmed live: `results.enr.clarityelections.com`, `admin.enr.clarityelections.com` (Hudson only), `www.livevoterturnout.com` (Salem only, legacy Clarity branding — confirmed via matching `LiveResultsVerifierColors.css`/`LiveResultsScripts_v4.1.js` asset names against OH's known Clarity deployments).
- Out-of-scope hostnames, confirmed live: `www.bergencountyclerk.gov`, `www.camdencounty.com`, `www.sussex.nj.us`, `www.warrencountyvotes.com`, `www.co.hunterdon.nj.us`.
- Election ID extraction: numeric path segment (e.g. `/NJ/Atlantic/126380/...` → `126380`; `/ENR/salemnjenr/12/...` → `12`, though Salem's exact `current_ver.txt` path beyond this is unconfirmed — see Task 7's note). Counties with no ID posted yet (Cumberland, Passaic, Somerset as of this recon) yield `election_id=None` and are skipped, not errored — IDs get discovered on a later run once posted.
- **Verified full pipeline against the real fixture**: 16 counties correctly classified in-scope, 5 correctly excluded, matching the manual recon count exactly. Working code is in Task 2.
- **Critical finding**: office titles for the identical statewide contest vary across counties (`"DEM U.S. Senator"` / `"US Senate (DEM)"` / `"United States Senator (DEM)"` / `"U.S. Senate (DEM)"` / `"DEM UNITED STATES SENATE"`), and candidate names do too (`"Cory BOOKER"` / `"Cory Booker"` / `"DEM Cory BOOKER"`, the last with party embedded directly in the candidate-name field). A normalization layer is required (Task 6) — **verified working against all 5 real office-title variants and all 3 real candidate-name variants** in recon; the tested code is in Task 6.
- **Bootstrap-grouping constraint**: `results/tasks.py::_bootstrap_races_from_results` groups parsed rows into `Race` records purely by `office_title` string (`rows_by_office: dict[str, list]`, keyed by `row.office_title` — see `results/tasks.py:120-125`). For primary elections, Clarity represents each party's primary as a **separate contest** (e.g. `"DEM U.S. Senator"` and `"REP U.S. Senator"` are two different entries in the same county's `summary.json`, each with their own candidate list). If both were normalized to the same plain `"UNITED STATES SENATOR"` office_title, the bootstrap would incorrectly merge two different contests (different candidates, different winners) into one `Race`. **The normalization layer's canonical display title must therefore embed the party for primaries** (e.g. `"UNITED STATES SENATOR (DEM PRIMARY)"`), and leave it off for general elections (no party token found in the source data) — this is what keeps Dem/Rep primaries as separate `Race` rows while still aggregating correctly across counties within one party's primary. See Task 6.
- Fixtures captured live and already staged:
  - `backend/integrations/nj_elections/tests/fixtures/election_night_results.html` (real county table, all 21 rows)
  - `backend/results/tests/fixtures/nj_atlantic_summary.json` (real Atlantic County `summary.json`, 204 contests)
  - `backend/results/tests/fixtures/nj_burlington_summary.json` (real Burlington County `summary.json`, 495 contests — different office-title phrasing than Atlantic, useful for exercising the normalization mismatch directly)

---

### Task 1: Scaffold `integrations/nj_elections` app

**Files:**
- Create: `backend/integrations/nj_elections/__init__.py`
- Create: `backend/integrations/nj_elections/apps.py`
- Create: `backend/integrations/nj_elections/exceptions.py`
- Create: `backend/integrations/nj_elections/tests/__init__.py`
- Modify: `backend/config/settings/base.py`

**Interfaces:**
- Produces: `NjElectionsError`, `NjElectionsRetryableError` exception classes for later tasks.

- [ ] **Step 1: Create the app package**

`backend/integrations/nj_elections/__init__.py` — empty file.

- [ ] **Step 2: Create `apps.py`**

```python
from django.apps import AppConfig


class NewJerseyElectionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.nj_elections"
    label = "nj_elections"
    verbose_name = "New Jersey Elections Integration"
```

- [ ] **Step 3: Create `exceptions.py`**

```python
class NjElectionsError(Exception):
    """Non-retryable New Jersey elections integration error."""


class NjElectionsRetryableError(NjElectionsError):
    """Transient error that warrants a Celery retry."""
```

- [ ] **Step 4: Register the app**

In `backend/config/settings/base.py`, find `'integrations.il_sbe',` in `INSTALLED_APPS` and add immediately after it:

```python
    'integrations.nj_elections',
```

- [ ] **Step 5: Create the tests package**

`backend/integrations/nj_elections/tests/__init__.py` — empty file.

- [ ] **Step 6: Verify Django can load the app**

Run: `docker exec civicmirror-worker python3 manage.py check` — but see the note below on how to actually run commands in this build.

**Environment note (applies to every remaining task in this plan):** Follow the same isolated-worktree + throwaway-test-image pattern used for the IL adapter build. Do not use `civicmirror-worker` directly (it runs whatever is on `main`, not this branch). From the worktree root: `docker build -t nj-adapter-test:latest backend`, then `docker run --rm --network civicmirror_default --env-file /data/DockerConfigs/CivicMirror/.env --entrypoint sh nj-adapter-test:latest -c "pip install -q -r requirements/dev.txt >/dev/null 2>&1 && <command>"`.

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 7: Commit**

```bash
git add backend/integrations/nj_elections/__init__.py backend/integrations/nj_elections/apps.py backend/integrations/nj_elections/exceptions.py backend/integrations/nj_elections/tests/__init__.py backend/config/settings/base.py
git commit -m "feat(nj): scaffold integrations.nj_elections app"
```

---

### Task 2: Parsers — county table parsing + Clarity-host classification

**Files:**
- Create: `backend/integrations/nj_elections/parsers.py`
- Create: `backend/integrations/nj_elections/tests/test_parsers.py`
- Test fixture (already staged): `backend/integrations/nj_elections/tests/fixtures/election_night_results.html`

**Interfaces:**
- Produces:
  - `parse_county_urls(html: str) -> list[dict]` — `[{"county": "Atlantic", "url": "https://..."}, ...]`, one entry per county row (21 total on the real fixture), `url` is `None` if no link is present.
  - `classify_clarity_counties(county_urls: list[dict]) -> list[dict]` — `[{"county": "Atlantic", "url": "...", "election_id": "126380"}, ...]`, filtered to only in-scope (Clarity-pattern) hostnames; `election_id` is `None` for a Clarity county with no ID posted yet.

This task's code has already been prototyped and verified against the real fixture during design recon (16 in-scope, 5 excluded, exact match to manual count) — transcribe it directly.

- [ ] **Step 1: Write the failing tests**

Create `backend/integrations/nj_elections/tests/test_parsers.py`:

```python
import os

import pytest

from integrations.nj_elections.parsers import classify_clarity_counties, parse_county_urls

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_county_urls_extracts_all_21_counties():
    html = _load_fixture("election_night_results.html")
    counties = parse_county_urls(html)
    assert len(counties) == 21
    names = {c["county"] for c in counties}
    assert "Atlantic" in names
    assert "Cape May" in names  # multi-word county name
    assert "Bergen" in names  # non-Clarity county still gets parsed here


def test_parse_county_urls_captures_real_clarity_url():
    html = _load_fixture("election_night_results.html")
    counties = parse_county_urls(html)
    atlantic = next(c for c in counties if c["county"] == "Atlantic")
    assert atlantic["url"] == "https://results.enr.clarityelections.com/NJ/Atlantic/126380/web.345435/#/summary"


def test_classify_clarity_counties_returns_16_in_scope():
    html = _load_fixture("election_night_results.html")
    counties = parse_county_urls(html)
    clarity = classify_clarity_counties(counties)
    assert len(clarity) == 16
    names = {c["county"] for c in clarity}
    assert names == {
        "Atlantic", "Burlington", "Cape May", "Cumberland", "Essex", "Gloucester",
        "Hudson", "Mercer", "Middlesex", "Monmouth", "Morris", "Ocean", "Passaic",
        "Salem", "Somerset", "Union",
    }


def test_classify_clarity_counties_excludes_off_platform_counties():
    html = _load_fixture("election_night_results.html")
    counties = parse_county_urls(html)
    clarity = classify_clarity_counties(counties)
    names = {c["county"] for c in clarity}
    for excluded in ("Bergen", "Camden", "Sussex", "Warren", "Hunterdon"):
        assert excluded not in names


def test_classify_clarity_counties_extracts_election_id_when_present():
    html = _load_fixture("election_night_results.html")
    counties = parse_county_urls(html)
    clarity = classify_clarity_counties(counties)
    atlantic = next(c for c in clarity if c["county"] == "Atlantic")
    assert atlantic["election_id"] == "126380"


def test_classify_clarity_counties_returns_none_id_when_not_posted():
    html = _load_fixture("election_night_results.html")
    counties = parse_county_urls(html)
    clarity = classify_clarity_counties(counties)
    for county_name in ("Cumberland", "Passaic", "Somerset"):
        entry = next(c for c in clarity if c["county"] == county_name)
        assert entry["election_id"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `... pytest --no-migrations -v integrations/nj_elections/tests/test_parsers.py`

Expected: `ModuleNotFoundError: No module named 'integrations.nj_elections.parsers'`

- [ ] **Step 3: Write `parsers.py`**

```python
"""
Parsers for New Jersey's election-night-results county table.

NJ has no state-level results aggregator — each of 21 counties publishes
results independently. This page (nj.gov/state/elections/election-night-
results.shtml) lists each county's results URL. Most, but not all, counties
run some flavor of Clarity Elections (ENR Web 4.x) — this module identifies
which.

Confirmed live 2026-07-12: 16 of 21 counties are Clarity-pattern, spread
across three hostnames due to different hosting arrangements:
  - results.enr.clarityelections.com (majority)
  - admin.enr.clarityelections.com (Hudson only, alternate subdomain)
  - www.livevoterturnout.com (Salem only, legacy Clarity branding —
    confirmed same underlying platform via matching asset filenames to
    other states' known Clarity deployments)
The remaining 5 counties (Bergen, Camden, Sussex, Warren, Hunterdon) each
run their own independent site with no common mechanism — out of scope.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

CLARITY_HOSTS: frozenset[str] = frozenset({
    "results.enr.clarityelections.com",
    "admin.enr.clarityelections.com",
    "www.livevoterturnout.com",
})

_COUNTY_ROW_RE = re.compile(r'^([A-Za-z. ]+) County')


def parse_county_urls(html: str) -> list[dict]:
    """Extract {county, url} for all 21 counties from the results page table."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for td in soup.find_all("td"):
        text = td.get_text(" ", strip=True)
        match = _COUNTY_ROW_RE.match(text)
        if not match:
            continue
        link = td.find("a", class_="elect_results")
        out.append({
            "county": match.group(1).strip(),
            "url": link["href"] if link else None,
        })
    return out


def classify_clarity_counties(county_urls: list[dict]) -> list[dict]:
    """
    Filter to counties on Clarity-pattern infrastructure and extract each
    county's numeric election ID from its URL path. A Clarity county with
    no ID posted yet for the current cycle returns election_id=None (still
    included — the caller decides whether to skip it).
    """
    in_scope = []
    for entry in county_urls:
        url = entry["url"]
        if not url:
            continue
        host = urlparse(url).hostname
        if host not in CLARITY_HOSTS:
            continue
        id_match = re.search(r'/(\d+)(?:/|$)', urlparse(url).path)
        in_scope.append({
            "county": entry["county"],
            "url": url,
            "election_id": id_match.group(1) if id_match else None,
        })
    return in_scope
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `... pytest --no-migrations -v integrations/nj_elections/tests/test_parsers.py`

Expected: all 6 tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/nj_elections/parsers.py backend/integrations/nj_elections/tests/test_parsers.py
git commit -m "feat(nj): add county table parser and Clarity-host classifier"
```

---

### Task 3: Client — fetch the election-night-results page

**Files:**
- Create: `backend/integrations/nj_elections/client.py`
- Create: `backend/integrations/nj_elections/tests/test_client.py`

**Interfaces:**
- Produces: `NewJerseyElectionsClient` class with `fetch_enr_page() -> str`.

This is much simpler than IL's client — a single GET, no postback replay needed.

- [ ] **Step 1: Write the failing test**

Create `backend/integrations/nj_elections/tests/test_client.py`:

```python
from unittest.mock import MagicMock, patch

from integrations.nj_elections.client import NewJerseyElectionsClient


def test_fetch_enr_page_returns_response_text():
    client = NewJerseyElectionsClient()
    mock_response = MagicMock(status_code=200, text="<html>county table</html>")

    with patch.object(client._session, "get", return_value=mock_response) as mock_get:
        result = client.fetch_enr_page()

    assert result == "<html>county table</html>"
    mock_get.assert_called_once()


def test_fetch_enr_page_retries_on_retryable_status():
    client = NewJerseyElectionsClient(max_retries=2)
    ok_response = MagicMock(status_code=200, text="<html>ok</html>")
    blocked_response = MagicMock(status_code=503)

    with patch.object(
        client._session, "get", side_effect=[blocked_response, ok_response]
    ) as mock_get:
        result = client.fetch_enr_page()

    assert result == "<html>ok</html>"
    assert mock_get.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `... pytest --no-migrations -v integrations/nj_elections/tests/test_client.py`

Expected: `ModuleNotFoundError: No module named 'integrations.nj_elections.client'`

- [ ] **Step 3: Write `client.py`**

```python
"""
New Jersey Division of Elections HTTP client.

Source: https://nj.gov/state/elections/election-night-results.shtml
No authentication required. A single page lists all 21 counties' results
URLs — no per-election postback or token resolution needed (unlike IL).
"""
from __future__ import annotations

import logging

import requests

from .exceptions import NjElectionsRetryableError

logger = logging.getLogger(__name__)

ENR_PAGE_URL = "https://nj.gov/state/elections/election-night-results.shtml"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_RETRYABLE_STATUSES = {403, 429, 500, 502, 503, 504}


class NewJerseyElectionsClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def fetch_enr_page(self) -> str:
        """GET the election-night-results county table page."""
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(ENR_PAGE_URL, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise NjElectionsRetryableError(f"NJ ENR page GET failed: {exc}") from exc
                logger.warning("nj_elections.client.retry attempt=%d err=%s", attempt, exc)
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise NjElectionsRetryableError(f"NJ ENR page returned {resp.status_code}")
                logger.warning(
                    "nj_elections.client.retry attempt=%d status=%d", attempt, resp.status_code,
                )
                continue
            resp.raise_for_status()
            return resp.text
        raise NjElectionsRetryableError("NJ ENR page GET retries exhausted")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `... pytest --no-migrations -v integrations/nj_elections/tests/test_client.py`

Expected: both tests `PASS`.

- [ ] **Step 5: Manually verify against the live site (not part of CI)**

Run:
```bash
... python3 -c "
from integrations.nj_elections.client import NewJerseyElectionsClient
from integrations.nj_elections.parsers import classify_clarity_counties, parse_county_urls

client = NewJerseyElectionsClient()
html = client.fetch_enr_page()
counties = parse_county_urls(html)
clarity = classify_clarity_counties(counties)
print('total counties:', len(counties))
print('in-scope (Clarity):', len(clarity))
assert len(counties) == 21
assert len(clarity) >= 10
for c in clarity:
    print(' ', c['county'], c['election_id'])
"
```

Expected: `total counties: 21`, `in-scope (Clarity): 16` (or close — county coverage can shift slightly between recon and implementation as counties post/remove IDs). This confirms the live pipeline still works as of implementation time, not just at recon time.

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/nj_elections/client.py backend/integrations/nj_elections/tests/test_client.py
git commit -m "feat(nj): add NJ elections HTTP client"
```

---

### Task 4: Stage 1 enrichment task — `sync_nj_county_urls`

**Files:**
- Create: `backend/integrations/nj_elections/tasks.py`
- Create: `backend/integrations/nj_elections/tests/test_tasks.py`

**Interfaces:**
- Consumes: `NewJerseyElectionsClient`, `classify_clarity_counties`, `parse_county_urls`.
- Produces: `sync_nj_county_urls` (Celery task, no args).

Unlike IL/CO's Stage 1, this task does **not** create `Election` rows (NJ Stage 1 stays on the existing Civic API sync) — it only enriches existing NJ `Election` rows with county URL data, so it does not use `aggregation.ingest`.

- [ ] **Step 1: Write the failing tests**

Create `backend/integrations/nj_elections/tests/test_tasks.py`:

```python
from unittest.mock import patch

import pytest

from elections.models import Election
from integrations.nj_elections.tasks import sync_nj_county_urls


@pytest.mark.django_db
def test_sync_nj_county_urls_updates_active_nj_elections():
    election = Election.objects.create(
        name="2026 New Jersey General Election",
        election_date="2026-11-03",
        election_type="general",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NJ",
        source_id="civic_api_nj_2026_general",
        status=Election.Status.RESULTS_PENDING,
        source_metadata={"some_existing_key": "preserved"},
    )
    other_state_election = Election.objects.create(
        name="2026 Ohio General Election",
        election_date="2026-11-03",
        election_type="general",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="OH",
        source_id="civic_api_oh_2026_general",
        status=Election.Status.RESULTS_PENDING,
    )

    fake_clarity_counties = [
        {"county": "Atlantic", "url": "https://results.enr.clarityelections.com/NJ/Atlantic/126380/", "election_id": "126380"},
        {"county": "Cumberland", "url": "https://results.enr.clarityelections.com/NJ/Cumberland/", "election_id": None},
    ]

    with patch(
        "integrations.nj_elections.tasks.NewJerseyElectionsClient.fetch_enr_page",
        return_value="<html>fake page</html>",
    ), patch(
        "integrations.nj_elections.tasks.parse_county_urls",
        return_value=[{"county": "Atlantic", "url": "x"}, {"county": "Cumberland", "url": "y"}],
    ), patch(
        "integrations.nj_elections.tasks.classify_clarity_counties",
        return_value=fake_clarity_counties,
    ):
        result = sync_nj_county_urls()

    assert result["updated"] == 1
    election.refresh_from_db()
    assert election.source_metadata["some_existing_key"] == "preserved"
    assert election.source_metadata["nj_county_urls"] == fake_clarity_counties

    other_state_election.refresh_from_db()
    assert "nj_county_urls" not in other_state_election.source_metadata


@pytest.mark.django_db
def test_sync_nj_county_urls_noop_when_no_active_nj_elections():
    Election.objects.create(
        name="2024 New Jersey General Election",
        election_date="2024-11-05",
        election_type="general",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NJ",
        source_id="civic_api_nj_2024_general",
        status=Election.Status.ARCHIVED,
    )

    with patch(
        "integrations.nj_elections.tasks.NewJerseyElectionsClient.fetch_enr_page",
        return_value="<html>fake page</html>",
    ):
        result = sync_nj_county_urls()

    assert result == {"updated": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `... pytest --no-migrations -v integrations/nj_elections/tests/test_tasks.py`

Expected: `ModuleNotFoundError: No module named 'integrations.nj_elections.tasks'`

- [ ] **Step 3: Write `tasks.py`**

```python
"""
New Jersey elections Celery tasks.

Stage 1 enrichment — sync_nj_county_urls:
  NJ has no custom election/race creation (Stage 1 stays on the existing
  Google Civic API sync). This task only enriches already-existing NJ
  Election rows with the current per-county Clarity URLs/IDs, scraped from
  the state's election-night-results page, so Stage 2 (results/adapters/
  nj.py) knows which counties to poll and with what election ID.

  Only elections with status ACTIVE or RESULTS_PENDING are enriched —
  the results page only ever reflects "the current" election, so applying
  it to archived/upcoming elections would be meaningless or wrong.
"""
import logging

from celery import shared_task
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog

from .client import NewJerseyElectionsClient
from .exceptions import NjElectionsRetryableError
from .parsers import classify_clarity_counties, parse_county_urls

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = (Election.Status.ACTIVE, Election.Status.RESULTS_PENDING)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_nj_county_urls(self):
    """Scrape the NJ ENR county table and attach it to active NJ elections."""
    sync_log = SyncLog.objects.create(
        source="nj_elections",
        task_name="sync_nj_county_urls",
        status=SyncLog.Status.STARTED,
    )
    client = NewJerseyElectionsClient()
    updated_count = 0

    try:
        elections = list(Election.objects.filter(state="NJ", status__in=_ACTIVE_STATUSES))
        if not elections:
            sync_log.notes = "No active NJ elections to enrich"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"updated": 0}

        html = client.fetch_enr_page()
        county_urls = parse_county_urls(html)
        clarity_counties = classify_clarity_counties(county_urls)

        for election in elections:
            meta = election.source_metadata or {}
            meta["nj_county_urls"] = clarity_counties
            election.source_metadata = meta
            election.last_synced_at = timezone.now()
            election.save(update_fields=["source_metadata", "last_synced_at"])
            updated_count += 1

        sync_log.records_updated = updated_count
        sync_log.notes = f"clarity_counties={len(clarity_counties)}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_updated", "notes", "status", "completed_at",
        ])
        return {"updated": updated_count}

    except NjElectionsRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("nj_elections.sync_county_urls.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `... pytest --no-migrations -v integrations/nj_elections/tests/test_tasks.py`

Expected: both tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/nj_elections/tasks.py backend/integrations/nj_elections/tests/test_tasks.py
git commit -m "feat(nj): add sync_nj_county_urls Stage 1 enrichment task"
```

---

### Task 5: Wire the internal trigger endpoint (including TASK_LOCKS)

**Files:**
- Modify: `backend/internal/views.py`
- Modify: `backend/internal/urls.py`
- Modify: `backend/internal/task_locks.py`

**Interfaces:**
- Produces: `POST /internal/tasks/sync-nj-elections/` → enqueues `sync_nj_county_urls`.

- [ ] **Step 1: Add the trigger view**

In `backend/internal/views.py`, add the import `from integrations.nj_elections.tasks import sync_nj_county_urls` alongside the other task imports, and add a new view (matching the exact decorator stack every other trigger view uses):

```python
@csrf_exempt
@require_POST
@require_internal_task_token
def sync_nj_elections_trigger(request):
    return _trigger("sync_nj_elections", sync_nj_county_urls, request)
```

- [ ] **Step 2: Register the URL**

In `backend/internal/urls.py`, add:

```python
    path("tasks/sync-nj-elections/", views.sync_nj_elections_trigger, name="internal-sync-nj-elections"),
```

- [ ] **Step 3: Register the TASK_LOCKS entry — DO NOT SKIP THIS STEP**

In `backend/internal/task_locks.py`, add to the `TASK_LOCKS` dict (matching the `WINDOW_DAILY` pattern every other daily-sync task uses):

```python
    "sync_nj_elections":    (WINDOW_DAILY,      23 * _HOUR),
```

This is the exact step that was missed for IL and caused a live 500 on first invocation — `_trigger()` in `views.py` does `TASK_LOCKS[task_name]` with no `.get()` fallback, so a missing entry is a `KeyError`, not a graceful no-op. `manage.py check` will NOT catch this — it's a runtime dict lookup, not an import-time or model-level check.

- [ ] **Step 4: Verify with `manage.py check`**

Run: `... python3 manage.py check`

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 5: Commit**

```bash
git add backend/internal/views.py backend/internal/urls.py backend/internal/task_locks.py
git commit -m "feat(nj): wire sync-nj-elections internal task endpoint with TASK_LOCKS entry"
```

**Note:** live deployment (redeploying `civicmirror-api`/`civicmirror-worker`, live-triggering the endpoint to confirm no 500, adding the cron entry) happens after this branch is reviewed and merged — same reasoning as IL: this build happens in an isolated worktree whose containers aren't the live shared infrastructure. Task 9 includes a checklist reminder for this.

---

### Task 6: Office/candidate normalization

**Files:**
- Create: `backend/results/adapters/nj_normalize.py`
- Create: `backend/results/tests/test_nj_normalize.py`

**Interfaces:**
- Produces:
  - `normalize_office(raw_title: str) -> tuple[str, str]` — `(canonical_office_key, party)`, e.g. `("US_SENATE", "DEM")`.
  - `canonical_office_title(canonical_key: str, party: str) -> str` — human-readable display title. Embeds party for primaries (`"UNITED STATES SENATOR (DEM PRIMARY)"`), omits it for general elections (`"UNITED STATES SENATOR"`) — see the plan header's "Bootstrap-grouping constraint" note for why this matters.
  - `normalize_candidate_name(raw_name: str) -> str | None` — returns `None` for non-candidate bookkeeping rows (`Write-in`, `WRITE-IN`, `Personal Choice`).

This task's code has already been prototyped and verified against all 5 real office-title variants and all 3 real candidate-name variants captured during design recon — transcribe it directly.

- [ ] **Step 1: Write the failing tests**

Create `backend/results/tests/test_nj_normalize.py`:

```python
import pytest

from results.adapters.nj_normalize import (
    canonical_office_title,
    normalize_candidate_name,
    normalize_office,
)


@pytest.mark.parametrize("raw_title,expected", [
    ("DEM U.S. Senator", ("US_SENATE", "DEM")),
    ("US Senate (DEM)", ("US_SENATE", "DEM")),
    ("United States Senator (DEM)", ("US_SENATE", "DEM")),
    ("U.S. Senate (DEM)", ("US_SENATE", "DEM")),
    ("DEM UNITED STATES SENATE", ("US_SENATE", "DEM")),
    ("REP UNITED STATES SENATE", ("US_SENATE", "REP")),
    ("Member of Congress - 1st Congressional District (DEM)", ("US_HOUSE_01", "DEM")),
])
def test_normalize_office_real_variants(raw_title, expected):
    assert normalize_office(raw_title) == expected


def test_canonical_office_title_embeds_party_for_primary():
    assert canonical_office_title("US_SENATE", "DEM") == "UNITED STATES SENATOR (DEM PRIMARY)"
    assert canonical_office_title("US_SENATE", "REP") == "UNITED STATES SENATOR (REP PRIMARY)"


def test_canonical_office_title_omits_party_for_general():
    assert canonical_office_title("US_SENATE", "") == "UNITED STATES SENATOR"


@pytest.mark.parametrize("raw_name,expected", [
    ("Cory BOOKER", "CORY BOOKER"),
    ("Cory Booker", "CORY BOOKER"),
    ("DEM Cory BOOKER", "CORY BOOKER"),
])
def test_normalize_candidate_name_real_variants(raw_name, expected):
    assert normalize_candidate_name(raw_name) == expected


@pytest.mark.parametrize("raw_name", ["Write-in", "WRITE-IN", "Write-In", "Personal Choice"])
def test_normalize_candidate_name_returns_none_for_bookkeeping_rows(raw_name):
    assert normalize_candidate_name(raw_name) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `... pytest --no-migrations -v results/tests/test_nj_normalize.py`

Expected: `ModuleNotFoundError: No module named 'results.adapters.nj_normalize'`

- [ ] **Step 3: Write `nj_normalize.py`**

```python
"""
Office title and candidate name normalization for New Jersey's per-county
Clarity results.

NJ has no state-level results aggregator, so office titles and candidate
names for the SAME statewide contest are not consistent strings across
counties. Confirmed live 2026-07-12 across 5 counties for one contest
(2026 US Senate primary, DEM):
    "DEM U.S. Senator"             (Atlantic)
    "US Senate (DEM)"              (Burlington)
    "United States Senator (DEM)"  (Essex)
    "U.S. Senate (DEM)"            (Mercer)
    "DEM UNITED STATES SENATE"     (Ocean)
And candidate names:
    "Cory BOOKER"       (Atlantic, Mercer)
    "Cory Booker"       (Burlington, Essex)
    "DEM Cory BOOKER"   (Ocean — party embedded in the name field itself)

canonical_office_title() embeds the party for primaries (not generals)
because results/tasks.py::_bootstrap_races_from_results groups rows into
Race records purely by office_title string. Clarity represents each
party's primary as a SEPARATE contest with its own candidate list —
without the party embedded, a Dem primary and Rep primary for the same
office would incorrectly merge into one Race.
"""
from __future__ import annotations

import re

_PARTY_TOKENS = frozenset({"DEM", "REP", "GOP", "IND", "UNA", "CON", "LIB", "GRN"})

_NON_CANDIDATE_NAMES = frozenset({
    "write-in", "writein", "personal choice", "under votes", "over votes", "blank ballots",
})

_CANONICAL_DISPLAY_TITLES: dict[str, str] = {
    "US_SENATE": "UNITED STATES SENATOR",
    "GOVERNOR": "GOVERNOR",
}


def _extract_party(title: str) -> tuple[str, str]:
    """Return (title_with_party_removed, party). party is '' if none found."""
    match = re.search(r'\(([A-Z]{2,4})\)', title)
    if match and match.group(1) in _PARTY_TOKENS:
        return title[:match.start()] + title[match.end():], match.group(1)

    words = title.split()
    if words and words[0].upper() in _PARTY_TOKENS:
        return " ".join(words[1:]), words[0].upper()
    if words and words[-1].upper() in _PARTY_TOKENS:
        return " ".join(words[:-1]), words[-1].upper()

    return title, ""


def normalize_office(raw_title: str) -> tuple[str, str]:
    """Return (canonical_office_key, party) for a raw Clarity contest title."""
    title, party = _extract_party(raw_title.strip())

    norm = title.upper().replace(".", "").replace(",", "")
    norm = " ".join(norm.split())

    if re.fullmatch(r'(US SENAT(OR|E)|UNITED STATES SENAT(OR|E))', norm):
        key = "US_SENATE"
    else:
        district_match = re.search(
            r'CONGRESS.*?(\d+)(?:ST|ND|RD|TH)?\s*(?:CONGRESSIONAL)?\s*DISTRICT', norm,
        )
        if district_match:
            key = f"US_HOUSE_{int(district_match.group(1)):02d}"
        elif "GOVERNOR" in norm:
            key = "GOVERNOR"
        else:
            # Unrecognized office phrasing — fall through unchanged. Still
            # usable as a grouping key within a single county, just won't
            # aggregate cross-county under a shared canonical key.
            key = norm

    return key, party


def canonical_office_title(canonical_key: str, party: str) -> str:
    """Human-readable Race.office_title for a canonical office key + party."""
    base = _CANONICAL_DISPLAY_TITLES.get(canonical_key, canonical_key)
    if party:
        return f"{base} ({party} PRIMARY)"
    return base


def normalize_candidate_name(raw_name: str) -> str | None:
    """
    Normalize a candidate name for cross-county matching. Returns None for
    non-candidate bookkeeping rows (write-ins, NJ's "Personal Choice" ballot
    line, under/over votes).
    """
    name = raw_name.strip()
    words = name.split()
    if words and words[0].upper() in _PARTY_TOKENS:
        name = " ".join(words[1:])

    collapsed = " ".join(name.split())
    if collapsed.lower() in _NON_CANDIDATE_NAMES:
        return None
    return collapsed.upper()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `... pytest --no-migrations -v results/tests/test_nj_normalize.py`

Expected: all 13 tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add backend/results/adapters/nj_normalize.py backend/results/tests/test_nj_normalize.py
git commit -m "feat(nj): add cross-county office/candidate normalization"
```

---

### Task 7: Stage 2 adapter — multi-county fetch and aggregation

**Files:**
- Create: `backend/results/adapters/nj.py`
- Modify: `backend/results/apps.py`

**Interfaces:**
- Consumes: `ClarityAdapter._parse_contests()` (inherited), `normalize_office`, `canonical_office_title`, `normalize_candidate_name` (Task 6).
- Produces: `NewJerseyAdapter` class registered under `state = "NJ"`.

- [ ] **Step 1: Write `nj.py`**

```python
"""
New Jersey (NJ) results adapter — multi-county Clarity aggregation.

NJ has no state-level results aggregator. Unlike every other Clarity-based
adapter in this codebase, this one does NOT use ClarityAdapter.fetch_results()
directly (that method is built around exactly one results_url per election).
Instead it fans out to each in-scope county's Clarity JSON API (discovered
by integrations.nj_elections.tasks.sync_nj_county_urls and cached on
Election.source_metadata["nj_county_urls"]), reusing the inherited
_parse_contests() for the JSON-to-ResultRow parsing, then normalizes and
aggregates across counties.

Scope: ~16 Clarity-pattern counties only (see nj_elections/parsers.py's
CLARITY_HOSTS). The 5 off-platform counties (Bergen, Camden, Sussex,
Warren, Hunterdon) are explicitly out of scope — NJ statewide totals from
this adapter are PARTIAL coverage, not full-state accuracy, until those
are built. See docs/superpowers/specs/2026-07-12-nj-adapter-design.md.

Office/candidate normalization: see nj_normalize.py — office titles and
candidate names are not consistent strings across counties; naive string
aggregation would produce duplicate races/candidates.
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict

import requests
from django.core.cache import cache

from core.http import UpstreamBlockedError, proxy_get
from integrations.nj_elections.parsers import CLARITY_HOSTS  # noqa: F401 (documents scope)

from .base import AdapterResult, ResultRow
from .clarity import _CLARITY_HEADERS, ClarityAdapter
from .nj_normalize import canonical_office_title, normalize_candidate_name, normalize_office
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days

# Offices that plausibly appear on every county's ballot — aggregate across
# ALL in-scope counties. District races (US_HOUSE_NN) only aggregate across
# counties that actually returned that key — no fabricated cross-county sums.
_STATEWIDE_OFFICE_KEYS = frozenset({"US_SENATE", "GOVERNOR"})


@register
class NewJerseyAdapter(ClarityAdapter):
    state = "NJ"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"nj_clarity:checksum:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("nj.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        counties = (election.source_metadata or {}).get("nj_county_urls") or []
        counties = [c for c in counties if c.get("election_id")]
        if not counties:
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes="No NJ county Clarity URLs with a posted election ID",
            )

        # (canonical_key, party) -> {normalized_candidate_name: total_votes}
        aggregated: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # (canonical_key, party) -> counties contributing (for district-race scoping)
        contributing_counties: dict[tuple[str, str], set[str]] = defaultdict(set)
        current_vers: list[str] = []
        source_url = ""

        for county in counties:
            county_name = county["county"]
            base_url = county["url"].split("web.")[0].rstrip("/") + "/"
            use_proxy = False  # NJ counties not yet known to block GCP IPs; add to
                                # CLARITY_PROXY_HOSTS in clarity.py if one is found to.

            try:
                ver_resp = proxy_get(
                    f"{base_url}current_ver.txt",
                    headers=_CLARITY_HEADERS, use_proxy=use_proxy,
                    timeout=self.FETCH_TIMEOUT_SHORT,
                )
                ver_resp.raise_for_status()
                current_ver = ver_resp.text.strip()
            except (UpstreamBlockedError, requests.RequestException) as exc:
                logger.warning("nj.adapter.county_version_failed county=%s err=%s", county_name, exc)
                continue

            current_vers.append(f"{county_name}:{current_ver}")

            try:
                summary_url = f"{base_url}{current_ver}/json/en/summary.json"
                data_resp = proxy_get(
                    summary_url, headers=_CLARITY_HEADERS, use_proxy=use_proxy,
                    timeout=self.FETCH_TIMEOUT_LONG,
                )
                data_resp.raise_for_status()
                payload = data_resp.json()
            except (UpstreamBlockedError, requests.RequestException, ValueError) as exc:
                logger.warning("nj.adapter.county_summary_failed county=%s err=%s", county_name, exc)
                continue

            contests = payload if isinstance(payload, list) else payload.get("Contests", payload.get("contests", []))
            county_rows = self._parse_contests(contests, current_ver)
            source_url = summary_url

            for row in county_rows:
                canonical_key, party = normalize_office(row.office_title or "")
                name = normalize_candidate_name(row.candidate_name or "")
                if name is None:
                    continue  # write-in / bookkeeping row — not aggregated as a candidate total

                group_key = (canonical_key, party)
                if canonical_key not in _STATEWIDE_OFFICE_KEYS:
                    # District race: only counties that actually have this
                    # district contribute — no cross-district fabrication.
                    contributing_counties[group_key].add(county_name)

                aggregated[group_key][name] += row.vote_count

        if not aggregated:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="none",
                notes="No result rows parsed from any in-scope NJ county",
            )

        all_rows: list[ResultRow] = []
        for (canonical_key, party), candidate_totals in aggregated.items():
            office_title = canonical_office_title(canonical_key, party)
            for candidate_name, vote_count in candidate_totals.items():
                all_rows.append(ResultRow(
                    candidate_name=candidate_name,
                    option_label=None,
                    vote_count=vote_count,
                    vote_pct=None,
                    is_winner=None,
                    result_type="unofficial",
                    office_title=office_title,
                    is_write_in_aggregate=False,
                    raw={"canonical_key": canonical_key, "party": party},
                ))

        checksum = hashlib.md5("|".join(sorted(current_vers)).encode()).hexdigest()
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == checksum:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="partial",
                unchanged=True, source_version=checksum,
            )

        return AdapterResult(
            rows=all_rows,
            source_url=source_url,
            mapping_confidence="partial",  # partial county coverage — see module docstring
            notes=f"counties_polled={len(current_vers)}/{len(counties)}",
            source_version=checksum,
        )
```

**Note on `mapping_confidence="partial"`:** unlike every other adapter in this codebase (which use `"full"` for complete-coverage sources), NJ's result set is *always* a subset of the true statewide total (5 counties are structurally excluded from this build, and any individual in-scope county can silently fail on a given poll). `"partial"` is the existing `AdapterResult.mapping_confidence` value already used elsewhere for exactly this situation (see `results/tasks.py`'s handling of `mapping_confidence in {'none', 'partial'}` around line 70-73) — using it here is honest about coverage, not a new convention.

- [ ] **Step 2: Register the adapter in `results/apps.py`**

Add `nj` to the `ready()` import list (alphabetically, between `me` and `ny`):

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
            nj,
            ny,
            oh,
            sc,
            tx,
            va,
            wa,
            wv,
        )
```

- [ ] **Step 3: Verify registration**

Run:
```bash
... python3 -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.prod')
django.setup()
from results.adapters.registry import get_adapter
adapter_class = get_adapter('NJ')
print('NJ adapter registered:', adapter_class)
assert adapter_class is not None
"
```

Expected: prints `NJ adapter registered: <class 'results.adapters.nj.NewJerseyAdapter'>`.

- [ ] **Step 4: Commit**

```bash
git add backend/results/adapters/nj.py backend/results/apps.py
git commit -m "feat(nj): add NJ multi-county Stage 2 results adapter"
```

---

### Task 8: Cross-county aggregation tests using real fixtures

**Files:**
- Create: `backend/results/tests/test_nj_adapter.py`
- Test fixtures (already staged): `backend/results/tests/fixtures/nj_atlantic_summary.json`, `backend/results/tests/fixtures/nj_burlington_summary.json`

**Interfaces:**
- None new — this task tests `NewJerseyAdapter.fetch_results()`'s aggregation logic end-to-end using real captured county data, with HTTP mocked at the `proxy_get` boundary.

- [ ] **Step 1: Write the failing tests**

Create `backend/results/tests/test_nj_adapter.py`:

```python
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from elections.models import Election
from results.adapters.nj import NewJerseyAdapter

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_json_fixture(name: str):
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def _mock_proxy_get_for_counties(county_payloads: dict[str, list]):
    """
    Returns a function usable as proxy_get's side_effect: routes
    current_ver.txt requests to a fixed fake version, and summary.json
    requests to the matching county's fixture payload.
    """
    def _side_effect(url, **kwargs):
        for county_name, payload in county_payloads.items():
            if county_name.lower() in url.lower():
                if url.endswith("current_ver.txt"):
                    return MagicMock(status_code=200, text="999", raise_for_status=lambda: None)
                if url.endswith("summary.json"):
                    resp = MagicMock(status_code=200, raise_for_status=lambda: None)
                    resp.json.return_value = payload
                    return resp
        raise AssertionError(f"Unexpected URL in test: {url}")
    return _side_effect


@pytest.mark.django_db
def test_fetch_results_aggregates_us_senate_across_counties_with_different_naming():
    atlantic_payload = _load_json_fixture("nj_atlantic_summary.json")
    burlington_payload = _load_json_fixture("nj_burlington_summary.json")

    election = Election.objects.create(
        name="2026 New Jersey Primary",
        election_date="2026-06-02",
        election_type="primary",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NJ",
        source_id="civic_api_nj_2026_primary",
        status=Election.Status.RESULTS_PENDING,
        source_metadata={
            "nj_county_urls": [
                {"county": "Atlantic", "url": "https://results.enr.clarityelections.com/NJ/Atlantic/126380/", "election_id": "126380"},
                {"county": "Burlington", "url": "https://results.enr.clarityelections.com/NJ/Burlington/126521/", "election_id": "126521"},
            ],
        },
    )

    adapter = NewJerseyAdapter()
    with patch(
        "results.adapters.nj.proxy_get",
        side_effect=_mock_proxy_get_for_counties({
            "Atlantic": atlantic_payload,
            "Burlington": burlington_payload,
        }),
    ):
        result = adapter.fetch_results(election.election_date, election.pk)

    senate_dem_rows = [r for r in result.rows if r.office_title == "UNITED STATES SENATOR (DEM PRIMARY)"]
    assert senate_dem_rows, "expected aggregated DEM US Senate rows despite differing office titles per county"

    booker_row = next(r for r in senate_dem_rows if r.candidate_name == "CORY BOOKER")
    # Atlantic's "DEM U.S. Senator" -> Cory BOOKER and Burlington's
    # "US Senate (DEM)" -> Cory Booker must have summed into ONE row, not two.
    assert booker_row.vote_count > 0

    # No duplicate candidate rows for the same normalized name within one office/party.
    names_seen = [r.candidate_name for r in senate_dem_rows]
    assert len(names_seen) == len(set(names_seen))


@pytest.mark.django_db
def test_fetch_results_keeps_dem_and_rep_primaries_as_separate_races():
    atlantic_payload = _load_json_fixture("nj_atlantic_summary.json")

    election = Election.objects.create(
        name="2026 New Jersey Primary",
        election_date="2026-06-02",
        election_type="primary",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NJ",
        source_id="civic_api_nj_2026_primary_2",
        status=Election.Status.RESULTS_PENDING,
        source_metadata={
            "nj_county_urls": [
                {"county": "Atlantic", "url": "https://results.enr.clarityelections.com/NJ/Atlantic/126380/", "election_id": "126380"},
            ],
        },
    )

    adapter = NewJerseyAdapter()
    with patch(
        "results.adapters.nj.proxy_get",
        side_effect=_mock_proxy_get_for_counties({"Atlantic": atlantic_payload}),
    ):
        result = adapter.fetch_results(election.election_date, election.pk)

    office_titles = {r.office_title for r in result.rows if "SENATOR" in (r.office_title or "")}
    assert "UNITED STATES SENATOR (DEM PRIMARY)" in office_titles
    assert "UNITED STATES SENATOR (REP PRIMARY)" in office_titles


@pytest.mark.django_db
def test_fetch_results_returns_empty_when_no_county_urls():
    election = Election.objects.create(
        name="2026 New Jersey Primary",
        election_date="2026-06-02",
        election_type="primary",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NJ",
        source_id="civic_api_nj_2026_primary_3",
        status=Election.Status.RESULTS_PENDING,
        source_metadata={},
    )

    adapter = NewJerseyAdapter()
    result = adapter.fetch_results(election.election_date, election.pk)

    assert result.rows == []
    assert result.mapping_confidence == "none"


@pytest.mark.django_db
def test_fetch_results_skips_county_that_fails_without_aborting():
    atlantic_payload = _load_json_fixture("nj_atlantic_summary.json")

    election = Election.objects.create(
        name="2026 New Jersey Primary",
        election_date="2026-06-02",
        election_type="primary",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NJ",
        source_id="civic_api_nj_2026_primary_4",
        status=Election.Status.RESULTS_PENDING,
        source_metadata={
            "nj_county_urls": [
                {"county": "Atlantic", "url": "https://results.enr.clarityelections.com/NJ/Atlantic/126380/", "election_id": "126380"},
                {"county": "BrokenCounty", "url": "https://results.enr.clarityelections.com/NJ/BrokenCounty/999/", "election_id": "999"},
            ],
        },
    )

    def _side_effect(url, **kwargs):
        if "brokencounty" in url.lower():
            raise __import__("requests").exceptions.ConnectionError("simulated failure")
        return _mock_proxy_get_for_counties({"Atlantic": atlantic_payload})(url, **kwargs)

    adapter = NewJerseyAdapter()
    with patch("results.adapters.nj.proxy_get", side_effect=_side_effect):
        result = adapter.fetch_results(election.election_date, election.pk)

    # BrokenCounty failing must not prevent Atlantic's rows from being returned.
    assert result.rows
    assert "counties_polled=1/2" in (result.notes or "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `... pytest --no-migrations -v results/tests/test_nj_adapter.py`

Expected: fails initially (module/fixture mismatches are likely on the first pass given the mock's URL-matching is approximate) — this is expected TDD churn. Iterate on the mock and the fixture data until you understand exactly which office titles/counts are present (`python3 -c "import json; d = json.load(open('...nj_atlantic_summary.json')); print([c['C'] for c in d if 'senat' in c['C'].lower()])"` is a fast way to check).

- [ ] **Step 3: Debug and fix until green**

This step is intentionally open-ended — the exact vote counts and contest structure in the real fixtures were not fully enumerated during planning (only the office-title/candidate-name strings for the US Senate race were verified). If a test's assertion needs adjusting to match real fixture data (e.g. the exact `booker_row.vote_count` isn't asserted to a specific number above, deliberately, since summing two real counties' live-changing vote counts isn't a stable thing to hardcode — but if you find a different mismatch), fix the test to reflect real, verified fixture data — never loosen an assertion just to make it pass without understanding why.

- [ ] **Step 4: Run tests to verify they pass**

Run: `... pytest --no-migrations -v results/tests/test_nj_adapter.py`

Expected: all 4 tests `PASS`, output pristine (no stray warnings).

- [ ] **Step 5: Commit**

```bash
git add backend/results/tests/test_nj_adapter.py
git commit -m "feat(nj): add cross-county aggregation tests using real captured fixtures"
```

---

### Task 9: Full test suite run + docs update

**Files:**
- Modify: `docs/state-research/NJ/NJ-Election_Research.md`
- Modify: `docs/state-research/00-MASTER-INDEX.md`

- [ ] **Step 1: Run the full NJ-related test suite together**

Run: `... pytest --no-migrations -v integrations/nj_elections/ results/tests/test_nj_normalize.py results/tests/test_nj_adapter.py`

Expected: every test from Tasks 2, 3, 4, 6, and 8 passes together.

- [ ] **Step 2: Run the full backend test suite**

Run: `... pytest --no-migrations -q`

Expected: no new failures beyond the pre-existing baseline (2 unrelated NC mock-timeout tests, confirmed during the IL build: `integrations/nc_sbe/tests/test_tasks.py::test_sync_nc_elections_retries_on_retryable_error` / `::test_sync_nc_elections_retries_on_requests_timeout`).

- [ ] **Step 3: Update the NJ research doc**

In `docs/state-research/NJ/NJ-Election_Research.md`, update the Coverage Status table:

```markdown
| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Active | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API (unchanged — NJ Stage 1 was not rebuilt) |
| Stage 2 — Results Ingestion | ✅ Built, partial coverage | ~16 of 21 counties (Clarity-pattern only). 5 off-platform counties (incl. Bergen and Camden, two of the largest) deferred. `results/adapters/nj.py` |
```

And append a new section documenting the office/candidate-naming inconsistency finding (for whoever builds the deferred 5 counties later) — summarize the "Critical finding" section from `docs/superpowers/specs/2026-07-12-nj-adapter-design.md` in a few sentences, with a pointer to that spec for full detail.

- [ ] **Step 4: Update the master index**

In `docs/state-research/00-MASTER-INDEX.md`, add NJ to **Near Core Coverage** (not Full Core — Stage 1 is still Civic-API-dependent and Stage 2 is partial-county), matching the existing format for CA/NC/NY's Near Core rows, with a note on the county-coverage caveat.

- [ ] **Step 5: Commit**

```bash
git add docs/state-research/NJ/NJ-Election_Research.md docs/state-research/00-MASTER-INDEX.md
git commit -m "docs(nj): update NJ research doc and master index for shipped adapter"
```

---

## Post-Plan Follow-Ups (not part of this plan)

- The 5 off-platform counties (Bergen, Camden, Sussex, Warren, Hunterdon) — each needs its own site-specific investigation, no shared mechanism. Bergen and Camden are high-priority given their population share.
- Salem's exact `current_ver.txt`/`summary.json` path was not resolved during recon — if Task 3's live verification step finds Salem still failing, it degrades gracefully (skipped like any other failed county per Task 7's per-county error handling) but should be investigated properly as a fast-follow.
- **Manual post-merge deployment steps** (same pattern as IL): after this branch is reviewed and merged to `main`, someone needs to: rebuild/redeploy `civicmirror-api`/`civicmirror-worker`, run the new migration if any (none expected — no new `Race.Source` value), live-trigger `/internal/tasks/sync-nj-elections/` to confirm no 500 (this is exactly the class of bug the `TASK_LOCKS` step in Task 5 exists to prevent — verify it worked), and add a `sync-nj-elections` cron entry to `/data/DockerConfigs/CivicMirror/scheduler/crontab` + recreate `civicmirror-scheduler`.
- Historical backfill.
