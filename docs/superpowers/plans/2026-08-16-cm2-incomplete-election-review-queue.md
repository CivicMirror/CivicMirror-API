# CM2.0 Incomplete-Election-Data Review Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any cm2 state source flag a real, discovered candidate/office whose election date isn't known yet, so it's tracked for human resolution and picked up on a later ingestion run — instead of being silently dropped because `ElectionRecord.election_date` is required.

**Architecture:** Extend the existing `cm2_review.IdentityReviewCase` model (new case type, new resolution action, new `resolution_data` JSON field, widened subject-required constraint) rather than building a parallel review model. A new `cm2_ingestion/review.py` module provides the flag/lookup/defer helpers any state's mapping code will call; a new Django admin row-action lets a human supply the missing date through the same review queue used for person-identity cases today.

**Tech Stack:** Django 5.2, `django-unfold` admin, `pytest` + `pytest-django` (run with `--no-migrations` locally per project convention — see `run-tests-no-migrations` memory).

**Spec:** `docs/superpowers/specs/2026-08-16-cm2-incomplete-election-review-queue-design.md`

## Global Constraints

- No Celery/cron/trigger-endpoint wiring in this plan — confirmed out of scope with the user; `cm2_nc` itself has none today.
- No MA/OCPF adapter code in this plan — this is the shared mechanism only; MA is a future consumer.
- `PersonSourceRecord.IMMUTABLE_SOURCE_FIELDS` and existing `IdentityReviewCase` constraints for the three existing case types (`person_identity`, `fuzzy_person_match`, `unresolved_result_choice`) must keep working unchanged.
- Every DB-touching test runs via `pytest --no-migrations` (project convention; local test-DB creation breaks on migration replay otherwise).
- **Test invocation correction (found during SDD setup, supersedes every task's literal `Run:` lines):** the `cm2_*` apps are only registered under `config.settings.v2` (via `pytest-v2.ini`), not the default `config.settings.dev` (`pytest.ini`) — running against the default settings module fails with `RuntimeError: Model class cm2_core.models.SourceArtifact doesn't declare an explicit app_label...`. The host Python is also 3.14, but this project requires `>=3.13,<3.14`. Every test run in this plan must use the `civicmirror-2-0-api` Docker image (Python 3.13) with `pytest-v2.ini`, from the worktree's `backend/` directory mounted at `/app`:
  ```bash
  docker run --rm --network civicmirror-2-0_default \
    -e CELERY_BROKER_URL=redis://redis:6379/2 -e CELERY_RESULT_BACKEND=redis://redis:6379/3 \
    -e DJANGO_DEBUG=True -e REDIS_URL=redis://redis:6379/2 \
    -e DATABASE_URL=postgres://civicmirror_v2:civicmirror_v2@db:5432/civicmirror_2_0 \
    -e CIVICMIRROR_V2_TEST_DATABASE_NAME=civicmirror_2_0_test -e CIVICMIRROR_V2_DATABASE_NAME=civicmirror_2_0 \
    -v <absolute-path-to-this-worktree>/backend:/app -w /app \
    civicmirror-2-0-api \
    pytest -c pytest-v2.ini --no-migrations <path> -v
  ```
  Wherever a task step below says `Run: cd backend && pytest --no-migrations <path> -v`, run the equivalent `docker run ... pytest -c pytest-v2.ini --no-migrations <path> -v` command above instead. Baseline confirmed clean this way: 116 passed across `cm2_review` + `cm2_ingestion` before Task 1 started.

---

### Task 1: Widen the `IdentityReviewCase` schema

**Files:**
- Modify: `backend/cm2_review/models.py:11-21` (`CaseType`, `ResolutionAction` choices), `backend/cm2_review/models.py:57-58` (add field), `backend/cm2_review/models.py:79-87` (constraint)
- Create: `backend/cm2_review/migrations/0006_incomplete_election_data_review.py` (generated, not hand-written — see Step 3)
- Test: `backend/cm2_review/tests/test_models.py`

**Interfaces:**
- Produces: `IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA` (value `"incomplete_election_data"`), `IdentityReviewCase.ResolutionAction.SUPPLY_MISSING_DATA` (value `"supply_missing_data"`), `IdentityReviewCase.resolution_data: dict` field. Every later task depends on these three names existing exactly as written here.

- [ ] **Step 1: Write the failing test**

```python
# backend/cm2_review/tests/test_models.py (append)

import pytest
from django.db import IntegrityError, transaction

from cm2_review.models import IdentityReviewCase


@pytest.mark.django_db
def test_incomplete_election_data_case_allows_no_subject():
    review_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA,
        deduplication_key="incomplete_election:ma:everett-mayoral:2026",
        supporting_evidence={"jurisdiction": "Everett", "office": "Mayoral"},
    )
    assert review_case.source_record_id is None
    assert review_case.provisional_person_id is None
    assert review_case.result_choice_id is None


