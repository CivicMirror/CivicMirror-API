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
