import pytest

from cm2_results.models import ResultChoice
from cm2_results.serializers import ResultChoiceSerializer


@pytest.mark.django_db
def test_unresolved_named_write_in_output_retains_label_without_inventing_person(
    contest_result,
    source_artifact,
):
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

    output = ResultChoiceSerializer(choice).data

    assert output["source_label"] == "Jane Doe (Write-In)"
    assert output["choice_type"] == "named_write_in"
    assert output["resolution_status"] == "unresolved"
    assert output["candidacy_public_id"] is None
    assert "person" not in output
    assert "source_artifact" not in output
    assert "source_choice_key" not in output


@pytest.mark.django_db
def test_aggregate_write_in_output_retains_votes_without_identity(contest_result, source_artifact):
    choice = ResultChoice.objects.create(
        contest_result=contest_result,
        source_label="Write-In (Miscellaneous)",
        normalized_label="write in miscellaneous",
        choice_type=ResultChoice.ChoiceType.WRITE_IN_AGGREGATE,
        resolution_status=ResultChoice.ResolutionStatus.NOT_APPLICABLE,
        vote_total=17,
        source_artifact=source_artifact,
        source_choice_key="misc-write-in",
    )

    output = ResultChoiceSerializer(choice).data

    assert output["vote_total"] == 17
    assert output["candidacy_public_id"] is None
    assert output["resolution_status"] == "not_applicable"
