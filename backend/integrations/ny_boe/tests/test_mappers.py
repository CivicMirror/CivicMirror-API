from datetime import date

import pytest

from elections.models import Candidate, Election, Race


def _election():
    return Election(
        name="2026 New York Primary",
        election_date=date(2026, 6, 23),
        election_type=Election.ElectionType.PRIMARY,
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NY",
        canonical_key="NY:primary:2026-06-23:state",
    )


def test_build_ny_source_identity_matches_flateau_contract():
    from integrations.ny_boe.mappers import build_ny_source_identity

    contest = {
        "office": "Representative in Congress",
        "district": "19",
        "district2": "",
        "party": "Democratic",
    }

    assert build_ny_source_identity(contest) == {
        "ny_identity_version": 1,
        "contest_code": "representative in congress|19|",
        "party_code": "DEM",
        "ny_office": "representative in congress",
        "ny_district": "19",
        "ny_district2": "",
        "ny_party": "DEM",
    }


def test_map_contest_to_race_preserves_existing_metadata_keys():
    from integrations.ny_boe.mappers import map_contest_to_race

    election = _election()
    contest = {
        "office": "Representative in Congress",
        "district": "19",
        "district2": "",
        "party": "Democratic",
        "vote_for": "1",
        "counties": "Albany, Part of Columbia",
        "key": "Representative in Congress|19||Democratic",
    }
    existing_metadata = {"curated": "keep-me", "contest_code": "old"}

    identity, fields = map_contest_to_race(contest, election, existing_metadata=existing_metadata)

    assert identity["contest_variant"] == "ny:representative in congress|19|:DEM"
    assert fields["source"] == Race.Source.NY_BOE
    assert fields["geography_scope"] == "district"
    assert fields["max_selections"] == 1
    assert fields["source_metadata"]["curated"] == "keep-me"
    assert fields["source_metadata"]["contest_code"] == "representative in congress|19|"
    assert fields["source_metadata"]["party_code"] == "DEM"


def test_map_candidate_preserves_existing_metadata_keys():
    from integrations.ny_boe.mappers import map_candidate

    fields = map_candidate(
        {"name": "Alex Rivera", "ballot_order": "1"},
        existing_metadata={"curated": "keep-me"},
    )

    assert fields["candidate_status"] == Candidate.CandidateStatus.RUNNING
    assert fields["source_metadata"]["curated"] == "keep-me"
    assert fields["source_metadata"]["ballot_order"] == "1"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Democratic", "DEM"),
        ("Republican", "REP"),
        ("Working Families", "WFP"),
        ("Conservative", "CON"),
    ],
)
def test_normalize_ny_party(raw, expected):
    from integrations.ny_boe.mappers import normalize_ny_party

    assert normalize_ny_party(raw) == expected