@pytest.mark.django_db
def test_other_case_types_still_require_a_subject():
    with pytest.raises(IntegrityError), transaction.atomic():
        IdentityReviewCase.objects.create(
            case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
            deduplication_key="no-subject-should-fail",
        )


@pytest.mark.django_db
def test_resolution_data_defaults_to_empty_dict():
    review_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA,
        deduplication_key="incomplete_election:ma:everett-mayoral:2026",
    )
    assert review_case.resolution_data == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest --no-migrations cm2_review/tests/test_models.py -k incomplete_election_data -v`
Expected: FAIL — `AttributeError: type object 'CaseType' has no attribute 'INCOMPLETE_ELECTION_DATA'` (or an `IntegrityError` from the current constraint rejecting the no-subject row).

- [ ] **Step 3: Edit the model**

In `backend/cm2_review/models.py`, inside `IdentityReviewCase`:

```python
    class CaseType(models.TextChoices):
        PERSON_IDENTITY = "person_identity", "New Person"
        FUZZY_PERSON_MATCH = "fuzzy_person_match", "Fuzzy person match"
        UNRESOLVED_RESULT_CHOICE = "unresolved_result_choice", "Unmatched Write-in"
        INCOMPLETE_ELECTION_DATA = "incomplete_election_data", "Incomplete election data"
```

```python
    class ResolutionAction(models.TextChoices):
        LINK_EXISTING = "link_existing", "Link existing"
        CONFIRM_NEW = "confirm_new", "Confirm new"
        MERGE_PEOPLE = "merge_people", "Merge people"
        LINK_CIVIC_DATA = "link_civic_data", "Link Civic-Data"
        DEFER = "defer", "Defer"
        REJECT = "reject", "Reject"
        SUPPLY_MISSING_DATA = "supply_missing_data", "Supply missing data"
```

Add the field right after `resolution_action` (models.py:58):

```python
    resolution_action = models.CharField(max_length=24, choices=ResolutionAction.choices, blank=True)
    resolution_data = models.JSONField(default=dict, blank=True)
```

Widen the constraint (models.py:79-87 today):

```python
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(source_record__isnull=False)
                    | models.Q(provisional_person__isnull=False)
                    | models.Q(result_choice__isnull=False)
                    | models.Q(case_type=CaseType.INCOMPLETE_ELECTION_DATA)
                ),
                name="cm2_review_case_subject_required",
            ),
```

(Leave the other two constraints in that list — `cm2_review_terminal_metadata`, `cm2_review_no_self_supersede` — untouched.)

- [ ] **Step 4: Generate and inspect the migration**

Run (per the Global Constraints test-invocation correction — `makemigrations` also needs `config.settings.v2` and Python 3.13, same as tests): `docker run --rm --network civicmirror-2-0_default -e CELERY_BROKER_URL=redis://redis:6379/2 -e CELERY_RESULT_BACKEND=redis://redis:6379/3 -e DJANGO_DEBUG=True -e REDIS_URL=redis://redis:6379/2 -e DATABASE_URL=postgres://civicmirror_v2:civicmirror_v2@db:5432/civicmirror_2_0 -e CIVICMIRROR_V2_TEST_DATABASE_NAME=civicmirror_2_0_test -e CIVICMIRROR_V2_DATABASE_NAME=civicmirror_2_0 -e DJANGO_SETTINGS_MODULE=config.settings.v2 -v <absolute-path-to-this-worktree>/backend:/app -w /app civicmirror-2-0-api python manage.py makemigrations cm2_review`
Confirm the generated file is named `backend/cm2_review/migrations/0006_*.py`, alters `case_type` and `resolution_action` choices, adds `resolution_data`, and replaces the `cm2_review_case_subject_required` constraint. Rename the auto-generated filename to `0006_incomplete_election_data_review.py` if Django picked a generic name.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && pytest --no-migrations cm2_review/tests/test_models.py -v`
Expected: PASS, including the three new tests and every pre-existing test in that file.

- [ ] **Step 6: Commit**

```bash
git add backend/cm2_review/models.py backend/cm2_review/migrations/0006_incomplete_election_data_review.py backend/cm2_review/tests/test_models.py
git commit -m "feat(cm2_review): add incomplete-election-data case type and resolution_data field"
```

---

### Task 2: Let `transition_review_case` record supplied resolution data

**Files:**
- Modify: `backend/cm2_review/workflow.py:50-213` (`transition_review_case`)
- Test: `backend/cm2_review/tests/test_workflow.py`

**Interfaces:**
- Consumes: `IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA`, `IdentityReviewCase.ResolutionAction.SUPPLY_MISSING_DATA`, `IdentityReviewCase.resolution_data` (Task 1).
- Produces: `transition_review_case(..., resolution_data: dict | None = None)` — when the action is `SUPPLY_MISSING_DATA`, `resolution_data` is required and non-empty; the case's `resolution_data` field is persisted. Task 4's admin action and Task 5's tests call this exact signature.

- [ ] **Step 1: Write the failing test**

```python
# backend/cm2_review/tests/test_workflow.py (append)

