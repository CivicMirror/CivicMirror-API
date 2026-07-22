# Utah (UT) Enhanced Voting Results Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Utah (UT) to the existing, shared `EnhancedVotingAdapter` (`results/adapters/enhanced_voting.py`) — the same base class already serving Virginia, Washington, and Georgia — bringing UT to "Results Coverage Only" tier with zero changes to shared parsing logic.

**Architecture:** Unlike Maryland, Missouri, and New Mexico (each of which needed a bespoke parser for a state-unique data format), Utah's research doc (`docs/state-research/UT/UT-Election_Research_V3.md`) confirms Utah runs an **Enhanced Voting "Enhanced Results" tenant** — the identical platform and JSON API shape already implemented generically in this codebase. This was independently re-verified live (2026-07-21): `GET https://electionresults.utah.gov/results/public/api/jurisdictions/Utah` and the per-election `/elections/Utah/{slug}` (meta) and `/elections/Utah/{slug}/data` endpoints return payloads that match `EnhancedVotingAdapter.fetch_results`'s existing parsing code exactly — `election.publicElectionId`, multilingual `name[]` arrays, `ballotItems[].contestType`/`summaryResults.ballotOptions[]`, `party.abbreviation`, `nativeId`, `isWriteIn`, `asOf` for version caching — field-for-field, with no schema differences requiring code changes.

This plan mirrors `results/adapters/ga.py` exactly (Georgia — the closest existing precedent: a self-hosted Enhanced Voting deployment at its own domain, not the shared `app.enhancedvoting.com`): a ~10-line subclass setting `state`, `state_name`, and `base_url`, plus tests mirroring `results/tests/test_ga_adapter.py`. **No new parser, no new client, no new Django app, and no changes to `results/adapters/enhanced_voting.py` or `results/adapters/base.py`.**

## Global Constraints

- Do not modify `results/adapters/enhanced_voting.py` (the shared base class), `results/adapters/base.py`, or `results/adapters/registry.py` — only import from them.
- Utah never sends a `votePercent` key in its real ballot-option payloads (confirmed live 2026-07-21: 0/27 options across the current election had one) — `ResultRow.vote_pct` will always be `None` for this adapter. This is expected, correct behavior (the existing `_safe_float(opt.get("votePercent"))` already returns `None` for a missing key), not a defect — tests should assert `vote_pct is None`, not skip checking it.
- Utah's race names carry a party **prefix** ("REP U.S. House District 2"), unlike Georgia's party **suffix** convention ("Governor - Rep") — both are stored verbatim in `office_title` with no special-casing needed; this is informational context, not a required behavior change.
- All fixture data must be real — captured live from `electionresults.utah.gov` on 2026-07-21, not synthetic.
- No new Celery task, internal endpoint, or `TASK_LOCKS` entry — Stage-2-only adapters are picked up automatically via `results.adapters.registry` once registered.
- Run tests with `pytest --no-migrations` (local test-DB creation breaks on an unrelated bad migration in this environment).
- Keep new test-file imports at the top of the file from the start — a prior task in a different, already-merged feature failed CI on a mid-file-import ruff `E402` error.
- Full research context: `docs/state-research/UT/UT-Election_Research_V3.md`.

---

### Task 1: `ut.py` — Utah Enhanced Voting adapter subclass + tests

**Files:**
- Create: `backend/results/adapters/ut.py`
- Create: `backend/results/tests/test_ut_adapter.py`

**Interfaces:**
- Consumes: `EnhancedVotingAdapter` (existing, `results/adapters/enhanced_voting.py`) and `register` (existing, `results/adapters/registry.py`) — import only, do not modify either.
- Produces: `UtahAdapter` registered under state `"UT"` — consumed automatically by `results.tasks.ingest_official_results` via `results.adapters.registry.get_adapter("UT")` once Task 2 registers the module. Not discoverable via the registry until Task 2 — that's expected for this task.

- [ ] **Step 1: Write the failing tests**

