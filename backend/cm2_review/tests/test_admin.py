import pytest
from django.contrib import messages
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory
from django.utils import timezone

from cm2_elections.models import Person
from cm2_review.admin import IdentityReviewCaseAdmin
from cm2_review.models import IdentityReviewCase, IdentityReviewSuggestion
from cm2_review.serializers import IdentityReviewCaseSerializer


def _admin_request(rf, user, post_data=None):
    request = rf.post("/admin/cm2_review/identityreviewcase/", data=post_data or {})
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def _admin_get_request(rf, user):
    request = rf.get("/admin/cm2_review/identityreviewcase/")
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


@pytest.fixture
def model_admin():
    return IdentityReviewCaseAdmin(IdentityReviewCase, AdminSite())


@pytest.mark.django_db
def test_evidence_comparison_shows_protected_evidence_to_reviewer(source_record, provisional_person, model_admin):
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="admin-evidence",
        source_record=source_record,
        provisional_person=provisional_person,
        has_private_evidence=True,
    )

    html = model_admin.evidence_comparison(review)

    assert "123 Private Lane" in html
    assert "private@example.test" in html


@pytest.mark.django_db
def test_evidence_comparison_shows_side_by_side_fuzzy_match_cards(
    source_record,
    provisional_person,
    source_artifact,
    model_admin,
):
    spelled_differently = Person.objects.create(
        canonical_name="Deidra Freeman",
        given_name="Deidra",
        family_name="Freeman",
        source_artifact=source_artifact,
    )
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
        deduplication_key="admin-fuzzy-comparison",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    IdentityReviewSuggestion.objects.create(
        review_case=review,
        suggested_person=spelled_differently,
        rank=1,
        score="0.8200",
    )

    html = model_admin.evidence_comparison(review)

    # Side-by-side headers for both records.
    assert "New person found" in html
    assert "Existing possible match" in html
    # The differently-spelled given name is flagged as a diff, not silently shown as a match.
    assert "DeDreana" in html
    assert "Deidra" in html
    # Middle name is absent on the candidate person record, so it should read as missing.
    assert "Missing" in html
    # Per-suggestion action buttons let a reviewer resolve straight from the comparison card.
    assert "Link existing to Deidra Freeman" in html
    assert "Merge people into Deidra Freeman" in html


@pytest.mark.django_db
def test_merge_people_suggestion_view_merges_provisional_into_target(
    source_record,
    provisional_person,
    source_artifact,
    django_user_model,
    model_admin,
):
    target = Person.objects.create(canonical_name="William Randy Burton", source_artifact=source_artifact)
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
        deduplication_key="admin-card-merge",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    suggestion = IdentityReviewSuggestion.objects.create(
        review_case=review,
        suggested_person=target,
        rank=1,
        score="0.8700",
    )
    reviewer = django_user_model.objects.create_user(username="admin-card-merge-reviewer")
    rf = RequestFactory()
    request = _admin_get_request(rf, reviewer)

    model_admin.merge_people_suggestion(request, str(review.pk), str(suggestion.pk))

    review.refresh_from_db()
    provisional_person.refresh_from_db()
    assert review.status == IdentityReviewCase.Status.APPROVED
    assert review.resolution_action == IdentityReviewCase.ResolutionAction.MERGE_PEOPLE
    assert provisional_person.merged_into == target


@pytest.mark.django_db
def test_link_existing_suggestion_view_links_provisional_to_target(
    source_record,
    provisional_person,
    source_artifact,
    django_user_model,
    model_admin,
):
    target = Person.objects.create(canonical_name="Dedreana Freeman", source_artifact=source_artifact)
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
        deduplication_key="admin-card-link",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    suggestion = IdentityReviewSuggestion.objects.create(
        review_case=review,
        suggested_person=target,
        rank=1,
        score="0.9500",
    )
    reviewer = django_user_model.objects.create_user(username="admin-card-link-reviewer")
    rf = RequestFactory()
    request = _admin_get_request(rf, reviewer)

    model_admin.link_existing_suggestion(request, str(review.pk), str(suggestion.pk))

    review.refresh_from_db()
    provisional_person.refresh_from_db()
    assert review.status == IdentityReviewCase.Status.APPROVED
    assert review.resolution_action == IdentityReviewCase.ResolutionAction.LINK_EXISTING
    assert provisional_person.merged_into == target


@pytest.mark.django_db
def test_merge_people_suggestion_view_rejects_already_resolved_case(
    source_record,
    provisional_person,
    source_artifact,
    django_user_model,
    model_admin,
):
    target = Person.objects.create(canonical_name="William Randy Burton", source_artifact=source_artifact)
    reviewer = django_user_model.objects.create_user(username="admin-card-resolved-reviewer")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
        deduplication_key="admin-card-already-resolved",
        source_record=source_record,
        provisional_person=provisional_person,
        status=IdentityReviewCase.Status.APPROVED,
        resolution_action=IdentityReviewCase.ResolutionAction.CONFIRM_NEW,
        reviewed_by=reviewer,
        reviewed_at=timezone.now(),
    )
    suggestion = IdentityReviewSuggestion.objects.create(
        review_case=review,
        suggested_person=target,
        rank=1,
        score="0.8700",
    )
    rf = RequestFactory()
    request = _admin_get_request(rf, reviewer)

    model_admin.merge_people_suggestion(request, str(review.pk), str(suggestion.pk))

    review.refresh_from_db()
    provisional_person.refresh_from_db()
    assert review.status == IdentityReviewCase.Status.APPROVED
    assert review.resolution_action == IdentityReviewCase.ResolutionAction.CONFIRM_NEW
    assert provisional_person.merged_into is None


