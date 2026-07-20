# Alabama Stage 1 (Elections + FCPA Candidates) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Alabama Stage 1 election/race/candidate ingestion so AL moves from "Results Adapter only" to Full Core coverage (ADR-007), joining AZ/CO/FL/GA/IL/MA/MI/PA/SC/TX/VA/WA/WV in `_FULL_CORE_STATES`.

**Architecture:** Extend the existing `backend/integrations/al_sos` package (currently Stage 2 ENR-export-only) with two independent Celery tasks that both call the existing `aggregation.ingest` merge engine:

1. `sync_al_elections` — scrapes the SOS year-specific Election Information page (`www.sos.alabama.gov/alabama-votes/voter/election-information/{year}`) and upserts one `Election` row per heading (name, date, type, and a list of official document links for future certification work).
2. `sync_al_fcpa_candidates` — queries the FCPA Political Race Search JSON API (`fcpa.alabamavotes.gov`) for a fixed whitelist of state/statewide offices, enriches each unique committee via the committee-detail page (which embeds a strict-JSON `committeeDetailsObj` — verified against the real HAR capture, not guessed), and upserts `Race` + `Candidate` rows against whichever `Election` has been manually curated with an `al_fcpa_election_id` in `source_metadata` (the FCPA "election" dropdown has one value per *cycle*, e.g. `160` = "2026 ELECTION CYCLE", not one per specific election date — see Global Constraints).

This mirrors the existing KY (`integrations/ky_sos`) and PA (`integrations/pa_sos`) two-stage adapter pattern exactly: plain `requests` HTTP client (no browser needed — FCPA and the SOS year page are both public, unauthenticated, non-JS-gated), pure-function parsers, a mappers module with a hardcoded in-scope-office whitelist, and Celery tasks that call `ingest_election` / `ingest_race` / `ingest_candidate`.

**Explicitly out of scope for this plan** (per user direction — leave for future work): candidate-certification PDF parsing, sample-ballot validation, statewide ballot measures, and all ArcGIS/district-geometry work described in `docs/state-research/AL/AL-Election_Research.md` §4, §5, §6. FCPA committee status must never be treated as ballot-qualified status (see Global Constraints) — that promotion path is future work once certifications are parsed.

**Tech Stack:** Django, Celery, `requests`, `beautifulsoup4`, existing `aggregation.ingest` (`ingest_election`/`ingest_race`/`ingest_candidate`), existing `ops.models.SyncLog`, existing `internal` task-trigger views.

## Global Constraints

