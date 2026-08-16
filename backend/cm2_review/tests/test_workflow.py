from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from cm2_core.models import SourceArtifact
from cm2_elections.models import Candidacy, Contest, Election, Jurisdiction, Office, Person, PersonIdentifier
from cm2_results.models import ContestResult, ResultChoice
from cm2_review.models import IdentityReviewAuditEvent, IdentityReviewCase, IdentityReviewSuggestion
from cm2_review.serializers import IdentityReviewCaseSerializer
from cm2_review.workflow import add_review_note, create_review_case, supersede_review_case, transition_review_case


@pytest.fixture
def write_in_result_choice(db):
    results_artifact = SourceArtifact.objects.create(
        source_system="nc_sbe",
        source_type=SourceArtifact.SourceType.RESULTS,
        url="https://example.test/nc/results.zip",
        retrieved_at=timezone.now(),
        content_sha256="b" * 64,
        parser_version="nc-results-v1",
        election_date=date(2026, 3, 3),
    )
    jurisdiction = Jurisdiction.objects.create(
        name="Harrellsville",
        classification="municipality",
        state="NC",
        record_status="verified",
    )
    office = Office.objects.create(jurisdiction=jurisdiction, canonical_name="Mayor", role="mayor")
    election = Election.objects.create(
        name="2026 Town of Harrellsville Election",
        election_date=date(2026, 3, 3),
        election_type="municipal",
        lifecycle_status="active",
    )
    contest = Contest.objects.create(election=election, office=office, vote_for=1)
    contest_result = ContestResult.objects.create(
        contest=contest,
        status=ContestResult.Status.UNOFFICIAL,
        source_artifact=results_artifact,
        total_votes=10,
    )
    return ResultChoice.objects.create(
        contest_result=contest_result,
        source_label="Lori Nuss (Write-In)",
        normalized_label="lori nuss",
        choice_type=ResultChoice.ChoiceType.NAMED_WRITE_IN,
        resolution_status=ResultChoice.ResolutionStatus.UNRESOLVED,
        vote_total=4,
        source_artifact=results_artifact,
        source_choice_key="harrellsville-mayor:lori-nuss",
    )


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
def test_serializer_handles_case_with_audit_events(source_record, provisional_person):
    review, created = create_review_case(
        deduplication_key="serializer-audit-events",
        defaults={
            "case_type": IdentityReviewCase.CaseType.PERSON_IDENTITY,
            "source_record": source_record,
            "provisional_person": provisional_person,
        },
    )
    assert created is True
    assert review.audit_events.exists()

    output = IdentityReviewCaseSerializer(review).data

    assert len(output["audit_events"]) >= 1
    assert output["audit_events"][0]["event_type"] == IdentityReviewAuditEvent.EventType.CREATED


@pytest.mark.django_db
def test_serializer_handles_case_with_suggestions(source_record, provisional_person):
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
        deduplication_key="serializer-suggestions",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    IdentityReviewSuggestion.objects.create(
        review_case=review,
        rank=1,
        external_scheme="civic-data",
        external_identifier="cd-serializer-test",
    )

    output = IdentityReviewCaseSerializer(review).data

    assert len(output["suggestions"]) >= 1
    suggestion_output = output["suggestions"][0]
    assert suggestion_output["rank"] == 1
    assert suggestion_output["external_scheme"] == "civic-data"
    assert suggestion_output["external_identifier"] == "cd-serializer-test"


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
def test_add_review_note_rechecks_status_against_locked_row(source_record, provisional_person, django_user_model):
    """A stale in-memory status must not bypass the terminal/superseded guard.

    The caller's `review_case` object is passed in with status still OPEN, but the row
    has since transitioned to REJECTED underneath it (simulating a concurrent transition
    that happened between when the caller read the object and when this call runs). The
    guard must be evaluated against the row fetched under select_for_update(), not the
    caller's stale copy, so this must still raise.
    """
    reviewer = django_user_model.objects.create_user(username="note-reviewer-4")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="add-note-stale-status",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    assert review.status == IdentityReviewCase.Status.OPEN

    # Simulate a concurrent transition to a terminal status without refreshing `review`.
    IdentityReviewCase.objects.filter(pk=review.pk).update(
        status=IdentityReviewCase.Status.REJECTED,
        resolution_action=IdentityReviewCase.ResolutionAction.REJECT,
        reviewed_by=reviewer,
        reviewed_at=timezone.now(),
    )
    assert review.status == IdentityReviewCase.Status.OPEN  # caller's copy is still stale

    with pytest.raises(ValidationError, match="status"):
        add_review_note(review, actor=reviewer, note="should not be appended")

    review.refresh_from_db()
    assert review.notes == ""
    assert not review.audit_events.filter(event_type=IdentityReviewAuditEvent.EventType.NOTE_ADDED).exists()


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


@pytest.mark.django_db
def test_transition_review_case_appends_notes_instead_of_overwriting(
    source_record, provisional_person, django_user_model
):
    reviewer = django_user_model.objects.create_user(username="append-notes-reviewer")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="append-notes",
        source_record=source_record,
        provisional_person=provisional_person,
    )

    add_review_note(review, actor=reviewer, note="Earlier note from ongoing review.")
    review.refresh_from_db()

    transition_review_case(
        review,
        reviewer=reviewer,
        status=IdentityReviewCase.Status.APPROVED,
        action=IdentityReviewCase.ResolutionAction.CONFIRM_NEW,
        notes="Final decision: confirmed distinct person.",
    )

    review.refresh_from_db()
    assert "Earlier note from ongoing review." in review.notes
    assert "Final decision: confirmed distinct person." in review.notes


