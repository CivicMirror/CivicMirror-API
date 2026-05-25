"""
Tests for integrations.ma_sos.mappers — pure transformation functions.
No DB or HTTP required.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from integrations.ma_sos import mappers


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------

def test_normalize_basic():
    assert mappers.normalize("  U.S.  House  ") == "u.s. house"


def test_normalize_empty():
    assert mappers.normalize("") == ""


def test_normalize_none():
    assert mappers.normalize(None) == ""


# ---------------------------------------------------------------------------
# infer_election_type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stage,expected", [
    ("General", "general"),
    ("Primaries", "primary"),
    ("Democratic", "primary"),
    ("Republican", "primary"),
    ("Green-Rainbow", "primary"),
    ("Special General", "special"),
    ("", "general"),
])
def test_infer_election_type(stage, expected):
    assert mappers.infer_election_type(stage) == expected


# ---------------------------------------------------------------------------
# infer_jurisdiction_level
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("office,expected", [
    ("U.S. House", "national"),
    ("President", "national"),
    ("Governor", "state"),
    ("State Senate", "state"),
    ("County Commissioner", "state"),
    ("City Council", "local"),
])
def test_infer_jurisdiction_level(office, expected):
    assert mappers.infer_jurisdiction_level(office) == expected


# ---------------------------------------------------------------------------
# infer_geography_scope
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("office,district,expected", [
    ("U.S. House", "1st Congressional", "federal"),
    ("Governor", "", "statewide"),
    ("State Senate", "Norfolk & Plymouth", "district"),
    ("State Representative", "statewide", "statewide"),
])
def test_infer_geography_scope(office, district, expected):
    assert mappers.infer_geography_scope(office, district) == expected


# ---------------------------------------------------------------------------
# parse_ocpf_date
# ---------------------------------------------------------------------------

def test_parse_ocpf_date_valid():
    assert mappers.parse_ocpf_date("11/5/2024") == date(2024, 11, 5)


def test_parse_ocpf_date_empty():
    assert mappers.parse_ocpf_date("") is None


def test_parse_ocpf_date_invalid():
    assert mappers.parse_ocpf_date("not-a-date") is None


# ---------------------------------------------------------------------------
# build_canonical_key
# ---------------------------------------------------------------------------

def test_build_canonical_key():
    key = mappers.build_canonical_key("ma_sos_165323", "U.S. House", "1st Congressional")
    assert key == "ma_sos:ma_sos_165323:u.s. house:1st congressional"


def test_build_canonical_key_no_district():
    key = mappers.build_canonical_key("ma_sos_165300", "President", "")
    assert key == "ma_sos:ma_sos_165300:president:statewide"


# ---------------------------------------------------------------------------
# map_election
# ---------------------------------------------------------------------------

def test_map_election_general():
    row = {"election_id": 165300, "office": "President", "district": "Statewide", "stage": "General", "year": 2024}
    schedule = {"primaryElectionDate": "9/3/2024", "generalElectionDate": "11/5/2024"}
    mapped = mappers.map_election(row, schedule)

    assert mapped["source_id"] == "ma_sos_165300"
    assert mapped["state"] == "MA"
    assert mapped["election_type"] == "general"
    assert mapped["election_date"] == date(2024, 11, 5)
    assert mapped["source_metadata"]["electionstats_id"] == 165300
    assert mapped["source_metadata"]["stage"] == "General"


def test_map_election_primary():
    row = {"election_id": 160657, "office": "Governor", "district": "", "stage": "Democratic", "year": 2024}
    schedule = {"primaryElectionDate": "9/3/2024", "generalElectionDate": "11/5/2024"}
    mapped = mappers.map_election(row, schedule)

    assert mapped["election_type"] == "primary"
    assert mapped["election_date"] == date(2024, 9, 3)


def test_map_election_no_schedule():
    row = {"election_id": 165300, "office": "President", "district": "", "stage": "General", "year": 2024}
    mapped = mappers.map_election(row, {})
    assert mapped["election_date"] is None


# ---------------------------------------------------------------------------
# map_race
# ---------------------------------------------------------------------------

def test_map_race_candidate():
    from elections.models import Election, Race
    mock_election = MagicMock(spec=Election)
    mock_election.source_id = "ma_sos_165323"
    mock_election.status = Election.Status.RESULTS_PENDING
    mock_election.source_metadata = {"electionstats_id": 165323}

    election_row = {"election_id": 165323, "office": "U.S. House", "district": "1st Congressional", "stage": "General"}
    result = mappers.map_race(mock_election, election_row)

    assert result["canonical_key"] == "ma_sos:ma_sos_165323:u.s. house:1st congressional"
    assert result["race_type"] == Race.RaceType.CANDIDATE
    assert result["geography_scope"] == "federal"
    assert result["source"] == Race.Source.MA_SOS


def test_map_race_includes_canonical_key():
    from elections.models import Election
    mock_election = MagicMock(spec=Election)
    mock_election.source_id = "ma_sos_165300"
    mock_election.status = Election.Status.UPCOMING
    mock_election.source_metadata = {"electionstats_id": 165300}

    row = {"election_id": 165300, "office": "President", "district": "", "stage": "General"}
    result = mappers.map_race(mock_election, row)
    assert "canonical_key" in result


# ---------------------------------------------------------------------------
# map_candidate
# ---------------------------------------------------------------------------

def test_map_candidate():
    row = {"name": "Richard E. Neal", "party": "Democratic", "col_index": 3}
    result = mappers.map_candidate(row)
    assert result["party"] == "Democratic"
    assert result["incumbent"] is False
    assert result["source_metadata"]["csv_column_index"] == 3


# ---------------------------------------------------------------------------
# map_ballot_question
# ---------------------------------------------------------------------------

def test_map_ballot_question():
    from elections.models import Election, Race
    mock_election = MagicMock(spec=Election)
    mock_election.status = Election.Status.RESULTS_PENDING

    metadata = {
        "bq_id": 11620,
        "question_number": "1",
        "question": "Do you approve?",
        "question_alias": "A - Audit The Legislature",
        "summary": "Short summary",
        "is_initiative_petition": True,
        "is_referendum": False,
        "is_local": False,
        "is_county": False,
    }
    result = mappers.map_ballot_question(metadata, mock_election)

    assert result["canonical_key"] == "ma_sos:bq_11620"
    assert result["race_type"] == Race.RaceType.MEASURE
    assert result["vote_method"] == Race.VoteMethod.YES_NO
    assert result["office_title"] == "Ballot Question 1"
    assert result["geography_scope"] == "statewide"
    assert result["source_metadata"]["electionstats_bq_id"] == 11620
    assert result["source_metadata"]["is_initiative_petition"] is True


def test_map_ballot_question_local():
    from elections.models import Election, Race
    mock_election = MagicMock(spec=Election)
    mock_election.status = Election.Status.UPCOMING

    metadata = {
        "bq_id": 99999,
        "question_number": "A",
        "question": "Local question",
        "question_alias": "",
        "summary": "",
        "is_initiative_petition": False,
        "is_referendum": False,
        "is_local": True,
        "is_county": False,
    }
    result = mappers.map_ballot_question(metadata, mock_election)
    assert result["geography_scope"] == "district"
    assert result["certification_status"] == Race.CertificationStatus.UPCOMING