```python
# backend/results/tests/test_ut_adapter.py
"""
Unit tests for the Utah results adapter.
Heavy parsing logic lives in EnhancedVotingAdapter and is tested via VA/GA
tests; these tests cover UT-specific configuration and real-world data shapes.
"""
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.enhanced_voting import _parse_ballot_items
from results.adapters.ut import UtahAdapter

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_ut_adapter_registered():
    import results.adapters.ut  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "UT" in list_supported_states()
    assert get_adapter("UT") is UtahAdapter
    assert get_adapter("ut") is UtahAdapter


def test_ut_adapter_base_url():
    assert UtahAdapter.base_url == "https://electionresults.utah.gov/results/public/api"
    assert UtahAdapter.state == "UT"
    assert UtahAdapter.state_name == "Utah"


# ---------------------------------------------------------------------------
# Real UT ballot item, captured live 2026-07-21 from Primary06232026
# (REP U.S. House District 2) — note no votePercent key: confirmed real,
# 0/27 ballot options across the live election had one.
# ---------------------------------------------------------------------------

_UT_BALLOT_ITEM = {
    "id": "01000000-b2af-048e-2bcd-08dec58ce469",
    "contestType": "Candidate",
    "name": [{"languageId": "en", "text": "REP U.S. House District 2"}],
    "summaryResults": {
        "ballotOptions": [
            {
                "name": [{"languageId": "en", "text": "BLAKE D. MOORE"}],
                "voteCount": 52673,
                "isWinner": None,
                "isWriteIn": False,
                "nativeId": "BLAKED.MOORE-1-Republican",
                "party": {"abbreviation": "REP"},
            },
            {
                "name": [{"languageId": "en", "text": "KARIANNE LISONBEE"}],
                "voteCount": 40271,
                "isWinner": None,
                "isWriteIn": False,
                "nativeId": "KARIANNELISONBEE-2-Republican",
                "party": {"abbreviation": "REP"},
            },
        ]
    },
}


def test_parse_ut_race_with_party_prefix_and_no_vote_percent():
    rows = _parse_ballot_items([_UT_BALLOT_ITEM], result_type="unofficial")

    assert len(rows) == 2
    # Office title preserved verbatim including party PREFIX (UT convention,
    # contrast with GA's party SUFFIX "Governor - Rep")
    assert rows[0].office_title == "REP U.S. House District 2"
    assert rows[0].candidate_name == "BLAKE D. MOORE"
    assert rows[0].vote_count == 52673
    assert rows[0].raw["party"] == "REP"
    assert rows[0].raw["native_id"] == "BLAKED.MOORE-1-Republican"
    # Utah never sends votePercent — must be None, not 0 or missing entirely
    assert rows[0].vote_pct is None
    assert rows[1].vote_pct is None
    # isWinner is None pre-certification, matching GA/VA/WA convention
    assert rows[0].is_winner is None


# ---------------------------------------------------------------------------
# fetch_results integration (mocked HTTP)
# ---------------------------------------------------------------------------


def test_fetch_results_no_slug():
    adapter = UtahAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {}

    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results(None, election_id=99)

    assert result.mapping_confidence == "none"
    assert "enr_slug" in result.notes


def test_fetch_results_no_slug_does_not_guess_from_date():
    adapter = UtahAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.enhanced_voting.requests.get") as mock_get:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results("2026-06-23", election_id=99)

    assert result.mapping_confidence == "none"
    mock_get.assert_not_called()


def test_fetch_results_uses_ut_base_url():
    adapter = UtahAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "Primary06232026"}
    mock_election.pk = 1

    meta_payload = {"asOf": "2026-07-20T22:49:17.0406178Z", "isOfficialResults": False}
    data_payload = {"ballotItems": [_UT_BALLOT_ITEM]}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.enhanced_voting.requests.get") as mock_get, \
         patch("results.adapters.enhanced_voting.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None

        meta_resp = MagicMock()
        meta_resp.json.return_value = meta_payload
        data_resp = MagicMock()
        data_resp.json.return_value = data_payload
        mock_get.side_effect = [meta_resp, data_resp]

        result = adapter.fetch_results(None, election_id=1)

    # Confirm requests hit electionresults.utah.gov, not the shared
    # app.enhancedvoting.com domain or another state's self-hosted domain
    calls = [c.args[0] for c in mock_get.call_args_list]
    assert all("electionresults.utah.gov" in url for url in calls)
    assert any("Primary06232026/data" in url for url in calls)

    assert result.mapping_confidence == "full"
    assert len(result.rows) == 2
    assert result.rows[0].result_type == "unofficial"
    assert result.rows[0].vote_pct is None


def test_fetch_results_version_unchanged():
    adapter = UtahAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "Primary06232026"}
    mock_election.pk = 1

    meta_payload = {"asOf": "2026-07-20T22:49:17.0406178Z", "isOfficialResults": False}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.enhanced_voting.requests.get") as mock_get, \
         patch("results.adapters.enhanced_voting.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = "2026-07-20T22:49:17.0406178Z"  # unchanged

        meta_resp = MagicMock()
        meta_resp.json.return_value = meta_payload
        mock_get.return_value = meta_resp

        result = adapter.fetch_results(None, election_id=1)

    assert result.unchanged is True
    assert mock_get.call_count == 1  # /data not fetched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest results/tests/test_ut_adapter.py --no-migrations -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'results.adapters.ut'`

