# Results Visibility and Poll Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make previous certified elections discoverable through public race endpoints and repair the stale local `poll_results` command.

**Architecture:** Keep results data exposed through the existing `/api/v1/races/{id}/results/` endpoint. Change only the race-discovery filters used by election race lookup and ZIP lookup so publishable archived/certified races are not hidden. Wire the management command to the existing Celery polling task instead of duplicating polling logic.

**Tech Stack:** Django, Django REST Framework, django-filter, Celery, pytest-django, Ruff.

## Global Constraints

- Do not inline `official_results` into `RaceDetailSerializer`; keep results as a separate plain-array endpoint.
- Public election race discovery must include `active` and `archived` races, and must exclude `draft`, `pending_review`, and `cancelled` races.
- Do not change `/api/v1/races/` default queryset behavior; it remains directly filterable by clients.
- Do not change production Cloud Scheduler wiring; only fix the stale synchronous management command.
- No database migration is required.
- **Election-level visibility is intentionally unchanged.** `LookupView` excludes elections with `status=Election.Status.ARCHIVED` (`backend/api/views.py:187`) *before* any race-level filtering, so an archived parent election hides all its races regardless of `race_status`. This is confirmed behavior (see Task 2 Step 5) and is correct for now: the certification flow (`results/tasks.py:310-311`) only sets the **race** to `ARCHIVED` while leaving the parent election at `RESULTS_PENDING`/`RESULTS_CERTIFIED` (both visible), and no production code currently sets `Election.Status.ARCHIVED`. Do **not** relax the election-level exclusion in this change. If a future change archives elections, revisit `views.py:187` so certified races remain discoverable.

---

### Task 1: Public Race Visibility Filter

**Files:**
- Modify: `backend/api/views.py`
- Test: `backend/api/tests/test_views.py`

**Interfaces:**
- Produces: `_public_race_queryset(races)` helper returning a queryset filtered to `Race.RaceStatus.ACTIVE` and `Race.RaceStatus.ARCHIVED`.
- Consumes: Existing `Race.RaceStatus` enum and existing `RaceDetailSerializer`.

- [ ] **Step 1: Add failing election-races test**

Add this test near `test_election_races_action` in `backend/api/tests/test_views.py`:

```python
@pytest.mark.django_db
def test_election_races_action_includes_archived_certified_and_hides_nonpublic(client, election):
    active = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Active Governor',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='civic_api:9530:active-governor:ocd:candidate:2026-03-21',
    )
    archived = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Certified Governor',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ARCHIVED,
        certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        canonical_key='civic_api:9530:certified-governor:ocd:candidate:2026-03-21',
    )
    hidden_statuses = [
        Race.RaceStatus.DRAFT,
        Race.RaceStatus.PENDING_REVIEW,
        Race.RaceStatus.CANCELLED,
    ]
    for index, status in enumerate(hidden_statuses):
        Race.objects.create(
            election=election,
            race_type=Race.RaceType.CANDIDATE,
            office_title=f'Hidden {status}',
            jurisdiction='Louisiana',
            geography_scope='statewide',
            source=Race.Source.CIVIC_API,
            race_status=status,
            canonical_key=f'civic_api:9530:hidden-{index}:ocd:candidate:2026-03-21',
        )

    response = client.get(f'/api/v1/elections/{election.id}/races/')

    assert response.status_code == 200
    payload = response.json()
    results = payload.get('results', payload)
    returned_ids = {race['id'] for race in results}
    assert returned_ids == {active.id, archived.id}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
python -m pytest api/tests/test_views.py::test_election_races_action_includes_archived_certified_and_hides_nonpublic -v --tb=short
```

Expected: FAIL because archived race is not returned.

- [ ] **Step 3: Implement shared public race queryset helper**

In `backend/api/views.py`, add this helper below `resolve_state_from_zip`:

```python
def _public_race_queryset(races):
    return races.filter(
        race_status__in=[
            Race.RaceStatus.ACTIVE,
            Race.RaceStatus.ARCHIVED,
        ]
    )
```

Then change `ElectionViewSet.races()` to:

```python
        qs = (
            _public_race_queryset(election.races)
            .prefetch_related('candidates', 'measure_options')
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd backend
python -m pytest api/tests/test_views.py::test_election_races_action_includes_archived_certified_and_hides_nonpublic -v --tb=short
```

