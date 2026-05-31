# CO SOS Aggregation Migration Plan

> ✅ **ARCHIVED — COMPLETED 2026-05-31** — Merged as PR #6. CO SOS adapter routes through aggregation ingest. Kept for historical reference.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the `co_sos` adapter through the aggregation ingest service, replacing `Election.objects.update_or_create` / `Race.objects.update_or_create` / `Candidate.objects.update_or_create` calls.

**Architecture:** Same per-state pattern as VA Elect and SC VREMS. Five fixes required before migration: (1) `map_election` omits `election_type` (ingest requires it); (2) `map_race` + `source_metadata` crash on null `source_id`; (3) `_resolve_election_for_type` looks up `Election.source_id` which is NULL after ingest — replace with a dict keyed from ingest return values; (4) withdrawn-candidate sweep must collect `pk` from `ingest_candidate` returns (not `update_or_create`); (5) party-primary races merge (R/D Governor → 1 Race) — accepted, same design decision as SC VREMS. CO results adapter uses `ClarityAdapter` — no `Race.source` filter fix needed.

**Tech Stack:** Django ORM, Celery shared tasks, `aggregation.ingest`, pytest + `--no-migrations`

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Modify | `backend/aggregation/migrations/_seed_data.py` | Add CO precedence rows |
| Create | `backend/aggregation/migrations/0006_seed_co_sos_precedence.py` | Apply CO rows at migrate time |
| Create | `backend/aggregation/tests/test_seed_co_sos_precedence.py` | Verify CO rows after seeding |
| Modify | `backend/integrations/co_sos/mappers.py` | Add `election_type` to `map_election`; fix null `source_id` in `map_race` + `source_metadata` |
| Create/Modify | `backend/integrations/co_sos/tests/test_mappers.py` | Tests for mapper fixes |
| Modify | `backend/integrations/co_sos/tasks.py` | Stage 1: `update_or_create` → `ingest_election`; Stage 2: `update_or_create` → `ingest_race`+`ingest_candidate`; keep `Candidate` for withdrawn sweep |
| Modify | `backend/integrations/co_sos/tests/test_tasks.py` | Update Stage 1 source_id assertion; update Stage 2 race count; add 2 DB integration tests |

---

## Task 1: Seed CO Precedence Rows

**Files:**
- Modify: `backend/aggregation/migrations/_seed_data.py`
- Create: `backend/aggregation/migrations/0006_seed_co_sos_precedence.py`
- Create: `backend/aggregation/tests/test_seed_co_sos_precedence.py`

- [ ] **Step 1: Add CO rows to `_seed_data.py`**

Append 8 CO rows after the SC block:

```python
    ("CO", "results",  "co_sos",   0),
    ("CO", "results",  "civic_api", 1),
    ("CO", "date",     "co_sos",   0),
    ("CO", "date",     "civic_api", 1),
    ("CO", "contacts", "civic_api", 0),
    ("CO", "contacts", "co_sos",   1),
    ("CO", "identity", "civic_api", 0),
    ("CO", "identity", "co_sos",   1),
```

- [ ] **Step 2: Create migration `0006_seed_co_sos_precedence.py`**

```python
from django.db import migrations

from ._seed_data import seed


def seed_co_sos_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    seed(SourcePrecedence)


def remove_co_sos_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="CO").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0005_seed_sc_vrems_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_co_sos_precedence, remove_co_sos_precedence),
    ]
```

- [ ] **Step 3: Create test file**

Create `backend/aggregation/tests/test_seed_co_sos_precedence.py`:

```python
import pytest


@pytest.mark.django_db
def test_co_sos_precedence_rows_seeded():
    from aggregation.migrations._seed_data import seed
    from aggregation.models import SourcePrecedence

    seed(SourcePrecedence)
    seed(SourcePrecedence)  # idempotency

    co_rows = list(
        SourcePrecedence.objects.filter(state="CO").values_list(
            "field_group", "source", "rank"
        )
    )
    assert len(co_rows) == 8, f"Expected 8 CO rows, got {len(co_rows)}"

    expected = [
        ("results",  "co_sos",   0),
        ("results",  "civic_api", 1),
        ("date",     "co_sos",   0),
        ("date",     "civic_api", 1),
        ("contacts", "civic_api", 0),
        ("contacts", "co_sos",   1),
        ("identity", "civic_api", 0),
        ("identity", "co_sos",   1),
    ]
    for field_group, source, rank in expected:
        assert (field_group, source, rank) in co_rows, (
            f"Missing CO precedence row: {field_group}/{source}/rank={rank}"
        )
```

