import pytest
from django.core.exceptions import ValidationError

from cm2_elections.models import Person
from cm2_review.models import IdentityReviewAuditEvent, IdentityReviewCase
from cm2_review.serializers import IdentityReviewCaseSerializer
from cm2_review.workflow import transition_review_case


@pytest.mark.django_db
def test_confirm_new_resolves_provisional_person_and_audits(source_record, provisional_person, django_user_model):
    reviewer = django_user_model.objects.create_user(username="reviewer")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="confirm-new",
        source_record=source_record,
        provisional_person=provisional_person,
    )

    transition_review_case(
        review,
        reviewer=reviewer,
        status=IdentityReviewCase.Status.APPROVED,
        action=IdentityReviewCase.ResolutionAction.CONFIRM_NEW,
        notes="Confirmed as a distinct person.",
    )

    provisional_person.refresh_from_db()
    review.refresh_from_db()
    assert provisional_person.identity_state == Person.IdentityState.RESOLVED
    assert review.status == IdentityReviewCase.Status.APPROVED
    assert review.reviewed_by == reviewer
    assert review.audit_events.filter(event_type=IdentityReviewAuditEvent.EventType.RESOLVED).exists()


@pytest.mark.django_db
def test_link_existing_requires_target_and_redirects_source(
    source_record,
    provisional_person,
    source_artifact,
    django_user_model,
):
    existing = Person.objects.create(canonical_name="Dedreana Freeman", source_artifact=source_artifact)
    reviewer = django_user_model.objects.create_user(username="link-reviewer")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
        deduplication_key="link-existing",
        source_record=source_record,
        provisional_person=provisional_person,
    )

    with pytest.raises(ValidationError, match="target_person"):
        transition_review_case(
            review,
            reviewer=reviewer,
            status=IdentityReviewCase.Status.APPROVED,
            action=IdentityReviewCase.ResolutionAction.LINK_EXISTING,
        )

    transition_review_case(
        review,
        reviewer=reviewer,
        status=IdentityReviewCase.Status.APPROVED,
        action=IdentityReviewCase.ResolutionAction.LINK_EXISTING,
        target_person=existing,
    )
    source_record.refresh_from_db()
    provisional_person.refresh_from_db()
    assert source_record.person == existing
    assert provisional_person.identity_state == Person.IdentityState.MERGED
    assert provisional_person.merged_into == existing


@pytest.mark.django_db
def test_public_review_serializer_redacts_private_evidence(source_record, provisional_person):
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="private-output",
        source_record=source_record,
        provisional_person=provisional_person,
        supporting_evidence={"phone": "private"},
        has_private_evidence=True,
    )
    output = IdentityReviewCaseSerializer(review).data
    assert "protected_address" not in output
    assert output["has_private_evidence"] is True
    assert output["supporting_evidence"] == {"redacted": True}


@pytest.mark.django_db
def test_reject_action_marks_provisional_person_disputed(source_record, provisional_person, django_user_model):
    reviewer = django_user_model.objects.create_user(username="reject-reviewer")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
        deduplication_key="reject-case",
        source_record=source_record,
        provisional_person=provisional_person,
    )

    transition_review_case(
        review,
        reviewer=reviewer,
        status=IdentityReviewCase.Status.REJECTED,
        action=IdentityReviewCase.ResolutionAction.REJECT,
        notes="Not enough evidence to resolve either way.",
    )

    provisional_person.refresh_from_db()
    review.refresh_from_db()
    assert provisional_person.identity_state == Person.IdentityState.DISPUTED
    assert review.status == IdentityReviewCase.Status.REJECTED
    assert review.resolution_action == IdentityReviewCase.ResolutionAction.REJECT


@pytest.mark.django_db
def test_reject_status_requires_reject_action(source_record, provisional_person, django_user_model):
    reviewer = django_user_model.objects.create_user(username="reject-reviewer-2")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="reject-mismatch",
        source_record=source_record,
        provisional_person=provisional_person,
    )

    with pytest.raises(ValidationError, match="action"):
        transition_review_case(
            review,
            reviewer=reviewer,
            status=IdentityReviewCase.Status.REJECTED,
            action=IdentityReviewCase.ResolutionAction.CONFIRM_NEW,
        )
