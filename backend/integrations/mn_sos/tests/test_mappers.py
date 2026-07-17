import datetime

from elections.models import Election, Race
from integrations.mn_sos.election_registry import MnElection
from integrations.mn_sos.mappers import (
    format_office_title,
    is_in_scope_file,
    is_write_in,
    map_candidate,
    map_election,
    map_race,
)


def test_is_in_scope_file_matches_confirmed_federal_state_labels():
    for label in (
        "U.S. President Statewide",
        "U.S. Senator Statewide",
        "U.S. Representative by District",
        "State Senator by District",
        "State Representative by District",
        "Supreme Court and Courts of Appeals Races",
    ):
        assert is_in_scope_file(label) is True


def test_is_in_scope_file_excludes_local_and_precinct_labels():
    for label in (
        "County Races",
        "County Races and Questions",
        "Municipal Questions",
        "Municipal and Hospital District Races and Questions",
        "Municipal, Hospital, and School District Races by Precinct",
        "Hospital District Races",
        "School Board Races",
        "School Referendum and Bond Questions",
        "Constitutional Amendment Statewide",
        "U.S. President by Precinct",
        "Precinct Reporting Statistics",
    ):
        assert is_in_scope_file(label) is False


def test_is_in_scope_file_matches_future_governor_label_by_pattern():
    assert is_in_scope_file("Governor and Lieutenant Governor Statewide") is True
    assert is_in_scope_file("governor by county") is False  # county-scoped, not statewide/district


def test_is_write_in_matches_9901_only():
    assert is_write_in("9901") is True
    assert is_write_in("0202") is False
    assert is_write_in("") is False


def test_format_office_title_appends_district_when_needed():
    assert format_office_title("State Senator", "1") == "State Senator District 1"
    assert format_office_title("State Senator District 1", "1") == "State Senator District 1"
    assert format_office_title("U.S. Senator", "") == "U.S. Senator"


def test_map_election_maps_descriptor_identity_and_metadata():
    election = MnElection(
        election_date=datetime.date(2024, 11, 5),
        election_type="general",
        name="2024 Minnesota General Election",
        status="results_certified",
        ers_election_id=170,
        source_id="mn_sos_2024_general",
    )
    mapped = map_election(election)
    assert mapped["source_id"] == "mn_sos_2024_general"
    assert mapped["state"] == "MN"
    assert mapped["election_type"] == "general"
    assert mapped["election_date"] == datetime.date(2024, 11, 5)
    assert mapped["jurisdiction_level"] == Election.JurisdictionLevel.STATE
    assert mapped["status"] == "results_certified"
    assert mapped["source_metadata"]["mn_ers_election_id"] == 170
    assert mapped["source_metadata"]["mn_date_path"] == "20241105"


def test_map_election_omits_ers_id_metadata_when_absent():
    election = MnElection(
        election_date=datetime.date(2026, 8, 11),
        election_type="primary",
        name="2026 Minnesota Primary",
    )
    mapped = map_election(election)
    assert mapped["source_id"] == "mn_sos_20260811"
    assert mapped["source_metadata"]["mn_date_path"] == "20260811"
    assert "mn_ers_election_id" not in mapped["source_metadata"]


def test_map_race_builds_statewide_office_fields():
    fields = map_race(office_id="0102", office_title="U.S. Senator")
    assert fields["office_title"] == "U.S. Senator"
    assert fields["race_type"] == Race.RaceType.CANDIDATE
    assert fields["source"] == "mn_sos"
    assert fields["source_metadata"]["mn_office_id"] == "0102"


def test_map_candidate_maps_party_and_source_metadata():
    row = {
        "candidate_id": "01020202", "candidate_name": "Amy Klobuchar",
        "office_id": "0102", "office_title": "U.S. Senator",
        "county_id": "88", "order_code": "02", "party": "DFL",
    }
    fields = map_candidate(row)
    assert fields["party"] == "DFL"
    assert fields["source_metadata"]["mn_candidate_id"] == "01020202"