- [ ] **Step 4: Run test**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend && .venv/bin/python -m pytest aggregation/tests/test_seed_co_sos_precedence.py -v --no-migrations
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API && git add backend/aggregation/migrations/_seed_data.py \
        backend/aggregation/migrations/0006_seed_co_sos_precedence.py \
        backend/aggregation/tests/test_seed_co_sos_precedence.py
git commit -m "feat(aggregation): seed CO SOS precedence (co_sos for results/date, Civic for identity/contacts)"
```

---

## Task 2: Fix Mapper Bugs

**Files:**
- Modify: `backend/integrations/co_sos/mappers.py`
- Create/Modify: `backend/integrations/co_sos/tests/test_mappers.py`

**Bug 1:** `map_election(year, election_type)` return dict omits `election_type` — ingest requires it in the identity tuple.

**Bug 2:** `map_race()` calls `build_race_canonical_key(election_obj.source_id, ...)` — crashes with `TypeError` when `source_id=None` (post-ingest elections). Fix: `election_obj.source_id or election_obj.canonical_key or ""`.

**Bug 3:** `map_race()` puts `election_obj.source_id` in `source_metadata["co_sos_election_id"]` — same null issue.

- [ ] **Step 1: Write failing tests**

Check if `backend/integrations/co_sos/tests/test_mappers.py` exists. If not, create it. Add:

```python
from unittest.mock import MagicMock


def test_map_election_includes_election_type():
    """map_election must return election_type for ingest identity."""
    from integrations.co_sos.mappers import map_election

    result = map_election(2026, "primary")
    assert "election_type" in result, "map_election must include 'election_type'"
    assert result["election_type"] == "primary"


def test_map_election_general_type():
    """map_election for general election_type returns 'general'."""
    from integrations.co_sos.mappers import map_election

    result = map_election(2026, "general")
    assert result["election_type"] == "general"


def test_map_race_handles_null_source_id():
    """map_race must not crash when election_obj.source_id is None."""
    from integrations.co_sos.mappers import map_race

    mock_election = MagicMock()
    mock_election.source_id = None
    mock_election.canonical_key = "CO:primary:2026-06-28:state"
    mock_election.status = "upcoming"

    race_group = {
        "office": "Governor",
        "district": "Statewide",
        "party_group": "Democratic Party",
        "candidates": [],
    }
    result = map_race(mock_election, race_group)
    assert isinstance(result["canonical_key"], str)
    assert "None" not in result["canonical_key"]


def test_map_race_source_metadata_no_none_election_id():
    """map_race source_metadata must not store None for co_sos_election_id."""
    from integrations.co_sos.mappers import map_race

    mock_election = MagicMock()
    mock_election.source_id = None
    mock_election.canonical_key = "CO:primary:2026-06-28:state"
    mock_election.status = "upcoming"

    race_group = {
        "office": "Governor",
        "district": "Statewide",
        "party_group": "Democratic Party",
        "candidates": [],
    }
    result = map_race(mock_election, race_group)
    election_id = result["source_metadata"]["co_sos_election_id"]
    assert election_id is not None, "co_sos_election_id must not be None when source_id is None"
    assert isinstance(election_id, str)
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend && .venv/bin/python -m pytest integrations/co_sos/tests/test_mappers.py -v --no-migrations
```

Expected: All 4 FAIL

- [ ] **Step 3: Apply fixes to `mappers.py`**

**Fix 1** — Add `election_type` to `map_election()` return dict:

```python
def map_election(year: int, election_type: str) -> dict:
    """Return Election model field values for the given CO election."""
    election_date = co_election_date(year, election_type)
    type_label = election_type.title()

    return {
        "source_id": build_election_source_id(year, election_type),
        "name": f"{year} Colorado {type_label} Election",
        "election_date": election_date,
        "election_type": election_type,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "CO",
        "status": infer_election_status(election_date),
    }