@pytest.mark.django_db
def test_public_serializer_still_redacts_despite_admin_visibility(source_record, provisional_person, model_admin):
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="admin-vs-public",
        source_record=source_record,
        provisional_person=provisional_person,
        has_private_evidence=True,
        supporting_evidence={"phone": "919-555-0100"},
    )

    admin_html = model_admin.evidence_comparison(review)
    public_output = IdentityReviewCaseSerializer(review).data

    assert "123 Private Lane" in admin_html
    assert public_output["supporting_evidence"] == {"redacted": True}


@pytest.mark.django_db
def test_link_existing_cases_action_links_to_target_person(
    source_record,
    provisional_person,
    source_artifact,
    django_user_model,
    model_admin,
):
    existing = Person.objects.create(canonical_name="Dedreana Freeman", source_artifact=source_artifact)
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
        deduplication_key="admin-link",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    reviewer = django_user_model.objects.create_user(username="admin-link-reviewer")
    rf = RequestFactory()
    request = _admin_request(rf, reviewer, {"target_person_public_id": existing.public_id})

    model_admin.link_existing_cases(request, IdentityReviewCase.objects.filter(pk=review.pk))

    review.refresh_from_db()
    provisional_person.refresh_from_db()
    assert review.status == IdentityReviewCase.Status.APPROVED
    assert review.resolution_action == IdentityReviewCase.ResolutionAction.LINK_EXISTING
    assert provisional_person.merged_into == existing


@pytest.mark.django_db
def test_link_existing_cases_action_reports_error_without_target(
    source_record,
    provisional_person,
    django_user_model,
    model_admin,
):
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
        deduplication_key="admin-link-missing-target",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    reviewer = django_user_model.objects.create_user(username="admin-link-reviewer-2")
    rf = RequestFactory()
    request = _admin_request(rf, reviewer)

    model_admin.link_existing_cases(request, IdentityReviewCase.objects.filter(pk=review.pk))

    review.refresh_from_db()
    assert review.status == IdentityReviewCase.Status.OPEN


@pytest.mark.django_db
def test_supersede_cases_action_marks_case_superseded(
    source_record,
    provisional_person,
    django_user_model,
    model_admin,
):
    old_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="admin-supersede-old",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    new_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="admin-supersede-new",
        provisional_person=provisional_person,
    )
    actor = django_user_model.objects.create_user(username="admin-supersede-actor")
    rf = RequestFactory()
    request = _admin_request(rf, actor, {"target_case_public_id": new_case.public_id})

    model_admin.supersede_cases(request, IdentityReviewCase.objects.filter(pk=old_case.pk))

    old_case.refresh_from_db()
    assert old_case.status == IdentityReviewCase.Status.SUPERSEDED
    assert old_case.superseded_by == new_case


@pytest.mark.django_db
def test_supersede_cases_action_reports_partial_failure_without_raising(
    source_record,
    provisional_person,
    django_user_model,
    model_admin,
):
    """One already-terminal case in the selection must not abort the whole batch."""
    open_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="admin-supersede-partial-open",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    actor = django_user_model.objects.create_user(username="admin-supersede-partial-actor")
    already_approved_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="admin-supersede-partial-approved",
        provisional_person=provisional_person,
        status=IdentityReviewCase.Status.APPROVED,
        resolution_action=IdentityReviewCase.ResolutionAction.CONFIRM_NEW,
        reviewed_by=actor,
        reviewed_at=timezone.now(),
    )
    new_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="admin-supersede-partial-target",
        provisional_person=provisional_person,
    )
    rf = RequestFactory()
    request = _admin_request(rf, actor, {"target_case_public_id": new_case.public_id})

    model_admin.supersede_cases(
        request,
        IdentityReviewCase.objects.filter(pk__in=[open_case.pk, already_approved_case.pk]),
    )

    open_case.refresh_from_db()
    already_approved_case.refresh_from_db()
    assert open_case.status == IdentityReviewCase.Status.SUPERSEDED
    assert already_approved_case.status == IdentityReviewCase.Status.APPROVED

    stored_messages = list(request._messages)
    assert len(stored_messages) == 1
    assert stored_messages[0].level == messages.WARNING
    assert "could not be superseded" in str(stored_messages[0])


