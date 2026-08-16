import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from cm2_ingestion.contracts import ContractValidationError, validate_pre_election_batch
from cm2_nc.mapping.batch import build_pre_election_batch
from cm2_nc.sources.candidate_filings import parse_candidate_rows
from cm2_nc.sources.upcoming_elections import parse_upcoming_elections

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_rows():
    return parse_candidate_rows((FIXTURES / "candidate_listing_2026_sanitized.csv").read_bytes())


def fixture_elections():
    return parse_upcoming_elections(
        (FIXTURES / "upcoming_elections_2026.html").read_bytes(),
        source_artifact_public_id="artifact/upcoming-2026",
    )


def test_fixture_batch_matches_hand_checked_manifest_and_shared_contract():
    rows = fixture_rows()
    batch = build_pre_election_batch(rows, discovered_elections=fixture_elections())
    expected = json.loads((FIXTURES / "expected_pre_election_manifest.json").read_text())

    actual = {
        "source_rows": len(rows),
        "jurisdictions": len(batch.jurisdictions),
        "offices": len(batch.offices),
        "elections": len(batch.elections),
        "contests": len(batch.contests),
        "candidates": len(batch.candidates),
        "source_evidence_rows": sum(len(candidate.source_records) for candidate in batch.candidates),
        "notices": dict(sorted(Counter(notice.code for notice in batch.notices).items())),
    }

    assert actual == expected
    validate_pre_election_batch(batch)


def test_repeated_county_rows_become_one_candidacy_with_all_source_evidence():
    batch = build_pre_election_batch(fixture_rows(), discovered_elections=fixture_elections())

    candidate = next(candidate for candidate in batch.candidates if candidate.ballot_name == "DeDreana Freeman")

    assert len(candidate.source_records) == 2
    assert {record.retrieval_context["county_name"] for record in candidate.source_records} == {"HOKE", "MOORE"}
    assert len({record.source_row_key for record in candidate.source_records}) == 2


def test_primary_party_contests_and_general_contest_remain_distinct():
    batch = build_pre_election_batch(fixture_rows(), discovered_elections=fixture_elections())
    office = next(office for office in batch.offices if office.canonical_name == "U.S. Representative")
    contests = [contest for contest in batch.contests if contest.office_public_id == office.public_id]
    elections = {election.public_id: election for election in batch.elections}

    assert sorted((elections[contest.election_public_id].election_type, contest.party_contest) for contest in contests) == [
        ("general", ""),
        ("primary", "DEM"),
        ("primary", "REP"),
    ]


def test_measure_is_excluded_but_candidate_name_containing_resolution_is_retained():
    batch = build_pre_election_batch(fixture_rows(), discovered_elections=fixture_elections())

    assert all("BOND RESOLUTION" not in contest.source_key for contest in batch.contests)
    assert any(candidate.ballot_name == "Jordan Resolution" for candidate in batch.candidates)
    measure_notices = [notice for notice in batch.notices if notice.code == "measure_excluded"]
    assert len(measure_notices) == 1
    assert measure_notices[0].subject_type == "source_contest"
    assert "BOND" not in measure_notices[0].subject_public_id


def test_csv_only_date_creates_other_provisional_election_without_month_heuristic():
    batch = build_pre_election_batch(fixture_rows(), discovered_elections=fixture_elections())
    election = next(election for election in batch.elections if election.election_date.isoformat() == "2026-12-01")

    assert election.election_type == "other"
    assert election.lifecycle_status == "provisional"
    assert election.source_artifact_public_id is None
    assert [notice.subject_public_id for notice in batch.notices if notice.code == "csv_only_election"] == [
        election.public_id
    ]


def test_source_row_lineage_ignores_changed_protected_contact_values():
    rows = fixture_rows()
    first = build_pre_election_batch(rows, discovered_elections=fixture_elections())
    changed_rows = (replace(rows[0], protected_email="changed-private@example.test"), *rows[1:])
    second = build_pre_election_batch(changed_rows, discovered_elections=fixture_elections())
    first_candidate = next(candidate for candidate in first.candidates if candidate.ballot_name == "DeDreana Freeman")
    second_candidate = next(candidate for candidate in second.candidates if candidate.ballot_name == "DeDreana Freeman")

    assert first_candidate.filing_key == second_candidate.filing_key
    assert [record.source_row_key for record in first_candidate.source_records] == [
        record.source_row_key for record in second_candidate.source_records
    ]
    assert second_candidate.source_records[0].protected_email == "changed-private@example.test"


def test_conflicting_rows_for_one_contest_fail_without_private_value_in_error():
    rows = fixture_rows()
    changed = replace(
        rows[1],
        vote_for=2,
        protected_email="never-publish@example.test",
    )

    with pytest.raises(ContractValidationError) as exc_info:
        build_pre_election_batch((rows[0], changed), discovered_elections=fixture_elections())

    assert "conflicting vote_for" in str(exc_info.value)
    assert "never-publish@example.test" not in str(exc_info.value)