```

**Fix 2+3** — Fix null `source_id` in `map_race()`:

```python
def map_race(election_obj: Election, race_group: dict) -> dict:
    """Map a race group to Race model field values."""
    office = race_group["office"]
    district = race_group["district"]
    party_group = race_group["party_group"]

    office_lower = normalize(office)
    is_federal = any(kw in office_lower for kw in _FEDERAL_KEYWORDS)

    certification_status = (
        Race.CertificationStatus.UPCOMING
        if election_obj.status in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_PENDING
    )

    election_ref = election_obj.source_id or election_obj.canonical_key or ""

    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office,
        "jurisdiction": infer_jurisdiction_for_race(office, district),
        "geography_scope": infer_geography_scope(office, district),
        "certification_status": certification_status,
        "source": Race.Source.CO_SOS,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "normalized_office_title": normalize(office),
        "canonical_key": build_race_canonical_key(
            election_ref, office, district, party_group
        ),
        "source_metadata": {
            "co_sos_election_id": election_ref,
            "district": district,
            "party_group": party_group,
            "is_federal": is_federal,
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend && .venv/bin/python -m pytest integrations/co_sos/tests/test_mappers.py -v --no-migrations
```

Expected: All 4 PASS

- [ ] **Step 5: Commit**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API && git add backend/integrations/co_sos/mappers.py backend/integrations/co_sos/tests/test_mappers.py
git commit -m "fix(co_sos): add election_type to map_election; handle null source_id in map_race"
```

---

## Task 3: Migrate `sync_co_elections` (Stage 1)

**Files:**
- Modify: `backend/integrations/co_sos/tasks.py` — Stage 1 only
- Modify: `backend/integrations/co_sos/tests/test_tasks.py` — update Stage 1 test

Replace `Election.objects.update_or_create(source_id=..., defaults=...)` with `ingest.ingest_election()`. Replace `_resolve_election_for_type()` in the fingerprint loop with a dict built from ingest returns.

- [ ] **Step 1: Update Stage 1 test (it will fail first)**

In `TestSyncCoElectionsTask.test_seeds_election_and_queues_candidates_on_changed_page`:

Change:
```python
assert Election.objects.filter(source_id="co_sos_2026_primary").exists()
```

To:
```python
from elections.models import ElectionSourceLink
assert ElectionSourceLink.objects.filter(
    source="co_sos", source_id="co_sos_2026_primary"
).exists()
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend && .venv/bin/python -m pytest "integrations/co_sos/tests/test_tasks.py::TestSyncCoElectionsTask::test_seeds_election_and_queues_candidates_on_changed_page" -v --no-migrations
```

Expected: FAIL

- [ ] **Step 3: Rewrite `sync_co_elections` in `tasks.py`**

Replace the entire `sync_co_elections` function:

```python
@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_co_elections(self):
    """
    Stage 1: Seed Colorado Election records via the aggregation ingest service
    and queue Stage 2 if the candidate list page has changed.
    """
    sync_log = SyncLog.objects.create(
        source="co_sos",
        task_name="sync_co_elections",
        status=SyncLog.Status.STARTED,
    )
    client = ColoradoSosClient()
    created_count = updated_count = queued_count = 0

    try:
        year = _current_even_year()

        from aggregation import ingest

        election_objs_by_type: dict[str, object] = {}

        for election_type in _ELECTION_TYPES:
            mapped = map_election(year, election_type)
            source_id = mapped.pop("source_id")
            identity = {
                "state":              mapped["state"],
                "election_type":      mapped["election_type"],
                "election_date":      mapped["election_date"],
                "jurisdiction_level": mapped["jurisdiction_level"],
            }
            fields = {k: v for k, v in mapped.items() if k not in identity}
            election_obj, was_created = ingest.ingest_election(
                source="co_sos",
                source_id=source_id,
                identity=identity,
                fields=fields,
            )
            if was_created:
                created_count += 1
            else:
                updated_count += 1
            election_objs_by_type[election_type] = election_obj

        logger.info(
            "co_sos.sync_elections.seeded year=%d created=%d updated=%d",
            year, created_count, updated_count,
        )

        for election_type in _ELECTION_TYPES:
            try:
                fingerprint = client.get_candidate_page_fingerprint(election_type)
            except Exception as exc:
                logger.warning(
                    "co_sos.sync_elections.fingerprint_error election_type=%s err=%s",
                    election_type, exc,
                )
                continue

            if fingerprint is None:
                logger.info(
                    "co_sos.sync_elections.page_unavailable election_type=%s", election_type
                )
                continue

            cache_key = _PAGE_CACHE_KEY.format(election_type=election_type)
            last_fingerprint = cache.get(cache_key)

            if fingerprint == last_fingerprint:
                logger.info(
                    "co_sos.sync_elections.page_unchanged election_type=%s", election_type
                )
                continue

            election_obj = election_objs_by_type.get(election_type)
            if election_obj is None:
                logger.warning(
                    "co_sos.sync_elections.no_election_for_type election_type=%s year=%d",
                    election_type, year,
                )
                continue

            logger.info(
                "co_sos.sync_elections.page_updated election_type=%s fingerprint=%s",
                election_type, fingerprint,
            )
            sync_co_candidates.delay(election_obj.pk, election_type, fingerprint, cache_key)
            queued_count += 1

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.notes = f"Queued {queued_count} candidate sync(s)"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created_count, "updated": updated_count, "queued": queued_count}

    except CoSosRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("co_sos.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

Note: Keep all current imports for now — Stage 2 still needs them.

- [ ] **Step 4: Run Stage 1 tests**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend && .venv/bin/python -m pytest integrations/co_sos/tests/test_tasks.py::TestSyncCoElectionsTask -v --no-migrations
```

Expected: Both PASS

- [ ] **Step 5: Commit**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API && git add backend/integrations/co_sos/tasks.py backend/integrations/co_sos/tests/test_tasks.py
git commit -m "feat(co_sos): route sync_co_elections through aggregation ingest service"
```

---

## Task 4: Migrate `sync_co_candidates` (Stage 2)

**Files:**
- Modify: `backend/integrations/co_sos/tasks.py` — Stage 2 function + imports
- Modify: `backend/integrations/co_sos/tests/test_tasks.py` — update Stage 2 tests + add 2 integration tests

Replace `Race.objects.update_or_create` + `Candidate.objects.update_or_create` with `ingest.ingest_race()` + `ingest.ingest_candidate()`. Collect PKs from ingest returns for the withdrawn sweep.

**Key design decisions:**
- `Candidate` must stay in `elections.models` import — needed for the withdrawn sweep
- `Race` can be removed from imports (no longer used directly)
- `seen_race_pks` guard prevents double-counting when R+D primary groups merge to same canonical Race
- `seen_candidate_pks` collected from `ingest_candidate` return `cand_obj.pk`
- Withdrawn sweep unchanged: `Candidate.objects.filter(...).exclude(pk__in=seen_candidate_pks).update(WITHDRAWN)`

- [ ] **Step 1: Update Stage 2 test for R/D merge**

The test `test_creates_races_and_candidates` currently asserts `Race.count() == 2` for a primary with D Governor + R Governor. After ingest (party-agnostic canonical key), both resolve to one Race. Update:

```python
def test_creates_races_and_candidates(self):
    from aggregation.models import SourcePrecedence
    from elections.models import Candidate, Race
    from integrations.co_sos.tasks import sync_co_candidates

    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)
    election = self._make_election()

    with (
        patch("integrations.co_sos.tasks.ColoradoSosClient") as MockClient,
        patch("integrations.co_sos.tasks.cache") as mock_cache,
    ):
        MockClient.return_value.fetch_candidate_html.return_value = self._candidate_html()
        mock_cache.set = MagicMock()

        result = sync_co_candidates.apply(
            args=[election.pk, "primary", "fp123", "co_sos:candidate_page_fingerprint:primary"]
        ).get()

    # Primary with D Governor + R Governor → 1 canonical Race (party-agnostic key), 2 candidates
    assert result["created"] >= 2  # at least race + 2 candidates
    assert Race.objects.filter(election=election).count() == 1
    assert Candidate.objects.filter(race__election=election).count() == 2
    mock_cache.set.assert_called_once()
