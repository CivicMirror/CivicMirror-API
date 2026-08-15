from decimal import Decimal

import pytest

from cm2_ingestion.aggregation import aggregate_precinct_observations
from cm2_ingestion.contracts import ContractValidationError, PrecinctResultObservation


def observation(
    observation_key,
    choice_key,
    label,
    choice_type,
    votes,
    *,
    contest="nc/2026-03-03/primary/durham-mayor",
    choice_party="",
):
    return PrecinctResultObservation(
        source_observation_key=observation_key,
        contest_public_id=contest,
        source_choice_key=choice_key,
        source_label=label,
        normalized_label=label.lower(),
        choice_type=choice_type,
        choice_party=choice_party,
        vote_total=votes,
    )


def test_precinct_rows_aggregate_once_and_include_write_ins_in_percentage_denominator():
    aggregated = aggregate_precinct_observations(
        (
            observation("precinct-a/candidate", "candidate", "Dedreana Freeman", "candidate", 5_000),
            observation("precinct-b/candidate", "candidate", "Dedreana Freeman", "candidate", 6_968),
            observation("precinct-a/misc", "misc", "Write-In (Miscellaneous)", "write_in_aggregate", 10),
            observation("precinct-b/misc", "misc", "Write-In (Miscellaneous)", "write_in_aggregate", 7),
            observation("precinct-a/jane", "jane", "Jane Doe (Write-In)", "named_write_in", 25),
        )
    )
    by_key = {choice.source_choice_key: choice for choice in aggregated}

    assert by_key["candidate"].vote_total == 11_968
    assert by_key["candidate"].percentage == Decimal("99.6503")
    assert by_key["candidate"].observation_count == 2
    assert by_key["candidate"].observation_keys == ("precinct-a/candidate", "precinct-b/candidate")
    assert by_key["misc"].vote_total == 17
    assert by_key["misc"].percentage == Decimal("0.1415")
    assert by_key["jane"].vote_total == 25
    assert by_key["jane"].percentage == Decimal("0.2082")
    assert by_key["jane"].choice_type == "named_write_in"


def test_duplicate_observation_key_is_rejected_instead_of_double_counted():
    duplicate = observation("same-observation", "candidate", "Candidate", "candidate", 10)

    with pytest.raises(ContractValidationError, match="duplicate result observation key"):
        aggregate_precinct_observations((duplicate, duplicate))


def test_conflicting_metadata_for_same_choice_key_is_rejected():
    with pytest.raises(ContractValidationError, match="conflicting result choice metadata"):
        aggregate_precinct_observations(
            (
                observation("one", "candidate", "DeDreana Freeman", "candidate", 10),
                observation("two", "candidate", "Dedreana Freeman", "candidate", 20),
            )
        )


def test_negative_observation_total_is_rejected():
    with pytest.raises(ContractValidationError, match="vote total cannot be negative"):
        aggregate_precinct_observations(
            (observation("negative", "candidate", "Candidate", "candidate", -1),)
        )


def test_empty_observation_batch_returns_empty_tuple():
    assert aggregate_precinct_observations(()) == ()


def test_aggregation_preserves_choice_party():
    aggregated = aggregate_precinct_observations(
        (
            observation("precinct-a/candidate", "candidate", "Elizabeth A. Temple", "candidate", 33, choice_party="REP"),
        )
    )
    assert aggregated[0].choice_party == "REP"