@pytest.mark.django_db
def test_supply_missing_data_requires_resolution_data(django_user_model):
    reviewer = django_user_model.objects.create_user(username="reviewer")
    review_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA,
        deduplication_key="incomplete_election:ma:everett-mayoral:2026",
    )

    with pytest.raises(ValidationError):
        transition_review_case(
            review_case,
            reviewer=reviewer,
            status=IdentityReviewCase.Status.APPROVED,
            action=IdentityReviewCase.ResolutionAction.SUPPLY_MISSING_DATA,
        )


@pytest.mark.django_db
def test_supply_missing_data_persists_resolution_data(django_user_model):
    reviewer = django_user_model.objects.create_user(username="reviewer")
    review_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA,
        deduplication_key="incomplete_election:ma:everett-mayoral:2026",
    )

    updated = transition_review_case(
        review_case,
        reviewer=reviewer,
        status=IdentityReviewCase.Status.APPROVED,
        action=IdentityReviewCase.ResolutionAction.SUPPLY_MISSING_DATA,
        resolution_data={"election_date": "2026-11-03"},
    )

    updated.refresh_from_db()
    assert updated.resolution_data == {"election_date": "2026-11-03"}
    assert updated.status == IdentityReviewCase.Status.APPROVED
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest --no-migrations cm2_review/tests/test_workflow.py -k supply_missing_data -v`
Expected: FAIL — `TypeError: transition_review_case() got an unexpected keyword argument 'resolution_data'`.

- [ ] **Step 3: Implement**

In `backend/cm2_review/workflow.py`, extend the signature:

```python
def transition_review_case(
    review_case: IdentityReviewCase,
    *,
    reviewer,
    status: str,
    action: str,
    target_person: Person | None = None,
    target_suggestion: "IdentityReviewSuggestion | None" = None,
    notes: str = "",
    resolution_data: dict | None = None,
) -> IdentityReviewCase:
```

Add a validation guard alongside the existing ones (near workflow.py:77, after the REJECT-status checks):

```python
    if action == IdentityReviewCase.ResolutionAction.SUPPLY_MISSING_DATA:
        if status != IdentityReviewCase.Status.APPROVED:
            raise ValidationError({"status": "Supplying missing data requires approved status."})
        if not resolution_data:
            raise ValidationError({"resolution_data": "This action requires resolution_data."})
```

Update the save block (workflow.py:185-200):

```python
    review_case.status = status
    review_case.resolution_action = action
    review_case.reviewed_by = reviewer
    review_case.reviewed_at = timezone.now()
    if notes:
        review_case.notes = _append_note(review_case.notes, notes)
    update_fields = ["status", "resolution_action", "reviewed_by", "reviewed_at", "notes", "updated_at"]
    if resolution_data is not None:
        review_case.resolution_data = resolution_data
        update_fields.append("resolution_data")
    review_case.save(update_fields=update_fields)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest --no-migrations cm2_review/tests/test_workflow.py -v`
Expected: PASS, including every pre-existing test in that file (the new guard must not affect any other action).

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_review/workflow.py backend/cm2_review/tests/test_workflow.py
git commit -m "feat(cm2_review): transition_review_case accepts resolution_data for supply_missing_data"
```

---

### Task 3: `cm2_ingestion.review` — flag and look up incomplete-election cases

**Files:**
- Create: `backend/cm2_ingestion/review.py`
- Test: `backend/cm2_ingestion/tests/test_review.py`

**Interfaces:**
- Consumes: `cm2_review.workflow.create_review_case(*, defaults: dict, deduplication_key: str) -> tuple[IdentityReviewCase, bool]` (existing, unmodified), `IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA`, `.Status.OPEN`, `.Status.APPROVED`, `.ResolutionAction.SUPPLY_MISSING_DATA` (Task 1).
- Produces: `flag_incomplete_election(*, deduplication_key: str, supporting_evidence: dict) -> tuple[IdentityReviewCase, bool]` and `get_resolved_incomplete_election(deduplication_key: str) -> IdentityReviewCase | None`. Task 4 and Task 6 call these exact names/signatures.