```

- [ ] **Step 2: Run to verify test fails (old code creates 2 races)**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend && .venv/bin/python -m pytest "integrations/co_sos/tests/test_tasks.py::TestSyncCoCandidatesTask::test_creates_races_and_candidates" -v --no-migrations
```

Expected: FAIL (still using old update_or_create with party-scoped key creating 2 races)

- [ ] **Step 3: Rewrite `sync_co_candidates` + clean up imports**

**Updated imports** (keep `Candidate` for withdrawn sweep, remove `Race`):

```python
import logging

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from elections.models import Candidate, Election
from ops.models import SyncLog

from .client import ColoradoSosClient
from .exceptions import CoSosRetryableError
from .mappers import (
    build_race_canonical_key,
    build_race_groups,
    map_candidate,
    map_election,
    map_race,
)
from .parsers import parse_candidate_table
```

**New `sync_co_candidates` function:**

```python
@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_co_candidates(
    self,
    election_pk: int,
    election_type: str,
    fingerprint: str,
    cache_key: str,
):
    """
    Stage 2: Parse the CO SOS candidate list HTML and upsert Race + Candidate records
    via the aggregation ingest service.

    After a successful sync, stores the page fingerprint in Redis so future
    Stage 1 runs skip unchanged pages.
    Also marks candidates absent from this run as WITHDRAWN.
    """
    try:
        election_obj = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("co_sos.sync_candidates.missing_election pk=%d", election_pk)
        return

    sync_log = SyncLog.objects.create(
        election=election_obj,
        source="co_sos",
        task_name="sync_co_candidates",
        status=SyncLog.Status.STARTED,
    )
    client = ColoradoSosClient()
    created_count = updated_count = withdrawn_count = 0

    try:
        html = client.fetch_candidate_html(election_type)
        candidates_raw = parse_candidate_table(html)

        if not candidates_raw:
            logger.info(
                "co_sos.sync_candidates.empty election=%s type=%s",
                election_obj.source_id or election_obj.pk, election_type,
            )
            sync_log.notes = "No candidates parsed from HTML"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created": 0, "updated": 0, "withdrawn": 0}

        is_primary = election_type == "primary"
        race_groups = build_race_groups(candidates_raw, is_primary=is_primary)

        from aggregation import ingest

        seen_candidate_pks: set[int] = set()
        seen_race_pks: set[int] = set()

        for group in race_groups:
            race_defaults = map_race(election_obj, group)
            race_defaults.pop("canonical_key", None)
            race_defaults.pop("source", None)

            race_identity = {
                "office_title":    race_defaults.pop("office_title"),
                "ocd_division_id": race_defaults.pop("ocd_division_id", "") or "",
                "race_type":       race_defaults.pop("race_type"),
            }
            if not race_identity["office_title"]:
                continue

            race_obj, race_was_new = ingest.ingest_race(
                election=election_obj,
                source="co_sos",
                identity=race_identity,
                fields=race_defaults,
            )
            if race_obj.pk not in seen_race_pks:
                seen_race_pks.add(race_obj.pk)
                if race_was_new:
                    created_count += 1
                else:
                    updated_count += 1

            for raw_candidate in group["candidates"]:
                name = (raw_candidate.get("candidate_name") or "").strip()
                if not name:
                    continue
                cand_fields = map_candidate(raw_candidate)
                party = cand_fields.pop("party", "")
                cand_obj, cand_was_new = ingest.ingest_candidate(
                    race=race_obj,
                    source="co_sos",
                    name=name,
                    party=party,
                    fields=cand_fields,
                )
                seen_candidate_pks.add(cand_obj.pk)
                if cand_was_new:
                    created_count += 1
                else:
                    updated_count += 1

        # Mark any previously-active candidates no longer in the page as WITHDRAWN
        withdrawn_qs = (
            Candidate.objects
            .filter(race__election=election_obj)
            .exclude(pk__in=seen_candidate_pks)
            .filter(candidate_status=Candidate.CandidateStatus.RUNNING)
        )
        withdrawn_count = withdrawn_qs.update(
            candidate_status=Candidate.CandidateStatus.WITHDRAWN
        )
        if withdrawn_count:
            logger.info(
                "co_sos.sync_candidates.withdrawn election=%s count=%d",
                election_obj.source_id or election_obj.pk, withdrawn_count,
            )

        election_obj.last_synced_at = timezone.now()
        election_obj.save(update_fields=["last_synced_at"])

        cache.set(cache_key, fingerprint, _PAGE_CACHE_TTL)

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.notes = f"election_type={election_type} | withdrawn={withdrawn_count}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {"created": created_count, "updated": updated_count, "withdrawn": withdrawn_count}

    except CoSosRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception(
            "co_sos.sync_candidates.failed election=%s",
            getattr(election_obj, "source_id", None) or getattr(election_obj, "pk", "?"),
        )
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise
```