@pytest.mark.django_db
def test_link_civic_data_rejects_identifier_already_linked_to_other_person(
    source_record,
    provisional_person,
    source_artifact,
    django_user_model,
):
    other_person = Person.objects.create(canonical_name="Someone Else", source_artifact=source_artifact)
    reviewer = django_user_model.objects.create_user(username="civic-data-reviewer-3")
    existing_identifier = PersonIdentifier.objects.create(
        person=other_person,
        scheme="civic-data",
        identifier="cd-taken",
        verification_method=PersonIdentifier.VerificationMethod.HUMAN_REVIEW,
        verified_by=reviewer,
        verified_at=timezone.now(),
    )
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="link-civic-data-conflict",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    suggestion = IdentityReviewSuggestion.objects.create(
        review_case=review,
        rank=1,
        external_scheme="civic-data",
        external_identifier="cd-taken",
    )

    with pytest.raises(ValidationError, match="target_suggestion"):
        transition_review_case(
            review,
            reviewer=reviewer,
            status=IdentityReviewCase.Status.APPROVED,
            action=IdentityReviewCase.ResolutionAction.LINK_CIVIC_DATA,
            target_suggestion=suggestion,
        )

    existing_identifier.refresh_from_db()
    provisional_person.refresh_from_db()
    assert existing_identifier.person_id == other_person.id
    assert provisional_person.identity_state == Person.IdentityState.PROVISIONAL


@pytest.mark.django_db
def test_add_review_note_metadata_does_not_leak_note_text(source_record, provisional_person, django_user_model):
    reviewer = django_user_model.objects.create_user(username="note-metadata-reviewer")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="note-metadata-leak",
        source_record=source_record,
        provisional_person=provisional_person,
    )

    secret_note = "Confidential: matches SSN on file, do not disclose."
    add_review_note(review, actor=reviewer, note=secret_note)

    event = review.audit_events.get(event_type=IdentityReviewAuditEvent.EventType.NOTE_ADDED)
    assert secret_note not in str(event.metadata)
    assert "note" not in event.metadata


@pytest.mark.django_db
def test_confirm_new_on_write_in_case_creates_person_and_candidacy(write_in_result_choice, django_user_model):
    reviewer = django_user_model.objects.create_user(username="write-in-reviewer")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.UNRESOLVED_RESULT_CHOICE,
        deduplication_key="write-in-confirm",
        result_choice=write_in_result_choice,
        supporting_evidence={"source_label": write_in_result_choice.source_label},
    )

    transition_review_case(
        review,
        reviewer=reviewer,
        status=IdentityReviewCase.Status.APPROVED,
        action=IdentityReviewCase.ResolutionAction.CONFIRM_NEW,
    )

    write_in_result_choice.refresh_from_db()
    review.refresh_from_db()
    assert write_in_result_choice.resolution_status == ResultChoice.ResolutionStatus.MATCHED
    assert write_in_result_choice.candidacy is not None

    candidacy = write_in_result_choice.candidacy
    assert candidacy.ballot_name == "Lori Nuss (Write-In)"
    assert candidacy.status == Candidacy.Status.WRITE_IN
    assert candidacy.contest_id == write_in_result_choice.contest_result.contest_id
    assert candidacy.source_artifact_id == write_in_result_choice.source_artifact_id
    assert candidacy.source_key == write_in_result_choice.source_choice_key

    person = candidacy.person
    assert person.canonical_name == "Lori Nuss (Write-In)"
    assert person.identity_state == Person.IdentityState.RESOLVED
    assert person.source_artifact_id == write_in_result_choice.source_artifact_id
    assert person.source_key == write_in_result_choice.source_choice_key

    assert review.status == IdentityReviewCase.Status.APPROVED
    assert review.resolution_action == IdentityReviewCase.ResolutionAction.CONFIRM_NEW
    assert review.audit_events.filter(event_type=IdentityReviewAuditEvent.EventType.RESOLVED).exists()


@pytest.mark.django_db
def test_confirm_new_on_write_in_case_rejects_already_linked_choice(write_in_result_choice, django_user_model):
    reviewer = django_user_model.objects.create_user(username="write-in-double-reviewer")
    other_person = Person.objects.create(canonical_name="Someone Else")
    write_in_result_choice.candidacy = Candidacy.objects.create(
        person=other_person,
        contest=write_in_result_choice.contest_result.contest,
        ballot_name="Someone Else",
        status=Candidacy.Status.WRITE_IN,
    )
    write_in_result_choice.resolution_status = ResultChoice.ResolutionStatus.MATCHED
    write_in_result_choice.save(update_fields=["candidacy", "resolution_status"])
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.UNRESOLVED_RESULT_CHOICE,
        deduplication_key="write-in-already-linked",
        result_choice=write_in_result_choice,
    )

    with pytest.raises(ValidationError, match="result_choice"):
        transition_review_case(
            review,
            reviewer=reviewer,
            status=IdentityReviewCase.Status.APPROVED,
            action=IdentityReviewCase.ResolutionAction.CONFIRM_NEW,
        )
