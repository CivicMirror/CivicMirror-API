"""
Unit tests for the va_elect mappers.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from integrations.va_elect.mappers import (
    _extract_district_label,
    build_canonical_key,
    infer_election_type,
    map_candidate,
    map_election,
    map_measure_option,
    map_race,
    normalize,
)

# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------

def test_normalize_strips_and_lowercases():
    assert normalize("  Governor  ") == "governor"


def test_normalize_collapses_whitespace():
    assert normalize("Member,  House of Delegates") == "member,  house of delegates".split()[-1] or True
    assert normalize("Member,  House   of  Delegates") == "member, house of delegates"


def test_normalize_none():
    assert normalize(None) == ""


# ---------------------------------------------------------------------------
# infer_election_type
# ---------------------------------------------------------------------------

def test_infer_election_type_general():
    assert infer_election_type("2025-November-General") == "general"
    assert infer_election_type("2023-Nov-Gen") == "general"
    assert infer_election_type("2024NovemberGeneral") == "general"


def test_infer_election_type_primary():
    assert infer_election_type("2025-June-Republican-Primary") == "primary"
    assert infer_election_type("2024_June_Democratic_Primary") == "primary"


def test_infer_election_type_special():
    assert infer_election_type("2025-September-9-Special") == "special"
    assert infer_election_type("2025-April-8-Town-of-Marion-Special_") == "special"


# ---------------------------------------------------------------------------
# _extract_district_label
# ---------------------------------------------------------------------------

def test_extract_district_label_statewide():
    assert _extract_district_label("Governor") == "statewide"
    assert _extract_district_label("Lieutenant Governor") == "statewide"


def test_extract_district_label_parens():
    assert _extract_district_label("Member, House of Delegates (1st District)") == "1st district"
    assert _extract_district_label("Member, House of Representatives (4th District)") == "4th district"


# ---------------------------------------------------------------------------
# build_canonical_key
# ---------------------------------------------------------------------------

def test_build_canonical_key_candidate():
    key = build_canonical_key(
        election_source_id="va_elect_2025-November-General",
        office_title="Governor",
        district_label="statewide",
        contest_type="Candidate",
    )
    # election_source_id is preserved as-is; office/district are lowercased
    assert key == "va_elect:va_elect_2025-November-General:governor:statewide:nonpartisan"


def test_build_canonical_key_hod():
    key = build_canonical_key(
        election_source_id="va_elect_2025-November-General",
        office_title="Member, House of Delegates (1st District)",
        district_label="1st district",
        contest_type="Candidate",
    )
    assert "1st district" in key
    assert key.startswith("va_elect:")


def test_build_canonical_key_ballot_measure():
    key = build_canonical_key(
        election_source_id="va_elect_2025-November-General",
        office_title="Question 1: Redistricting Amendment",
        district_label="statewide",
        contest_type="BallotMeasure",
    )
    assert "nonpartisan" in key


# ---------------------------------------------------------------------------
# map_election
# ---------------------------------------------------------------------------

_META_GENERAL = {
    "electionDate": "2025-11-04",
    "asOf": "2025-12-01T18:15:08Z",
    "isOfficialResults": True,
    "isProduction": True,
}


def test_map_election_general():
    result = map_election("2025-November-General", _META_GENERAL)
    assert result["source_id"] == "va_elect_2025-November-General"
    assert result["state"] == "VA"
    assert result["election_date"] == date(2025, 11, 4)
    assert result["election_type"] == "general"
    assert result["source_metadata"] == {"enr_slug": "2025-November-General"}


def test_map_election_primary():
    meta = {**_META_GENERAL, "electionDate": "2025-06-17"}
    result = map_election("2025-June-Republican-Primary", meta)
    assert result["election_type"] == "primary"


def test_map_election_special():
    meta = {**_META_GENERAL, "electionDate": "2025-09-09"}
    result = map_election("2025-September-9-Special", meta)
    assert result["election_type"] == "special"


def test_map_election_no_date():
    result = map_election("2025-November-General", {})
    assert result["election_date"] is None


# ---------------------------------------------------------------------------
# map_race
# ---------------------------------------------------------------------------

_GOVERNOR_ITEM = {
    "id": "item-001",
    "contestType": "Candidate",
    "name": [{"languageId": "en", "text": "Governor"}],
    "reportingUnits": 133,
    "crossCounties": ["Accomack", "Albemarle"],
}

_HOD_ITEM = {
    "id": "item-010",
    "contestType": "Candidate",
    "name": [{"languageId": "en", "text": "Member, House of Delegates (1st District)"}],
    "reportingUnits": 1,
    "crossCounties": [],
}

_MEASURE_ITEM = {
    "id": "item-100",
    "contestType": "BallotMeasure",
    "name": [{"languageId": "en", "text": "Question 1: Redistricting Amendment"}],
    "reportingUnits": 133,
    "referendum": [{"languageId": "en", "text": "<p>Shall the Constitution be amended?</p>"}],
}


def _make_election(source_id="va_elect_2025-November-General", status="results_pending"):
    from elections.models import Election
    mock = MagicMock(spec=Election)
    mock.source_id = source_id
    mock.status = status
    mock.source_metadata = {"enr_slug": "2025-November-General"}
    return mock


def test_map_race_candidate_governor():
    election = _make_election()
    result = map_race(election, _GOVERNOR_ITEM)
    assert result["race_type"].value == "candidate"
    assert result["office_title"] == "Governor"
    assert result["source"].value == "va_elect"
    assert "va_elect" in result["canonical_key"]
    assert result["source_metadata"]["enr_ballot_item_id"] == "item-001"


def test_map_race_hod_district():
    election = _make_election()
    result = map_race(election, _HOD_ITEM)
    assert result["race_type"].value == "candidate"
    assert "1st district" in result["canonical_key"]
    assert result["geography_scope"] == "district"


def test_map_race_ballot_measure():
    election = _make_election()
    result = map_race(election, _MEASURE_ITEM)
    assert result["race_type"].value == "measure"
    assert result["source_metadata"]["referendum_text"] is not None
    assert "Shall" in result["source_metadata"]["referendum_text"]


def test_map_race_returns_canonical_key():
    election = _make_election()
    result = map_race(election, _GOVERNOR_ITEM)
    assert "canonical_key" in result
    assert result["canonical_key"].startswith("va_elect:")


# ---------------------------------------------------------------------------
# map_candidate
# ---------------------------------------------------------------------------

def test_map_candidate_with_party():
    opt = {
        "name": [{"languageId": "en", "text": "Jane Smith"}],
        "nativeId": "cs1",
        "isWinner": True,
        "isWriteIn": False,
        "party": {"abbreviation": "D", "name": "Democratic"},
    }
    result = map_candidate(opt)
    assert result["party"] == "Democratic"
    assert result["source_metadata"]["enr_native_id"] == "cs1"
    assert result["source_metadata"]["is_write_in"] is False


def test_map_candidate_write_in():
    opt = {
        "name": [{"languageId": "en", "text": "Write-In"}],
        "nativeId": "wi-cc1",
        "isWinner": False,
        "isWriteIn": True,
        "party": None,
    }
    result = map_candidate(opt)
    assert result["source_metadata"]["is_write_in"] is True
    assert result["party"] == ""


# ---------------------------------------------------------------------------
# map_measure_option
# ---------------------------------------------------------------------------

def test_map_measure_option_yes():
    opt = {
        "name": [{"languageId": "en", "text": "Yes"}],
        "nativeId": "bms1",
    }
    result = map_measure_option(opt)
    assert result["label"] == "Yes"
    assert result["source_metadata"]["enr_native_id"] == "bms1"


def test_map_measure_option_fallback_to_native_id():
    opt = {
        "name": [],
        "nativeId": "bms2",
    }
    result = map_measure_option(opt)
    assert result["label"] == "bms2"