- [ ] **Step 4: Run all task tests**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend && .venv/bin/python -m pytest integrations/co_sos/tests/test_tasks.py -v --no-migrations -p no:cacheprovider 2>&1 | tail -20
```

Expected: All PASS

- [ ] **Step 5: Add two `@pytest.mark.django_db` integration tests**

Append to `backend/integrations/co_sos/tests/test_tasks.py`:

```python
# ------------------------------------------------------------------
# Integration tests — ingest service routing (real DB)
# ------------------------------------------------------------------

from datetime import date as _date
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_sync_co_elections_routes_through_ingest_service():
    """Each CO election lands as a canonical Election with contributing_sources=['co_sos']."""
    from aggregation.models import SourcePrecedence
    from elections.models import Election, ElectionSourceLink
    from integrations.co_sos.tasks import sync_co_elections

    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)

    with patch("integrations.co_sos.tasks.ColoradoSosClient") as MockClient, \
         patch("integrations.co_sos.tasks.cache") as mock_cache, \
         patch("integrations.co_sos.tasks.sync_co_candidates"), \
         patch("integrations.co_sos.tasks.timezone") as mock_tz, \
         patch("integrations.co_sos.tasks._current_even_year", return_value=2026):
        MockClient.return_value.get_candidate_page_fingerprint.return_value = "fp123"
        mock_cache.get.return_value = None
        mock_cache.set = MagicMock()
        mock_tz.now.return_value = MagicMock()
        mock_tz.localdate.return_value = _date(2026, 1, 1)
        sync_co_elections.run()

    link = ElectionSourceLink.objects.filter(source="co_sos", source_id="co_sos_2026_primary").first()
    assert link is not None
    assert "co_sos" in link.election.contributing_sources
    assert link.election.canonical_key.startswith("CO:")


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_sync_co_candidates_routes_through_ingest_service():
    """sync_co_candidates writes canonical Race + Candidate via ingest."""
    from aggregation.models import SourcePrecedence
    from elections.models import Candidate, Election, Race
    from integrations.co_sos.tasks import sync_co_candidates

    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)

    e = Election.objects.create(
        name="2026 Colorado Primary Election",
        election_date=_date(2026, 6, 30),
        election_type="primary",
        jurisdiction_level="state",
        state="CO",
        canonical_key="CO:primary:2026-06-30:state",
        contributing_sources=["co_sos"],
    )

    html = """
    <html><body><table>
      <tr>
        <th scope='col'>Candidate name</th>
        <th scope='col'>Office</th>
        <th scope='col'>District</th>
        <th scope='col'>Party</th>
        <th scope='col'>Write in?</th>
      </tr>
      <tr>
        <td>Alice Johnson</td><td>Governor</td><td>Statewide</td><td>Democratic Party</td><td>N</td>
      </tr>
    </table></body></html>
    """

    with patch("integrations.co_sos.tasks.ColoradoSosClient") as MockClient, \
         patch("integrations.co_sos.tasks.cache") as mock_cache:
        MockClient.return_value.fetch_candidate_html.return_value = html
        mock_cache.set = MagicMock()
        sync_co_candidates.run(e.pk, "primary", "fp123", "co_sos:fingerprint:primary")

    race = Race.objects.filter(election=e).first()
    assert race is not None
    assert "co_sos" in race.contributing_sources
    cands = list(Candidate.objects.filter(race=race))
    assert len(cands) == 1
    assert cands[0].name == "Alice Johnson"