- [ ] **Step 1: Write the failing tests**

```python
# backend/cm2_ingestion/tests/test_review.py

import pytest

from cm2_ingestion.review import flag_incomplete_election, get_resolved_incomplete_election
from cm2_review.models import IdentityReviewCase
from cm2_review.workflow import transition_review_case

_KEY = "incomplete_election:ma:everett-mayoral:2026"


@pytest.mark.django_db
def test_flag_incomplete_election_creates_open_case():
    review_case, created = flag_incomplete_election(
        deduplication_key=_KEY,
        supporting_evidence={"jurisdiction": "Everett", "office": "Mayoral", "candidates": ["Gerly Adrien"]},
    )

    assert created is True
    assert review_case.case_type == IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA
    assert review_case.status == IdentityReviewCase.Status.OPEN
    assert review_case.supporting_evidence["office"] == "Mayoral"


@pytest.mark.django_db
def test_flag_incomplete_election_refreshes_evidence_when_still_open():
    flag_incomplete_election(deduplication_key=_KEY, supporting_evidence={"candidates": ["Gerly Adrien"]})

    review_case, created = flag_incomplete_election(
        deduplication_key=_KEY,
        supporting_evidence={"candidates": ["Gerly Adrien", "Someone Else"]},
    )

    assert created is False
    assert review_case.supporting_evidence["candidates"] == ["Gerly Adrien", "Someone Else"]
    assert IdentityReviewCase.objects.filter(deduplication_key=_KEY).count() == 1


@pytest.mark.django_db
def test_flag_incomplete_election_does_not_overwrite_a_resolved_case(django_user_model):
    review_case, _ = flag_incomplete_election(
        deduplication_key=_KEY, supporting_evidence={"candidates": ["Gerly Adrien"]},
    )
    reviewer = django_user_model.objects.create_user(username="reviewer")
    transition_review_case(
        review_case,
        reviewer=reviewer,
        status=IdentityReviewCase.Status.APPROVED,
        action=IdentityReviewCase.ResolutionAction.SUPPLY_MISSING_DATA,
        resolution_data={"election_date": "2026-11-03"},
    )

    review_case_again, created = flag_incomplete_election(
        deduplication_key=_KEY,
        supporting_evidence={"candidates": ["Gerly Adrien", "Late Filer"]},
    )

    assert created is False
    assert review_case_again.status == IdentityReviewCase.Status.APPROVED
    assert review_case_again.supporting_evidence["candidates"] == ["Gerly Adrien"]


@pytest.mark.django_db
def test_get_resolved_incomplete_election_returns_none_when_still_open():
    flag_incomplete_election(deduplication_key=_KEY, supporting_evidence={})

    assert get_resolved_incomplete_election(_KEY) is None


@pytest.mark.django_db
def test_get_resolved_incomplete_election_returns_none_when_no_case_exists():
    assert get_resolved_incomplete_election(_KEY) is None


@pytest.mark.django_db
def test_get_resolved_incomplete_election_returns_the_supplied_date(django_user_model):
    review_case, _ = flag_incomplete_election(deduplication_key=_KEY, supporting_evidence={})
    reviewer = django_user_model.objects.create_user(username="reviewer")
    transition_review_case(
        review_case,
        reviewer=reviewer,
        status=IdentityReviewCase.Status.APPROVED,
        action=IdentityReviewCase.ResolutionAction.SUPPLY_MISSING_DATA,
        resolution_data={"election_date": "2026-11-03"},
    )

    resolved = get_resolved_incomplete_election(_KEY)

    assert resolved is not None
    assert resolved.resolution_data["election_date"] == "2026-11-03"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest --no-migrations cm2_ingestion/tests/test_review.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cm2_ingestion.review'`.

- [ ] **Step 3: Implement**

