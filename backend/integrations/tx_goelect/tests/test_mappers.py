"""Unit tests for TX GoElect mappers."""
from datetime import date
from unittest.mock import MagicMock

import pytest

from integrations.tx_goelect.mappers import (
    classify_election,
    infer_election_type,
    map_candidate,
    map_county_fragment,
    map_election,
    map_race,
    parse_election_date,
)


# ---------------------------------------------------------------------------
# parse_election_date
# ---------------------------------------------------------------------------

def test_parse_election_date_mmddyyyy():
    assert parse_election_date("05022026") == date(2026, 5, 2)


def test_parse_election_date_november():
    assert parse_election_date("11032026") == date(2026, 11, 3)


def test_parse_election_date_invalid_returns_none():
    assert parse_election_date("") is None
    assert parse_election_date("BADDATE") is None


# ---------------------------------------------------------------------------
# infer_election_type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code,expected", [
    ("P",  "primary"),
    ("RU", "primary_runoff"),
    ("GE", "general"),
    ("S",  "special"),
    ("SR", "special"),
    ("GR", "general_runoff"),
    ("XX", "other"),
])
def test_infer_election_type(code, expected):
    assert infer_election_type(code) == expected


# ---------------------------------------------------------------------------
# classify_election
# ---------------------------------------------------------------------------

def test_classify_general_2026():
    home = {"ElecDate": "11032026"}
    result = classify_election(59001, "GE", home)
    assert result["is_target_general_2026"] is True
    assert result["election_type_code"] == "GE"
    assert result["source_date"] == "2026-11-03"
    assert result["election_scope"] == "statewide"


def test_classify_special_not_target():
    home = {"ElecDate": "05022026"}
    result = classify_election(56181, "S", home)
    assert result["is_target_general_2026"] is False
    assert result["election_type_code"] == "S"


def test_classify_wrong_date_not_target():
    """A GE on wrong date is not the 2026 target."""
    home = {"ElecDate": "11032025"}
    result = classify_election(55000, "GE", home)
    assert result["is_target_general_2026"] is False


# ---------------------------------------------------------------------------
# map_election
# ---------------------------------------------------------------------------

def test_map_election_general():
    home = {"ElecDate": "11032026"}
    result = map_election(59001, "GE", home, "2026 GENERAL ELECTION")
    assert result["state"] == "TX"
    assert result["election_date"] == date(2026, 11, 3)
    assert result["election_type"] == "general"
    assert result["source_metadata"]["tx_election_id"] == 59001
    assert result["source_metadata"]["is_target_general_2026"] is True
    assert result["source_id"] == "tx_goelect:59001"


def test_map_election_special():
    home = {"ElecDate": "05022026"}
    result = map_election(56181, "S", home, "2026 SPECIAL ELECTION SENATE DISTRICT 4")
    assert result["election_type"] == "special"
    assert result["source_metadata"]["is_target_general_2026"] is False


# ---------------------------------------------------------------------------
# map_race
# ---------------------------------------------------------------------------

def test_map_race_statewide_candidate():
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.status = "results_pending"
    office = {"ID": 5031, "ON": "U.S. SENATOR", "SSO": 0}
    result = map_race(mock_election, office, "FEDERAL OFFICES", election_id=59001)

    assert result["race_type"] == "candidate"
    assert result["geography_scope"] == "statewide"
    assert result["office_title"] == "U.S. SENATOR"
    assert result["source_id"] == "tx_goelect:59001:office:5031"
    assert result["source_metadata"]["tx_office_id"] == 5031


def test_map_race_district():
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.status = "results_pending"
    office = {"ID": 5032, "ON": "STATE SENATOR, DISTRICT 4", "SSO": 4}
    result = map_race(mock_election, office, "DISTRICT OFFICES", election_id=56181)

    assert result["geography_scope"] == "district"
    assert result["source_id"] == "tx_goelect:56181:office:5032"


def test_map_race_measure():
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.status = "results_pending"
    office = {"ID": 6001, "ON": "PROPOSITION 1", "SSO": 0}
    result = map_race(mock_election, office, "PROPOSITIONS", election_id=59001)

    assert result["race_type"] == "measure"


# ---------------------------------------------------------------------------
# map_candidate
# ---------------------------------------------------------------------------

def test_map_candidate_with_party():
    opt = {"ID": 36388, "BN": "BRETT W. LIGON", "P": "REP"}
    result = map_candidate(election_id=56181, office_id=5031, ballot_option=opt)

    assert result["name"] == "BRETT W. LIGON"
    assert result["party"] == "REP"
    assert result["source_id"] == "tx_goelect:56181:office:5031:candidate:36388"
    assert result["source_metadata"]["tx_candidate_id"] == 36388


def test_map_candidate_no_party():
    opt = {"ID": 99, "BN": "WRITE-IN"}
    result = map_candidate(election_id=56181, office_id=5031, ballot_option=opt)
    assert result["party"] == ""


# ---------------------------------------------------------------------------
# map_county_fragment
# ---------------------------------------------------------------------------

def test_map_county_fragment_lowercase():
    entry = {"CN": "HARRIS", "MID": 48201}
    assert map_county_fragment(entry) == "harris"


def test_map_county_fragment_mid_preserved():
    entry = {"CN": "GALVESTON", "MID": 48167}
    # Function returns the slug; MID is stored in raw by the adapter, not here
    assert map_county_fragment(entry) == "galveston"
