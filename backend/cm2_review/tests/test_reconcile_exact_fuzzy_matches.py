import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from cm2_elections.models import Person
from cm2_review.models import IdentityReviewCase, IdentityReviewSuggestion


@pytest.fixture
def reviewer(django_user_model):
    return django_user_model.objects.create_user(username="reconcile-bot")


def _make_case(*, key, source_record, provisional_person, target_person, score, **suggestion_kwargs):
    case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
        deduplication_key=key,
        source_record=source_record,
        provisional_person=provisional_person,
    )
    IdentityReviewSuggestion.objects.create(
        review_case=case,
        suggested_person=target_person,
        rank=1,
        score=score,
        **suggestion_kwargs,
    )
    return case


@pytest.mark.django_db
def test_resolves_exact_single_candidate_case(
    source_record, provisional_person, source_artifact, reviewer
):
    target = Person.objects.create(canonical_name="DeDreana Freeman", source_artifact=source_artifact)
    case = _make_case(
        key="reconcile-exact",
        source_record=source_record,
        provisional_person=provisional_person,
        target_person=target,
        score="1.0000",
    )

    call_command("reconcile_exact_fuzzy_matches", reviewer="reconcile-bot")

    case.refresh_from_db()
    provisional_person.refresh_from_db()
    assert case.status == IdentityReviewCase.Status.APPROVED
    assert case.resolution_action == IdentityReviewCase.ResolutionAction.MERGE_PEOPLE
    assert case.reviewed_by == reviewer
    assert provisional_person.merged_into == target


@pytest.mark.django_db
def test_leaves_lower_score_case_untouched(
    source_record, provisional_person, source_artifact, reviewer
):
    target = Person.objects.create(canonical_name="Deidra Freeman", source_artifact=source_artifact)
    case = _make_case(
        key="reconcile-low-score",
        source_record=source_record,
        provisional_person=provisional_person,
        target_person=target,
        score="0.8700",
    )

    call_command("reconcile_exact_fuzzy_matches", reviewer="reconcile-bot")

    case.refresh_from_db()
    assert case.status == IdentityReviewCase.Status.OPEN
    assert case.resolution_action == ""


@pytest.mark.django_db
def test_leaves_case_with_conflicting_evidence_untouched(
    source_record, provisional_person, source_artifact, reviewer
):
    target = Person.objects.create(canonical_name="DeDreana Freeman", source_artifact=source_artifact)
    case = _make_case(
        key="reconcile-conflicting",
        source_record=source_record,
        provisional_person=provisional_person,
        target_person=target,
        score="1.0000",
        conflicting_evidence={"dob": "mismatch"},
    )

    call_command("reconcile_exact_fuzzy_matches", reviewer="reconcile-bot")

    case.refresh_from_db()
    assert case.status == IdentityReviewCase.Status.OPEN


@pytest.mark.django_db
def test_leaves_case_with_multiple_suggestions_untouched(
    source_record, provisional_person, source_artifact, reviewer
):
    target_a = Person.objects.create(canonical_name="DeDreana Freeman A", source_artifact=source_artifact)
    target_b = Person.objects.create(canonical_name="DeDreana Freeman B", source_artifact=source_artifact)
    case = IdentityReviewCase.objects.create(
        case_type=IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH,
        deduplication_key="reconcile-multi",
        source_record=source_record,
        provisional_person=provisional_person,
    )
    IdentityReviewSuggestion.objects.create(review_case=case, suggested_person=target_a, rank=1, score="1.0000")
    IdentityReviewSuggestion.objects.create(review_case=case, suggested_person=target_b, rank=2, score="1.0000")

    call_command("reconcile_exact_fuzzy_matches", reviewer="reconcile-bot")

    case.refresh_from_db()
    assert case.status == IdentityReviewCase.Status.OPEN


@pytest.mark.django_db
def test_leaves_case_with_structured_name_mismatch_untouched(
    source_record, provisional_person, source_artifact, reviewer
):
    """source_record fixture has blank given/family_name, so exercise the
    mismatch path via a source record with structured parts that disagree
    with the candidate despite an (implausible but defensive) 1.0 score."""
    from cm2_elections.models import PersonSourceRecord

    target = Person.objects.create(
        canonical_name="Jordan Smith", given_name="Jordan", family_name="Smith", source_artifact=source_artifact
    )
    mismatched_source = PersonSourceRecord.objects.create(
        source_artifact=source_artifact,
        source_row_key="mismatch-row",
        person=provisional_person,
        reported_name="Jordan Smith",
        given_name="Jordan",
        family_name="Smithe",
        parser_version="nc-candidates-v1",
    )
    case = _make_case(
        key="reconcile-name-mismatch",
        source_record=mismatched_source,
        provisional_person=provisional_person,
        target_person=target,
        score="1.0000",
    )

    call_command("reconcile_exact_fuzzy_matches", reviewer="reconcile-bot")

    case.refresh_from_db()
    assert case.status == IdentityReviewCase.Status.OPEN


@pytest.mark.django_db
def test_dry_run_does_not_write_changes(
    source_record, provisional_person, source_artifact, reviewer, tmp_path
):
    target = Person.objects.create(canonical_name="DeDreana Freeman", source_artifact=source_artifact)
    case = _make_case(
        key="reconcile-dry-run",
        source_record=source_record,
        provisional_person=provisional_person,
        target_person=target,
        score="1.0000",
    )
    audit_file = tmp_path / "audit.jsonl"

    call_command(
        "reconcile_exact_fuzzy_matches",
        reviewer="reconcile-bot",
        dry_run=True,
        audit_file=str(audit_file),
    )

    case.refresh_from_db()
    assert case.status == IdentityReviewCase.Status.OPEN
    assert audit_file.exists()
    assert "reconcile-dry-run" in audit_file.read_text() or str(case.public_id) in audit_file.read_text()


@pytest.mark.django_db
def test_unknown_reviewer_raises_command_error(source_record, provisional_person):
    with pytest.raises(CommandError):
        call_command("reconcile_exact_fuzzy_matches", reviewer="does-not-exist")