```python
# backend/cm2_ingestion/review.py
from __future__ import annotations

from cm2_review.models import IdentityReviewCase
from cm2_review.workflow import create_review_case


def flag_incomplete_election(*, deduplication_key: str, supporting_evidence: dict) -> tuple[IdentityReviewCase, bool]:
    """
    Record (or refresh) a review case for a discovered candidate/office whose
    election date isn't known yet, so it's tracked for human resolution and
    picked up on a later ingestion run instead of being silently dropped
    (ElectionRecord.election_date has no null/placeholder path).

    Idempotent on `deduplication_key`: a repeat call while the case is still
    OPEN refreshes `supporting_evidence` in place rather than creating a
    duplicate row. A repeat call after the case has been resolved (or
    deferred/rejected) leaves it untouched -- callers should check
    get_resolved_incomplete_election() for a resolved case before calling
    this again for the same discovery.
    """
    review_case, created = create_review_case(
        defaults={
            "case_type": IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA,
            "supporting_evidence": supporting_evidence,
        },
        deduplication_key=deduplication_key,
    )
    if not created and review_case.status == IdentityReviewCase.Status.OPEN:
        review_case.supporting_evidence = supporting_evidence
        review_case.save(update_fields=["supporting_evidence", "updated_at"])
    return review_case, created


def get_resolved_incomplete_election(deduplication_key: str) -> IdentityReviewCase | None:
    """
    Look up an approved incomplete-election-data case ready for promotion
    into a real Election/Contest/Candidacy. Returns None if no case exists
    for this key, or it exists but hasn't been approved with
    SUPPLY_MISSING_DATA yet (still open, deferred, or rejected).
    """
    return IdentityReviewCase.objects.filter(
        deduplication_key=deduplication_key,
        case_type=IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA,
        status=IdentityReviewCase.Status.APPROVED,
        resolution_action=IdentityReviewCase.ResolutionAction.SUPPLY_MISSING_DATA,
    ).first()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest --no-migrations cm2_ingestion/tests/test_review.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ingestion/review.py backend/cm2_ingestion/tests/test_review.py
git commit -m "feat(cm2_ingestion): add flag/lookup helpers for incomplete-election-data review cases"
```

---

### Task 4: `defer_failed_promotion` — system-triggered deferral on a failed promotion attempt

**Files:**
- Modify: `backend/cm2_ingestion/review.py`
- Test: `backend/cm2_ingestion/tests/test_review.py`

**Interfaces:**
- Consumes: `IdentityReviewCase`, `IdentityReviewAuditEvent` (from `cm2_review.models`).
- Produces: `defer_failed_promotion(review_case: IdentityReviewCase, *, error: str) -> IdentityReviewCase`.

- [ ] **Step 1: Write the failing test**

```python
# backend/cm2_ingestion/tests/test_review.py (append)

from cm2_ingestion.review import defer_failed_promotion
from cm2_review.models import IdentityReviewAuditEvent


@pytest.mark.django_db
def test_defer_failed_promotion_moves_an_approved_case_to_deferred(django_user_model):
    review_case, _ = flag_incomplete_election(deduplication_key=_KEY, supporting_evidence={})
    reviewer = django_user_model.objects.create_user(username="reviewer")
    transition_review_case(
        review_case,
        reviewer=reviewer,
        status=IdentityReviewCase.Status.APPROVED,
        action=IdentityReviewCase.ResolutionAction.SUPPLY_MISSING_DATA,
        resolution_data={"election_date": "2026-11-03"},
    )

    deferred = defer_failed_promotion(review_case, error="office public_id no longer resolves")

    deferred.refresh_from_db()
    assert deferred.status == IdentityReviewCase.Status.DEFERRED
    assert deferred.conflicting_evidence["promotion_error"] == "office public_id no longer resolves"
    assert deferred.audit_events.filter(
        event_type=IdentityReviewAuditEvent.EventType.DEFERRED,
        metadata__reason="promotion_failed",
    ).exists()


@pytest.mark.django_db
def test_defer_failed_promotion_preserves_existing_conflicting_evidence():
    review_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA,
        deduplication_key=_KEY,
        conflicting_evidence={"prior_note": "kept"},
    )

    deferred = defer_failed_promotion(review_case, error="boom")

    assert deferred.conflicting_evidence == {"prior_note": "kept", "promotion_error": "boom"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest --no-migrations cm2_ingestion/tests/test_review.py -k defer_failed_promotion -v`
Expected: FAIL — `ImportError: cannot import name 'defer_failed_promotion'`.

- [ ] **Step 3: Implement**

Add to `backend/cm2_ingestion/review.py` (extend the existing import line and append the function):