```

- [ ] **Step 6: Run all tests including integration tests**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend && .venv/bin/python -m pytest integrations/co_sos/tests/test_tasks.py -v --no-migrations -p no:cacheprovider 2>&1 | tail -25
```

Expected: All PASS

- [ ] **Step 7: Commit**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API && git add backend/integrations/co_sos/tasks.py backend/integrations/co_sos/tests/test_tasks.py
git commit -m "feat(co_sos): route sync_co_candidates through aggregation ingest service"
```

---

## Task 5: Full Suite, Ruff, Push, PR

- [ ] **Step 1: Run full aggregation + co_sos test suite**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend && .venv/bin/python -m pytest aggregation/ integrations/co_sos/ -v --no-migrations -p no:cacheprovider 2>&1 | tail -10
```

Expected: All PASS

- [ ] **Step 2: Ruff**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend && .venv/bin/python -m ruff check integrations/co_sos/ aggregation/
```

Auto-fix if needed:
```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend && .venv/bin/python -m ruff check --fix integrations/co_sos/ aggregation/
git add backend/integrations/co_sos/ backend/aggregation/ && git commit -m "style: clean up ruff findings in CO SOS migration"
```

- [ ] **Step 3: Push and open PR**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API && git push -u origin feat/aggregation-co-sos
```

