# Election Canonical-Key Collision Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `aggregation.ingest.ingest_election()` from silently merging unrelated, independently-scheduled special elections that happen to share a date, and repair the 44 production `Election` rows already corrupted by this collision (issue [#187](https://github.com/CivicMirror/CivicMirror-API/issues/187)).

**Architecture:** Add an optional `contest_group` discriminator to `election_canonical_key()`, mirroring the existing `contest_variant` parameter on `race_canonical_key()` (same additive, backward-compatible shape — see `aggregation/identity.py`). Thread it through `ingest_election()`. Wire six adapters (`ma_sos`, `ga_sos`, `sc_vrems`, `tx_goelect`, `va_elect`, `nc_sbe`) to populate it for `election_type="special"` using each adapter's own already-discovered per-contest source id. Ship one reusable Django management command that splits already-collided `Election` rows using the new key, run once per state after each adapter's code fix lands.

**Tech Stack:** Django 5, Celery, pytest (`--no-migrations` — see project convention), PostgreSQL (production), existing `aggregation.ingest` normalize-on-write merge engine.

## Global Constraints

- Every code change to `aggregation/identity.py` / `aggregation/ingest.py` must be additive-only: omitting the new parameter must produce byte-identical output to today, so all adapters not touched in this plan are unaffected (mirrors the existing `contest_variant` contract — see `test_race_canonical_key_omitted_variant_matches_pre_existing_key`).
- Run tests with `pytest <path> -q --no-migrations` (local test-DB creation breaks on a bad migration in this repo).
- `contest_group` is populated **only** when `election_type == Election.ElectionType.SPECIAL` in every adapter task — general/primary "one ballot, many offices" days must keep merging exactly as they do today; there is no evidence they're broken, and blindly discriminating them would create unwanted new `Election` rows.
- The repair management command must default to a dry run (require an explicit `--yes` flag to mutate) and must be safely re-runnable (querying for already-collided rows returns nothing once repaired, so a second run is a no-op).
- Do not touch `sc_enr`, `election_type` values other than `special`, or any state outside the six named in issue #187 — those are out of scope for this plan.

## File Structure

- Modify `backend/aggregation/identity.py` — add `contest_group` param to `election_canonical_key()`.
- Modify `backend/aggregation/ingest.py` — thread `identity.get("contest_group")` through `ingest_election()`.
- Modify `backend/aggregation/tests/test_identity.py` — new tests for `election_canonical_key`.
- Modify `backend/aggregation/tests/test_ingest.py` — new test proving `ingest_election` uses `contest_group`.
- Create `backend/elections/management/commands/repair_collided_elections.py` — generic repair command, plus `backend/elections/management/commands/__init__.py` and `.../management/__init__.py` if the `management` package doesn't already exist under `elections/`.
- Create `backend/elections/tests/test_repair_collided_elections.py`.
- Modify `backend/integrations/ma_sos/tasks.py`, `.../ga_sos/tasks.py`, `.../sc_vrems/tasks.py`, `.../tx_goelect/tasks.py`, `.../va_elect/tasks.py`, `.../nc_sbe/tasks.py` — populate `contest_group` in each adapter's `identity` dict for special elections (NC requires a structural change — see Task 8).
- Modify the corresponding `tests/test_tasks.py` in each of those six adapter packages.

---

### Task 1: Add `contest_group` to `election_canonical_key()` and thread it through `ingest_election()`

**Files:**
- Modify: `backend/aggregation/identity.py`
- Modify: `backend/aggregation/ingest.py`
- Test: `backend/aggregation/tests/test_identity.py`
- Test: `backend/aggregation/tests/test_ingest.py`

**Interfaces:**
- Produces: `election_canonical_key(state: str, election_type: str, election_date: date, jurisdiction_level: str, contest_group: str = "") -> str`. Every later task calls this (indirectly, via `ingest_election`) by putting `identity["contest_group"] = "<normalized string>"`.

- [ ] **Step 1: Write the failing tests in `test_identity.py`**

Add these next to the existing `race_canonical_key` variant tests (after line 198, following the exact same style):

```python
def test_election_canonical_key_omitted_contest_group_matches_pre_existing_key():
    """Default behavior (no contest_group) must be byte-identical to the
    pre-extension key, so existing sources are unaffected."""
    d = date(2025, 5, 13)
    assert (
        election_canonical_key("MA", "special", d, "state")
        == election_canonical_key("MA", "special", d, "state", "")
        == "MA:special:2025-05-13:state"
    )


def test_election_canonical_key_contest_group_appended_when_present():
    d = date(2025, 5, 13)
    key = election_canonical_key("MA", "special", d, "state", "state representative:6th essex")
    assert key == "MA:special:2025-05-13:state|state representative:6th essex"


def test_election_canonical_key_contest_group_disambiguates_same_day_specials():
    """The bug this fix exists for: MA's 6th Essex special general and 3rd
    Bristol special primary both fell on 2025-05-13 and collapsed into one
    Election (production id 2158) without this fix. See issue #187."""
    d = date(2025, 5, 13)
    essex = election_canonical_key("MA", "special", d, "state", "state representative:6th essex")
    bristol = election_canonical_key("MA", "special", d, "state", "state representative:3rd bristol")
    assert essex != bristol


def test_election_canonical_key_contest_group_is_case_and_whitespace_normalized():
    d = date(2025, 5, 13)
    a = election_canonical_key("MA", "special", d, "state", "State Representative:6th Essex")
    b = election_canonical_key("MA", "special", d, "state", "  state representative:6th essex  ")
    assert a == b


def test_election_canonical_key_blank_contest_group_after_normalization_is_omitted():
    d = date(2025, 5, 13)
    key = election_canonical_key("MA", "special", d, "state", "   ")
    assert key == "MA:special:2025-05-13:state"
```

The `date` import already exists at the top of `test_identity.py` (used by the `race_canonical_key` tests above).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest aggregation/tests/test_identity.py -q --no-migrations -k contest_group`
Expected: FAIL with `TypeError: election_canonical_key() takes 4 positional arguments but 5 were given` (or `got an unexpected keyword argument 'contest_group'`).

- [ ] **Step 3: Implement `contest_group` in `identity.py`**

Replace the existing `election_canonical_key` function (currently at `aggregation/identity.py`, right before `_normalize_variant`):

```python
def election_canonical_key(
    state: str, election_type: str, election_date: date, jurisdiction_level: str,
    contest_group: str = "",
) -> str:
    """
    contest_group is an optional, source-supplied disambiguator for elections
    that the (state, election_type, election_date, jurisdiction_level) tuple
    alone cannot tell apart — e.g. two unrelated special elections in
    different districts that happen to share a date (see issue #187).
    Omitted (the default), this is a no-op and produces the exact same key
    as before, so existing sources are unaffected. Mirrors
    race_canonical_key's contest_variant parameter.
    """
    key = f"{state}:{election_type}:{election_date.isoformat()}:{jurisdiction_level}"
    normalized_group = _squash(contest_group or "").lower()
    if normalized_group:
        key = f"{key}|{normalized_group}"
    return key
```

This reuses the existing `_squash` helper already defined above in the same file — no new import needed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest aggregation/tests/test_identity.py -q --no-migrations -k contest_group`
Expected: PASS (5 tests)

- [ ] **Step 5: Write the failing test in `test_ingest.py`**

Add after `test_two_sources_merge_onto_one_election` (around line 51):

```python
@pytest.mark.django_db
def test_ingest_election_contest_group_splits_same_day_specials(ca_precedence):
    """Two unrelated same-day special elections must NOT merge when the
    caller supplies distinct contest_group values. Regression test for
    issue #187 (MA 6th Essex / 3rd Bristol collision)."""
    identity_base = dict(
        state="MA", election_type="special",
        election_date=date(2025, 5, 13), jurisdiction_level="state",
    )
    essex, _ = ingest.ingest_election(
        source="ma_sos", source_id="ma_sos:171339",
        identity={**identity_base, "contest_group": "state representative:6th essex"},
        fields={"name": "6th Essex Special General"},
    )
    bristol, _ = ingest.ingest_election(
        source="ma_sos", source_id="ma_sos:171341",
        identity={**identity_base, "contest_group": "state representative:3rd bristol"},
        fields={"name": "3rd Bristol Special Primary — Republican"},
    )
    assert essex.pk != bristol.pk
    assert essex.canonical_key == "MA:special:2025-05-13:state|state representative:6th essex"
    assert bristol.canonical_key == "MA:special:2025-05-13:state|state representative:3rd bristol"


@pytest.mark.django_db
def test_ingest_election_omitted_contest_group_still_merges(ca_precedence):
    """Backward compatibility: callers that don't supply contest_group keep
    today's merge-by-date behavior."""
    identity = _election_identity()
    e1, _ = ingest.ingest_election(
        source="ca_sos", source_id="a", identity=identity, fields={"name": "A"},
    )
    e2, _ = ingest.ingest_election(
        source="civic_api", source_id="b", identity=identity, fields={"name": "B"},
    )
    assert e1.pk == e2.pk
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `cd backend && pytest aggregation/tests/test_ingest.py -q --no-migrations -k contest_group`
Expected: FAIL — both elections get the same `canonical_key` (`MA:special:2025-05-13:state`), so `essex.pk != bristol.pk` fails.

- [ ] **Step 7: Thread `contest_group` through `ingest_election` in `ingest.py`**

In `aggregation/ingest.py`, inside `ingest_election` (around line 60-95), change:

```python
    key = election_canonical_key(state, election_type, election_date, jurisdiction_level)
