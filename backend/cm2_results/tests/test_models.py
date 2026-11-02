from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from cm2_elections.models import Candidacy, Contest, Election, Office, Person
from cm2_results.models import ContestResult, ResultChoice


@pytest.mark.django_db
def test_unresolved_named_write_in_needs_no_person_or_candidacy(contest_result, source_artifact):
    choice = ResultChoice.objects.create(
        contest_result=contest_result,
        source_label="Jane Doe (Write-In)",
        normalized_label="jane doe",
        choice_type=ResultChoice.ChoiceType.NAMED_WRITE_IN,
        resolution_status=ResultChoice.ResolutionStatus.UNRESOLVED,
        vote_total=41,
        source_artifact=source_artifact,
        source_choice_key="jane-doe-write-in",
    )

    assert choice.candidacy is None
    assert choice.source_label == "Jane Doe (Write-In)"


@pytest.mark.django_db
def test_aggregate_write_in_forbids_candidacy(contest_result, candidacy, source_artifact):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ResultChoice.objects.create(
                contest_result=contest_result,
                source_label="Write-In (Miscellaneous)",
                normalized_label="write in miscellaneous",
                choice_type=ResultChoice.ChoiceType.WRITE_IN_AGGREGATE,
                resolution_status=ResultChoice.ResolutionStatus.NOT_APPLICABLE,
                candidacy=candidacy,
                vote_total=17,
                source_artifact=source_artifact,
                source_choice_key="misc-write-in",
            )


@pytest.mark.django_db
def test_aggregate_write_in_requires_not_applicable_resolution(contest_result, source_artifact):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ResultChoice.objects.create(
                contest_result=contest_result,
                source_label="Write-In (Miscellaneous)",
                normalized_label="write in miscellaneous",
                choice_type=ResultChoice.ChoiceType.WRITE_IN_AGGREGATE,
                resolution_status=ResultChoice.ResolutionStatus.UNRESOLVED,
                vote_total=17,
                source_artifact=source_artifact,
                source_choice_key="misc-write-in",
            )


@pytest.mark.django_db
def test_matched_choice_requires_candidacy(contest_result, source_artifact):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ResultChoice.objects.create(
                contest_result=contest_result,
                source_label="Known Candidate",
                normalized_label="known candidate",
                choice_type=ResultChoice.ChoiceType.CANDIDATE,
                resolution_status=ResultChoice.ResolutionStatus.MATCHED,
                vote_total=59,
                source_artifact=source_artifact,
                source_choice_key="known-candidate",
            )


@pytest.mark.django_db
def test_provisional_candidate_choice_can_link_provisional_candidacy(contest_result, candidacy, source_artifact):
    choice = ResultChoice.objects.create(
        contest_result=contest_result,
        source_label="Known Candidate",
        normalized_label="known candidate",
        choice_type=ResultChoice.ChoiceType.CANDIDATE,
        resolution_status=ResultChoice.ResolutionStatus.PROVISIONAL,
        candidacy=candidacy,
        vote_total=59,
        percentage=Decimal("59.0000"),
        source_artifact=source_artifact,
        source_choice_key="known-candidate",
    )

    assert choice.candidacy == candidacy


@pytest.mark.django_db
def test_choice_candidacy_must_belong_to_the_same_contest(contest_result, candidacy, source_artifact):
    other_office = Office.objects.create(
        public_id="nc/town/harrellsville/council",
        jurisdiction=contest_result.contest.office.jurisdiction,
        canonical_name="Town Council",
        role="legislator",
        source_artifact=source_artifact,
    )
    other_contest = Contest.objects.create(
        public_id="nc/2026-03-03/primary/harrellsville-council",
        election=contest_result.contest.election,
        office=other_office,
        source_artifact=source_artifact,
    )
    other_person = Person.objects.create(canonical_name="Other Candidate", source_artifact=source_artifact)
    other_candidacy = Candidacy.objects.create(
        person=other_person,
        contest=other_contest,
        ballot_name="Other Candidate",
        source_artifact=source_artifact,
    )
    choice = ResultChoice(
        contest_result=contest_result,
        source_label="Other Candidate",
        normalized_label="other candidate",
        choice_type=ResultChoice.ChoiceType.CANDIDATE,
        resolution_status=ResultChoice.ResolutionStatus.MATCHED,
        candidacy=other_candidacy,
        vote_total=1,
        source_artifact=source_artifact,
        source_choice_key="other-candidate",
    )

    with pytest.raises(ValidationError, match="same Contest"):
        choice.full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("vote_total", "percentage"),
    [(-1, Decimal("1.0000")), (1, Decimal("-0.0001")), (1, Decimal("100.0001"))],
)
def test_choice_rejects_invalid_vote_or_percentage_values(
    contest_result,
    source_artifact,
    vote_total,
    percentage,
):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ResultChoice.objects.create(
                contest_result=contest_result,
                source_label="Invalid Choice",
                normalized_label="invalid choice",
                choice_type=ResultChoice.ChoiceType.CANDIDATE,
                resolution_status=ResultChoice.ResolutionStatus.UNRESOLVED,
                vote_total=vote_total,
                percentage=percentage,
                source_artifact=source_artifact,
                source_choice_key=f"invalid-{vote_total}-{percentage}",
            )


@pytest.mark.django_db
def test_source_choice_key_is_unique_within_current_result(contest_result, source_artifact):
    values = {
        "contest_result": contest_result,
        "source_label": "Choice",
        "normalized_label": "choice",
        "choice_type": ResultChoice.ChoiceType.CANDIDATE,
        "resolution_status": ResultChoice.ResolutionStatus.UNRESOLVED,
        "vote_total": 1,
        "source_artifact": source_artifact,
        "source_choice_key": "choice-key",
    }
    ResultChoice.objects.create(**values)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ResultChoice.objects.create(**values)


@pytest.mark.django_db
def test_contest_has_only_one_current_result(contest_result, source_artifact):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ContestResult.objects.create(
                contest=contest_result.contest,
                status=ContestResult.Status.CORRECTED,
                source_artifact=source_artifact,
                total_votes=101,
            )


@pytest.mark.django_db
def test_contest_result_rejects_negative_total(contest, source_artifact):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ContestResult.objects.create(
                contest=contest,
                status=ContestResult.Status.UNOFFICIAL,
                source_artifact=source_artifact,
                total_votes=-1,
            )