```python
from django.db import transaction

from cm2_review.models import IdentityReviewAuditEvent, IdentityReviewCase
from cm2_review.workflow import create_review_case


@transaction.atomic
def defer_failed_promotion(review_case: IdentityReviewCase, *, error: str) -> IdentityReviewCase:
    """
    Move a case back to DEFERRED after an ingestion run tried to promote its
    supplied resolution_data and hit a downstream validation error (e.g. the
    rebuilt batch still failed validate_pre_election_batch for an unrelated
    reason). Distinct from transition_review_case: this is a system-triggered
    transition, not a new human decision, so it bypasses the
    authenticated-reviewer gate and records the error on conflicting_evidence
    rather than notes, alongside the original supporting_evidence.
    """
    review_case.status = IdentityReviewCase.Status.DEFERRED
    review_case.conflicting_evidence = {
        **(review_case.conflicting_evidence or {}),
        "promotion_error": error,
    }
    review_case.save(update_fields=["status", "conflicting_evidence", "updated_at"])
    IdentityReviewAuditEvent.objects.create(
        review_case=review_case,
        actor=None,
        event_type=IdentityReviewAuditEvent.EventType.DEFERRED,
        metadata={"reason": "promotion_failed", "error": error},
        has_private_evidence=review_case.has_private_evidence,
    )
    return review_case
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest --no-migrations cm2_ingestion/tests/test_review.py -v`
Expected: PASS (8 tests total in this file).

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ingestion/review.py backend/cm2_ingestion/tests/test_review.py
git commit -m "feat(cm2_ingestion): add defer_failed_promotion for failed incomplete-election promotions"
```

---

### Task 5: Admin — let a reviewer supply the missing election date

**Files:**
- Modify: `backend/cm2_review/admin.py`
- Test: `backend/cm2_review/tests/test_admin.py`

**Interfaces:**
- Consumes: `transition_review_case(..., resolution_data=...)` (Task 2), `IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA` / `.ResolutionAction.SUPPLY_MISSING_DATA` (Task 1).

- [ ] **Step 1: Write the failing test**

Check `backend/cm2_review/tests/test_admin.py` first for the existing pattern used to test `defer_case_row` (same shape — a `RequestFactory`/admin-site instance hitting the method directly, or a full client + login). Match whichever pattern is already there. Append:

```python
# backend/cm2_review/tests/test_admin.py (append; adapt request/client setup to match the file's existing pattern for defer_case_row)

@pytest.mark.django_db
def test_supply_missing_date_row_approves_case_with_supplied_date(admin_client):
    review_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA,
        deduplication_key="incomplete_election:ma:everett-mayoral:2026",
        supporting_evidence={"office": "Mayoral"},
    )
    url = reverse("admin:cm2_review_identityreviewcase_supply_missing_date_row", args=[review_case.pk])

    response = admin_client.post(url, {"election_date": "2026-11-03"})

    review_case.refresh_from_db()
    assert response.status_code == 302
    assert review_case.status == IdentityReviewCase.Status.APPROVED
    assert review_case.resolution_data == {"election_date": "2026-11-03"}


@pytest.mark.django_db
def test_supply_missing_date_row_rejects_bad_date_format(admin_client):
    review_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA,
        deduplication_key="incomplete_election:ma:everett-mayoral:2026",
    )
    url = reverse("admin:cm2_review_identityreviewcase_supply_missing_date_row", args=[review_case.pk])

    admin_client.post(url, {"election_date": "not-a-date"})

    review_case.refresh_from_db()
    assert review_case.status == IdentityReviewCase.Status.OPEN


@pytest.mark.django_db
def test_supply_missing_date_row_rejects_wrong_case_type(admin_client, source_record, provisional_person):
    review_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="wrong-case-type",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    url = reverse("admin:cm2_review_identityreviewcase_supply_missing_date_row", args=[review_case.pk])

    admin_client.post(url, {"election_date": "2026-11-03"})

    review_case.refresh_from_db()
    assert review_case.status == IdentityReviewCase.Status.OPEN