@pytest.mark.django_db
def test_reject_cases_action_disputes_provisional_person(
    source_record,
    provisional_person,
    django_user_model,
    model_admin,
):
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
        deduplication_key="admin-reject",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    reviewer = django_user_model.objects.create_user(username="admin-reject-reviewer")
    rf = RequestFactory()
    request = _admin_request(rf, reviewer)

    model_admin.reject_cases(request, IdentityReviewCase.objects.filter(pk=review.pk))

    review.refresh_from_db()
    provisional_person.refresh_from_db()
    assert review.status == IdentityReviewCase.Status.REJECTED
    assert provisional_person.identity_state == Person.IdentityState.DISPUTED


@pytest.mark.django_db
def test_add_note_to_cases_action_appends_note_and_audits(
    source_record,
    provisional_person,
    django_user_model,
    model_admin,
):
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="admin-add-note",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    reviewer = django_user_model.objects.create_user(username="admin-note-reviewer")
    rf = RequestFactory()
    request = _admin_request(rf, reviewer, {"note": "Flagging for a second look."})

    model_admin.add_note_to_cases(request, IdentityReviewCase.objects.filter(pk=review.pk))

    review.refresh_from_db()
    assert "Flagging for a second look." in review.notes


def test_mutable_workflow_fields_are_readonly_on_admin_change_form(model_admin):
    """Status/resolution/audit-adjacent fields must only be mutable via workflow.py, never the raw change form."""
    readonly = model_admin.readonly_fields
    for field_name in (
        "status",
        "resolution_action",
        "reviewed_by",
        "reviewed_at",
        "superseded_by",
        "notes",
        "case_type",
        "has_private_evidence",
    ):
        assert field_name in readonly, f"{field_name} must be readonly so admin saves cannot bypass transition_review_case"


@pytest.mark.django_db
def test_confirm_new_action_reaches_deferred_cases(
    source_record,
    provisional_person,
    django_user_model,
    model_admin,
):
    reviewer = django_user_model.objects.create_user(username="admin-confirm-deferred-reviewer")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="admin-confirm-deferred",
        source_record=source_record,
        provisional_person=provisional_person,
        status=IdentityReviewCase.Status.DEFERRED,
        resolution_action=IdentityReviewCase.ResolutionAction.DEFER,
        reviewed_by=reviewer,
        reviewed_at=timezone.now(),
    )
    rf = RequestFactory()
    request = _admin_request(rf, reviewer)

    model_admin.confirm_new(request, IdentityReviewCase.objects.filter(pk=review.pk))

    review.refresh_from_db()
    provisional_person.refresh_from_db()
    assert review.status == IdentityReviewCase.Status.APPROVED
    assert review.resolution_action == IdentityReviewCase.ResolutionAction.CONFIRM_NEW
    assert provisional_person.identity_state == Person.IdentityState.RESOLVED


@pytest.mark.django_db
def test_confirm_new_action_reports_skipped_cases(
    source_record,
    provisional_person,
    django_user_model,
    model_admin,
):
    reviewer = django_user_model.objects.create_user(username="admin-confirm-skip-reviewer")
    open_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="admin-confirm-skip-open",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    approved_case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.PERSON_IDENTITY,
        deduplication_key="admin-confirm-skip-approved",
        provisional_person=provisional_person,
        status=IdentityReviewCase.Status.APPROVED,
        resolution_action=IdentityReviewCase.ResolutionAction.CONFIRM_NEW,
        reviewed_by=reviewer,
        reviewed_at=timezone.now(),
    )
    rf = RequestFactory()
    request = _admin_request(rf, reviewer)

    model_admin.confirm_new(request, IdentityReviewCase.objects.filter(pk__in=[open_case.pk, approved_case.pk]))

    open_case.refresh_from_db()
    approved_case.refresh_from_db()
    assert open_case.status == IdentityReviewCase.Status.APPROVED
    assert approved_case.status == IdentityReviewCase.Status.APPROVED
    assert approved_case.resolution_action == IdentityReviewCase.ResolutionAction.CONFIRM_NEW

    stored_messages = list(request._messages)
    assert len(stored_messages) == 1
    assert "1 skipped (not open or deferred)" in str(stored_messages[0])


@pytest.mark.django_db
def test_link_existing_cases_action_reaches_deferred_cases(
    source_record,
    provisional_person,
    source_artifact,
    django_user_model,
    model_admin,
):
    existing = Person.objects.create(canonical_name="Dedreana Freeman", source_artifact=source_artifact)
    reviewer = django_user_model.objects.create_user(username="admin-link-deferred-reviewer")
    review = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
        deduplication_key="admin-link-deferred",
        source_record=source_record,
        provisional_person=provisional_person,
        status=IdentityReviewCase.Status.DEFERRED,
        resolution_action=IdentityReviewCase.ResolutionAction.DEFER,
        reviewed_by=reviewer,
        reviewed_at=timezone.now(),
    )
    rf = RequestFactory()
    request = _admin_request(rf, reviewer, {"target_person_public_id": existing.public_id})

    model_admin.link_existing_cases(request, IdentityReviewCase.objects.filter(pk=review.pk))

    review.refresh_from_db()
    provisional_person.refresh_from_db()
    assert review.status == IdentityReviewCase.Status.APPROVED
    assert provisional_person.merged_into == existing
