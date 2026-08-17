import pytest
from datetime import date

from cm2_elections.models import Candidacy, Contest, Election
from cm2_ingestion.contracts import ContractValidationError, ElectionRecord, validate_pre_election_batch
from cm2_ingestion.persistence import apply_pre_election_batch
from cm2_ingestion.review import (
    defer_failed_promotion,
    flag_incomplete_election,
    get_resolved_election_date,
    get_resolved_incomplete_election,
)
from cm2_review.models import IdentityReviewAuditEvent, IdentityReviewCase
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


@pytest.mark.django_db
def test_get_resolved_election_date_returns_none_when_unresolved():
    assert get_resolved_election_date(_KEY) is None

    flag_incomplete_election(deduplication_key=_KEY, supporting_evidence={})

    assert get_resolved_election_date(_KEY) is None


@pytest.mark.django_db
def test_get_resolved_election_date_parses_the_supplied_date(django_user_model):
    review_case, _ = flag_incomplete_election(deduplication_key=_KEY, supporting_evidence={})
    reviewer = django_user_model.objects.create_user(username="reviewer")
    transition_review_case(
        review_case,
        reviewer=reviewer,
        status=IdentityReviewCase.Status.APPROVED,
        action=IdentityReviewCase.ResolutionAction.SUPPLY_MISSING_DATA,
        resolution_data={"election_date": "2026-11-03"},
    )

    assert get_resolved_election_date(_KEY) == date(2026, 11, 3)


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


@pytest.mark.django_db
def test_round_trip_flag_resolve_and_apply_pre_election_batch(django_user_model, source_artifact, batch_factory):
    """
    Simulates what a real state's mapping code does once it exists (no state
    package consumes this yet -- MA/OCPF is future work): flag on first
    sight, confirm nothing's promotable yet, have a reviewer supply the date,
    then confirm the resolved case's data is sufficient to clear real
    validate_pre_election_batch validation and produce real
    Election/Contest/Candidacy rows via apply_pre_election_batch.
    """
    flag_incomplete_election(
        deduplication_key=_KEY,
        supporting_evidence={"jurisdiction": "Everett", "office": "Mayoral", "candidates": ["Gerly Adrien"]},
    )
    assert get_resolved_incomplete_election(_KEY) is None
    assert get_resolved_election_date(_KEY) is None

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
    resolved_date = get_resolved_election_date(_KEY)
    assert resolved_date == date(2026, 11, 3)

    election_record = ElectionRecord(
        public_id="nc/2026-11-03/general",
        name="2026 General Election",
        election_date=resolved_date,
        election_type="general",
        lifecycle_status="upcoming",
        source_key="2026-11-03-general",
    )
    batch = batch_factory(elections=(election_record,))

    # Should not raise: the resolved date is sufficient to build a valid batch.
    validate_pre_election_batch(batch)

    report = apply_pre_election_batch(artifact=source_artifact, batch=batch)

    election = Election.objects.get(public_id="nc/2026-11-03/general")
    assert election.election_date == date(2026, 11, 3)
    contest = Contest.objects.get(public_id="nc/2026-11-03/general/us-senator")
    assert contest.election_id == election.id
    assert Candidacy.objects.filter(contest=contest).exists()
    assert report.sync_log.aggregate_counts["elections_created"] == 1
    assert report.sync_log.aggregate_counts["contests_created"] == 1
    assert report.sync_log.aggregate_counts["candidacies_created"] == 1

    # The case has served its purpose and is done: it's already terminal
    # (APPROVED) from the SUPPLY_MISSING_DATA transition above -- a real
    # ingestion run wouldn't need to touch it again.
    review_case.refresh_from_db()
    assert review_case.status == IdentityReviewCase.Status.APPROVED


@pytest.mark.django_db
def test_round_trip_defers_on_a_failed_promotion(django_user_model, source_artifact, batch_factory):
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
    resolved_date = get_resolved_election_date(_KEY)

    # Build a genuinely invalid batch: the contest references an office
    # public_id that isn't present in the batch's offices, which
    # validate_pre_election_batch actually rejects.
    election_record = ElectionRecord(
        public_id="nc/2026-11-03/general",
        name="2026 General Election",
        election_date=resolved_date,
        election_type="general",
        lifecycle_status="upcoming",
        source_key="2026-11-03-general",
    )
    batch = batch_factory(elections=(election_record,), offices=())
    contest_record = batch.contests[0]
    assert contest_record.office_public_id not in {office.public_id for office in batch.offices}

    with pytest.raises(ContractValidationError) as exc_info:
        validate_pre_election_batch(batch)

    # Simulate a downstream validation failure during promotion: the batch
    # rebuilt from resolved case data still fails validation for an
    # unrelated reason, so the case goes back to DEFERRED instead of being
    # silently lost.
    deferred = defer_failed_promotion(resolved, error=str(exc_info.value))

    assert deferred.status == IdentityReviewCase.Status.DEFERRED
    assert get_resolved_incomplete_election(_KEY) is None
    assert deferred.conflicting_evidence["promotion_error"] == "contest references unknown office"
