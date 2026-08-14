import pytest

from cm2_elections.models import Person
from cm2_review.matching import find_person_match_candidates, normalize_name_for_matching


def test_normalize_name_for_matching_collapses_case_and_whitespace():
    assert normalize_name_for_matching("  DeDreana   Freeman ") == "dedreana freeman"


@pytest.mark.django_db
def test_find_person_match_candidates_scores_spelling_variant(source_artifact):
    existing = Person.objects.create(
        canonical_name="Dedreana Freeman",
        family_name="Freeman",
        given_name="Dedreana",
        identity_state=Person.IdentityState.PROVISIONAL,
        source_artifact=source_artifact,
    )
    new_person = Person.objects.create(
        canonical_name="DeDreana Freeman",
        family_name="Freeman",
        given_name="DeDreana",
        identity_state=Person.IdentityState.PROVISIONAL,
        source_artifact=source_artifact,
    )

    candidates = find_person_match_candidates(
        canonical_name=new_person.canonical_name,
        family_name=new_person.family_name,
        exclude_person_id=new_person.id,
    )

    assert len(candidates) == 1
    assert candidates[0].person == existing
    assert candidates[0].score >= 0.9
    assert candidates[0].supporting_evidence["matched_name"] == "Dedreana Freeman"


@pytest.mark.django_db
def test_find_person_match_candidates_excludes_merged_people(source_artifact):
    redirect_target = Person.objects.create(
        canonical_name="Someone Else",
        family_name="Freeman",
        identity_state=Person.IdentityState.PROVISIONAL,
        source_artifact=source_artifact,
    )
    merged = Person.objects.create(
        canonical_name="Dedreana Freeman",
        family_name="Freeman",
        identity_state=Person.IdentityState.MERGED,
        merged_into=redirect_target,
        source_artifact=source_artifact,
    )
    new_person = Person.objects.create(
        canonical_name="DeDreana Freeman",
        family_name="Freeman",
        identity_state=Person.IdentityState.PROVISIONAL,
        source_artifact=source_artifact,
    )

    candidates = find_person_match_candidates(
        canonical_name=new_person.canonical_name,
        family_name=new_person.family_name,
        exclude_person_id=new_person.id,
    )

    assert merged not in [candidate.person for candidate in candidates]


@pytest.mark.django_db
def test_find_person_match_candidates_returns_empty_below_score_floor(source_artifact):
    Person.objects.create(
        canonical_name="John Smith",
        family_name="Smith",
        identity_state=Person.IdentityState.PROVISIONAL,
        source_artifact=source_artifact,
    )
    new_person = Person.objects.create(
        canonical_name="DeDreana Freeman",
        family_name="Freeman",
        identity_state=Person.IdentityState.PROVISIONAL,
        source_artifact=source_artifact,
    )

    candidates = find_person_match_candidates(
        canonical_name=new_person.canonical_name,
        family_name=new_person.family_name,
        exclude_person_id=new_person.id,
    )

    assert candidates == []


@pytest.mark.django_db
def test_find_person_match_candidates_includes_blank_family_name(source_artifact):
    existing = Person.objects.create(
        canonical_name="DeDreana Freeman",
        family_name="",
        identity_state=Person.IdentityState.PROVISIONAL,
        source_artifact=source_artifact,
    )
    new_person = Person.objects.create(
        canonical_name="Dedreana Freeman",
        family_name="Freeman",
        given_name="Dedreana",
        identity_state=Person.IdentityState.PROVISIONAL,
        source_artifact=source_artifact,
    )

    candidates = find_person_match_candidates(
        canonical_name=new_person.canonical_name,
        family_name=new_person.family_name,
        exclude_person_id=new_person.id,
    )

    assert existing in [candidate.person for candidate in candidates]
