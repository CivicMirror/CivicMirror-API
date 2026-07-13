import datetime

from elections.models import Election, Race
from integrations.mn_sos.mappers import is_in_scope_file, is_write_in, map_candidate, map_election, map_race


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


def test_map_election_returns_2024_general_poc_identity():
    mapped = map_election()
    assert mapped["source_id"] == "mn_sos_2024_general"
    assert mapped["state"] == "MN"
    assert mapped["election_type"] == "general"
    assert mapped["election_date"] == datetime.date(2024, 11, 5)
    assert mapped["jurisdiction_level"] == Election.JurisdictionLevel.STATE
    assert mapped["source_metadata"]["mn_ers_election_id"] == 170
    assert mapped["source_metadata"]["mn_date_path"] == "20241105"


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
