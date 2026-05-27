"""
Tests for SC ENR mappers.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from integrations.sc_enr.mappers import parse_enr_date, map_enr_election, attempt_election_link
from integrations.sc_enr.models import ENRElection


# ------------------------------------------------------------------
# parse_enr_date
# ------------------------------------------------------------------

def test_parse_enr_date_standard():
    result = parse_enr_date("11/03/2026 07:00:00")
    assert result == date(2026, 11, 3)


def test_parse_enr_date_single_digit_month_day():
    result = parse_enr_date("6/8/2027 07:00:00")
    assert result == date(2027, 6, 8)


def test_parse_enr_date_invalid_returns_none():
    with pytest.raises(ValueError):
        parse_enr_date("not a date")


def test_parse_enr_date_empty_returns_none():
    with pytest.raises(ValueError):
        parse_enr_date("")


def test_parse_enr_date_none_input_returns_none():
    with pytest.raises(ValueError):
        parse_enr_date(None)


# ------------------------------------------------------------------
# map_enr_election
# ------------------------------------------------------------------

def test_map_enr_election_state_level():
    entry = {
        "ElectionName": "2026 General Election",
        "Date": "11/03/2026 07:00:00",
        "State": "SC",
        "County": None,
        "EID": 130000,
    }
    result = map_enr_election(entry)
    assert result["eid"] == 130000
    assert result["scope"] == ENRElection.Scope.STATE
    assert result["county"] is None
    assert result["election_name"] == "2026 General Election"
    assert result["election_date"] == date(2026, 11, 3)


def test_map_enr_election_county_level():
    entry = {
        "ElectionName": "2026 General Election",
        "Date": "11/03/2026 07:00:00",
        "State": "SC",
        "County": "Charleston",
        "EID": 121000,
    }
    result = map_enr_election(entry)
    assert result["eid"] == 121000
    assert result["scope"] == ENRElection.Scope.COUNTY
    assert result["county"] == "Charleston"


def test_map_enr_election_builds_base_url_state():
    entry = {
        "ElectionName": "2026 General Election",
        "Date": "11/03/2026 07:00:00",
        "State": "SC",
        "County": None,
        "EID": 130000,
    }
    result = map_enr_election(entry)
    assert "/SC/130000/" in result["enr_base_url"]


def test_map_enr_election_builds_base_url_county():
    entry = {
        "ElectionName": "2026 General Election",
        "Date": "11/03/2026 07:00:00",
        "State": "SC",
        "County": "Richland",
        "EID": 121500,
    }
    result = map_enr_election(entry)
    assert "/SC/Richland/121500/" in result["enr_base_url"]


def test_map_enr_election_null_date_raises():
    entry = {
        "ElectionName": "Test",
        "Date": "invalid date",
        "State": "SC",
        "County": None,
        "EID": 130000,
    }
    with pytest.raises(ValueError):
        map_enr_election(entry)


# ------------------------------------------------------------------
# attempt_election_link
# ------------------------------------------------------------------

@pytest.fixture
def state_enr():
    obj = MagicMock(spec=ENRElection)
    obj.scope = ENRElection.Scope.STATE
    obj.election_date = date(2026, 11, 3)
    obj.link_confidence = ENRElection.LinkConfidence.AMBIGUOUS
    return obj


def test_attempt_election_link_single_match(state_enr):
    mock_election = MagicMock()
    mock_election.pk = 42
    with patch("integrations.sc_enr.mappers.Election") as mock_election_cls:
        mock_election_cls.objects.filter.return_value = [mock_election]
        link, confidence = attempt_election_link(state_enr)
    assert link == mock_election
    assert confidence == ENRElection.LinkConfidence.AUTO


def test_attempt_election_link_no_match_returns_ambiguous(state_enr):
    with patch("integrations.sc_enr.mappers.Election") as mock_election_cls:
        mock_election_cls.objects.filter.return_value = []
        link, confidence = attempt_election_link(state_enr)
    assert link is None
    assert confidence == ENRElection.LinkConfidence.AMBIGUOUS


def test_attempt_election_link_multiple_matches_returns_ambiguous(state_enr):
    with patch("integrations.sc_enr.mappers.Election") as mock_election_cls:
        mock_election_cls.objects.filter.return_value = [MagicMock(), MagicMock()]
        link, confidence = attempt_election_link(state_enr)
    assert link is None
    assert confidence == ENRElection.LinkConfidence.AMBIGUOUS


def test_attempt_election_link_county_returns_ambiguous():
    county_enr = MagicMock(spec=ENRElection)
    county_enr.scope = ENRElection.Scope.COUNTY
    county_enr.election_date = date(2026, 11, 3)
    link, confidence = attempt_election_link(county_enr)
    assert link is None
    assert confidence == ENRElection.LinkConfidence.AMBIGUOUS


def test_attempt_election_link_no_date_returns_ambiguous(state_enr):
    state_enr.election_date = None
    with patch("integrations.sc_enr.mappers.Election") as mock_election_cls:
        mock_election_cls.objects.filter.return_value.count.return_value = 0
        link, confidence = attempt_election_link(state_enr)
    assert link is None
    assert confidence == ENRElection.LinkConfidence.AMBIGUOUS
