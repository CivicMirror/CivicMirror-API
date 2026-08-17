import pytest
from datetime import date

from cm2_ingestion.contracts import ElectionRecord
from cm2_ingestion.review import defer_failed_promotion, flag_incomplete_election, get_resolved_incomplete_election
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

    # Simulate a downstream validation failure during promotion (e.g. public_id
    # validation failed after attempting to construct the ElectionRecord).
    deferred = defer_failed_promotion(resolved, error="public_id was empty")

    assert deferred.status == IdentityReviewCase.Status.DEFERRED
    assert get_resolved_incomplete_election(_KEY) is None
