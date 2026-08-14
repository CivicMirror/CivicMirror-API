import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from cm2_elections.models import Person
from cm2_review.admin import IdentityReviewCaseAdmin
from cm2_review.models import IdentityReviewCase
from cm2_review.serializers import IdentityReviewCaseSerializer


def _admin_request(rf, user, post_data=None):
    request = rf.post("/admin/cm2_review/identityreviewcase/", data=post_data or {})
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