Expected: PASS.

### Task 2: Lookup Visibility Matches Election Races

**Files:**
- Modify: `backend/api/views.py`
- Test: `backend/api/tests/test_views.py`

**Interfaces:**
- Consumes: `_public_race_queryset(races)` from Task 1.
- Produces: Lookup responses whose `races` array includes `active` and `archived` races only, for any non-`ARCHIVED` parent election. Archived parent elections remain excluded at the election level (unchanged; see Global Constraints).

- [ ] **Step 1: Add failing lookup test**

Add this test near `test_lookup_election_id_filter` in `backend/api/tests/test_views.py`:

```python
@pytest.mark.django_db
def test_lookup_includes_archived_certified_and_hides_nonpublic(client, election):
    active = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Active Lookup Race',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='civic_api:9530:active-lookup:ocd:candidate:2026-03-21',
    )
    archived = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Archived Lookup Race',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ARCHIVED,
        certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        canonical_key='civic_api:9530:archived-lookup:ocd:candidate:2026-03-21',
    )
    Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Draft Lookup Race',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.DRAFT,
        canonical_key='civic_api:9530:draft-lookup:ocd:candidate:2026-03-21',
    )

    response = client.get(f'/api/v1/lookup/?zip=70801&election_id={election.id}')

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    returned_ids = {race['id'] for race in data[0]['races']}
    assert returned_ids == {active.id, archived.id}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
python -m pytest api/tests/test_views.py::test_lookup_includes_archived_certified_and_hides_nonpublic -v --tb=short
```

Expected: FAIL because lookup only returns active races.

- [ ] **Step 3: Reuse helper in lookup**

In `backend/api/views.py`, change `LookupView.get()` race query to:

```python
            races = (
                _public_race_queryset(election.races)
                .prefetch_related('candidates', 'measure_options')
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd backend
python -m pytest api/tests/test_views.py::test_lookup_includes_archived_certified_and_hides_nonpublic -v --tb=short
```

Expected: PASS.

- [ ] **Step 5: Add parent-election-status regression test**

The lookup tests above use the `election` fixture (`status=UPCOMING`), so they
never exercise the post-election states the goal actually targets. This test
pins down which parent `Election.status` values surface races through `/lookup/`
and locks in the intentional `ARCHIVED`-election exclusion (see Global
Constraints). It passes against the current code (the race is `ACTIVE`, so the
parent election status is the only variable) and must keep passing after the
Task 2 change. Add it near `test_lookup_election_id_filter` in
`backend/api/tests/test_views.py`:

```python
@pytest.mark.django_db
@pytest.mark.parametrize(
    'election_status,expected_visible',
    [
        (Election.Status.UPCOMING, True),
        (Election.Status.ACTIVE, True),
        (Election.Status.RESULTS_PENDING, True),
        (Election.Status.RESULTS_CERTIFIED, True),
        (Election.Status.ARCHIVED, False),
    ],
)
def test_lookup_parent_election_status_visibility(client, db, election_status, expected_visible):
    # Confirms which parent Election.status values are surfaced by /lookup/.
    # LookupView excludes Election.Status.ARCHIVED, so an archived parent
    # election hides its races regardless of race_status.
    parent = Election.objects.create(
        source_id='9531',
        name=f'Louisiana {election_status} Election',
        election_date='2026-03-21',
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='LA',
        status=election_status,
    )
    # Use an ACTIVE race so the current race-level filter passes; this isolates
    # the parent Election.status as the only variable under test.
    Race.objects.create(
        election=parent,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Governor',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key=f'civic_api:9531:gov-{election_status}:ocd:candidate:2026-03-21',
    )

    response = client.get(f'/api/v1/lookup/?zip=70801&election_id={parent.id}')

    assert response.status_code == 200
    data = response.json()
    if expected_visible:
        assert len(data) == 1
        assert len(data[0]['races']) == 1
    else:
        assert data == []
```

- [ ] **Step 6: Run parent-election-status test**

Run:

```bash
cd backend
python -m pytest api/tests/test_views.py::test_lookup_parent_election_status_visibility -v --tb=short
```

Expected: PASS (5 parametrized cases) — `ARCHIVED` parent hidden, all other statuses visible.