- State code is `AL`; all new code lives in `backend/integrations/al_sos/` (already exists for Stage 2) plus small touch points in `backend/elections/models.py`, `backend/internal/`, and `backend/ops/views.py`.
- The FCPA "election" filter is **cycle-granular for regular statewide-cycle years only** — verified live, not assumed: `election=102` ("2022 ELECTION") + `office=23` (Governor) returns 17 candidates in one response, including Republican primary-only candidates who lost the May 2022 primary (Blanchard, James, Burdette, George, Odle, Zeigler, Young) *and* Yolanda Flowers, who only appeared on the November general ballot — one ID, two different election dates, no field to distinguish them. By contrast, special elections *do* get per-date IDs: the HD49 2020 special race splits cleanly into `election=80` (primary, 6 candidates), `81` (runoff, 2 candidates), `82` (general, 1 candidate). Every regular AL statewide-cycle year (2014, 2016, 2018, 2020, 2022, 2024, 2026) has exactly one `{year} ELECTION`/`{year} ELECTION CYCLE` dropdown entry — confirmed against the full 162-option live dropdown, not just 2026's. Since this plan's Core scope is exactly those regular-cycle statewide/legislative races, treat `election` as cycle-only and do not attempt to infer primary/runoff/general from FCPA data for them. Attach FCPA-sourced races/candidates only to the `Election` row that a human has explicitly tagged via `Election.source_metadata["al_fcpa_election_id"]` (set manually in Django admin, same convention as Clarity states' manually-set `results_url` per ADR-007). Document this as a known simplification.
- FCPA committee data (`CANDIDATESTATUS`, `dissolved`) describes the **campaign-finance committee**, not ballot qualification. Never promote it to a "certified" concept that doesn't exist yet — just map `dissolved: true` to `Candidate.CandidateStatus.WITHDRAWN` and everything else to `RUNNING`.
- The FCPA office whitelist (confirmed against the live `<select id="office">` options captured in `docs/state-research/AL/fcpa.alabamavotes.gov_Archive [26-07-20 12-42-17].har`) is: Governor (23), Lt. Governor (26), Attorney General (3), Secretary of State (36), State Auditor (38), State Treasurer (42), Commissioner of Agriculture & Industries (10), State Board of Education (39), President of the Public Service Commission (32), Public Service Commissioner (31), State Senator (41), State Representative (40). Do not add county/municipal offices from that same dropdown (License Commissioner, Sheriff, Tax Assessor, etc.) — those are enhanced/local coverage, not Core.
- Normalize office titles to match the existing cross-state convention already used by `pa_sos`/`mi_sos`: `"State Senate - District {N}"`, `"State House - District {N}"`, `"Lieutenant Governor"` (not "Lt. Governor").
- `committeeDetailsObj` is emitted as **strict JSON** inside a `<script>` tag (`const committeeDetailsObj = {...};`) — verified directly against the real captured HTML, not assumed. Parse it with `json.loads` after extracting the balanced `{...}` substring; do not write a JS-object-literal fuzzy parser, since real data doesn't need one.
- Build `Candidate.name` from the committee detail's structured `candidateFirstName`/`candidateMiddleName`/`candidateLastName`/`suffix` fields, not by comma-splitting the search-result row's `CANDIDATE` field.
- `Race.Source.AL_SOS` must exist before any `al_sos`-sourced race/candidate is ingested.
- Every new Celery task needs a `TASK_LOCKS` entry in `backend/internal/task_locks.py`, a trigger view + URL in `backend/internal/`, and a documented (not executed — the scheduler crontab is root-owned) crontab line for `/data/DockerConfigs/CivicMirror/scheduler/crontab`.
- Tests run with `pytest --no-migrations` (per this repo's standing convention — local test-DB creation breaks on a bad migration).
- Do not touch anything under `docs/state-research/AL/*.har` or the `2020 Primary Runoff Precinct Results.zip` research artifact — those stay as uncommitted/reference material.

---

## File Structure

- `backend/elections/models.py`: add `Source.AL_SOS` choice to `Race`.
- `backend/integrations/al_sos/client.py`: add `fetch_election_year_page`, `fetch_fcpa_race_search`, `fetch_fcpa_committee_detail` to the existing `AlSosClient`.
- `backend/integrations/al_sos/parsers.py`: add `parse_election_year_page`, `parse_fcpa_race_search_response`, `parse_fcpa_committee_detail`.
- `backend/integrations/al_sos/mappers.py` (new): `CORE_OFFICE_IDS`, `OFFICE_LABELS`, `normalize_office_title`, `geography_scope`, `party_abbrev`, `build_candidate_name`, `infer_election_type`.
- `backend/integrations/al_sos/tasks.py` (new): `sync_al_elections`, `sync_al_fcpa_candidates`.
- `backend/integrations/al_sos/tests/fixtures/al_year_page_2026.html` (new): trimmed real capture of the SOS year page.
- `backend/integrations/al_sos/tests/fixtures/al_fcpa_search_results_page1.json` (new): trimmed real capture of the FCPA race-search JSON response.
- `backend/integrations/al_sos/tests/fixtures/al_fcpa_committee_detail_4834.html` (new): real captured committee-detail page.
- `backend/integrations/al_sos/tests/test_parsers.py` (new): parser unit tests against the fixtures above.
- `backend/integrations/al_sos/tests/test_mappers.py` (new): mapper unit tests.
- `backend/integrations/al_sos/tests/test_tasks.py` (new): task integration tests (network mocked).
- `backend/internal/views.py`: add `sync_al_elections_trigger`, `sync_al_fcpa_trigger`.
- `backend/internal/urls.py`: add `tasks/sync-al-elections/`, `tasks/sync-al-fcpa/`.
- `backend/internal/task_locks.py`: add `sync_al_elections`, `sync_al_fcpa` entries.
- `backend/ops/views.py`: add `"AL"` to `_FULL_CORE_STATES`.
- `backend/ops/tests/test_views.py`: update the `tiers["AL"]` assertion from `"results"` to `"full"`.
- `docs/adr/ADR-007-Phase3-State-Expansion.md`: add an AL row to the Outcomes table.
- `docs/state-research/AL/AL-Election_Research.md`: update §13 "Current Coverage Tier" to reflect shipped Stage 1.

---

### Task 1: Add `Race.Source.AL_SOS`

**Files:**
- Modify: `backend/elections/models.py:92-114` (the `Race.Source` `TextChoices`)
- Test: `backend/elections/tests/test_models.py` (create if it doesn't already assert on `Source` choices — check first with `grep -n "class.*Source\|Source\." backend/elections/tests/test_models.py`)

**Interfaces:**
- Produces: `Race.Source.AL_SOS == "al_sos"`, used by every later task's `ingest_race`/`ingest_candidate`/`ingest_election` calls with `source="al_sos"`.

- [ ] **Step 1: Write the failing test**

```python
def test_race_source_has_alabama_choice():
    from elections.models import Race

    assert Race.Source.AL_SOS == "al_sos"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest elections/tests/test_models.py::test_race_source_has_alabama_choice -v --no-migrations`
Expected: FAIL with `AttributeError: AL_SOS`

- [ ] **Step 3: Add the choice**

In `backend/elections/models.py`, inside `class Source(models.TextChoices):` (currently ending with `KY_SOS = 'ky_sos', 'Kentucky SOS'` at line 113), add:

```python
        KY_SOS = 'ky_sos', 'Kentucky SOS'
        AL_SOS = 'al_sos', 'Alabama SOS'
```

- [ ] **Step 4: Confirm no migration is required**

Run: `cd backend && python manage.py makemigrations --check --dry-run elections`
Expected: `No changes detected in app 'elections'` (matches the existing `KY_SOS`/`TN_SOS` precedent — Django's migration autodetector doesn't emit a migration for a `choices=` addition alone). If it unexpectedly reports changes, run `python manage.py makemigrations elections` and include the generated migration file in this task's commit.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest elections/tests/test_models.py::test_race_source_has_alabama_choice -v --no-migrations`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/elections/models.py backend/elections/tests/test_models.py
git commit -m "feat(elections): add AL_SOS race source choice"
```

---

### Task 2: Election year-page parser

**Files:**
- Modify: `backend/integrations/al_sos/client.py`
- Modify: `backend/integrations/al_sos/parsers.py`
- Create: `backend/integrations/al_sos/tests/fixtures/al_year_page_2026.html`
- Create: `backend/integrations/al_sos/tests/test_parsers.py`

**Interfaces:**
- Consumes: none (pure HTML parsing).
- Produces: `parse_election_year_page(html: str) -> list[dict]`, where each dict has keys `name: str`, `election_date: datetime.date`, `election_type: str` (one of `elections.models.Election.ElectionType` values), `source_id: str`, `document_links: list[dict]` (each `{"label": str, "url": str}`). Also `fetch_election_year_page(year: int) -> str` on `AlSosClient`. Both are consumed by Task 3's `sync_al_elections`.

- [ ] **Step 1: Create the fixture**

Create `backend/integrations/al_sos/tests/fixtures/al_year_page_2026.html` with this content (trimmed from the real capture in `docs/state-research/AL/www.sos.alabama.gov_Archive [26-07-18 10-38-22].har`, entry for `election-information/2026` — heading text, dash character, and link markup are verbatim from that capture):

```html
<!DOCTYPE html>
<html><body>
<article>
<h3>Special General Election House District 63 &#8211; January 13, 2026</h3>
<blockquote><p><a href="/sites/default/files/election-2026/HD63CertificationofResults.pdf">Certification of Results</a> (certified by State Canvassing Board 1/20/2026)</p></blockquote>
<hr>
<h3>Primary Election &#8211; May 19, 2026</h3>
<blockquote><p><a href="https://www.sos.alabama.gov/alabama-votes/2026-primary-election-sample-ballots">Sample Ballots</a></p><p><a href="/sites/default/files/election-2026/2026RepublicanCertification.pdf">Republican Party Certification of Candidates</a> (certified by Party 2/25/2026)</p><p><a href="https://www.sos.alabama.gov/sites/default/files/election-2026/Democratic%20Certifcation.pdf">Democratic Party Certification of Candidates</a> (certified by Party 2/26/2026)</p></blockquote>
<hr>
<h3>Primary Runoff Election &#8211; June 16, 2026</h3>
<blockquote><p><a href="/sites/default/files/election-2026/RunoffSampleBallots.pdf">Sample Ballots</a></p></blockquote>
<hr>
<h3>General Election &#8211; November 3, 2026</h3>
<blockquote><p><a href="/sites/default/files/election-2026/CertificationofRepublicanPartyCandidates-2026General.pdf">Certification of Republican Party Candidates</a> (certified by party 6/30/2026)</p><p><a href="/sites/default/files/election-2026/CertificationofDemocraticPartyCandidates-2026General.pdf">Certification of Democratic Party Candidates</a> (certified by party 7/1/2026)</p></blockquote>
</article>
</body></html>
```

- [ ] **Step 2: Write the failing tests**

Create `backend/integrations/al_sos/tests/test_parsers.py`:

```python
"""Unit tests for al_sos parsers. No network access."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from integrations.al_sos.parsers import parse_election_year_page

_FIXTURES = Path(__file__).parent / "fixtures"


def _year_page_html() -> str:
    return (_FIXTURES / "al_year_page_2026.html").read_text()


def test_parse_election_year_page_finds_all_headings():
    elections = parse_election_year_page(_year_page_html())

    assert len(elections) == 4
    names = [e["name"] for e in elections]
    assert "Special General Election House District 63" in names
    assert "Primary Election" in names
    assert "Primary Runoff Election" in names
    assert "General Election" in names


def test_parse_election_year_page_extracts_dates_and_types():
    elections = parse_election_year_page(_year_page_html())
    by_name = {e["name"]: e for e in elections}

    assert by_name["Primary Election"]["election_date"] == dt.date(2026, 5, 19)
    assert by_name["Primary Election"]["election_type"] == "primary"
    assert by_name["Primary Runoff Election"]["election_date"] == dt.date(2026, 6, 16)
    assert by_name["Primary Runoff Election"]["election_type"] == "primary_runoff"
    assert by_name["General Election"]["election_date"] == dt.date(2026, 11, 3)
    assert by_name["General Election"]["election_type"] == "general"
    assert by_name["Special General Election House District 63"]["election_type"] == "special"


def test_parse_election_year_page_extracts_document_links():
    elections = parse_election_year_page(_year_page_html())
    by_name = {e["name"]: e for e in elections}

    primary_links = by_name["Primary Election"]["document_links"]
    assert {"label": "Sample Ballots", "url": "https://www.sos.alabama.gov/alabama-votes/2026-primary-election-sample-ballots"} in primary_links
    republican_cert = next(link for link in primary_links if "Republican Party Certification" in link["label"])
    assert republican_cert["url"] == "https://www.sos.alabama.gov/sites/default/files/election-2026/2026RepublicanCertification.pdf"


def test_parse_election_year_page_source_id_is_stable_and_unique():
    elections = parse_election_year_page(_year_page_html())
    source_ids = [e["source_id"] for e in elections]

    assert len(source_ids) == len(set(source_ids))
    assert all(sid.startswith("al_sos_2026_") for sid in source_ids)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest integrations/al_sos/tests/test_parsers.py -v --no-migrations`
Expected: FAIL with `ImportError: cannot import name 'parse_election_year_page'`

- [ ] **Step 4: Implement the parser**

In `backend/integrations/al_sos/parsers.py`, add near the top (after existing imports) and at the end of the file:

```python
import re as _re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

_YEAR_PAGE_BASE_URL = "https://www.sos.alabama.gov"
_DASH_RE = _re.compile(r"\s[‐-―-]\s")


def _slugify(text: str) -> str:
    return _re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _infer_election_type(heading_text: str) -> str:
    lowered = heading_text.lower()
    if "special" in lowered:
        return "special"
    if "runoff" in lowered:
        return "primary_runoff"
    if "primary" in lowered:
        return "primary"
    if "general" in lowered:
        return "general"
    if "municipal" in lowered:
        return "municipal"
    return "other"


def parse_election_year_page(html: str) -> list[dict]:
    """
    Parse an Alabama SOS year-specific Election Information page
    (www.sos.alabama.gov/alabama-votes/voter/election-information/{year}).

    Each <h3> heading is "{Name} – {Month Day, Year}"; the immediately
    following <blockquote> holds that election's official document links.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []

    for heading in soup.find_all("h3"):
        text = " ".join(heading.get_text().split())
        parts = _DASH_RE.split(text, maxsplit=1)
        if len(parts) != 2:
            continue
        name, date_text = parts[0].strip(), parts[1].strip()
        try:
            election_date = dt_datetime_strptime(date_text, "%B %d, %Y")
        except ValueError:
            continue

        blockquote = heading.find_next_sibling("blockquote")
        document_links = []
        if blockquote is not None:
            for a in blockquote.find_all("a", href=True):
                label = " ".join(a.get_text().split())
                url = urljoin(_YEAR_PAGE_BASE_URL, a["href"])
                document_links.append({"label": label, "url": url})

        results.append({
            "name": name,
            "election_date": election_date,
            "election_type": _infer_election_type(name),
            "source_id": f"al_sos_{election_date.year}_{_slugify(name)}",
            "document_links": document_links,
        })

    return results


def dt_datetime_strptime(date_text: str, fmt: str):
    import datetime as _dt
    return _dt.datetime.strptime(date_text, fmt).date()
```

Note: `–` is the en dash (`–`) used verbatim in the real SOS headings; the fixture encodes it as the numeric HTML entity `&#8211;`, which BeautifulSoup decodes to the same `–` character when `get_text()` is called, so `_DASH_RE` matches either way.

- [ ] **Step 5: Add the client method**

In `backend/integrations/al_sos/client.py`, add to `AlSosClient`:

```python
    def fetch_election_year_page(self, year: int) -> str:
        url = f"https://www.sos.alabama.gov/alabama-votes/voter/election-information/{year}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AlSosRetryableError(f"Alabama election-information page request failed: {exc}") from exc
        return response.text
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest integrations/al_sos/tests/test_parsers.py -v --no-migrations`
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/integrations/al_sos/client.py backend/integrations/al_sos/parsers.py backend/integrations/al_sos/tests/
git commit -m "feat(al_sos): parse SOS year-page election headings and document links"
```

---

### Task 3: `sync_al_elections` Celery task

**Files:**
- Create: `backend/integrations/al_sos/tasks.py`
- Create: `backend/integrations/al_sos/tests/test_tasks.py`

**Interfaces:**
- Consumes: `AlSosClient.fetch_election_year_page(year)` (Task 2), `parse_election_year_page(html)` (Task 2), `aggregation.ingest.ingest_election(*, source, source_id, identity, fields)` (existing), `ops.models.SyncLog` (existing).
- Produces: `sync_al_elections(self, year: int | None = None)` Celery task, consumed by Task 8's trigger view.

- [ ] **Step 1: Write the failing test**

Create `backend/integrations/al_sos/tests/test_tasks.py`:

```python
"""Integration tests for al_sos Celery tasks. All network access is mocked."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

_FIXTURES = Path(__file__).parent / "fixtures"


def _year_page_html() -> str:
    return (_FIXTURES / "al_year_page_2026.html").read_text()


@pytest.mark.django_db
def test_sync_al_elections_creates_elections():
    from elections.models import Election
    from integrations.al_sos.tasks import sync_al_elections

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        MC.return_value.fetch_election_year_page.return_value = _year_page_html()
        sync_al_elections.apply(kwargs={"year": 2026})

    assert Election.objects.filter(state="AL", election_type="primary").exists()
    assert Election.objects.filter(state="AL", election_type="general").exists()
    assert Election.objects.filter(state="AL", election_type="primary_runoff").exists()


@pytest.mark.django_db
def test_sync_al_elections_stores_document_links_in_metadata():
    from elections.models import Election
    from integrations.al_sos.tasks import sync_al_elections

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        MC.return_value.fetch_election_year_page.return_value = _year_page_html()
        sync_al_elections.apply(kwargs={"year": 2026})

    primary = Election.objects.get(state="AL", election_type="primary")
    links = primary.source_metadata["al_document_links"]
    assert any("Sample Ballots" == link["label"] for link in links)


@pytest.mark.django_db
def test_sync_al_elections_is_idempotent():
    from elections.models import Election
    from integrations.al_sos.tasks import sync_al_elections

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        MC.return_value.fetch_election_year_page.return_value = _year_page_html()
        sync_al_elections.apply(kwargs={"year": 2026})
        sync_al_elections.apply(kwargs={"year": 2026})

    assert Election.objects.filter(state="AL").count() == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest integrations/al_sos/tests/test_tasks.py -v --no-migrations`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.al_sos.tasks'`

- [ ] **Step 3: Implement the task**

Create `backend/integrations/al_sos/tasks.py`:

```python
"""
Alabama SOS Celery tasks.

sync_al_elections (Stage 1a):
    Scrapes the year-specific Election Information page and upserts an
    Election row per heading, preserving official document links in
    source_metadata for future certification-parsing work.

sync_al_fcpa_candidates (Stage 1b):
    See mappers.py / parsers.py docstrings for the FCPA cycle-vs-election
    caveat. Populates Race + Candidate rows for Elections that have been
    manually tagged with source_metadata["al_fcpa_election_id"].
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from ops.models import SyncLog

from .client import AlSosClient
from .exceptions import AlSosRetryableError
from .parsers import parse_election_year_page

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_al_elections(self, year: int | None = None):
    """Stage 1a: upsert AL Election rows from the SOS year page."""
    from aggregation import ingest

    target_year = year or timezone.localdate().year
    sync_log = SyncLog.objects.create(
        source="al_sos",
        task_name="sync_al_elections",
        status=SyncLog.Status.STARTED,
    )

    try:
        client = AlSosClient()
        html = client.fetch_election_year_page(target_year)
        parsed = parse_election_year_page(html)

        created_count = 0
        for entry in parsed:
            election, created = ingest.ingest_election(
                source="al_sos",
                source_id=entry["source_id"],
                identity={
                    "state": "AL",
                    "election_type": entry["election_type"],
                    "election_date": entry["election_date"],
                    "jurisdiction_level": "state",
                },
                fields={
                    "name": entry["name"],
                    "source_metadata": {"al_document_links": entry["document_links"]},
                },
            )
            if created:
                created_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = len(parsed) - created_count
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "records_updated", "status", "completed_at"])
        return {"parsed": len(parsed), "created": created_count}

    except AlSosRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("al_sos.sync_al_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

Note: `entry["source_metadata"]` field name relies on `_apply_fields`'s default field group (see `backend/aggregation/precedence.py` — `source_metadata` isn't in `_FIELD_GROUPS`, so it falls back to `DEFAULT_GROUP`, same as every other adapter's free-form metadata dict).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest integrations/al_sos/tests/test_tasks.py -v --no-migrations`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/al_sos/tasks.py backend/integrations/al_sos/tests/test_tasks.py
git commit -m "feat(al_sos): add sync_al_elections Celery task"
```

---

### Task 4: FCPA mappers (office whitelist + normalization)

**Files:**
- Create: `backend/integrations/al_sos/mappers.py`
- Create: `backend/integrations/al_sos/tests/test_mappers.py`

**Interfaces:**
- Produces: `CORE_OFFICE_IDS: frozenset[int]`, `OFFICE_LABELS: dict[int, str]`, `normalize_office_title(office: str, district: str) -> str`, `geography_scope(office_title: str) -> str`, `party_abbrev(party_name: str) -> str`, `build_candidate_name(detail: dict) -> str`. Consumed by Task 7's `sync_al_fcpa_candidates`.

- [ ] **Step 1: Write the failing tests**

Create `backend/integrations/al_sos/tests/test_mappers.py`:

```python
"""Unit tests for al_sos FCPA mappers."""
from __future__ import annotations

from integrations.al_sos.mappers import (
    CORE_OFFICE_IDS,
    OFFICE_LABELS,
    build_candidate_name,
    geography_scope,
    normalize_office_title,
    party_abbrev,
)


def test_office_ids_and_labels_match():
    assert CORE_OFFICE_IDS == set(OFFICE_LABELS)
    assert OFFICE_LABELS[23] == "Governor"
    assert OFFICE_LABELS[40] == "State Representative"
    assert OFFICE_LABELS[41] == "State Senator"


def test_normalize_office_title_statewide():
    assert normalize_office_title("Governor", "") == "Governor"
    assert normalize_office_title("Lt. Governor", "") == "Lieutenant Governor"


def test_normalize_office_title_legislative_district():
    assert normalize_office_title("State Senator", "27") == "State Senate - District 27"
    assert normalize_office_title("State Representative", "55") == "State House - District 55"
    assert normalize_office_title("State Senator", "") == "State Senate"


def test_geography_scope():
    assert geography_scope("State Senate - District 27") == "state_legislative_district"
    assert geography_scope("State House - District 55") == "state_legislative_district"
    assert geography_scope("Governor") == "statewide"


def test_party_abbrev():
    assert party_abbrev("Republican") == "REP"
    assert party_abbrev("Democratic") == "DEM"
    assert party_abbrev("Independent") == "IND"
    assert party_abbrev("") == ""


def test_build_candidate_name_joins_structured_fields():
    detail = {
        "candidateFirstName": "JIMMY",
        "candidateMiddleName": "",
        "candidateLastName": "ABBETT",
        "suffix": "",
    }
    assert build_candidate_name(detail) == "JIMMY ABBETT"


def test_build_candidate_name_includes_suffix():
    detail = {
        "candidateFirstName": "John",
        "candidateMiddleName": "Q",
        "candidateLastName": "Public",
        "suffix": "Jr.",
    }
    assert build_candidate_name(detail) == "John Q Public Jr."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest integrations/al_sos/tests/test_mappers.py -v --no-migrations`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.al_sos.mappers'`

- [ ] **Step 3: Implement the mappers**

Create `backend/integrations/al_sos/mappers.py`:

```python
"""
Mappers for Alabama FCPA Political Race Search data -> CivicMirror model
fields.

The FCPA office dropdown (fcpa.alabamavotes.gov/page.request.do?page=
page.acfPublicPoliticalRaceSearch) lists 45 offices including county and
municipal seats (Sheriff, Tax Assessor, Circuit Clerk, ...). CORE_OFFICE_IDS
restricts Stage 1 ingestion to statewide and state-legislative offices,
matching the "federal and state elections" Core coverage target in
docs/state-research/AL/AL-Election_Research.md. IDs confirmed against the
live dropdown captured in
docs/state-research/AL/fcpa.alabamavotes.gov_Archive [26-07-20 12-42-17].har.
"""
from __future__ import annotations

OFFICE_LABELS: dict[int, str] = {
    23: "Governor",
    26: "Lt. Governor",
    3: "Attorney General",
    36: "Secretary of State",
    38: "State Auditor",
    42: "State Treasurer",
    10: "Commissioner of Agriculture & Industries",
    39: "State Board of Education",
    32: "President of the Public Service Commission",
    31: "Public Service Commissioner",
    41: "State Senator",
    40: "State Representative",
}

CORE_OFFICE_IDS = frozenset(OFFICE_LABELS)

assert CORE_OFFICE_IDS == set(OFFICE_LABELS), "CORE_OFFICE_IDS and OFFICE_LABELS keys must match"

_OFFICE_TITLE_OVERRIDES = {
    "Lt. Governor": "Lieutenant Governor",
}

_PARTY_MAP = {
    "democratic": "DEM",
    "republican": "REP",
    "independent": "IND",
    "libertarian": "LIB",
    "green": "GRN",
}


def normalize_office_title(office: str, district: str) -> str:
    """
    E.g. ("State Senator", "27") -> "State Senate - District 27", matching
    the cross-state convention used by integrations.pa_sos and
    integrations.mi_sos.
    """
    office = (office or "").strip()
    district = (district or "").strip()
    title = _OFFICE_TITLE_OVERRIDES.get(office, office)

    if title == "State Senator":
        return f"State Senate - District {district}" if district else "State Senate"
    if title == "State Representative":
        return f"State House - District {district}" if district else "State House"
    return title


def geography_scope(office_title: str) -> str:
    title = office_title.lower()
    if "state senate" in title or "state house" in title:
        return "state_legislative_district"
    return "statewide"


def party_abbrev(party_name: str) -> str:
    return _PARTY_MAP.get((party_name or "").lower().strip(), (party_name or "").upper()[:3])


def build_candidate_name(detail: dict) -> str:
    """Build a display name from committeeDetailsObj's structured name fields."""
    parts = [
        detail.get("candidateFirstName", "").strip(),
        detail.get("candidateMiddleName", "").strip(),
        detail.get("candidateLastName", "").strip(),
    ]
    name = " ".join(part for part in parts if part)
    suffix = detail.get("suffix", "").strip()
    return f"{name} {suffix}".strip() if suffix else name
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest integrations/al_sos/tests/test_mappers.py -v --no-migrations`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/al_sos/mappers.py backend/integrations/al_sos/tests/test_mappers.py
git commit -m "feat(al_sos): add FCPA office whitelist and normalization mappers"
```

---

### Task 5: FCPA client methods

**Files:**
- Modify: `backend/integrations/al_sos/client.py`
- Create: `backend/integrations/al_sos/tests/test_client.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `AlSosClient.fetch_fcpa_race_search(election_id: str, office_id: int, page_number: int, page_size: int = 100) -> str`, `AlSosClient.fetch_fcpa_committee_detail(committee_id: int) -> str`. Consumed by Task 7's `sync_al_fcpa_candidates`.

- [ ] **Step 1: Write the failing tests**

Create `backend/integrations/al_sos/tests/test_client.py`:

```python
"""Unit tests for AlSosClient FCPA methods. Network is mocked via requests_mock-style monkeypatching."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from integrations.al_sos.client import AlSosClient


def test_fetch_fcpa_race_search_builds_correct_url():
    client = AlSosClient()
    with patch.object(client.session, "get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, text='{"data":{"totalRecords":0,"list":[]},"success":true}')
        mock_get.return_value.raise_for_status = MagicMock()
        client.fetch_fcpa_race_search("160", 23, 1)

    url = mock_get.call_args[0][0]
    assert "page=com.acf.common.page.politicalracesearchresults" in url
    assert "election=160" in url
    assert "office=23" in url
    assert "pageNumber=1" in url
    assert "pageSize=100" in url


def test_fetch_fcpa_committee_detail_base64_encodes_id():
    client = AlSosClient()
    with patch.object(client.session, "get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, text="<html></html>")
        mock_get.return_value.raise_for_status = MagicMock()
        client.fetch_fcpa_committee_detail(4834)

    url = mock_get.call_args[0][0]
    # base64("pcc") == "cGNj", base64("4834") == "NDgzNA==" -- verified against
    # the real captured URL in the FCPA HAR.
    assert "type=cGNj" in url
    assert "id=NDgzNA%3D%3D" in url or "id=NDgzNA==" in url
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest integrations/al_sos/tests/test_client.py -v --no-migrations`
Expected: FAIL with `AttributeError: 'AlSosClient' object has no attribute 'fetch_fcpa_race_search'`

- [ ] **Step 3: Implement the client methods**

In `backend/integrations/al_sos/client.py`, add:

```python
import base64

_FCPA_BASE_URL = "https://fcpa.alabamavotes.gov/page.request.do"
```

and add to `AlSosClient`:

```python
    def fetch_fcpa_race_search(self, election_id: str, office_id: int, page_number: int, page_size: int = 100) -> str:
        params = {
            "page": "com.acf.common.page.politicalracesearchresults",
            "pageNumber": page_number,
            "pageSize": page_size,
            "sortDirection": "ASC",
            "sortBy": "candidate",
            "election": election_id,
            "office": office_id,
            "jurisdiction": "null",
            "party": "null",
            "place": "null",
            "district": "null",
            "city": "null",
            "year": "null",
        }
        try:
            response = self.session.get(_FCPA_BASE_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AlSosRetryableError(f"Alabama FCPA race search request failed: {exc}") from exc
        return response.text

    def fetch_fcpa_committee_detail(self, committee_id: int) -> str:
        encoded_type = base64.b64encode(b"pcc").decode()
        encoded_id = base64.b64encode(str(committee_id).encode()).decode()
        params = {
            "page": "page.acfPublicCommitteeDetails",
            "type": encoded_type,
            "id": encoded_id,
        }
        try:
            response = self.session.get(_FCPA_BASE_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AlSosRetryableError(f"Alabama FCPA committee detail request failed: {exc}") from exc
        return response.text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest integrations/al_sos/tests/test_client.py -v --no-migrations`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/al_sos/client.py backend/integrations/al_sos/tests/test_client.py
git commit -m "feat(al_sos): add FCPA race-search and committee-detail HTTP client methods"
```

---

### Task 6: FCPA parsers

**Files:**
- Modify: `backend/integrations/al_sos/parsers.py`
- Create: `backend/integrations/al_sos/tests/fixtures/al_fcpa_search_results_page1.json`
- Create: `backend/integrations/al_sos/tests/fixtures/al_fcpa_committee_detail_4834.html`
- Modify: `backend/integrations/al_sos/tests/test_parsers.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `parse_fcpa_race_search_response(json_text: str) -> tuple[list[dict], int]` (rows, total_records — each row has `committee_id: int`, `candidate_name: str`, `candidate_status: str`, `year: int`); `parse_fcpa_committee_detail(html: str) -> dict` (keys: `committee_id`, `candidateFirstName`, `candidateMiddleName`, `candidateLastName`, `suffix`, `office`, `jurisdiction`, `district`, `party`, `committeeStatus`, `dissolved`). Both consumed by Task 7's `sync_al_fcpa_candidates`.

- [ ] **Step 1: Create the fixtures**

Create `backend/integrations/al_sos/tests/fixtures/al_fcpa_search_results_page1.json` (real data captured live from `fcpa.alabamavotes.gov`, `election=160` = "2026 ELECTION CYCLE", office omitted; the full response had 848 rows, trimmed here to 3):

```json
{
  "data": {
    "totalRecords": 848,
    "list": [
      {"COMMITTEEID": 4834, "CANDIDATE": "ABBETT, JIMMY ", "CANDIDATESTATUS": "Active", "BEGINNINGFUNDS": 623.00, "MONETARYCONTRIB": 0.00, "MONETARYEXP": 0.00, "NONMONETARYCONTRIB": 0.00, "OTHERSOURCES": 0.00, "ENDINGFUNDS": 623.00, "YEAR": 2026},
      {"COMMITTEEID": 566, "CANDIDATE": "ABERNATHY, RON", "CANDIDATESTATUS": "Active", "BEGINNINGFUNDS": 45372.31, "MONETARYCONTRIB": 3750.00, "MONETARYEXP": 51364.89, "NONMONETARYCONTRIB": 0.00, "OTHERSOURCES": 0.00, "ENDINGFUNDS": 3042.52, "YEAR": 2026},
      {"COMMITTEEID": 3612, "CANDIDATE": "ABNEY, ELIZABETH TAYLOR", "CANDIDATESTATUS": "Active", "BEGINNINGFUNDS": 0.00, "MONETARYCONTRIB": 0.00, "MONETARYEXP": 0.00, "NONMONETARYCONTRIB": 1680.00, "OTHERSOURCES": 0.00, "ENDINGFUNDS": 0.00, "YEAR": 2026}
    ]
  },
  "success": true
}
```

Create `backend/integrations/al_sos/tests/fixtures/al_fcpa_committee_detail_4834.html` (real capture, committee id 4834, decoded from the `type=cGNj&id=NDgzNA%3D%3D` request in the FCPA HAR — the `committeeDetailsObj` block is verbatim):

```html
<!DOCTYPE html>
<html><body>
<script type="text/javascript">
    const committeeDetailsObj = {"zipCode":"36853","committeeType":"Principal Campaign Committee","registeredDate":"2022-01-07T08:59:00","city":"DADEVILLE","jurisdiction":"TALLAPOOSA COUNTY","committeeId":"29709","office":"Sheriff","suffix":"","committeeAppointment":"I appoint myself as the sole member of my principal campaign committee.","candidateFirstName":"JIMMY","members":[{"lastName":"ABBETT","zipCode":"36853","city":"DADEVILLE","smsOptIn":false,"linkedUser":"JABBETT29709","legacyOfficerId":40792,"memberStatus":"Active User","addressState":"Alabama","baseId":4834,"suffix":"","parentId":4834,"firstName":"JIMMY","phone":"2568254310","addressLine1":"568 HENDERSON STREET","memberType":"Candidate","id":12891,"email":"JIMMYABBETT@YAHOO.COM","memberRole":"","trackingId":12891}],"place":"","id":4834,"dissolved":false,"committeeAddressLine1":"568 HENDERSON STREET","email":"JIMMYABBETT@YAHOO.COM","trackingId":4834,"officeCity":"","committeeStatus":"Active","candidateLastName":"ABBETT","committeeState":"Alabama","phone":"2568254310","pacType":"","district":"","durationOfPac":"","party":"Republican"}
</script>
</body></html>
```

Note: this real committee happens to be a Sheriff (county office, not in `CORE_OFFICE_IDS`) — that's fine, this fixture only exercises the detail-page parser in isolation. Task 7's task-level test builds a synthetic in-whitelist detail dict directly rather than needing a second real fixture.

- [ ] **Step 2: Write the failing tests**

Append to `backend/integrations/al_sos/tests/test_parsers.py`:

```python
from integrations.al_sos.parsers import parse_fcpa_committee_detail, parse_fcpa_race_search_response


def _search_results_json() -> str:
    return (_FIXTURES / "al_fcpa_search_results_page1.json").read_text()


def _committee_detail_html() -> str:
    return (_FIXTURES / "al_fcpa_committee_detail_4834.html").read_text()


def test_parse_fcpa_race_search_response_returns_rows_and_total():
    rows, total_records = parse_fcpa_race_search_response(_search_results_json())

    assert total_records == 848
    assert len(rows) == 3
    assert rows[0]["committee_id"] == 4834
    assert rows[0]["candidate_name"] == "ABBETT, JIMMY"
    assert rows[0]["candidate_status"] == "Active"
    assert rows[0]["year"] == 2026


def test_parse_fcpa_committee_detail_extracts_structured_fields():
    detail = parse_fcpa_committee_detail(_committee_detail_html())

    assert detail["committee_id"] == 4834
    assert detail["candidateFirstName"] == "JIMMY"
    assert detail["candidateLastName"] == "ABBETT"
    assert detail["suffix"] == ""
    assert detail["office"] == "Sheriff"
    assert detail["jurisdiction"] == "TALLAPOOSA COUNTY"
    assert detail["district"] == ""
    assert detail["party"] == "Republican"
    assert detail["committeeStatus"] == "Active"
    assert detail["dissolved"] is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest integrations/al_sos/tests/test_parsers.py -v --no-migrations`
Expected: FAIL with `ImportError: cannot import name 'parse_fcpa_race_search_response'`

- [ ] **Step 4: Implement the parsers**

Append to `backend/integrations/al_sos/parsers.py`:

```python
import json


def parse_fcpa_race_search_response(json_text: str) -> tuple[list[dict], int]:
    """Parse a com.acf.common.page.politicalracesearchresults JSON response."""
    payload = json.loads(json_text)
    if not payload.get("success"):
        raise AlSosError("Alabama FCPA race search response reported success=false")

    data = payload.get("data") or {}
    rows = [
        {
            "committee_id": row["COMMITTEEID"],
            "candidate_name": _clean(row.get("CANDIDATE", "")),
            "candidate_status": row.get("CANDIDATESTATUS", ""),
            "year": row.get("YEAR"),
        }
        for row in data.get("list", [])
    ]
    return rows, int(data.get("totalRecords", 0))


def _extract_balanced_object(text: str, marker: str) -> str:
    """Extract the {...} object literal immediately following `marker`."""
    start = text.find(marker)
    if start == -1:
        raise AlSosError(f"Alabama FCPA committee detail page missing {marker!r}")
    brace_start = text.find("{", start)
    if brace_start == -1:
        raise AlSosError("Alabama FCPA committee detail page missing object literal")

    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start:i + 1]
    raise AlSosError("Alabama FCPA committee detail page has unterminated object literal")


def parse_fcpa_committee_detail(html: str) -> dict:
    """
    Parse the committeeDetailsObj JSON embedded in a committee detail page
    (page.acfPublicCommitteeDetails). Verified strict JSON against the real
    capture in docs/state-research/AL/fcpa.alabamavotes.gov_Archive
    [26-07-20 12-42-17].har -- json.loads works directly, no JS-literal
    normalization needed.
    """
    raw = _extract_balanced_object(html, "committeeDetailsObj")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AlSosError(f"Alabama FCPA committeeDetailsObj is not valid JSON: {exc}") from exc

    return {
        "committee_id": data.get("id"),
        "candidateFirstName": data.get("candidateFirstName", ""),
        "candidateMiddleName": data.get("candidateMiddleName", ""),
        "candidateLastName": data.get("candidateLastName", ""),
        "suffix": data.get("suffix", ""),
        "office": data.get("office", ""),
        "jurisdiction": data.get("jurisdiction", ""),
        "district": data.get("district", ""),
        "party": data.get("party", ""),
        "committeeStatus": data.get("committeeStatus", ""),
        "dissolved": bool(data.get("dissolved", False)),
    }
```

Also add the `AlSosError` import at the top of `parsers.py` if not already present (it already is, per the existing Stage 2 code), and add a module-level `_clean` helper if one doesn't already exist in this file — it does (used by the Stage 2 workbook parser), so reuse it.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest integrations/al_sos/tests/test_parsers.py -v --no-migrations`
Expected: PASS (6 tests total in this file)

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/al_sos/parsers.py backend/integrations/al_sos/tests/
git commit -m "feat(al_sos): parse FCPA race-search JSON and committeeDetailsObj"
```

---

### Task 7: `sync_al_fcpa_candidates` Celery task

**Files:**
- Modify: `backend/integrations/al_sos/tasks.py`
- Modify: `backend/integrations/al_sos/tests/test_tasks.py`

**Interfaces:**
- Consumes: `CORE_OFFICE_IDS`, `normalize_office_title`, `geography_scope`, `party_abbrev`, `build_candidate_name` (Task 4); `AlSosClient.fetch_fcpa_race_search`/`fetch_fcpa_committee_detail` (Task 5); `parse_fcpa_race_search_response`/`parse_fcpa_committee_detail` (Task 6); `aggregation.ingest.ingest_race`/`ingest_candidate` (existing).
- Produces: `sync_al_fcpa_candidates(self)` Celery task, consumed by Task 8's trigger view.

- [ ] **Step 1: Write the failing tests**

Append to `backend/integrations/al_sos/tests/test_tasks.py`:

```python
def _make_al_election(**overrides):
    from elections.models import Election

    defaults = dict(
        name="2026 General Election",
        election_date="2026-11-03",
        election_type="general",
        jurisdiction_level="state",
        state="AL",
        source_id="al_sos_2026_general_election",
        source_metadata={"al_fcpa_election_id": "160"},
    )
    defaults.update(overrides)
    return Election.objects.create(**defaults)


_SEARCH_PAGE_1 = {
    "data": {
        "totalRecords": 1,
        "list": [
            {"COMMITTEEID": 9001, "CANDIDATE": "SMITH, JANE", "CANDIDATESTATUS": "Active", "YEAR": 2026},
        ],
    },
    "success": True,
}

_SEARCH_PAGE_EMPTY = {"data": {"totalRecords": 1, "list": []}, "success": True}

_COMMITTEE_DETAIL = {
    "id": 9001,
    "candidateFirstName": "Jane",
    "candidateMiddleName": "",
    "candidateLastName": "Smith",
    "suffix": "",
    "office": "State Senator",
    "jurisdiction": "Jefferson County",
    "district": "15",
    "party": "Democratic",
    "committeeStatus": "Active",
    "dissolved": False,
}


@pytest.mark.django_db
def test_sync_al_fcpa_candidates_creates_race_and_candidate():
    import json as _json

    from elections.models import Candidate, Race
    from integrations.al_sos.tasks import sync_al_fcpa_candidates

    _make_al_election()

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        client = MC.return_value
        client.fetch_fcpa_race_search.side_effect = (
            lambda election_id, office_id, page_number, page_size=100: (
                _json.dumps(_SEARCH_PAGE_1) if office_id == 41 and page_number == 1 else _json.dumps(_SEARCH_PAGE_EMPTY)
            )
        )
        client.fetch_fcpa_committee_detail.return_value = "<html></html>"
        with patch("integrations.al_sos.tasks.parse_fcpa_committee_detail", return_value=_COMMITTEE_DETAIL):
            sync_al_fcpa_candidates.apply()

    assert Race.objects.filter(election__state="AL", office_title="State Senate - District 15").exists()
    candidate = Candidate.objects.get(name="Jane Smith")
    assert candidate.party == "DEM"
    assert candidate.source_metadata["al_fcpa_committee_id"] == 9001
    assert candidate.candidate_status == Candidate.CandidateStatus.RUNNING


@pytest.mark.django_db
def test_sync_al_fcpa_candidates_skips_elections_without_fcpa_id():
    from elections.models import Race
    from integrations.al_sos.tasks import sync_al_fcpa_candidates

    _make_al_election(source_metadata={}, source_id="al_sos_2026_primary_election", election_type="primary", election_date="2026-05-19")

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        sync_al_fcpa_candidates.apply()
        MC.return_value.fetch_fcpa_race_search.assert_not_called()

    assert not Race.objects.filter(election__state="AL").exists()


@pytest.mark.django_db
def test_sync_al_fcpa_candidates_marks_dissolved_committee_withdrawn():
    import json as _json

    from elections.models import Candidate
    from integrations.al_sos.tasks import sync_al_fcpa_candidates

    _make_al_election()
    dissolved_detail = {**_COMMITTEE_DETAIL, "dissolved": True}

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        client = MC.return_value
        client.fetch_fcpa_race_search.side_effect = (
            lambda election_id, office_id, page_number, page_size=100: (
                _json.dumps(_SEARCH_PAGE_1) if office_id == 41 and page_number == 1 else _json.dumps(_SEARCH_PAGE_EMPTY)
            )
        )
        client.fetch_fcpa_committee_detail.return_value = "<html></html>"
        with patch("integrations.al_sos.tasks.parse_fcpa_committee_detail", return_value=dissolved_detail):
            sync_al_fcpa_candidates.apply()

    candidate = Candidate.objects.get(source_metadata__al_fcpa_committee_id=9001)
    assert candidate.candidate_status == Candidate.CandidateStatus.WITHDRAWN
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest integrations/al_sos/tests/test_tasks.py -v --no-migrations -k fcpa`
Expected: FAIL with `ImportError: cannot import name 'sync_al_fcpa_candidates'`

- [ ] **Step 3: Implement the task**

Append to `backend/integrations/al_sos/tasks.py` (add these imports to the existing import block at the top of the file):

```python
from elections.models import Candidate, Election

from .mappers import CORE_OFFICE_IDS, build_candidate_name, geography_scope, normalize_office_title, party_abbrev
from .parsers import parse_fcpa_committee_detail, parse_fcpa_race_search_response
```

Then append the task:

```python
@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_al_fcpa_candidates(self):
    """
    Stage 1b: populate Race + Candidate from FCPA for every AL Election
    curated with source_metadata["al_fcpa_election_id"].

    The FCPA "election" filter is cycle-granular for regular statewide-cycle
    years (one ID covers the primary, runoff, and general together) --
    verified live against fcpa.alabamavotes.gov, not assumed. See the plan's
    Global Constraints for the verification (election=102/office=23 returns
    both May-2022-primary-only losers and the November general opponent
    under one ID). A human must set this key in Django admin per Election;
    elections without it are skipped entirely.
    """
    from aggregation import ingest

    sync_log = SyncLog.objects.create(
        source="al_sos",
        task_name="sync_al_fcpa_candidates",
        status=SyncLog.Status.STARTED,
    )

    try:
        elections = [
            election for election in Election.objects.filter(state="AL")
            if (election.source_metadata or {}).get("al_fcpa_election_id")
        ]

        total_created_races = total_created_candidates = 0
        client = AlSosClient()

        for election in elections:
            fcpa_election_id = election.source_metadata["al_fcpa_election_id"]
            seen_committee_ids: set[int] = set()
            dissolved_committee_ids: set[int] = set()

            for office_id in CORE_OFFICE_IDS:
                page_number = 1
                while True:
                    json_text = client.fetch_fcpa_race_search(fcpa_election_id, office_id, page_number)
                    rows, total_records = parse_fcpa_race_search_response(json_text)
                    if not rows:
                        break

                    for row in rows:
                        committee_id = row["committee_id"]
                        if committee_id in seen_committee_ids:
                            continue
                        seen_committee_ids.add(committee_id)

                        detail_html = client.fetch_fcpa_committee_detail(committee_id)
                        detail = parse_fcpa_committee_detail(detail_html)
                        if detail["dissolved"]:
                            dissolved_committee_ids.add(committee_id)

                        office_title = normalize_office_title(detail["office"], detail["district"])
                        race, race_created = ingest.ingest_race(
                            election=election,
                            source="al_sos",
                            identity={
                                "office_title": office_title,
                                "ocd_division_id": "",
                                "race_type": "candidate",
                            },
                            fields={
                                "office_title": office_title,
                                "jurisdiction": detail["jurisdiction"] or "Alabama",
                                "geography_scope": geography_scope(office_title),
                            },
                        )
                        if race_created:
                            total_created_races += 1

                        name = build_candidate_name(detail)
                        candidate, candidate_created = ingest.ingest_candidate(
                            race=race,
                            source="al_sos",
                            name=name,
                            party=party_abbrev(detail["party"]),
                            fields={
                                "candidate_status": (
                                    Candidate.CandidateStatus.WITHDRAWN if detail["dissolved"]
                                    else Candidate.CandidateStatus.RUNNING
                                ),
                                "source_metadata": {
                                    "al_fcpa_committee_id": committee_id,
                                    "al_committee_status_raw": detail["committeeStatus"],
                                },
                            },
                        )
                        if candidate_created:
                            total_created_candidates += 1

                    if page_number * 100 >= total_records:
                        break
                    page_number += 1

            if dissolved_committee_ids:
                withdrawn = (
                    Candidate.objects
                    .filter(
                        race__election=election,
                        source_metadata__al_fcpa_committee_id__in=list(dissolved_committee_ids),
                    )
                    .exclude(candidate_status=Candidate.CandidateStatus.WITHDRAWN)
                    .update(candidate_status=Candidate.CandidateStatus.WITHDRAWN)
                )
                if withdrawn:
                    logger.info("al_sos.sync_fcpa.dissolved count=%d election=%d", withdrawn, election.pk)

            election.last_synced_at = timezone.now()
            election.save(update_fields=["last_synced_at"])

        sync_log.records_created = total_created_candidates
        sync_log.notes = f"races_created={total_created_races}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "notes", "status", "completed_at"])
        return {"races_created": total_created_races, "candidates_created": total_created_candidates}

    except AlSosRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("al_sos.sync_al_fcpa_candidates.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest integrations/al_sos/tests/test_tasks.py -v --no-migrations`
Expected: PASS (all tests in this file, both `sync_al_elections` and `sync_al_fcpa_candidates` tests)

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/al_sos/tasks.py backend/integrations/al_sos/tests/test_tasks.py
git commit -m "feat(al_sos): add sync_al_fcpa_candidates Celery task"
```

---

### Task 8: Wire internal trigger endpoints, task locks, and scheduler

**Files:**
- Modify: `backend/internal/views.py`
- Modify: `backend/internal/urls.py`
- Modify: `backend/internal/task_locks.py`
- Test: `backend/internal/tests/test_views.py` (check first with `grep -n "sync_ky_sos_trigger\|sync_pa_sos_trigger" backend/internal/tests/test_views.py` for the existing pattern to follow)

**Interfaces:**
- Consumes: `sync_al_elections`, `sync_al_fcpa_candidates` (Tasks 3 and 7).
- Produces: `POST /internal/tasks/sync-al-elections/` and `POST /internal/tasks/sync-al-fcpa/`, following the exact `_trigger`/`TASK_LOCKS`/`@require_internal_task_token` pattern already used by every other state.

- [ ] **Step 1: Confirm the existing trigger test pattern**

`backend/internal/tests/test_views.py` uses function-based tests with `client`/`internal_token` fixtures (already defined at the top of the file), patches the task binding inside `internal.views`, and asserts on `response.json()["task_id"]`. Reference example already in the file (`test_sync_pa_sos_valid_token`):

```python
@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_sync_pa_sos_valid_token(client, internal_token):
    with patch("internal.views.sync_pa_elections") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "pa-task"
        mock_task.apply_async.return_value = mock_result
        response = client.post(
            "/internal/tasks/sync-pa-sos/",
            HTTP_AUTHORIZATION=f"Bearer {internal_token}",
        )
    assert response.status_code == 202
    assert response.json()["task_id"] == "pa-task"
```

There is also a lock-registration test with no fixtures at all (`test_sync_tn_sos_has_lock`):

```python
def test_sync_tn_sos_has_lock():
    from internal.task_locks import TASK_LOCKS

    assert TASK_LOCKS["sync_tn_sos"] == ("daily", 23 * 60 * 60)
```

- [ ] **Step 2: Write the failing tests**

Add to `backend/internal/tests/test_views.py`, following the exact patterns above:

```python
@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_sync_al_elections_valid_token(client, internal_token):
    with patch("internal.views.sync_al_elections") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "al-elections-1"
        mock_task.apply_async.return_value = mock_result
        response = client.post(
            "/internal/tasks/sync-al-elections/",
            HTTP_AUTHORIZATION=f"Bearer {internal_token}",
        )
    assert response.status_code == 202
    assert response.json()["task_id"] == "al-elections-1"


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_sync_al_fcpa_valid_token(client, internal_token):
    with patch("internal.views.sync_al_fcpa_candidates") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "al-fcpa-1"
        mock_task.apply_async.return_value = mock_result
        response = client.post(
            "/internal/tasks/sync-al-fcpa/",
            HTTP_AUTHORIZATION=f"Bearer {internal_token}",
        )
    assert response.status_code == 202
    assert response.json()["task_id"] == "al-fcpa-1"


def test_sync_al_elections_has_lock():
    from internal.task_locks import TASK_LOCKS

    assert TASK_LOCKS["sync_al_elections"] == ("daily", 23 * 60 * 60)


def test_sync_al_fcpa_has_lock():
    from internal.task_locks import TASK_LOCKS

    assert TASK_LOCKS["sync_al_fcpa"] == ("daily", 23 * 60 * 60)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest internal/tests/test_views.py -v --no-migrations -k "al_elections or al_fcpa"`
Expected: FAIL with 404 (URL not registered)

- [ ] **Step 4: Wire the trigger views**

In `backend/internal/views.py`, add to the import block (alongside the existing `from integrations.ky_sos.tasks import sync_ky_sos` line):

```python
from integrations.al_sos.tasks import sync_al_elections, sync_al_fcpa_candidates
```

And add the trigger view functions (following the exact shape of `sync_ky_sos_trigger`/`sync_pa_sos_trigger`):

```python
@csrf_exempt
@require_POST
@require_internal_task_token
def sync_al_elections_trigger(request):
    return _trigger("sync_al_elections", sync_al_elections, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_al_fcpa_trigger(request):
    return _trigger("sync_al_fcpa", sync_al_fcpa_candidates, request)
```

- [ ] **Step 5: Register the URLs**

In `backend/internal/urls.py`, add (after the `sync-tn-sos` line):

```python
    path("tasks/sync-al-elections/", views.sync_al_elections_trigger, name="internal-sync-al-elections"),
    path("tasks/sync-al-fcpa/", views.sync_al_fcpa_trigger, name="internal-sync-al-fcpa"),
```

- [ ] **Step 6: Add task locks**

In `backend/internal/task_locks.py`, add to `TASK_LOCKS` (after the `sync_tn_sos` line):

```python
    "sync_al_elections":    (WINDOW_DAILY,      23 * _HOUR),
    "sync_al_fcpa":         (WINDOW_DAILY,      23 * _HOUR),
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && python -m pytest internal/tests/test_views.py -v --no-migrations -k "al_elections or al_fcpa"`
Expected: PASS

- [ ] **Step 8: Document (do not execute) the scheduler crontab lines**

The scheduler crontab at `/data/DockerConfigs/CivicMirror/scheduler/crontab` is root-owned — do not attempt to edit it directly. Instead, tell the user the two lines that need adding, in the same style as the existing entries (check existing lines first with a command the user runs, since the file isn't readable without sudo):

```
0 6 * * * /path/to/trigger.sh /internal/tasks/sync-al-elections/
15 6 * * * /path/to/trigger.sh /internal/tasks/sync-al-fcpa/
```

Ask the user to confirm the exact existing cron time-slot convention (other `*-sos` entries' hour) before finalizing the two new lines, and apply them with `sudo crontab -e` or equivalent themselves.

- [ ] **Step 9: Commit**

```bash
git add backend/internal/views.py backend/internal/urls.py backend/internal/task_locks.py backend/internal/tests/test_views.py
git commit -m "feat(internal): wire AL Stage 1 sync task trigger endpoints"
```

---

### Task 9: Flip AL to Full Core coverage and update docs

**Files:**
- Modify: `backend/ops/views.py`
- Modify: `backend/ops/tests/test_views.py`
- Modify: `docs/adr/ADR-007-Phase3-State-Expansion.md`
- Modify: `docs/state-research/AL/AL-Election_Research.md`

**Interfaces:**
- Consumes: nothing new (this task only changes the coverage-tier classification, not ingestion logic).

- [ ] **Step 1: Write the failing test**

In `backend/ops/tests/test_views.py`, change:

```python
    assert tiers["AL"] == "results"
```

to:

```python
    assert tiers["AL"] == "full"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest ops/tests/test_views.py -v --no-migrations -k coverage`
Expected: FAIL (`tiers["AL"]` is still `"results"`)

- [ ] **Step 3: Update the coverage tier**

In `backend/ops/views.py`, change:

```python
_FULL_CORE_STATES = frozenset([
    "AZ", "CO", "FL", "GA", "IL", "MA", "MI", "PA", "SC", "TX", "VA", "WA", "WV",
])
```

to:

```python
_FULL_CORE_STATES = frozenset([
    "AL", "AZ", "CO", "FL", "GA", "IL", "MA", "MI", "PA", "SC", "TX", "VA", "WA", "WV",
])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest ops/tests/test_views.py -v --no-migrations -k coverage`
Expected: PASS

- [ ] **Step 5: Update ADR-007's Outcomes table**

In `docs/adr/ADR-007-Phase3-State-Expansion.md`, add a row to the Outcomes table (after the `KY` row, before the closing of the table):

```markdown
| **AL** | B | `results/adapters/al.py` + `integrations/al_sos/` | 2026-07-20 | Full Core | FCPA Political Race Search for state/statewide offices (Stage 1); ENR statewide Excel export for results (Stage 2, shipped earlier); `al_fcpa_election_id` in `source_metadata` is cycle-granular for regular statewide-cycle years (verified live against fcpa.alabamavotes.gov — one ID spans primary+runoff+general; special elections get per-date IDs) and must be curated per target Election; certifications/sample-ballots/district geometry deferred |
```

- [ ] **Step 6: Update the research doc's coverage-tier section**

In `docs/state-research/AL/AL-Election_Research.md`, in `# 13. Implementation Decision`, replace the `## Current Coverage Tier` section (currently reading `**Stage 1 path identified / implementation pending + Results Adapter confirmed.**`) with:

```markdown
## Current Coverage Tier

**Full Core Coverage (shipped 2026-07-20).** `sync_al_elections` ingests elections from the SOS year page; `sync_al_fcpa_candidates` ingests federal/state-office races and candidates from FCPA for any Election manually tagged with `source_metadata["al_fcpa_election_id"]`; `results/adapters/al.py` ingests live/unofficial results from the ENR export (shipped earlier).

Deferred to future work (see §4-§6 above): candidate-certification PDF parsing and the FCPA-provisional -> certified-ballot-qualified promotion path, sample-ballot validation, statewide ballot measures, and ArcGIS district-geometry ingestion.
```

- [ ] **Step 7: Commit**

```bash
git add backend/ops/views.py backend/ops/tests/test_views.py docs/adr/ADR-007-Phase3-State-Expansion.md docs/state-research/AL/AL-Election_Research.md
git commit -m "docs: mark Alabama as Full Core coverage (ADR-007)"
```

---

## Self-Review Notes

- **Spec coverage:** Election Creation (Task 2/3), Candidate information + Race Creation (Task 4/5/6/7) are covered. GIS/districts, certifications, sample ballots, and measures are explicitly excluded per user direction and called out in Global Constraints and Task 9's doc update.
- **Real data, not fabricated fixtures:** all HTML/JSON fixtures in Tasks 2, 5, and 6 are trimmed copies of real captures already sitting in `docs/state-research/AL/*.har` (verified directly against those files during planning) rather than guessed shapes — this removes the "PDF/JS-shape unverified" risk that applies to the certification work this plan explicitly defers.
- **Known simplification flagged, not hidden:** the FCPA cycle-vs-specific-election ambiguity is stated in Global Constraints, in `tasks.py`'s module docstring, and in Task 9's doc update — a future task can revisit this once certification parsing (deferred) provides a real per-election candidate list to cross-check against.
- **Type/name consistency check:** `AlSosClient`, `parse_election_year_page`, `parse_fcpa_race_search_response`, `parse_fcpa_committee_detail`, `CORE_OFFICE_IDS`, `normalize_office_title`, `geography_scope`, `party_abbrev`, `build_candidate_name`, `sync_al_elections`, `sync_al_fcpa_candidates` are each defined once and referenced with the same name/signature in every later task that consumes them.
