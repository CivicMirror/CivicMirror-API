import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from cm2_elections.models import Person
from cm2_review.models import IdentityReviewAuditEvent, IdentityReviewCase, IdentityReviewSuggestion


@pytest.mark.django_db
def test_review_case_defaults_open_and_preserves_evidence(source_record, provisional_person):
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="nc-sbe:candidate-row-1:identity",
        source_record=source_record,
        provisional_person=provisional_person,
        supporting_evidence={"name_similarity": "high"},
        conflicting_evidence={"spelling": ["DeDreana", "Dedreana"]},
        has_private_evidence=True,
    )

    assert review.status == IdentityReviewCase.Status.OPEN
    assert review.resolution_action == ""
    assert review.has_private_evidence is True
    assert review.conflicting_evidence == {"spelling": ["DeDreana", "Dedreana"]}


@pytest.mark.django_db
def test_review_deduplication_key_prevents_unchanged_rejected_case_reopening(
    source_record,
    provisional_person,
    django_user_model,
):
    reviewer = django_user_model.objects.create_user(username="reviewer")
    values = {
        "case_type": IdentityReviewCase.CaseType.PERSON_IDENTITY,
        "deduplication_key": "nc-sbe:candidate-row-1:identity",
        "source_record": source_record,
        "provisional_person": provisional_person,
        "status": IdentityReviewCase.Status.REJECTED,
        "resolution_action": IdentityReviewCase.ResolutionAction.CONFIRM_NEW,
        "reviewed_by": reviewer,
        "reviewed_at": timezone.now(),
    }
    IdentityReviewCase.objects.create(**values)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            IdentityReviewCase.objects.create(**{**values, "status": IdentityReviewCase.Status.OPEN})


@pytest.mark.django_db
@pytest.mark.parametrize("status", [IdentityReviewCase.Status.APPROVED, IdentityReviewCase.Status.REJECTED])
def test_terminal_review_states_require_reviewer_timestamp_and_action(
    status,
    source_record,
    provisional_person,
):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            IdentityReviewCase.objects.create(
                case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
                deduplication_key=f"terminal:{status}",
                source_record=source_record,
                provisional_person=provisional_person,
                status=status,
            )


@pytest.mark.django_db
def test_review_case_requires_a_review_subject():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            IdentityReviewCase.objects.create(
                case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
                deduplication_key="missing-subject",
            )


@pytest.mark.django_db
def test_local_person_suggestion_preserves_supporting_and_conflicting_evidence(
    source_record,
    provisional_person,
    source_artifact,
):
    existing = Person.objects.create(
        canonical_name="Dedreana Freeman",
        identity_state=Person.IdentityState.RESOLVED,
        source_artifact=source_artifact,
    )
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
        deduplication_key="fuzzy-person-match",
        source_record=source_record,
        provisional_person=provisional_person,
        has_private_evidence=True,
    )
    suggestion = IdentityReviewSuggestion.objects.create(
        review_case=review,
        suggested_person=existing,
        rank=1,
        score="0.9700",
        supporting_evidence={"normalized_name": "dedreana freeman"},
        conflicting_evidence={"source_spelling": "DeDreana Freeman"},
        uses_private_evidence=True,
    )

    assert suggestion.suggested_person == existing
    assert suggestion.uses_private_evidence is True


@pytest.mark.django_db
def test_external_suggestion_requires_both_scheme_and_identifier(source_record, provisional_person):
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="external-target",
        source_record=source_record,
        provisional_person=provisional_person,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            IdentityReviewSuggestion.objects.create(
                review_case=review,
                external_scheme="civic-data",
                rank=1,
            )

    suggestion = IdentityReviewSuggestion.objects.create(
        review_case=review,
        external_scheme="civic-data",
        external_identifier="person/nc/dedreana-freeman",
        rank=1,
    )
    assert suggestion.external_identifier == "person/nc/dedreana-freeman"


@pytest.mark.django_db
def test_suggestion_rejects_both_local_and_external_targets(
    source_record,
    provisional_person,
    source_artifact,
):
    existing = Person.objects.create(canonical_name="Existing Person", source_artifact=source_artifact)
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="two-targets",
        source_record=source_record,
        provisional_person=provisional_person,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            IdentityReviewSuggestion.objects.create(
                review_case=review,
                suggested_person=existing,
                external_scheme="civic-data",
                external_identifier="person/nc/existing",
                rank=1,
            )


@pytest.mark.django_db
def test_audit_events_are_immutable_and_record_public_metadata(source_record, provisional_person, django_user_model):
    reviewer = django_user_model.objects.create_user(username="audit-reviewer")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="audit-case",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    event = IdentityReviewAuditEvent.objects.create(
        review_case=review,
        actor=reviewer,
        event_type=IdentityReviewAuditEvent.EventType.CREATED,
        metadata={"status": "open"},
    )

    assert event.metadata == {"status": "open"}
    event.metadata = {"status": "changed"}
    with pytest.raises(Exception, match="immutable"):
        event.save()