### Task 3: Preserve Separate Results Endpoint Contract

**Files:**
- Modify: `backend/api/tests/test_views.py`
- Test: `backend/api/tests/test_views.py`

**Interfaces:**
- Consumes: Existing `/api/v1/races/{id}/results/` action.
- Produces: Regression coverage proving archived races still expose results through the separate endpoint.

- [ ] **Step 1: Add archived-race results endpoint regression test**

Add this test below `test_race_results_action` in `backend/api/tests/test_views.py`:

```python
@pytest.mark.django_db
def test_archived_race_results_action_returns_plain_array(client, election):
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Certified Governor',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ARCHIVED,
        certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        canonical_key='civic_api:9530:certified-results:ocd:candidate:2026-03-21',
    )
    candidate = Candidate.objects.create(race=race, name='Jane Smith')
    OfficialResult.objects.create(
        race=race,
        candidate=candidate,
        vote_count=2500,
        result_type=OfficialResult.ResultType.OFFICIAL,
    )

    response = client.get(f'/api/v1/races/{race.id}/results/')

    assert response.status_code == 200
    results = response.json()
    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]['vote_count'] == 2500
    assert results[0]['result_type'] == OfficialResult.ResultType.OFFICIAL
```

- [ ] **Step 2: Run regression test**

Run:

```bash
cd backend
python -m pytest api/tests/test_views.py::test_archived_race_results_action_returns_plain_array -v --tb=short
```

Expected: PASS without production code changes.

### Task 4: Synchronous `poll_results` Management Command

**Files:**
- Modify: `backend/elections/management/commands/poll_results.py`
- Test: create `backend/elections/tests/test_poll_results_command.py`

**Interfaces:**
- Consumes: `results.tasks.poll_pending_results`
- Produces: `python manage.py poll_results` that calls `poll_pending_results()` synchronously and writes `Queued <n> elections for results polling.`

- [ ] **Step 1: Add failing management command test**

Create `backend/elections/tests/test_poll_results_command.py`:

```python
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command


def test_poll_results_command_runs_poll_task_synchronously():
    stdout = StringIO()

    with patch("elections.management.commands.poll_results.poll_pending_results") as mock_poll:
        mock_poll.return_value = {"queued": 3}
        call_command("poll_results", stdout=stdout)

    mock_poll.assert_called_once_with()
    assert "Queued 3 elections for results polling." in stdout.getvalue()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
python -m pytest elections/tests/test_poll_results_command.py -v --tb=short
```

Expected: FAIL because the command raises `CommandError`.

- [ ] **Step 3: Implement command**

Replace `backend/elections/management/commands/poll_results.py` with:

```python
from django.core.management.base import BaseCommand

from results.tasks import poll_pending_results


class Command(BaseCommand):
    help = "Poll pending elections for official results synchronously."

    def handle(self, *args, **options):
        result = poll_pending_results()
        queued = result.get("queued", 0) if isinstance(result, dict) else 0
        self.stdout.write(
            self.style.SUCCESS(f"Queued {queued} elections for results polling.")
        )
```

- [ ] **Step 4: Run command test to verify it passes**

Run:

```bash
cd backend
python -m pytest elections/tests/test_poll_results_command.py -v --tb=short
```

Expected: PASS.

### Task 5: Final Verification

**Files:**
- Verify only.

**Interfaces:**
- Consumes: All behavior from Tasks 1-4.
- Produces: Passing targeted tests and static checks.

- [ ] **Step 1: Run targeted API tests**

Run:

```bash
cd backend
python -m pytest api/tests/test_views.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 2: Run management command and results task tests**

Run:

```bash
cd backend
python -m pytest elections/tests/test_poll_results_command.py results/tests/test_tasks.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 3: Run Django system check**

Run:

```bash
cd backend
python manage.py check
```

Expected: `System check identified no issues`.

- [ ] **Step 4: Run Ruff**

Run:

```bash
cd backend
ruff check .
```

Expected: no lint errors.

- [ ] **Step 5: Review git diff**

Run:

```bash
git diff -- backend/api/views.py backend/api/tests/test_views.py backend/elections/management/commands/poll_results.py backend/elections/tests/test_poll_results_command.py
```

Expected: diff only contains the public race visibility helper, tests, and command fix.