```bash
gh pr create \
  --base main \
  --head feat/aggregation-co-sos \
  --title "feat(co_sos): route sync through aggregation ingest service" \
  --body "$(cat <<'EOF'
## Summary

- Seeds CO SOS precedence rows (co_sos wins results/date; civic_api wins identity/contacts) via migration 0006
- Routes \`sync_co_elections\` through \`aggregation.ingest.ingest_election()\` — replaces \`Election.objects.update_or_create\`; \`_resolve_election_for_type\` no longer needed in the sync loop (replaced by dict keyed from ingest returns)
- Routes \`sync_co_candidates\` through \`ingest.ingest_race()\` + \`ingest.ingest_candidate()\` — withdrawn-candidate sweep preserved via \`seen_candidate_pks\` collected from ingest returns
- Fixes three mapper bugs: \`map_election\` was missing \`election_type\`; \`map_race\` and \`source_metadata\` block crashed with \`TypeError\` when \`Election.source_id\` is NULL after ingest
- CO results adapter (\`results/adapters/co.py\`) uses \`ClarityAdapter\` — no \`Race.source\` filter fix needed
- **Semantic note:** Party-partitioned primary races (R Governor + D Governor) merge into one canonical Race — same design decision as SC VREMS; party lives on Candidate; \`seen_race_pks\` guard prevents double-counting

## Test plan

- [ ] \`pytest aggregation/ integrations/co_sos/ --no-migrations\` all green
- [ ] \`ruff check integrations/co_sos/ aggregation/\` clean
- [ ] Resume scheduler + trigger manually after merge:

\`\`\`bash
gcloud scheduler jobs resume sync-co-elections \
  --project=civicmirror-2026 --location=us-central1
INTERNAL_TOKEN=\$(gcloud secrets versions access latest --secret=INTERNAL_TASK_TOKEN --project=civicmirror-2026)
curl -s -X POST "https://api.civicmirror.welshrd.com/internal/tasks/sync-co-elections/" \
  -H "Authorization: Bearer \$INTERNAL_TOKEN"
# verify: GET /api/elections/?state=CO shows canonical_key + contributing_sources containing "co_sos"
\`\`\`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- ✅ CO precedence rows seeded (migration 0006 + test)
- ✅ `map_election` gets `election_type` added to return dict
- ✅ `map_race` + `source_metadata` null `source_id` crash fixed
- ✅ `sync_co_elections` → `ingest.ingest_election()` per type; dict replaces `_resolve_election_for_type`
- ✅ Stage 1 test: `Election.filter(source_id=...)` → `ElectionSourceLink.filter(...)`
- ✅ `sync_co_candidates` → `ingest.ingest_race()` + `ingest.ingest_candidate()`; `seen_candidate_pks` from ingest returns; `seen_race_pks` double-count guard
- ✅ Withdrawn sweep preserved with `seen_candidate_pks` from ingest
- ✅ `Candidate` kept in imports; `Race` removed
- ✅ Stage 2 test updated for R/D merge (1 race, 2 candidates)
- ✅ 2 new DB integration tests
- ✅ CO results adapter confirmed clean

**Type consistency:**
- `ingest.ingest_race(election=..., source="co_sos", identity={office_title, ocd_division_id, race_type}, fields=...)` — matches `aggregation/ingest.py:117`
- `ingest.ingest_candidate(race=..., source="co_sos", name=..., party=..., fields=...)` — matches `aggregation/ingest.py:148`
- `Candidate.CandidateStatus.RUNNING` / `.WITHDRAWN` — model constants, unchanged