- [ ] **Step 3: Write the implementation**

```python
# backend/results/adapters/ut.py
"""
Utah results adapter using the Enhanced Voting ENR API.

Utah self-hosts the Enhanced Voting platform at electionresults.utah.gov —
same API shape as VA ELECT, WA VoteWA, and GA (results.sos.ga.gov),
different base URL. Independently re-verified live 2026-07-21 against
docs/state-research/UT/UT-Election_Research_V3.md: GET .../jurisdictions/Utah,
.../elections/Utah/{slug}, and .../elections/Utah/{slug}/data all match
EnhancedVotingAdapter's existing parsing exactly, field-for-field.

Election slugs (enr_slug) are opaque, case-sensitive, and inconsistently
formatted (e.g. "primary08122025", "Primary06232026", "general11052024") —
discover them from GET .../jurisdictions/Utah's elections[].publicElectionId
for the election matching the target date; do not derive from the date.
One catalog entry ("primary09052023_Demo") is an explicit demo election —
exclude demo/test elections by policy when building a discovery step
(out of scope for this build). Set
election.source_metadata = {"enr_slug": "<publicElectionId>"}.

Confirmed live (2026-07-21, Primary06232026, 12 ballot items, 0/27 ballot
options had a votePercent key) — Utah never sends votePercent, so
ResultRow.vote_pct is always None for this adapter; this is a real,
confirmed data characteristic, not a bug (the field is Optional and the
existing _safe_float(opt.get("votePercent")) already handles a missing
key gracefully by returning None).

Race names carry a party PREFIX ("REP U.S. House District 2"), unlike
GA's party SUFFIX convention ("Governor - Rep") — stored verbatim, same
as GA; cross-source race matching handles normalization downstream.

The research doc documents real data-quality issues in Utah's feed
(top-level ballotsCast/turnout reported as 0 despite real contest votes;
isOfficialResults=false even when signed canvass documents exist) — none
of these affect this adapter, since it only reads per-contest
ballotItems/ballotOptions data and the existing isOfficialResults ->
result_type mapping already treats it as an advisory signal, consistent
with how GA/VA/WA are handled today. Top-level turnout/reporting fields
are not parsed by this adapter at all.
"""
from __future__ import annotations

from .enhanced_voting import EnhancedVotingAdapter
from .registry import register

_UTAH_API_BASE = "https://electionresults.utah.gov/results/public/api"


@register
class UtahAdapter(EnhancedVotingAdapter):
    state = "UT"
    state_name = "Utah"
    base_url = _UTAH_API_BASE
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest results/tests/test_ut_adapter.py --no-migrations -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/results/adapters/ut.py backend/results/tests/test_ut_adapter.py
git commit -m "feat(ut): add UtahAdapter subclassing the shared EnhancedVotingAdapter"
```

---

### Task 2: Register the adapter and verify end-to-end

**Files:**
- Modify: `backend/results/apps.py`

**Interfaces:**
- Consumes: Task 1's `UtahAdapter`.
- Produces: `UtahAdapter` discoverable via `results.adapters.registry.get_adapter("UT")` at Django startup.