```

to:

```python
    contest_group = identity.get("contest_group", "")
    key = election_canonical_key(state, election_type, election_date, jurisdiction_level, contest_group)
```

No other lines in the function change — `identity.get("contest_group", "")` defaults to `""`, which `election_canonical_key` treats as a no-op, so every caller that doesn't set it is unaffected.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd backend && pytest aggregation/tests/test_ingest.py aggregation/tests/test_identity.py -q --no-migrations`
Expected: PASS (all tests, including the pre-existing ones — this confirms backward compatibility)

- [ ] **Step 9: Run the full aggregation test suite for regressions**

Run: `cd backend && pytest aggregation/ -q --no-migrations`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add backend/aggregation/identity.py backend/aggregation/ingest.py \
        backend/aggregation/tests/test_identity.py backend/aggregation/tests/test_ingest.py
git commit -m "feat(aggregation): add optional contest_group to election_canonical_key

Mirrors race_canonical_key's existing contest_variant parameter. Lets
adapters disambiguate independently-scheduled elections that happen to
share (state, election_type, election_date, jurisdiction_level) — see
issue #187."
```

---

### Task 2: Fix `ma_sos` + build the reusable repair command, applied to MA's 1 collided row

**Files:**
- Modify: `backend/integrations/ma_sos/tasks.py`
- Test: `backend/integrations/ma_sos/tests/test_tasks.py`
- Create: `backend/elections/management/__init__.py` (if absent)
- Create: `backend/elections/management/commands/__init__.py` (if absent)
- Create: `backend/elections/management/commands/repair_collided_elections.py`
- Test: `backend/elections/tests/test_repair_collided_elections.py`

**Interfaces:**
- Consumes: `election_canonical_key(..., contest_group: str = "")` and `ingest_election(identity: dict)` reading `identity["contest_group"]` from Task 1.
- Produces: `manage.py repair_collided_elections --state <XX> --group-by {jurisdiction,office_title} [--yes]` — every later adapter task (3-7) invokes this same command against its own state.

- [ ] **Step 1: Check whether `elections/management/` exists**

Run: `ls backend/elections/management/commands/ 2>&1`
If it doesn't exist, create both `__init__.py` files (empty) at `backend/elections/management/__init__.py` and `backend/elections/management/commands/__init__.py` — standard Django management-command package layout.

- [ ] **Step 2: Write the failing test for `ma_sos`'s `contest_group` wiring**

In `integrations/ma_sos/tests/test_tasks.py`, add after `test_sync_ma_elections_recovers_date_from_view_page_for_special_election` (around line 177):

```python
@patch("integrations.ma_sos.tasks.SyncLog")
@patch("integrations.ma_sos.tasks.sync_ma_races")
@patch("integrations.ma_sos.tasks.sync_ma_ballot_question")
@patch("integrations.ma_sos.tasks.MaSosClient")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_elections_special_populates_contest_group(
    mock_tz, mock_client_cls, mock_bq_task, mock_races_task, mock_synclog_cls,
):
    """Regression test for issue #187: two unrelated same-day MA specials
    (6th Essex general vs. 3rd Bristol primary) must get distinct
    contest_group values so ingest_election doesn't merge them."""
    from integrations.ma_sos.tasks import sync_ma_elections

    mock_log = MagicMock()
    mock_synclog_cls.objects.create.return_value = mock_log
    mock_synclog_cls.Status.STARTED = "started"
    mock_synclog_cls.Status.COMPLETED = "completed"
    mock_synclog_cls.Status.COMPLETED_WITH_WARNINGS = "warnings"
    mock_synclog_cls.Status.FAILED = "failed"

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.get_ocpf_schedule.return_value = {"generalElectionDate": "", "primaryElectionDate": ""}

    def fake_get_election_ids(year, stage):
        if year == 2025 and stage == "General":
            return [{
                "election_id": 171339, "office": "State Representative",
                "district": "6th Essex", "stage": "General", "year": 2025,
            }]
        if year == 2025 and stage == "Republican":
            return [{
                "election_id": 171341, "office": "State Representative",
                "district": "3rd Bristol", "stage": "Republican", "year": 2025,
            }]
        return []

    mock_client.get_election_ids.side_effect = fake_get_election_ids
    mock_client.get_ballot_question_ids.return_value = []
    mock_client.get_election_detail.side_effect = lambda eid: {
        171339: {"election_id": 171339, "date": "2025-05-13", "is_special": True, "year": 2025},
        171341: {"election_id": 171341, "date": "2025-05-13", "is_special": True, "year": 2025},
    }[eid]

    mock_saved_election = MagicMock()
    mock_saved_election.pk = 1
    mock_saved_election.source_metadata = {"electionstats_id": 171339}

    mock_tz.now.return_value = MagicMock()
    mock_tz.localdate.return_value = date(2025, 12, 1)

    with patch("integrations.ma_sos.tasks.date") as mock_date, \
         patch("aggregation.ingest.ingest_election", return_value=(mock_saved_election, True)) as mock_ingest:
        mock_date.today.return_value = date(2025, 12, 1)
        sync_ma_elections.run()

    calls = mock_ingest.call_args_list
    groups = {c.kwargs["identity"].get("contest_group", "") for c in calls}
    assert "" not in groups, "every special-election identity must set a non-empty contest_group"
    assert len(groups) == 2, "6th Essex and 3rd Bristol must get distinct contest_group values"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && pytest integrations/ma_sos/tests/test_tasks.py -q --no-migrations -k contest_group`
Expected: FAIL — `groups == {""}` since `contest_group` is never set today.

- [ ] **Step 4: Populate `contest_group` in `ma_sos/tasks.py`**

In `sync_ma_elections` (`integrations/ma_sos/tasks.py`), the `identity` dict is built at line 150-155:

```python
            identity = {
                "state": mapped["state"],
                "election_type": mapped["election_type"],
                "election_date": mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
```

Change to:

```python
            identity = {
                "state": mapped["state"],
                "election_type": mapped["election_type"],
                "election_date": mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            if mapped["election_type"] == Election.ElectionType.SPECIAL:
                office = row.get("office", "")
                district = row.get("district", "")
                identity["contest_group"] = f"{office}:{district}".strip().lower()
```

`row` (the discovery-row dict from `client.get_election_ids`) is already in scope at this point in the loop (`for idx, row in enumerate(unique_rows):`), and both `office`/`district` are present on every row per the docstring at the top of the file. `Election` is already imported at the top of `tasks.py` (`from elections.models import Election, MeasureOption, Race`).

The date-recovery fallback branch a few lines above (lines 128-149, the `client.get_election_detail` call for elections OCPF has no date for) also needs the same treatment, since it independently sets `mapped["election_type"] = "special"` — the `contest_group` line above already runs *after* that branch (it's outside the `if mapped.get("election_date") is None:` block), so it picks up the recovered type/date correctly without any extra change.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && pytest integrations/ma_sos/tests/test_tasks.py -q --no-migrations -k contest_group`
Expected: PASS

- [ ] **Step 6: Run the full ma_sos test suite for regressions**

Run: `cd backend && pytest integrations/ma_sos/ -q --no-migrations`
Expected: PASS

- [ ] **Step 7: Write the failing test for the repair command**

Create `backend/elections/tests/test_repair_collided_elections.py`:

```python
import datetime

import pytest
from django.core.management import call_command

from elections.models import Election, ElectionSourceLink, Race


@pytest.mark.django_db
def test_repair_splits_ma_6th_essex_3rd_bristol_collision():
    """Reproduces production Election id 2158 (issue #187): 6th Essex
    special general + 3rd Bristol special primary collapsed onto one
    Election because contest_group didn't exist yet."""
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="2025 MA State Representative 3rd Bristol Republican",
    )
    ElectionSourceLink.objects.create(election=collided, source="ma_sos", source_id="ma_sos:171341")
    essex = Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-essex",
    )
    bristol_d = Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-bristol-d",
    )
    bristol_r = Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-bristol-r",
    )

    call_command("repair_collided_elections", state="MA", group_by="jurisdiction", yes=True)

    essex.refresh_from_db()
    bristol_d.refresh_from_db()
    bristol_r.refresh_from_db()

    assert essex.election_id != bristol_d.election_id
    assert bristol_d.election_id == bristol_r.election_id
    assert not Election.objects.filter(pk=collided.pk).exists()
    assert Election.objects.filter(
        canonical_key="MA:special:2025-05-13:state|6th essex"
    ).exists()
    assert Election.objects.filter(
        canonical_key="MA:special:2025-05-13:state|3rd bristol"
    ).exists()


@pytest.mark.django_db
def test_repair_dry_run_makes_no_changes():
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="Collided",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-essex",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-bristol",
    )

    call_command("repair_collided_elections", state="MA", group_by="jurisdiction")  # no --yes

    assert Election.objects.filter(pk=collided.pk).exists()
    assert Election.objects.count() == 1


@pytest.mark.django_db
def test_repair_is_idempotent():
    """A second run after a successful repair finds nothing left to split."""
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="Collided",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-essex",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-bristol",
    )

    call_command("repair_collided_elections", state="MA", group_by="jurisdiction", yes=True)
    count_after_first_run = Election.objects.count()
    call_command("repair_collided_elections", state="MA", group_by="jurisdiction", yes=True)

    assert Election.objects.count() == count_after_first_run
```

- [ ] **Step 8: Run the tests to verify they fail**

Run: `cd backend && pytest elections/tests/test_repair_collided_elections.py -q --no-migrations`
Expected: FAIL with `django.core.management.base.CommandError: Unknown command: 'repair_collided_elections'`

- [ ] **Step 9: Implement the repair command**

Create `backend/elections/management/commands/repair_collided_elections.py`:

```python
"""
Split Election rows that collapsed unrelated same-day special elections
before contest_group existed on election_canonical_key. See issue #187.

Usage:
    python manage.py repair_collided_elections --state MA --group-by jurisdiction
    python manage.py repair_collided_elections --state MA --group-by jurisdiction --yes
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from aggregation.identity import election_canonical_key
from elections.models import Election, ElectionSourceLink, Race

_GROUP_FIELDS = {"jurisdiction", "office_title"}


class Command(BaseCommand):
    help = "Split Election rows whose Races span more than one distinct contest (issue #187)."

    def add_arguments(self, parser):
        parser.add_argument("--state", required=True, help="Two-letter state code, e.g. MA")
        parser.add_argument(
            "--group-by", required=True, choices=sorted(_GROUP_FIELDS),
            help="Race field that distinguishes the collided contests",
        )
        parser.add_argument(
            "--yes", action="store_true",
            help="Actually mutate the database. Without this flag, only prints what would happen.",
        )

    def handle(self, *args, **options):
        state = options["state"]
        group_by = options["group_by"]
        apply_changes = options["yes"]

        collided = (
            Election.objects.filter(state=state, election_type="special")
            .annotate(n_groups=Count(f"races__{group_by}", distinct=True))
            .filter(n_groups__gt=1)
            .order_by("election_date")
        )

        if not collided.exists():
            self.stdout.write(self.style.SUCCESS(f"No collided special elections found for {state}."))
            return

        for election in collided:
            self._split_one(election, group_by, apply_changes)

    def _split_one(self, election: Election, group_by: str, apply_changes: bool) -> None:
        races = list(election.races.all())
        groups: dict[str, list[Race]] = {}
        for race in races:
            raw_value = getattr(race, group_by) or ""
            key = " ".join(raw_value.split()).lower()
            groups.setdefault(key, []).append(race)

        if len(groups) <= 1:
            return  # annotate() can be stale mid-loop after a prior split; skip if already fixed

        self.stdout.write(
            f"Election {election.pk} ({election.name!r}, {election.canonical_key}): "
            f"splitting into {len(groups)} groups by {group_by}"
        )

        with transaction.atomic():
            for group_value, group_races in groups.items():
                new_key = election_canonical_key(
                    election.state, election.election_type, election.election_date,
                    election.jurisdiction_level, contest_group=group_value,
                )
                sample = group_races[0]
                titles = ", ".join(sorted({r.office_title for r in group_races}))
                self.stdout.write(
                    f"  group={group_value!r} -> canonical_key={new_key} "
                    f"({len(group_races)} race(s): {titles})"
                )
                if not apply_changes:
                    continue

                new_election, created = Election.objects.get_or_create(
                    canonical_key=new_key,
                    defaults={
                        "state": election.state,
                        "election_type": election.election_type,
                        "election_date": election.election_date,
                        "jurisdiction_level": election.jurisdiction_level,
                        "name": f"{election.name} ({sample.jurisdiction or sample.office_title})",
                        "status": election.status,
                        "last_synced_at": election.last_synced_at,
                        "source_metadata": {"repaired_from_election_id": election.pk},
                        "contributing_sources": list(election.contributing_sources or []),
                    },
                )
                for race in group_races:
                    race.election = new_election
                    race.save(update_fields=["election"])

            if apply_changes:
                ElectionSourceLink.objects.filter(election=election).delete()
                election.delete()

        if apply_changes:
            self.stdout.write(self.style.SUCCESS(f"  done — original Election {election.pk} removed"))
        else:
            self.stdout.write(self.style.WARNING("  (dry run — pass --yes to apply)"))
```

`election.races` uses the `related_name="races"` already defined on `Race.election` (`elements/models.py:142`). Reparenting every group's races happens before the original `Election` (and its cascading `ElectionSourceLink` rows) is deleted, so no `Race` rows are ever orphaned mid-transaction — the whole split for one collided election runs inside `transaction.atomic()`.

- [ ] **Step 10: Run the tests to verify they pass**

Run: `cd backend && pytest elections/tests/test_repair_collided_elections.py -q --no-migrations`
Expected: PASS (3 tests)

- [ ] **Step 11: Dry-run the command against production data for MA, then apply it**

```bash
cd /data/DockerConfigs/CivicMirror
docker exec civicmirror-api python manage.py repair_collided_elections --state MA --group-by jurisdiction
```

Confirm the printed output shows exactly one collided election (id 2158) splitting into 2 groups (`3rd bristol` with 2 races, `6th essex` with 1 race), then re-run with `--yes`:

```bash
docker exec civicmirror-api python manage.py repair_collided_elections --state MA --group-by jurisdiction --yes
```

- [ ] **Step 12: Verify against production DB**

```bash
docker exec civicmirror-postgres psql -U civicmirror -d civicmirror_api -c "
SELECT e.id, e.election_date, e.name, e.canonical_key
FROM elections_election e WHERE e.state='MA' AND e.election_date='2025-05-13';
"
```
Expected: two rows now, one per district, neither named "3rd Bristol Republican" while containing the other district's race.

- [ ] **Step 13: Commit**

```bash
git add backend/integrations/ma_sos/tasks.py backend/integrations/ma_sos/tests/test_tasks.py \
        backend/elections/management backend/elections/tests/test_repair_collided_elections.py
git commit -m "fix(ma_sos): populate contest_group for special elections; add repair command

Fixes the 6th Essex / 3rd Bristol same-day collision (issue #187). Adds
a reusable repair_collided_elections management command used by this
and the following per-state fixes."
```

---

### Task 3: Fix `ga_sos` (27 collided rows — highest volume)

**Files:**
- Modify: `backend/integrations/ga_sos/tasks.py`
- Test: `backend/integrations/ga_sos/tests/test_tasks.py`

**Interfaces:**
- Consumes: `repair_collided_elections` command from Task 2.

**Background:** GA's `client.list_elections()` already returns one row per `publicElectionId` — Georgia's own Enhanced Voting platform's per-contest identifier, already captured as `source_metadata["ga_public_election_id"]` in `map_election()` (`integrations/ga_sos/mappers.py:110-128`). This is the natural `contest_group` value; no new data needs to be fetched.

- [ ] **Step 1: Write the failing test**

In `integrations/ga_sos/tests/test_tasks.py`, add after `test_sync_ga_elections_discovers_elections_and_queues_race_sync` (around line 53):

```python
def test_sync_ga_elections_special_populates_contest_group():
    """Regression test for issue #187: GA batches unrelated same-day
    specials under distinct publicElectionIds — contest_group must use
    that id so they don't collapse into one Election."""
    election_row = {
        "publicElectionId": "01092018SpecialGeneral-HD111",
        "name": [{"text": "January 9, 2018 - Special Election"}],
        "electionDate": "2018-01-09",
    }
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.source_metadata = {}

    with patch("integrations.ga_sos.tasks.GaSosClient") as mock_client_cls, \
         patch("integrations.ga_sos.tasks.SyncLog") as mock_log_cls, \
         patch("integrations.ga_sos.tasks.sync_ga_races"), \
         patch("aggregation.ingest.ingest_election", return_value=(mock_election, True)) as mock_ingest:
        _mock_sync_log(mock_log_cls)
        mock_client_cls.return_value.list_elections.return_value = [election_row]

        sync_ga_elections()

    kwargs = mock_ingest.call_args.kwargs
    assert kwargs["identity"]["contest_group"] == "01092018specialgeneral-hd111"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest integrations/ga_sos/tests/test_tasks.py -q --no-migrations -k contest_group`
Expected: FAIL with `KeyError: 'contest_group'`

- [ ] **Step 3: Populate `contest_group` in `ga_sos/tasks.py`**

In `sync_ga_elections` (`integrations/ga_sos/tasks.py:48-53`), change:

```python
            identity = {
                "state": mapped["state"],
                "election_type": mapped["election_type"],
                "election_date": mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
```

to:

```python
            identity = {
                "state": mapped["state"],
                "election_type": mapped["election_type"],
                "election_date": mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            if mapped["election_type"] == Election.ElectionType.SPECIAL:
                identity["contest_group"] = public_id.lower()
```

`public_id` is already in scope (`public_id = (row.get("publicElectionId") or "").strip()`, line 35), and `Election` is already imported at the top of the file.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && pytest integrations/ga_sos/tests/test_tasks.py -q --no-migrations -k contest_group`
Expected: PASS

- [ ] **Step 5: Run the full ga_sos test suite for regressions**

Run: `cd backend && pytest integrations/ga_sos/ -q --no-migrations`
Expected: PASS

- [ ] **Step 6: Dry-run then apply the repair command for GA**

```bash
docker exec civicmirror-api python manage.py repair_collided_elections --state GA --group-by jurisdiction
```

Inspect the output carefully — GA has the widest merges found (up to 140 districts in one row, election id 2135). Confirm the group count and office titles printed look sane (spot-check a couple of groups against `docker exec civicmirror-postgres psql ...` before applying), then:

```bash
docker exec civicmirror-api python manage.py repair_collided_elections --state GA --group-by jurisdiction --yes
```

- [ ] **Step 7: Verify against production DB**

```bash
docker exec civicmirror-postgres psql -U civicmirror -d civicmirror_api -c "
SELECT e.id, COUNT(DISTINCT r.jurisdiction) AS n
FROM elections_election e JOIN elections_race r ON r.election_id = e.id
WHERE e.state='GA' AND e.election_type='special'
GROUP BY e.id HAVING COUNT(DISTINCT r.jurisdiction) > 1;
"
```
Expected: 0 rows.

- [ ] **Step 8: Commit**

```bash
git add backend/integrations/ga_sos/tasks.py backend/integrations/ga_sos/tests/test_tasks.py
git commit -m "fix(ga_sos): populate contest_group from publicElectionId for special elections

Fixes 27 collided Election rows (issue #187) — GA already discovers a
per-contest id, it just wasn't reaching ingest_election's identity."
```

---

### Task 4: Fix `sc_vrems` (4 collided rows) + verify `sc_enr` degrades safely

**Files:**
- Modify: `backend/integrations/sc_vrems/tasks.py`
- Test: `backend/integrations/sc_vrems/tests/test_tasks.py`

**Interfaces:**
- Consumes: `repair_collided_elections` command from Task 2.

**Background:** Same shape as GA — `client.get_all_elections()` already returns one row per VREMS `electionId`, captured as `source_metadata["vrems_election_id"]` via `map_election()`. Confirmed from production data: race 9980 ("City Council Seat, Johnsonville", Florence Co.) has `vrems_election_id="22744"`; race 9981 ("School Board, District 1", Lexington Co.) has `vrems_election_id="22746"` — both under the same collided `Election` id 1790 today.

**Downstream risk to verify, not fix:** `integrations/sc_enr/mappers.py::attempt_election_link` links `ENRElection` rows to `Election` rows by `(election_date, state="SC")` alone, requiring *exactly one* match — it currently relies on SC's collision bug to make that single-match assumption hold. Splitting same-day SC specials will make some dates resolve to multiple `Election` rows, which `attempt_election_link` already handles safely: `len(matches) > 1` returns `(None, "ambiguous")` (see `sc_enr/mappers.py:94-101`), a safe degrade to "needs manual link," not a crash or wrong link. No code change needed there; Step 6 below just confirms this behavior with a test.

- [ ] **Step 1: Write the failing test**

In `integrations/sc_vrems/tests/test_tasks.py`, add after `test_sync_sc_elections_creates_election` (around line 37):

```python
@pytest.mark.django_db
@patch("integrations.sc_vrems.tasks.VremsClient")
def test_sync_sc_elections_special_populates_contest_group(MockClient):
    """Regression test for issue #187: unrelated same-day SC specials
    (different towns/counties) must not collapse into one Election."""
    MockClient.return_value.get_all_elections.return_value = [
        {
            "electionId": "22744",
            "electionName": "City of Johnsonville Special Election",
            "displayName": "6/23/2026 City of Johnsonville Special Election",
            "electionDate": "2026-06-23T00:00:00",
            "filingPeriodBeginDate": "2020-03-16T12:00:00",
            "electionType": "Special",
        },
        {
            "electionId": "22746",
            "electionName": "Lexington School Board District 1 Special Election",
            "displayName": "6/23/2026 Lexington School Board District 1 Special Election",
            "electionDate": "2026-06-23T00:00:00",
            "filingPeriodBeginDate": "2020-03-16T12:00:00",
            "electionType": "Special",
        },
    ]
    with patch("integrations.sc_vrems.tasks.sync_sc_races"):
        from integrations.sc_vrems.tasks import sync_sc_elections
        sync_sc_elections()

    from elections.models import Election
    johnsonville = Election.objects.get(source_id__isnull=True, canonical_key__endswith="|22744")
    lexington = Election.objects.get(canonical_key__endswith="|22746")
    assert johnsonville.pk != lexington.pk
```

Adjust the lookup if `map_election` doesn't set `source_id=None` on the `Election` model directly (it's popped into `ElectionSourceLink` per the `ingest_election` contract from Task 1) — use `Election.objects.get(canonical_key__endswith="|22744")` for both instead if the `source_id__isnull` filter doesn't match; confirm the exact assertion against `map_election`'s actual output before finalizing (see Step 3).

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest integrations/sc_vrems/tests/test_tasks.py -q --no-migrations -k contest_group`
Expected: FAIL — both rows produce the same `canonical_key` (no `|22744`/`|22746` suffix at all).

- [ ] **Step 3: Populate `contest_group` in `sc_vrems/tasks.py`**

In `sync_sc_elections` (`integrations/sc_vrems/tasks.py:55-60`), change:

```python
            identity = {
                "state":              mapped["state"],
                "election_type":      mapped["election_type"],
                "election_date":      mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
```

to:

```python
            identity = {
                "state":              mapped["state"],
                "election_type":      mapped["election_type"],
                "election_date":      mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            if mapped["election_type"] == Election.ElectionType.SPECIAL:
                vrems_id = (mapped.get("source_metadata") or {}).get("vrems_election_id", "")
                identity["contest_group"] = str(vrems_id).lower()
```

Add `from elections.models import Election` to the imports at the top of `sc_vrems/tasks.py` if not already present — check first: `grep -n "^from elections.models" integrations/sc_vrems/tasks.py`. Confirm `map_election()` in `sc_vrems/mappers.py` actually stores the VREMS id under `source_metadata["vrems_election_id"]` (matching what production data showed) before writing this line — `grep -n "vrems_election_id" integrations/sc_vrems/mappers.py`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && pytest integrations/sc_vrems/tests/test_tasks.py -q --no-migrations -k contest_group`
Expected: PASS

- [ ] **Step 5: Run the full sc_vrems test suite for regressions**

Run: `cd backend && pytest integrations/sc_vrems/ -q --no-migrations`
Expected: PASS

- [ ] **Step 6: Write a test proving `sc_enr`'s linker degrades safely on a split date**

In `integrations/sc_enr/tests/test_mappers.py` (check the file exists first: `ls integrations/sc_enr/tests/`), add:

```python
@pytest.mark.django_db
def test_attempt_election_link_ambiguous_when_date_has_multiple_elections():
    """After the sc_vrems contest_group fix, a same-day split into two
    Elections must make attempt_election_link report ambiguous rather than
    silently picking one — confirms issue #187's fix doesn't introduce a
    wrong auto-link (verification, not new behavior: this branch already
    existed at mappers.py:94-101)."""
    from elections.models import Election
    from integrations.sc_enr.mappers import attempt_election_link
    from integrations.sc_enr.models import ENRElection

    d = datetime.date(2026, 6, 23)
    Election.objects.create(
        state="SC", election_type="special", election_date=d,
        jurisdiction_level=Election.JurisdictionLevel.LOCAL,
        canonical_key="SC:special:2026-06-23:local|22744", name="Johnsonville",
    )
    Election.objects.create(
        state="SC", election_type="special", election_date=d,
        jurisdiction_level=Election.JurisdictionLevel.LOCAL,
        canonical_key="SC:special:2026-06-23:local|22746", name="Lexington",
    )
    enr = ENRElection.objects.create(
        eid=99999, election_date=d, scope=ENRElection.Scope.STATE, county=None,
        election_name="test", enr_base_url="https://example.com/SC/99999/",
    )

    election_obj, confidence = attempt_election_link(enr)

    assert election_obj is None
    assert confidence == ENRElection.LinkConfidence.AMBIGUOUS
```

Check `ENRElection`'s actual required fields via `grep -n "class ENRElection" -A 30 integrations/sc_enr/models.py` before finalizing the `.objects.create(...)` call — adjust field names/required args to match.

- [ ] **Step 7: Run the test to verify it passes (no code change expected)**

Run: `cd backend && pytest integrations/sc_enr/tests/test_mappers.py -q --no-migrations -k ambiguous_when_date_has_multiple`
Expected: PASS immediately — this step is verification, confirming the existing `len(matches) > 1` branch in `attempt_election_link` already handles this correctly. If it fails, stop and re-read `attempt_election_link` before changing anything — that would mean the risk noted above is real and needs its own fix, out of scope for this task.

- [ ] **Step 8: Dry-run then apply the repair command for SC**

```bash
docker exec civicmirror-api python manage.py repair_collided_elections --state SC --group-by jurisdiction
docker exec civicmirror-api python manage.py repair_collided_elections --state SC --group-by jurisdiction --yes
```

- [ ] **Step 9: Verify against production DB**

```bash
docker exec civicmirror-postgres psql -U civicmirror -d civicmirror_api -c "
SELECT e.id, COUNT(DISTINCT r.jurisdiction) AS n
FROM elections_election e JOIN elections_race r ON r.election_id = e.id
WHERE e.state='SC' AND e.election_type='special'
GROUP BY e.id HAVING COUNT(DISTINCT r.jurisdiction) > 1;
"
```
Expected: 0 rows.

- [ ] **Step 10: Commit**

```bash
git add backend/integrations/sc_vrems/tasks.py backend/integrations/sc_vrems/tests/test_tasks.py \
        backend/integrations/sc_enr/tests/test_mappers.py
git commit -m "fix(sc_vrems): populate contest_group from vrems_election_id for special elections

Fixes 4 collided Election rows (issue #187). Adds a verification test
confirming sc_enr's attempt_election_link already degrades safely
(ambiguous, not a wrong auto-link) when a date resolves to more than
one Election post-fix."
```

---

### Task 5: Fix `tx_goelect` (2 collided rows — two call sites)

**Files:**
- Modify: `backend/integrations/tx_goelect/tasks.py`
- Test: `backend/integrations/tx_goelect/tests/test_tasks.py`

**Interfaces:**
- Consumes: `repair_collided_elections` command from Task 2.

**Background:** TX discovers per-contest `election_id`s in two places — the `electionConstants` loop (`sync_tx_elections`, lines 72-113) and the sequential-ID probe loop (lines 115-170+) — both already captured as `source_metadata["tx_election_id"]` via `classify_election()` (`tx_goelect/mappers.py:34-50`). Confirmed from production: race 11091 ("STATE SENATOR, DISTRICT 9") and race 11097 ("U.S. REPRESENTATIVE DISTRICT 18") are unrelated offices/chambers merged under one Election (id 2004) today.

- [ ] **Step 1: Write the failing test**

In `integrations/tx_goelect/tests/test_tasks.py`, find the existing helper `_run_sync_tx_elections_with_one_online_election` (around line 16) and add a new test after it that exercises two elections in one run:

```python
def test_sync_tx_elections_special_populates_contest_group():
    """Regression test for issue #187: TX's CD18 special and an unrelated
    SD9 special landing on the same date must not collapse into one
    Election — contest_group must use TX's own per-row election_id."""
    constants = {
        "electionInfo": {
            "2025": {
                "SP": {
                    "11090": {"O": "Y", "N": "SPECIAL ELECTION CONGRESSIONAL DISTRICT 18"},
                    "11088": {"O": "Y", "N": "SPECIAL ELECTION STATE SENATE DISTRICT 9"},
                }
            }
        }
    }
    home = {"ElecDate": "11042025", "CountiesReporting": {"CR": 1, "CT": 1}}
    ingest_calls = []

    def fake_ingest_election(**kwargs):
        ingest_calls.append(kwargs)
        m = MagicMock()
        m.pk = len(ingest_calls)
        return m, True

    with patch("integrations.tx_goelect.tasks.TxGoElectClient") as MockClient, \
         patch("integrations.tx_goelect.tasks.SyncLog") as MockLog, \
         patch("integrations.tx_goelect.tasks.cache") as mock_cache, \
         patch("integrations.tx_goelect.tasks.sync_tx_races"), \
         patch("aggregation.ingest.ingest_election", side_effect=fake_ingest_election):

        client = MockClient.return_value
        client.get_election_constants.return_value = constants
        client.get_election_data.return_value = {"version": 1, "home": home, "lookups": {}}
        client.probe_election.return_value = False
        mock_cache.get.side_effect = lambda key, default=None: 99999 if "watermark" in key else default
        MockLog.objects.create.return_value = _mock_log()

        sync_tx_elections.run()

    groups = {c["identity"].get("contest_group", "") for c in ingest_calls}
    assert "" not in groups
    assert len(groups) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest integrations/tx_goelect/tests/test_tasks.py -q --no-migrations -k contest_group`
Expected: FAIL — `groups == {""}`.

- [ ] **Step 3: Populate `contest_group` at both call sites in `tx_goelect/tasks.py`**

First call site (`electionConstants` loop, lines 95-100):

```python
                    identity = {
                        "state": fields["state"],
                        "election_type": fields["election_type"],
                        "election_date": fields["election_date"],
                        "jurisdiction_level": fields["jurisdiction_level"],
                    }
```

becomes:

```python
                    identity = {
                        "state": fields["state"],
                        "election_type": fields["election_type"],
                        "election_date": fields["election_date"],
                        "jurisdiction_level": fields["jurisdiction_level"],
                    }
                    if fields["election_type"] == Election.ElectionType.SPECIAL:
                        identity["contest_group"] = str(election_id).lower()
```

Second call site (sequential probe loop, lines 151-156) — identical change, using `probe_id` instead of `election_id`:

```python
            identity = {
                "state": fields["state"],
                "election_type": fields["election_type"],
                "election_date": fields["election_date"],
                "jurisdiction_level": fields["jurisdiction_level"],
            }
            if fields["election_type"] == Election.ElectionType.SPECIAL:
                identity["contest_group"] = str(probe_id).lower()
```

Check whether `Election` is already imported in `tx_goelect/tasks.py` (`grep -n "^from elections.models" integrations/tx_goelect/tasks.py`); add `from elections.models import Election` if not.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && pytest integrations/tx_goelect/tests/test_tasks.py -q --no-migrations -k contest_group`
Expected: PASS

- [ ] **Step 5: Run the full tx_goelect test suite for regressions**

Run: `cd backend && pytest integrations/tx_goelect/ -q --no-migrations`
Expected: PASS

- [ ] **Step 6: Dry-run then apply the repair command for TX**

```bash
docker exec civicmirror-api python manage.py repair_collided_elections --state TX --group-by jurisdiction
docker exec civicmirror-api python manage.py repair_collided_elections --state TX --group-by jurisdiction --yes
```

- [ ] **Step 7: Verify against production DB**

```bash
docker exec civicmirror-postgres psql -U civicmirror -d civicmirror_api -c "
SELECT e.id, COUNT(DISTINCT r.jurisdiction) AS n
FROM elections_election e JOIN elections_race r ON r.election_id = e.id
WHERE e.state='TX' AND e.election_type='special'
GROUP BY e.id HAVING COUNT(DISTINCT r.jurisdiction) > 1;
"
```
Expected: 0 rows.

- [ ] **Step 8: Commit**

```bash
git add backend/integrations/tx_goelect/tasks.py backend/integrations/tx_goelect/tests/test_tasks.py
git commit -m "fix(tx_goelect): populate contest_group from tx_election_id for special elections

Fixes 2 collided Election rows (issue #187) at both discovery call
sites (electionConstants loop + sequential ID probe)."
```

---

### Task 6: Fix `va_elect` (4 collided rows)

**Files:**
- Modify: `backend/integrations/va_elect/tasks.py`
- Test: `backend/integrations/va_elect/tests/test_tasks.py`

**Interfaces:**
- Consumes: `repair_collided_elections` command from Task 2.

**Background:** Same shape as GA/SC/TX — `client.get_election_slugs()` already returns one slug per contest, captured as `source_metadata["enr_slug"]` via `map_election()`. Confirmed from production: election id 1851 ("2025 January 7 Specials") merges 3 unrelated House of Delegates districts (10th, 26th, 32nd).

- [ ] **Step 1: Write the failing test**

In `integrations/va_elect/tests/test_tasks.py`, using the existing `_make_election_dict` helper (line 14), add:

```python
def test_sync_va_elections_special_populates_contest_group():
    """Regression test for issue #187: VA bundles unrelated same-day
    House of Delegates specials — contest_group must use the per-contest
    ENR slug so they don't collapse into one Election."""
    d1 = _make_election_dict(slug="2025-January-Special-HD10")
    d1["election_type"] = "special"
    d1["election_date"] = _date(2025, 1, 7)
    d2 = _make_election_dict(slug="2025-January-Special-HD26")
    d2["election_type"] = "special"
    d2["election_date"] = _date(2025, 1, 7)

    ingest_calls = []

    def fake_ingest_election(**kwargs):
        ingest_calls.append(kwargs)
        m = MagicMock()
        m.pk = len(ingest_calls)
        m.source_metadata = {}
        return m, True

    with patch("integrations.va_elect.tasks.VaElectClient") as MockClient, \
         patch("integrations.va_elect.tasks.SyncLog") as MockLog, \
         patch("integrations.va_elect.tasks.sync_va_races"), \
         patch("integrations.va_elect.tasks.map_election", side_effect=[d1, d2]), \
         patch("aggregation.ingest.ingest_election", side_effect=fake_ingest_election):

        client = MockClient.return_value
        client.get_election_slugs.return_value = ["2025-January-Special-HD10", "2025-January-Special-HD26"]
        client.get_election_metadata.side_effect = lambda slug: {}

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log

        sync_va_elections()

    groups = {c["identity"].get("contest_group", "") for c in ingest_calls}
    assert "" not in groups
    assert len(groups) == 2
```

Check the exact import path for `map_election` used by `va_elect/tasks.py` (`grep -n "^from .mappers import\|^from integrations.va_elect.mappers import" integrations/va_elect/tasks.py`) and adjust the `patch("integrations.va_elect.tasks.map_election", ...)` target if it's imported under a different name.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest integrations/va_elect/tests/test_tasks.py -q --no-migrations -k contest_group`
Expected: FAIL — `groups == {""}`.

- [ ] **Step 3: Populate `contest_group` in `va_elect/tasks.py`**

In `sync_va_elections` (`integrations/va_elect/tasks.py:76-81`), change:

```python
            identity = {
                "state":              mapped["state"],
                "election_type":      mapped["election_type"],
                "election_date":      mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
```

to:

```python
            identity = {
                "state":              mapped["state"],
                "election_type":      mapped["election_type"],
                "election_date":      mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            if mapped["election_type"] == Election.ElectionType.SPECIAL:
                identity["contest_group"] = enr_slug_value.lower()
```

`enr_slug_value` is already computed one line below the current identity block (`enr_slug_value = (fields.get("source_metadata") or {}).get("enr_slug", "")`, line 83) — move that line up so it's available before building `identity`:

```python
            fields = {k: v for k, v in mapped.items() if k not in identity}
            enr_slug_value = (fields.get("source_metadata") or {}).get("enr_slug", "")
```

needs to happen before the `identity["contest_group"] = ...` line, but `fields` itself is built from `mapped` and `identity` — reorder to:

```python
            source_id = mapped.pop("source_id")
            enr_slug_value = (mapped.get("source_metadata") or {}).get("enr_slug", "")
            identity = {
                "state":              mapped["state"],
                "election_type":      mapped["election_type"],
                "election_date":      mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            if mapped["election_type"] == Election.ElectionType.SPECIAL:
                identity["contest_group"] = enr_slug_value.lower()
            fields = {k: v for k, v in mapped.items() if k not in identity}
```

and delete the now-duplicate `enr_slug_value = (fields.get("source_metadata") or {}).get("enr_slug", "")` line that follows (previously line 83) since it's computed above now. Check `Election` is imported (`grep -n "^from elections.models" integrations/va_elect/tasks.py`) — add if missing.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && pytest integrations/va_elect/tests/test_tasks.py -q --no-migrations -k contest_group`
Expected: PASS

- [ ] **Step 5: Run the full va_elect test suite for regressions**

Run: `cd backend && pytest integrations/va_elect/ -q --no-migrations`
Expected: PASS (this also confirms the `enr_slug_value` reordering didn't break the existing "force-write enr_slug" logic later in the function, which still reads `enr_slug_value`)

- [ ] **Step 6: Dry-run then apply the repair command for VA**

```bash
docker exec civicmirror-api python manage.py repair_collided_elections --state VA --group-by jurisdiction
docker exec civicmirror-api python manage.py repair_collided_elections --state VA --group-by jurisdiction --yes
```

- [ ] **Step 7: Verify against production DB**

```bash
docker exec civicmirror-postgres psql -U civicmirror -d civicmirror_api -c "
SELECT e.id, COUNT(DISTINCT r.jurisdiction) AS n
FROM elections_election e JOIN elections_race r ON r.election_id = e.id
WHERE e.state='VA' AND e.election_type='special'
GROUP BY e.id HAVING COUNT(DISTINCT r.jurisdiction) > 1;
"
```
Expected: 0 rows.

- [ ] **Step 8: Commit**

```bash
git add backend/integrations/va_elect/tasks.py backend/integrations/va_elect/tests/test_tasks.py
git commit -m "fix(va_elect): populate contest_group from enr_slug for special elections

Fixes 4 collided Election rows (issue #187), including the 3-district
'2025 January 7 Specials' merge."
```

---

### Task 7: Fix `nc_sbe` (6 collided rows — structural: defer special-Election creation to Stage 2)

**Files:**
- Modify: `backend/integrations/nc_sbe/tasks.py`
- Test: `backend/integrations/nc_sbe/tests/test_tasks.py`

**Interfaces:**
- Consumes: `repair_collided_elections` command from Task 2.

**Background — why NC is different from the other 5:** `sync_nc_elections` (Stage 1) discovers only S3 folder *dates* (`client.list_election_date_strs()`), with no per-contest id available yet — contest names aren't known until `sync_nc_candidates` (Stage 2) parses that year's `Candidate_Listing_{YEAR}.csv`. So there's no `contest_group` value to attach at Stage 1 time for NC the way GA/SC/TX/VA/MA can. Also, NC's `jurisdiction` field is **not** a usable group key — `map_race_identity()` (`nc_sbe/mappers.py:148`) hardcodes `"jurisdiction": "North Carolina"` for every race, so `--group-by jurisdiction` would not split anything for NC. The real per-contest signal is `office_title` (NC's `contest_name`, e.g. `"NC HOUSE OF REPRESENTATIVES DISTRICT 023"` vs `"US HOUSE OF REPRESENTATIVES DISTRICT 06"`), which is why Task 7's repair run below uses `--group-by office_title` where every other task uses `--group-by jurisdiction`.

The fix: for `election_type="special"` dates only, stop eagerly creating one `Election` per date in Stage 1. Instead, let Stage 2 create the correctly-scoped `Election` per `contest_name` group, using `contest_group=normalize(contest_name)`, and copy the S3 `results_url`/`nc_date_str` metadata onto each of those split `Election` rows (the ZIP itself still covers the whole date, so every split contest's results still live at the same URL). General/primary dates are untouched — they keep today's one-Election-per-date behavior, since there's no evidence those need splitting.

- [ ] **Step 1: Write the failing test for Stage 1 skipping special dates**

In `integrations/nc_sbe/tests/test_tasks.py`, add after `test_sync_nc_elections_stores_results_url_in_metadata` (around line 60):

```python
@pytest.mark.django_db
def test_sync_nc_elections_does_not_create_election_for_special_date():
    """Regression test for issue #187: special-election dates must not get
    an eager one-Election-per-date row from Stage 1 — Stage 2 creates the
    correctly-scoped Election(s) once contest names are known."""
    from elections.models import Election
    from integrations.nc_sbe.tasks import sync_nc_elections

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_election_date_strs.return_value = ["2014_07_15"]  # not Nov/Mar/May
        sync_nc_elections.apply()

    assert not Election.objects.filter(state="NC", election_date=datetime.date(2014, 7, 15)).exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest integrations/nc_sbe/tests/test_tasks.py -q --no-migrations -k does_not_create_election_for_special`
Expected: FAIL — today's code creates an `Election` for every discovered date regardless of type.

- [ ] **Step 3: Skip eager Election creation for special dates in Stage 1**

In `sync_nc_elections` (`integrations/nc_sbe/tasks.py`), inside the `for date_str in date_strs:` loop, after `etype = election_type_from_date(d)` (around line 96):

```python
            etype = election_type_from_date(d)
```

add:

```python
            etype = election_type_from_date(d)
            if etype == "special":
                # Contest names aren't known yet at this stage (S3 only gives
                # dates) — Stage 2 (sync_nc_candidates) creates the correctly
                # per-contest-scoped Election(s) once it parses the candidate
                # CSV. See issue #187.
                skipped += 1
                continue
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && pytest integrations/nc_sbe/tests/test_tasks.py -q --no-migrations -k does_not_create_election_for_special`
Expected: PASS

- [ ] **Step 5: Run the full nc_sbe Stage 1 test suite to check for regressions**

Run: `cd backend && pytest integrations/nc_sbe/tests/test_tasks.py -q --no-migrations -k sync_nc_elections`
Expected: PASS — `test_sync_nc_elections_creates_election_records` (which asserts both a `general` and a `primary` Election get created from `_DATE_STRS = ["2024_11_05", "2026_03_03"]`) is unaffected since neither of those dates is `special`.

- [ ] **Step 6: Write the failing test for Stage 2 creating per-contest Elections on special dates**

In `integrations/nc_sbe/tests/test_tasks.py`, add after the existing `sync_nc_candidates` tests (after `test_sync_nc_candidates_skips_rows_with_no_matching_election`, around line 213):

```python
@pytest.mark.django_db
def test_sync_nc_candidates_creates_separate_elections_for_special_contests():
    """Regression test for issue #187: two unrelated NC special contests on
    the same date must land on two different Election rows, each with
    contest_group set from the (normalized) contest_name."""
    from elections.models import Election, Race
    from integrations.nc_sbe.tasks import sync_nc_candidates

    csv_bytes = _csv_bytes(
        _candidate_row("07/15/2014", "BERTIE", "NC HOUSE OF REPRESENTATIVES DISTRICT 023", "A Person", "DEM", "DEM"),
        _candidate_row("07/15/2014", "MECKLENBURG", "US HOUSE OF REPRESENTATIVES DISTRICT 06", "B Person", "REP", "REP"),
    )

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_candidate_filing_csv_key.return_value = "Elections/2014/Candidate Filing/Candidate_Listing_2014.csv"
        MockClient.return_value.fetch_candidate_filing_csv.return_value = csv_bytes
        sync_nc_candidates.apply()

    house023 = Race.objects.get(office_title="NC HOUSE OF REPRESENTATIVES DISTRICT 023")
    ushouse06 = Race.objects.get(office_title="US HOUSE OF REPRESENTATIVES DISTRICT 06")
    assert house023.election_id != ushouse06.election_id
    for election in (house023.election, ushouse06.election):
        assert election.state == "NC"
        assert election.election_type == "special"
        assert election.election_date == datetime.date(2014, 7, 15)
```

- [ ] **Step 7: Run the test to verify it fails**

Run: `cd backend && pytest integrations/nc_sbe/tests/test_tasks.py -q --no-migrations -k creates_separate_elections`
Expected: FAIL — no `Election` exists at all for this date, since Step 3 made Stage 1 skip it, and Stage 2 still only does `elections_by_date.get(d)` (returns `None`, contest gets skipped via `skipped_no_election`).

- [ ] **Step 8: Make Stage 2 create special-election Elections per contest_name**

In `sync_nc_candidates` (`integrations/nc_sbe/tasks.py`), the current lookup at lines 214-218:

```python
                d = parse_candidate_filing_date(election_dt)
                election = elections_by_date.get(d) if d else None
                if election is None:
                    skipped_no_election += 1
                    continue
```

becomes:

```python
                d = parse_candidate_filing_date(election_dt)
                if d is None:
                    skipped_no_election += 1
                    continue

                if election_type_from_date(d) == "special":
                    election, _ = ingest.ingest_election(
                        source=_SOURCE,
                        source_id=f"nc_sbe_{d.isoformat()}_{contest_name.strip().lower()}",
                        identity={
                            "state": "NC",
                            "election_type": "special",
                            "election_date": d,
                            "jurisdiction_level": Election.JurisdictionLevel.STATE,
                            "contest_group": contest_name.strip().lower(),
                        },
                        fields={
                            "name": f"{contest_name.strip().title()} Special Election ({d.strftime('%B %-d, %Y')})",
                            "status": (
                                Election.Status.RESULTS_PENDING
                                if d <= timezone.localdate() else Election.Status.UPCOMING
                            ),
                            "source_metadata": {
                                "nc_date_str": d.strftime("%Y_%m_%d"),
                                "results_url": _results_zip_url(d.strftime("%Y_%m_%d")),
                            },
                        },
                    )
                else:
                    election = elections_by_date.get(d)
                    if election is None:
                        skipped_no_election += 1
                        continue
```

`ingest` is already imported at the top of `sync_nc_candidates` (`from aggregation import ingest`, line 183). Add `from .client import _results_zip_url` if not already imported into `tasks.py`'s namespace — check first: `grep -n "_results_zip_url" integrations/nc_sbe/tasks.py` (it's already imported for `sync_nc_elections`, per the top-of-file import list at line 37, so no new import needed).

- [ ] **Step 9: Run the test to verify it passes**

Run: `cd backend && pytest integrations/nc_sbe/tests/test_tasks.py -q --no-migrations -k creates_separate_elections`
Expected: PASS

- [ ] **Step 10: Run the full nc_sbe test suite for regressions**

Run: `cd backend && pytest integrations/nc_sbe/ -q --no-migrations`
Expected: PASS — pay particular attention to `test_sync_nc_candidates_creates_race_and_dedupes_candidate_across_counties` and `test_sync_nc_candidates_skips_rows_with_no_matching_election`, both of which use `election_type="primary"` dates and must be completely unaffected by the new `special` branch.

- [ ] **Step 11: Dry-run then apply the repair command for NC — note the different `--group-by`**

```bash
docker exec civicmirror-api python manage.py repair_collided_elections --state NC --group-by office_title
```

Confirm the printed groups for election 1961 (2014-07-15) separate by contest name (e.g. `"nc house of representatives district 023"` as its own group, `"sheriff (dem)"` as another, etc.) — NOT by jurisdiction, which would print one giant group since every NC race shares `jurisdiction="North Carolina"`. Then:

```bash
docker exec civicmirror-api python manage.py repair_collided_elections --state NC --group-by office_title --yes
```

- [ ] **Step 12: Verify against production DB**

```bash
docker exec civicmirror-postgres psql -U civicmirror -d civicmirror_api -c "
SELECT e.id, COUNT(DISTINCT r.office_title) AS n
FROM elections_election e JOIN elections_race r ON r.election_id = e.id
WHERE e.state='NC' AND e.election_type='special'
GROUP BY e.id HAVING COUNT(DISTINCT r.office_title) > 1;
"
```
Expected: 0 rows. Also spot-check that the pre-existing out-of-scope county races (Sheriff, Coroner, etc. — legacy rows from before `is_in_scope_contest` existed) now sit on their own small `Election` rows rather than bundled with the in-scope federal/state races, even though nothing in this task re-scopes or removes them.

- [ ] **Step 13: Commit**

```bash
git add backend/integrations/nc_sbe/tasks.py backend/integrations/nc_sbe/tests/test_tasks.py
git commit -m "fix(nc_sbe): create per-contest Elections for special dates in Stage 2

Fixes 6 collided Election rows (issue #187). NC's S3 discovery has no
per-contest id at Stage 1 (only dates), and jurisdiction is hardcoded
to 'North Carolina' so it can't group-key repairs either — special
elections now defer Election creation to Stage 2, keyed by
contest_group=normalized contest_name. General/primary dates are
unchanged."
```

---

### Task 8: Fix `repair_collided_elections` grouping-key convergence for MA/SC/TX; exclude GA/VA from repair

> **Partially superseded by Task 10.** The convergence work below stands. Two conclusions do not: (a) the GA/VA *hard exclusion* was correct about not splitting them but left them unable to converge at all (blocker C1) — Task 10 replaces it with an in-place rekey path; (b) NC's repair invocation is withdrawn entirely (blocker C3) — Task 7 is reverted. Read Task 10 before acting on anything in this task or Task 9.

**Discovered during Task 7's review, not in the original plan.** The repair command (Task 2) groups races by a generic Race model field (`jurisdiction` or `office_title`) to decide how to split a collided `Election`. But each adapter's live `contest_group` (Tasks 2-7) is computed from a different, adapter-specific value. Verified directly against the merged code and production data:

| State | Repair grouped by (as merged) | Live `contest_group` | Converge? |
|---|---|---|---|
| MA | `jurisdiction` | `f"{office}:{district}"` | ❌ |
| SC | `jurisdiction` | `vrems_election_id` (verified reliable per-race via `Race.source_metadata`) | ❌ |
| TX | `jurisdiction` | `tx_election_id` (verified reliable per-race via `Race.source_metadata`) | ❌ |
| NC | `office_title` | `contest_name` (= office_title) | ✅ already converges, no change needed |
| GA | `jurisdiction` | `public_id` | N/A — **no genuine collisions exist**, see below |
| VA | `jurisdiction` | `enr_slug` | N/A — **no genuine collisions exist**, see below |

Left as-is, running repair against MA/SC/TX would produce a `canonical_key` that each state's *next scheduled sync* won't recognize — `ingest_election` would fail to find the repaired row and mint a duplicate Election, silently reintroducing the exact problem being fixed.

**GA and VA additionally need to be excluded from repair entirely** — verified against production that every one of GA's 27 and VA's 4 "collided" rows shares exactly **one** distinct `public_id`/`enr_slug` (confirmed via `r.source_metadata->>'ga_public_election_id'` / `'enr_slug'` grouped counts). These are legitimate single-ballot, multi-district special-election days that GA/VA bundle by design (e.g. GA's "Special Election State House 23 and 121" literally names two districts as one combined event; GA's 2022 general/special row has 274 races under one `public_id`). The original collision-detection heuristic (multi-jurisdiction + `election_type='special'`) false-positived on all 31 of these rows. Running `repair --group-by jurisdiction` against them would shatter legitimate ballots into fake separate Elections — actively destructive, not a fix. GA's and VA's Tasks 3/6 code changes stay merged as harmless no-ops (each state's `public_id`/`enr_slug` is already ~1:1 with its true collision boundary, so `contest_group` never actually disambiguates anything for these two states, but it also never hurts anything).

NC's true collision count is also corrected here: **19 rows**, not the 6 originally estimated (the original jurisdiction-based audit undercounted NC since its `jurisdiction` field is a hardcoded constant; Task 7's fix and repair invocation are unaffected — this is a scope correction only, no code change).

**Revised real scope: MA (1) + SC (4) + TX (2) + NC (19) = 26 genuine collided rows to repair. GA and VA: 0.**

**Files:**
- Modify: `backend/elections/management/commands/repair_collided_elections.py`
- Test: `backend/elections/tests/test_repair_collided_elections.py`

- [ ] **Step 1: Add `--group-by-metadata <key>` support**

Add a new mutually-exclusive CLI option that groups races by `race.source_metadata.get(key, "")` instead of a model field, for SC (`vrems_election_id`) and TX (`tx_election_id`).

- [ ] **Step 2: Add `--group-by-compound field1,field2` support**

Add a new mutually-exclusive CLI option that groups races by joining multiple model fields with `:` (matching `ma_sos`'s own join character), for MA (`office_title,jurisdiction`).

- [ ] **Step 3: Add a convergence test per state (MA, SC, TX), mirroring NC's verified pattern from Task 7**

For each state, assert that the repair command's computed grouping key, run through `election_canonical_key(..., contest_group=<key>)`, produces the **exact same string** as that state's adapter would compute for `contest_group` on the same synthetic race/discovery data. This is the property the whole fix rests on — it must be proven equal, not assumed.

- [ ] **Step 4: Run the full `elections/` test suite**

Run: `cd backend && pytest elections/ -q --no-migrations`
Expected: PASS, including all pre-existing repair-command tests (MA's Task 2 tests must still pass under the new `--group-by-compound` invocation).

- [ ] **Step 5: Commit**

---

### Task 9: Full-system verification and production repair — MA, SC, TX, NC only

> **Superseded by Task 10 Step 5.** The state list below is wrong in both directions: GA and VA must now be run (in-place rekey, blocker C1), and NC must not be run at all (blocker C3, Task 7 reverted). Use Task 10's runbook. The verification queries in Steps 2-4 remain useful, with the state list adjusted.

**Files:** none (verification and production commands only)

- [ ] **Step 1: Dry-run then apply the repair command for MA, SC, TX, NC — NOT GA or VA** *(superseded — see Task 10 Step 5)*

```bash
docker exec civicmirror-api python manage.py repair_collided_elections --state MA --group-by-compound office_title,jurisdiction
docker exec civicmirror-api python manage.py repair_collided_elections --state MA --group-by-compound office_title,jurisdiction --yes

docker exec civicmirror-api python manage.py repair_collided_elections --state SC --group-by-metadata vrems_election_id
docker exec civicmirror-api python manage.py repair_collided_elections --state SC --group-by-metadata vrems_election_id --yes

docker exec civicmirror-api python manage.py repair_collided_elections --state TX --group-by-metadata tx_election_id
docker exec civicmirror-api python manage.py repair_collided_elections --state TX --group-by-metadata tx_election_id --yes

docker exec civicmirror-api python manage.py repair_collided_elections --state NC --group-by office_title
docker exec civicmirror-api python manage.py repair_collided_elections --state NC --group-by office_title --yes
```

Review each dry-run's printed output before applying `--yes`. Do not run this command for GA or VA — see Task 8.

- [ ] **Step 2: Confirm zero remaining genuine collisions for MA/SC/TX/NC**

```bash
docker exec civicmirror-postgres psql -U civicmirror -d civicmirror_api -c "
SELECT e.state, e.id, e.election_date, e.name
FROM elections_election e
JOIN elections_race r ON r.election_id = e.id
WHERE e.election_type = 'special' AND e.state IN ('MA','SC','TX','NC')
GROUP BY e.id, e.state, e.election_date, e.name
HAVING COUNT(DISTINCT r.jurisdiction) > 1 AND COUNT(DISTINCT r.office_title) > 1;
"
```
Expected: 0 rows. (GA and VA are intentionally excluded from this check — their remaining "collisions" are the legitimate multi-district bundles documented in Task 8, expected to persist, not a bug.)

- [ ] **Step 3: Confirm general/primary elections are untouched, per state**

```bash
docker exec civicmirror-postgres psql -U civicmirror -d civicmirror_api -c "
SELECT e.state, e.election_type, e.election_date, COUNT(r.id) AS race_count
FROM elections_election e JOIN elections_race r ON r.election_id = e.id
WHERE e.state IN ('MA','GA','NC','SC','TX','VA') AND e.election_type IN ('general','primary')
GROUP BY e.state, e.election_type, e.election_date
HAVING COUNT(r.id) > 1
ORDER BY e.state, e.election_date DESC
LIMIT 12;
"
```
Expected: multiple rows returned (one general/primary day per state with several races bundled, exactly as before this plan).

- [ ] **Step 4: Run the full backend test suite once**

Run: `cd backend && pytest -q --no-migrations`
Expected: PASS, no regressions introduced by any of Tasks 1-8.

- [ ] **Step 5: Close out issue #187 with the corrected scope**

Post a summary comment on [#187](https://github.com/CivicMirror/CivicMirror-API/issues/187) referencing the commits from Tasks 1-8, the GA/VA false-positive finding, the NC scope correction (19 rows not 6), and the verification queries above, then close the issue.

---

### Task 10: Resolve the whole-branch review's 3 Critical blockers (C1, C2, C3)

**Added after the whole-branch review**, which found three issues visible only across the branch as a whole. Tasks 1-8 all passed individually; these are integration-level. Discussion and rationale: [issue #187 comment](https://github.com/CivicMirror/CivicMirror-API/issues/187#issuecomment-5275346387).

| Blocker | Resolution |
|---|---|
| **C1** — deploying as-is duplicates all 134 stored special elections, and GA/VA's 77 rows have no path to converge at all | `repair_collided_elections` becomes a *rekeyer*: one grouping value across an Election's races → **rekey in place**; more than one → split (as before). GA/VA's hard `CommandError` exclusion is deleted — the single-group branch is what protects them, structurally. |
| **C2** — repaired elections still mint duplicate *races*, because `Race.canonical_key` embeds the election key | Race keys are **prefix-swapped**, not recomputed. |
| **C3** — NC's `election_type_from_date()` is a catch-all, not a special-election signal | **Task 7 reverted.** NC leaves this branch entirely; tracked in #188. |

**Why prefix-swap and not the `merge_duplicate_races` recompute the review pointed at:** that command's `_new_key()` omits `contest_variant`, and `Race` has no column persisting one. Recomputing would collapse party-split races in exactly the affected states (`ma_sos` passes a variant for MA specials; NC and MD do too). Swapping only the leading election-key segment carries office/OCD/race_type/variant over byte-for-byte from whatever the adapter last computed — which is exactly what the adapter computes again next sync. (The `merge_duplicate_races` variant gap is a real latent bug, tracked in #189; it is not this branch's to fix.)

**Why NC cannot be fixed here:** `election_type` is *inside* the base canonical key. Classifying NC's municipal/runoff dates correctly (`Election.ElectionType.MUNICIPAL` / `PRIMARY_RUNOFF`, both existing and unused by `nc_sbe`) changes the base key of every stored NC non-Nov/Mar/May row, so NC needs its own rekey migration regardless of design. `nc_sbe` also has no per-date signal at Stage 1 — `client.list_election_date_strs()` returns bare S3 date strings with no election title — so #188 starts with a data audit of whether contest names in the filing CSV / results TSV can positively identify genuine specials.

**Files:**
- Modify: `backend/elections/management/commands/repair_collided_elections.py`
- Modify: `backend/elections/tests/test_repair_collided_elections.py`
- Modify: `backend/integrations/ma_sos/tasks.py`, `backend/integrations/ma_sos/tests/test_tasks.py`
- Revert: `backend/integrations/nc_sbe/tasks.py`, `backend/integrations/nc_sbe/tests/test_tasks.py` (commit `e99d58d`)

- [x] **Step 1: Revert Task 7 (NC)** — `git revert --no-commit e99d58d`. NC returns to one Election per date at Stage 1, exactly as in production today.

- [x] **Step 2: Rekey-or-split, with the convergence invariant enforced**

Per special Election in the target state:
- no races → report, skip (nothing can derive a group; the row is inert)
- any race with an empty grouping value → refuse *that election*, collect, continue (each election is its own transaction, so one bad row no longer aborts a batch mid-run — this also closes Important #4)
- one distinct group → rekey in place
- more than one → split, as before

At the end the command re-scans the state and fails if any special Election **with races** still lacks a `|` suffix, then exits non-zero listing every unresolved item. Post-condition: *every stored special Election's key equals what the live adapter will compute.*

- [x] **Step 3: Prefix-swap child race keys in both paths**

```python
race.canonical_key = new_election_key + stored[len(old_election_key):]
```
Races whose stored key doesn't start with the old election key are left untouched and reported (never guessed at); a race whose target key is already held by another row is left untouched and flagged `MatchConfidence.FLAGGED`, mirroring `merge_duplicate_races`' conflict handling.

- [x] **Step 4: Tests**

Added: GA in-place rekey (no split); GA and VA convergence proofs running the real `sync_ga_elections`/`sync_va_elections` against a rekeyed row and asserting **no duplicate row appears**; in-place idempotency; race-key prefix swap preserving two distinct `contest_variant` suffixes across a split; unrecognized-prefix race left alone + non-zero exit; race-less election reported but non-fatal. Existing fixtures were rewritten to use realistic `<election_key>|…` race keys so the swap is genuinely exercised. MA degenerate-group guard tests (both halves empty → omit `contest_group`; one half empty → still emit).

- [x] **Step 5: Production runbook (replaces Task 9 Step 1)**

```bash
# 1. Pause the sync schedulers for MA/SC/TX/GA/VA
# 2. Deploy this branch
# 3. Dry-run, inspect, then apply — per state:
docker exec civicmirror-api python manage.py repair_collided_elections --state MA --group-by-compound office_title,jurisdiction
docker exec civicmirror-api python manage.py repair_collided_elections --state SC --group-by-metadata vrems_election_id
docker exec civicmirror-api python manage.py repair_collided_elections --state TX --group-by-metadata tx_election_id
docker exec civicmirror-api python manage.py repair_collided_elections --state GA --group-by-metadata ga_public_election_id
docker exec civicmirror-api python manage.py repair_collided_elections --state VA --group-by-metadata enr_slug
# …then re-run each with --yes
# 4. Resume schedulers
```

NC is **not** in this list. Before running GA/VA, confirm their races actually carry the grouping key (races ingested before the mapper wrote it would be refused, loudly, rather than mis-grouped):

```sql
SELECT e.state, COUNT(*) FILTER (WHERE COALESCE(r.source_metadata->>'ga_public_election_id', r.source_metadata->>'enr_slug', '') = '') AS missing_key,
       COUNT(*) AS total_races
FROM elections_election e JOIN elections_race r ON r.election_id = e.id
WHERE e.election_type = 'special' AND e.state IN ('GA','VA')
GROUP BY e.state;
```
Expected: `missing_key = 0`. Any non-zero count must be resolved before the GA/VA runs.

---

## Self-Review Notes

- **Spec coverage:** Task 1 covers the foundational `identity.py`/`ingest.py` change from issue #187's "Suggested fix" §1-2. Tasks 2-7 cover each of the 6 states from the issue's tracking checklist. Task 8 (added post-Task-7-review) fixes a repair/sync canonical-key convergence gap and corrects the repair scope to exclude GA/VA (no genuine collisions) and correct NC's count (19 rows, not 6). Task 9 covers final cross-state verification and the actual production repair runs, scoped to MA/SC/TX/NC only.
- **Placeholder scan:** every code step above has concrete code; the two genuinely-open verification points (Task 4 Step 1's exact `Election.objects.get(...)` filter, Task 6 Step 1's `map_election` import path) are flagged as "confirm against the actual mapper output/import before finalizing" rather than left as unresolved TODOs — both are one `grep` away from a definite answer and don't block writing the rest of the test.
- **Type consistency:** `contest_group: str = ""` in `election_canonical_key` (Task 1) is used identically as `identity["contest_group"]` in every adapter task (2-7). The repair command's grouping key (Task 2's original `--group-by`, extended by Task 8's `--group-by-metadata`/`--group-by-compound`) is verified — not assumed — to produce byte-identical `contest_group` strings to each state's live adapter, via Task 8's per-state convergence tests.
- **Revision note:** this plan was executed with subagent-driven-development; Task 8 was inserted mid-execution after Task 7's task reviewer surfaced the convergence gap, and further investigation (prompted by that finding) surfaced the GA/VA false-positive scope correction. Task 10 was added after the whole-branch review found three integration-level Critical blockers that no single task's review could see; it supersedes Task 8's GA/VA exclusion and Task 9's state list, and reverts Task 7 (NC) out of the branch. All are documented here and in the SDD ledger for audit purposes.
- **Final scope:** MA (1 genuine collision, split) + SC (4, split) + TX (2, split) + GA (27, rekey in place) + VA (4, rekey in place). NC deferred to its own issue. Every stored special election in those five states is rekeyed whether or not it was collided — that is the C1 convergence requirement, not scope creep.
