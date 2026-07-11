import datetime

import pytest

from integrations.il_sbe.mappers import (
    infer_election_type_and_date,
    is_federal_or_state_office,
    map_election,
    map_race,
)


@pytest.mark.parametrize("office_name,expected", [
    ("UNITED STATES SENATOR", True),
    ("PRESIDENT AND VICE PRESIDENT", True),
    ("1ST CONGRESS", True),
    ("17TH CONGRESS", True),
    ("GOVERNOR AND LIEUTENANT GOVERNOR", True),
    ("ATTORNEY GENERAL", True),
    ("SECRETARY OF STATE", True),
    ("COMPTROLLER", True),
    ("TREASURER", True),
    ("2ND SENATE", True),
    ("118TH REPRESENTATIVE", True),
    ("1ST STATE CENTRAL COMMITTEEPERSON", False),
    ("1ST APPELLATE - HOFFMAN VACANCY", False),
    ("COOK CIRCUIT - RETAIN FLANAGAN", False),
    ('"Should any candidate appearing on the Illinois ballot..."', False),
])
def test_is_federal_or_state_office(office_name, expected):
    assert is_federal_or_state_office(office_name) is expected


def test_infer_election_type_and_date_general_election():
    election_type, election_date = infer_election_type_and_date("2024 GENERAL ELECTION")
    assert election_type == "general"
    assert election_date == datetime.date(2024, 11, 5)


def test_infer_election_type_and_date_consolidated_election():
    election_type, election_date = infer_election_type_and_date("2025 CONSOLIDATED ELECTION")
    assert election_type == "municipal"
    assert election_date == datetime.date(2025, 4, 1)


def test_infer_election_type_and_date_general_primary_is_approximate():
    election_type, election_date = infer_election_type_and_date("2026 GENERAL PRIMARY")
    assert election_type == "primary"
    # Best-effort statutory default (third Tuesday in March); flagged as
    # approximate in map_election()'s source_metadata.
    assert election_date == datetime.date(2026, 3, 17)


def test_infer_election_type_and_date_returns_none_for_special_elections():
    assert infer_election_type_and_date("2015 SPECIAL GENERAL ELECTION") is None
    assert infer_election_type_and_date("2013 SPECIAL PRIMARY") is None


def test_map_election_flags_primary_date_as_approximate():
    result = map_election("69", "2026 GENERAL PRIMARY")
    assert result["name"] == "2026 Illinois General Primary"
    assert result["state"] == "IL"
    assert result["election_type"] == "primary"
    assert result["source_id"] == "il_sbe_69"
    assert result["source_metadata"]["il_sbe_election_value"] == "69"
    assert result["source_metadata"]["election_date_approximate"] is True


def test_map_election_general_election_not_flagged_approximate():
    result = map_election("66", "2024 GENERAL ELECTION")
    assert result["source_metadata"]["election_date_approximate"] is False


def test_map_election_returns_none_for_special_elections():
    assert map_election("59", "2015 SPECIAL GENERAL ELECTION") is None


def test_map_race_sets_federal_geography_for_congress():
    election = type("FakeElection", (), {"pk": 1, "source_id": "il_sbe_69", "state": "IL"})()
    result = map_race(election, "1ST CONGRESS")
    assert result["office_title"] == "1ST CONGRESS"
    assert result["geography_scope"] == "district"
    assert result["jurisdiction"] == "1ST CONGRESS"


def test_map_race_sets_statewide_geography_for_row_offices():
    election = type("FakeElection", (), {"pk": 1, "source_id": "il_sbe_69", "state": "IL"})()
    result = map_race(election, "GOVERNOR AND LIEUTENANT GOVERNOR")
    assert result["geography_scope"] == "statewide"
    assert result["jurisdiction"] == "Illinois"