- [ ] **Step 1: Register the adapter module**

In `backend/results/apps.py`, find this line inside `ResultsConfig.ready()`'s `adapter_modules` list:

```python
            "ok", "oregon", "pa", "ri", "sc", "sd", "tn", "tx", "va",
```

Replace with (inserting `"ut"` alphabetically between `"tx"` and `"va"`):

```python
            "ok", "oregon", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "va",
```

- [ ] **Step 2: Verify the adapter is discoverable via the registry**

Run:
```bash
cd backend && SECRET_KEY=test-only python -c "
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')
django.setup()
from results.adapters.registry import list_supported_states
assert 'UT' in list_supported_states(), list_supported_states()
print('OK: UT registered')
"
```
Expected: `OK: UT registered`

- [ ] **Step 3: Run the full test suite to check for regressions**

Run: `cd backend && pytest --no-migrations -q`
Expected: all tests pass, no regressions.

- [ ] **Step 4: Run ruff and Django's system check**

Run: `cd backend && ruff check . && python manage.py check`
Expected: `All checks passed!` and `System check identified no issues (0 silenced).`

- [ ] **Step 5: Commit**

```bash
git add backend/results/apps.py
git commit -m "feat(ut): register UtahAdapter in results app startup"
```

---

## Follow-up work (explicitly out of scope for this plan)

- **`enr_slug` discovery/automation** — this plan (like GA/VA/WA before it) requires `Election.source_metadata["enr_slug"]` to be set manually (Django admin or the aggregation ingest layer) per election; no automated catalog-polling discovery task is built. The research doc's own election catalog includes a demo election (`primary09052023_Demo`) — any future discovery automation must explicitly exclude demo/test elections, not just take the newest catalog entry.
- **Locality/county-level results** — this adapter only reads the statewide `/elections/Utah/{slug}/data` payload's top-level `ballotItems`. County-level `/elections/{locality-slug}/{slug}/data` endpoints (confirmed live for `beaver-county-ut` and `sanpete-county-ut`) and the ballot-item breakdown endpoint (`/data/ballot-item/{uuid}`, which links `parentBallotItemId` to statewide contests) are not fetched.
- **Turnout/registration/reporting-status fields** — the research doc documents real inconsistencies here (top-level `ballotsCast: 0` despite tens of thousands of real contest votes) that this adapter doesn't need to worry about, since it never reads those fields — but a future adapter that does would need the doc's Section 5 reconciliation rules (treat zero as unknown/unpopulated when contest totals show activity, never overwrite a known nonzero with zero, don't trust `ballotItemCount`).
- **Reports/exports** ("All Results Excel" 4-sheet workbook, media-export JSON, PDF/canvass documents) — not fetched by this adapter. The XLSX workbook is the doc's recommended source for overvotes/undervotes/count-groups/precinct totals and would need a dedicated parser (more MD/MO-shaped work) if pursued.
- **Utah Vote Search** (pre-election candidate/race discovery, sample-ballot lookups) — separate system, separate concerns (address-based lookups, privacy-sensitive), explicitly recommended by the doc as supplementary only, never the primary results source.
- **Historical backfill** (structured XLSX canvass workbooks back to ~2000s, scanned/OCR-required PDFs back to 1960) — separate, much larger effort per the doc's own Phase 6.
- **Certification/status evidence modeling** — the doc recommends a multi-field evidence model (`publication_status`, `certification_documents[]`, `certified_at`, etc.) rather than trusting `isOfficialResults` alone; this adapter still passes that flag straight through to `result_type` (`"official"`/`"unofficial"`), matching the existing GA/VA/WA convention exactly — no different or new behavior for UT specifically.

## Verification

- `cd backend && .venv/bin/python -m pytest --no-migrations -q results/tests/test_ut_adapter.py -v` after Task 1.
- `cd backend && .venv/bin/ruff check .` before every commit.
- Full suite (`pytest --no-migrations -q`) and `manage.py check` after Task 2, plus the registry smoke test (`get_adapter("UT")` returns `UtahAdapter`) — same pattern as every prior state's final task.
