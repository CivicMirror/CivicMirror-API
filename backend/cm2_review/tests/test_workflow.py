import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from cm2_elections.models import Person, PersonIdentifier
from cm2_review.models import IdentityReviewAuditEvent, IdentityReviewCase, IdentityReviewSuggestion
from cm2_review.serializers import IdentityReviewCaseSerializer
from cm2_review.workflow import add_review_note, supersede_review_case, transition_review_case


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


@pytest.mark.django_db
def test_link_civic_data_creates_verified_person_identifier(source_record, provisional_person, django_user_model):
    reviewer = django_user_model.objects.create_user(username="civic-data-reviewer")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="link-civic-data",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    suggestion = IdentityReviewSuggestion.objects.create(
        review_case=review,
        rank=1,
        external_scheme="civic-data",
        external_identifier="cd-12345",
    )

    transition_review_case(
        review,
        reviewer=reviewer,
        status=IdentityReviewCase.Status.APPROVED,
        action=IdentityReviewCase.ResolutionAction.LINK_CIVIC_DATA,
        target_suggestion=suggestion,
    )

    provisional_person.refresh_from_db()
    identifier = PersonIdentifier.objects.get(scheme="civic-data", identifier="cd-12345")
    assert identifier.person == provisional_person
    assert identifier.verification_method == PersonIdentifier.VerificationMethod.HUMAN_REVIEW
    assert identifier.verified_by == reviewer
    assert provisional_person.identity_state == Person.IdentityState.RESOLVED


@pytest.mark.django_db
def test_link_civic_data_requires_target_suggestion_belonging_to_case(
    source_record,
    provisional_person,
    django_user_model,
):
    reviewer = django_user_model.objects.create_user(username="civic-data-reviewer-2")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="link-civic-data-2",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    other_review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="link-civic-data-other",
        provisional_person=provisional_person,
    )
    foreign_suggestion = IdentityReviewSuggestion.objects.create(
        review_case=other_review,
        rank=1,
        external_scheme="civic-data",
        external_identifier="cd-99999",
    )

    with pytest.raises(ValidationError, match="target_suggestion"):
        transition_review_case(
            review,
            reviewer=reviewer,
            status=IdentityReviewCase.Status.APPROVED,
            action=IdentityReviewCase.ResolutionAction.LINK_CIVIC_DATA,
            target_suggestion=foreign_suggestion,
        )


@pytest.mark.django_db
def test_supersede_review_case_marks_superseded_and_audits(source_record, provisional_person, django_user_model):
    actor = django_user_model.objects.create_user(username="supersede-actor")
    old_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="supersede-old",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    new_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="supersede-new",
        provisional_person=provisional_person,
    )

    supersede_review_case(old_case, superseded_by=new_case, actor=actor)

    old_case.refresh_from_db()
    assert old_case.status == IdentityReviewCase.Status.SUPERSEDED
    assert old_case.superseded_by == new_case
    assert old_case.audit_events.filter(event_type=IdentityReviewAuditEvent.EventType.SUPERSEDED).exists()


@pytest.mark.django_db
def test_supersede_review_case_rejects_self_supersede(source_record, provisional_person, django_user_model):
    actor = django_user_model.objects.create_user(username="supersede-actor-2")
    case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="supersede-self",
        source_record=source_record,
        provisional_person=provisional_person,
    )

    with pytest.raises(ValidationError, match="superseded_by"):
        supersede_review_case(case, superseded_by=case, actor=actor)


@pytest.mark.django_db
def test_add_review_note_appends_note_and_emits_audit_event(source_record, provisional_person, django_user_model):
    reviewer = django_user_model.objects.create_user(username="note-reviewer")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="add-note",
        source_record=source_record,
        provisional_person=provisional_person,
    )

    add_review_note(review, actor=reviewer, note="Needs a second source before resolving.")

    review.refresh_from_db()
    assert "Needs a second source" in review.notes
    assert review.audit_events.filter(event_type=IdentityReviewAuditEvent.EventType.NOTE_ADDED).count() == 1


@pytest.mark.django_db
def test_add_review_note_rejects_terminal_case(source_record, provisional_person, django_user_model):
    reviewer = django_user_model.objects.create_user(username="note-reviewer-2")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="add-note-terminal",
        source_record=source_record,
        provisional_person=provisional_person,
        status=IdentityReviewCase.Status.REJECTED,
        resolution_action=IdentityReviewCase.ResolutionAction.REJECT,
        reviewed_by=reviewer,
        reviewed_at=timezone.now(),
    )

    with pytest.raises(ValidationError, match="status"):
        add_review_note(review, actor=reviewer, note="too late")


@pytest.mark.django_db
def test_add_review_note_requires_nonempty_note(source_record, provisional_person, django_user_model):
    reviewer = django_user_model.objects.create_user(username="note-reviewer-3")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="add-note-empty",
        source_record=source_record,
        provisional_person=provisional_person,
    )

    with pytest.raises(ValidationError, match="note"):
        add_review_note(review, actor=reviewer, note="   ")