```

Note: `reverse(...)` for a `unfold`/`@action` row action follows the same URL-naming convention as `confirm_new_row`/`defer_case_row` already registered via `actions_row` — those don't need a `get_urls()` entry (only `link_existing_suggestion`/`merge_people_suggestion` do, per admin.py:124-137). Confirm the exact reverse name by checking how `defer_case_row` is invoked/tested in the existing `test_admin.py` before assuming the name above; adjust to match.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest --no-migrations cm2_review/tests/test_admin.py -k supply_missing_date -v`
Expected: FAIL — `NoReverseMatch` (the action/URL doesn't exist yet).

- [ ] **Step 3: Implement**

Add the `datetime.date` import at the top of `backend/cm2_review/admin.py`:

```python
from datetime import date
```

Add a field to `ReviewCaseActionForm` (admin.py:24-39):

```python
    election_date = forms.CharField(
        required=False,
        widget=UnfoldAdminTextInputWidget(attrs={"size": 14, "placeholder": "YYYY-MM-DD"}),
        help_text="Election date to supply for an incomplete-election-data case.",
    )
```

Add the row action to `IdentityReviewCaseAdmin` (near `defer_case_row`, admin.py:196-209):

```python
    @action(description="Supply election date")
    def supply_missing_date_row(self, request, object_id):
        review_case = IdentityReviewCase.objects.get(pk=object_id)
        if review_case.case_type != IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA:
            self.message_user(
                request, "This action only applies to incomplete-election-data cases.", messages.ERROR
            )
            return self._redirect_back(request)
        if review_case.status != IdentityReviewCase.Status.OPEN:
            self.message_user(request, "This case is not open.", messages.WARNING)
            return self._redirect_back(request)
        raw_date = request.POST.get("election_date", "").strip()
        if not raw_date:
            self.message_user(request, "Provide an election date above.", messages.ERROR)
            return self._redirect_back(request)
        try:
            parsed_date = date.fromisoformat(raw_date)
        except ValueError:
            self.message_user(request, "Election date must be in YYYY-MM-DD format.", messages.ERROR)
            return self._redirect_back(request)
        transition_review_case(
            review_case,
            reviewer=request.user,
            status=IdentityReviewCase.Status.APPROVED,
            action=IdentityReviewCase.ResolutionAction.SUPPLY_MISSING_DATA,
            resolution_data={"election_date": parsed_date.isoformat()},
        )
        self.message_user(request, f"Supplied election date {parsed_date.isoformat()}.", messages.SUCCESS)
        return self._redirect_back(request)
```

Register it alongside the other row actions (admin.py:83-84):

```python
    actions_row = ("confirm_new_row", "defer_case_row", "reject_case_row", "supply_missing_date_row")
    actions_detail = ("confirm_new_row", "defer_case_row", "reject_case_row", "supply_missing_date_row")
```

Add `resolution_data` to `readonly_fields` (admin.py:56-71) and to the "Resolution" fieldset (admin.py:88-91) so it's visible after being set:

```python
    readonly_fields = (
        "id",
        "public_id",
        "deduplication_key",
        "created_at",
        "updated_at",
        "evidence_comparison",
        "status",
        "resolution_action",
        "resolution_data",
        "reviewed_by",
        "reviewed_at",
        "superseded_by",
        "notes",
        "case_type",
        "has_private_evidence",
    )
    ...
    fieldsets = (
        (None, {"fields": ("public_id", "case_type", "status", "has_private_evidence")}),
        ("Evidence comparison", {"fields": ("evidence_comparison",)}),
        (
            "Resolution",
            {"fields": ("resolution_action", "resolution_data", "reviewed_by", "reviewed_at", "notes", "superseded_by")},
        ),
        ("Metadata", {"fields": ("id", "deduplication_key", "created_at", "updated_at")}),
    )
```

Add the new case type to the `case_type_display` label map (admin.py:95-105) so it renders with a badge like the other three:

```python
    @display(
        description="Case Type",
        ordering="case_type",
        label={
            IdentityReviewCase.CaseType.PERSON_IDENTITY: "info",
            IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH: "warning",
            IdentityReviewCase.CaseType.UNRESOLVED_RESULT_CHOICE: "danger",
            IdentityReviewCase.CaseType.INCOMPLETE_ELECTION_DATA: "warning",
        },
    )
```

If Step 2's failure showed `supply_missing_date_row` needs an explicit URL (i.e. `@action`-decorated row methods in this `unfold` version aren't auto-routed the same way `link_existing_suggestion` is), add it to `get_urls()` (admin.py:124-137) following the existing pattern instead, and adjust the test's `reverse(...)` name to match. Use whichever mechanism the failing test's actual traceback points to — don't guess past what Step 2 showed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest --no-migrations cm2_review/tests/test_admin.py -v`
Expected: PASS, including every pre-existing test in the file.

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_review/admin.py backend/cm2_review/tests/test_admin.py
git commit -m "feat(cm2_review): admin action to supply a missing election date"
```

---

### Task 6: Round-trip test proving the full flag → resolve → promote contract

**Files:**
- Test: `backend/cm2_ingestion/tests/test_review.py`

**Interfaces:**
- Consumes: everything produced by Tasks 1-4 (`flag_incomplete_election`, `get_resolved_incomplete_election`, `defer_failed_promotion`, `transition_review_case`) plus `cm2_ingestion.contracts.ElectionRecord` (existing, unmodified).

- [ ] **Step 1: Write the test**

```python
# backend/cm2_ingestion/tests/test_review.py (append)

from datetime import date

from cm2_ingestion.contracts import ElectionRecord


@pytest.mark.django_db
def test_round_trip_flag_resolve_and_build_election_record(django_user_model):
    """
    Simulates what a real state's mapping code does once it exists (no state
    package consumes this yet -- MA/OCPF is future work): flag on first
    sight, confirm nothing's promotable yet, have a reviewer supply the date,
    then confirm the resolved case's data is sufficient to build the
    ElectionRecord the pre-election batch contract requires.
    """
    flag_incomplete_election(
        deduplication_key=_KEY,
        supporting_evidence={"jurisdiction": "Everett", "office": "Mayoral", "candidates": ["Gerly Adrien"]},
    )
    assert get_resolved_incomplete_election(_KEY) is None

    review_case = IdentityReviewCase.objects.get(deduplication_key=_KEY)
    reviewer = django_user_model.objects.create_user(username="reviewer")
    transition_review_case(
        review_case,
        reviewer=reviewer,
        status=IdentityReviewCase.Status.APPROVED,
        action=IdentityReviewCase.ResolutionAction.SUPPLY_MISSING_DATA,
        resolution_data={"election_date": "2026-11-03"},
    )

    resolved = get_resolved_incomplete_election(_KEY)
    assert resolved is not None

    election_record = ElectionRecord(
        public_id="ma/election/everett-mayoral-2026",
        name="2026 Everett Mayoral Election",
        election_date=date.fromisoformat(resolved.resolution_data["election_date"]),
        election_type="municipal",
    )

    assert election_record.election_date == date(2026, 11, 3)


@pytest.mark.django_db
def test_round_trip_defers_on_a_failed_promotion(django_user_model):
    flag_incomplete_election(deduplication_key=_KEY, supporting_evidence={"office": "Mayoral"})
    review_case = IdentityReviewCase.objects.get(deduplication_key=_KEY)
    reviewer = django_user_model.objects.create_user(username="reviewer")
    transition_review_case(
        review_case,
        reviewer=reviewer,
        status=IdentityReviewCase.Status.APPROVED,
        action=IdentityReviewCase.ResolutionAction.SUPPLY_MISSING_DATA,
        resolution_data={"election_date": "2026-11-03"},
    )
    resolved = get_resolved_incomplete_election(_KEY)

    try:
        ElectionRecord(
            public_id="",  # simulate a downstream validation failure at promotion time
            name="2026 Everett Mayoral Election",
            election_date=date.fromisoformat(resolved.resolution_data["election_date"]),
            election_type="municipal",
        )
        raise AssertionError("expected building the promoted record to be treated as failed by this test")
    except Exception:
        deferred = defer_failed_promotion(resolved, error="public_id was empty")

    assert deferred.status == IdentityReviewCase.Status.DEFERRED
    assert get_resolved_incomplete_election(_KEY) is None
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `cd backend && pytest --no-migrations cm2_ingestion/tests/test_review.py -v`
Expected: PASS (10 tests total in this file).

- [ ] **Step 3: Run the full affected test suites once more**

Run: `cd backend && pytest --no-migrations cm2_review cm2_ingestion -v`
Expected: PASS, no regressions in either app's existing tests.

- [ ] **Step 4: Commit**

```bash
git add backend/cm2_ingestion/tests/test_review.py
git commit -m "test(cm2_ingestion): round-trip flag/resolve/promote/defer coverage"
```

---

## Self-Review Notes

- **Spec coverage:** Schema changes (Task 1) ✅, flagging helper (Task 3) ✅, resolution via admin (Task 2 + 5) ✅, promotion-check helper (Task 3's `get_resolved_incomplete_election`) ✅, error-handling deferral (Task 4) ✅, round-trip + failure-path tests (Task 6) ✅, migration test (Task 1) ✅.
- **Type consistency:** `flag_incomplete_election`/`get_resolved_incomplete_election`/`defer_failed_promotion` signatures are identical everywhere they're referenced across Tasks 3, 4, and 6. `resolution_data` is always a `dict` keyed by field name (`{"election_date": "YYYY-MM-DD"}` as an ISO string, not a `date` object — JSONField can't store `date` natively, and every consumer in this plan parses it back with `date.fromisoformat`).
- **Known open item flagged in-plan, not hidden:** Task 5, Step 3 explicitly tells the executor to verify the row-action URL-routing mechanism against this `unfold` version's actual behavior rather than assuming — the existing `link_existing_suggestion`/`merge_people_suggestion` needed manual `get_urls()` entries while `confirm_new_row`/`defer_case_row` apparently don't; the plan doesn't paper over that inconsistency.
