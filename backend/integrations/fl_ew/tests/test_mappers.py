"""
Unit tests for fl_ew mappers. No DB required.
"""
from datetime import date
from unittest.mock import MagicMock

import pytest

from integrations.fl_ew.mappers import (
    build_candidate_name,
    build_race_groups,
    infer_election_status,
    infer_election_type,
    map_candidate,
    map_election,
    map_race,
    normalize,
)
from integrations.fl_ew.parsers import ElectionRow


def _make_row(
    race_name="State Senator, District 14",
    party_code="REP",
    party_name="Republican Party",
    race_code="STS",
    juris1_num="014",
    juris2_num="",
    county_code="HIL",
    county_name="Hillsborough",
    can_name_last="Tomkow",
    can_name_first="Josie",
    can_name_middle="",
    can_votes=39836,
    precincts=152,
    precincts_reporting=152,
    election_date=None,
):
    return ElectionRow(
        election_date=election_date or date(2026, 3, 24),
        party_code=party_code,
        party_name=party_name,
        race_code=race_code,
        race_name=race_name,
        county_code=county_code,
        county_name=county_name,
        juris1_num=juris1_num,
        juris2_num=juris2_num,
        precincts=precincts,
        precincts_reporting=precincts_reporting,
        can_name_last=can_name_last,
        can_name_first=can_name_first,
        can_name_middle=can_name_middle,
        can_votes=can_votes,
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def test_normalize():
    assert normalize("  State Senator  ") == "state senator"
    assert normalize("State  Senator") == "state senator"
    assert normalize(None) == ""


def test_build_candidate_name_no_middle():
    row = _make_row(can_name_first="Josie", can_name_middle="", can_name_last="Tomkow")
    assert build_candidate_name(row) == "Josie Tomkow"


def test_build_candidate_name_with_middle():
    row = _make_row(can_name_first="Edwin", can_name_middle="S.", can_name_last="Perez")
    assert build_candidate_name(row) == "Edwin S. Perez"


def test_build_candidate_name_last_only():
    row = _make_row(can_name_first="", can_name_middle="", can_name_last="Yes")
    assert build_candidate_name(row) == "Yes"


# ---------------------------------------------------------------------------
# infer_election_type
# ---------------------------------------------------------------------------

def test_infer_election_type_primary():
    assert infer_election_type(date(2026, 8, 18)) == "primary"


def test_infer_election_type_general():
    assert infer_election_type(date(2026, 11, 3)) == "general"


def test_infer_election_type_special():
    assert infer_election_type(date(2026, 3, 24)) == "special"
    assert infer_election_type(date(2026, 4, 14)) == "special"


# ---------------------------------------------------------------------------
# infer_election_status
# ---------------------------------------------------------------------------

def test_infer_status_upcoming():
    from unittest.mock import patch
    with patch("integrations.fl_ew.mappers.timezone") as mock_tz:
        mock_tz.localdate.return_value = date(2026, 1, 1)
        assert infer_election_status(date(2026, 8, 18)) == "upcoming"


def test_infer_status_active():
    from unittest.mock import patch
    with patch("integrations.fl_ew.mappers.timezone") as mock_tz:
        mock_tz.localdate.return_value = date(2026, 8, 18)
        assert infer_election_status(date(2026, 8, 18)) == "active"


def test_infer_status_results_pending():
    from unittest.mock import patch
    with patch("integrations.fl_ew.mappers.timezone") as mock_tz:
        mock_tz.localdate.return_value = date(2026, 8, 19)
        assert infer_election_status(date(2026, 8, 18)) == "results_pending"


# ---------------------------------------------------------------------------
# map_election
# ---------------------------------------------------------------------------

def test_map_election_primary():
    row = _make_row(election_date=date(2026, 8, 18))
    result = map_election("20260818", row.election_date)

    assert result["source_id"] == "fl_ew:20260818"
    assert result["state"] == "FL"
    assert result["election_date"] == date(2026, 8, 18)
    assert result["election_type"] == "primary"
    assert result["jurisdiction_level"] == "state"
    assert result["source_metadata"]["fl_ew_slug"] == "20260818"


def test_map_election_general():
    result = map_election("20261103", date(2026, 11, 3))
    assert result["election_type"] == "general"
    assert "November" in result["name"] or "2026" in result["name"]


def test_map_election_special():
    result = map_election("20260324", date(2026, 3, 24))
    assert result["election_type"] == "special"


# ---------------------------------------------------------------------------
# build_race_groups
# ---------------------------------------------------------------------------

def test_build_race_groups_general_merges_parties():
    """In a general election, both REP and DEM candidates for same race → one group."""
    rows = [
        _make_row(party_code="REP", can_name_last="Tomkow"),
        _make_row(party_code="DEM", can_name_last="Nathan"),
    ]
    groups = build_race_groups(rows, is_primary=False)
    assert len(groups) == 1
    assert len(groups[0]["rows"]) == 2


def test_build_race_groups_primary_splits_by_party():
    """In a primary, REP and DEM rows for same race_name → two groups."""
    rows = [
        _make_row(race_name="Governor", party_code="REP", juris1_num="000"),
        _make_row(race_name="Governor", party_code="DEM", juris1_num="000"),
    ]
    groups = build_race_groups(rows, is_primary=True)
    assert len(groups) == 2
    party_codes = {g["party_code"] for g in groups}
    assert party_codes == {"REP", "DEM"}


def test_build_race_groups_different_districts():
    """Different juris1_num → always separate groups regardless of primary flag."""
    rows = [
        _make_row(race_name="State Senator", juris1_num="014", party_code="REP"),
        _make_row(race_name="State Senator", juris1_num="016", party_code="REP"),
    ]
    groups = build_race_groups(rows, is_primary=False)
    assert len(groups) == 2


# ---------------------------------------------------------------------------
# map_race
# ---------------------------------------------------------------------------

def _make_election_obj(status="upcoming", election_type="special"):
    e = MagicMock()
    e.status = status
    e.election_type = election_type
    e.source_id = "fl_ew:20260324"
    e.canonical_key = "fl:special:2026-03-24:state"
    return e


def test_map_race_basic():
    election = _make_election_obj()
    group = {
        "race_name": "State Senator, District 14",
        "race_code": "STS",
        "juris1_num": "014",
        "juris2_num": "",
        "party_code": "",
        "party_name": "",
        "rows": [_make_row()],
    }
    result = map_race(election, group)

    assert result["race_type"] == "candidate"
    assert result["office_title"] == "State Senator, District 14"
    assert result["source_metadata"]["fl_ew_race_code"] == "STS"
    assert result["source_metadata"]["fl_ew_juris1_num"] == "014"
    assert result["vote_method"] == "single_choice"
    assert result["max_selections"] == 1


def test_map_race_certification_upcoming():
    election = _make_election_obj(status="upcoming")
    group = {
        "race_name": "Governor",
        "race_code": "GOV",
        "juris1_num": "000",
        "juris2_num": "",
        "party_code": "REP",
        "party_name": "Republican Party",
        "rows": [],
    }
    result = map_race(election, group)
    assert result["certification_status"] == "upcoming"


def test_map_race_certification_active():
    election = _make_election_obj(status="active")
    group = {
        "race_name": "Governor",
        "race_code": "GOV",
        "juris1_num": "000",
        "juris2_num": "",
        "party_code": "REP",
        "party_name": "Republican Party",
        "rows": [],
    }
    result = map_race(election, group)
    assert result["certification_status"] == "upcoming"


def test_map_race_certification_results_pending():
    election = _make_election_obj(status="results_pending")
    group = {
        "race_name": "Governor",
        "race_code": "GOV",
        "juris1_num": "000",
        "juris2_num": "",
        "party_code": "",
        "party_name": "",
        "rows": [],
    }
    result = map_race(election, group)
    assert result["certification_status"] == "results_pending"


# ---------------------------------------------------------------------------
# map_candidate
# ---------------------------------------------------------------------------

def test_map_candidate_basic():
    row = _make_row(
        can_name_first="Josie",
        can_name_middle="",
        can_name_last="Tomkow",
        party_code="REP",
        party_name="Republican Party",
    )
    name, party, fields = map_candidate(row)

    assert name == "Josie Tomkow"
    assert party == "Republican Party"
    assert fields["incumbent"] is False
    assert fields["source_metadata"]["fl_ew_party_code"] == "REP"


def test_map_candidate_uses_party_name_over_code():
    row = _make_row(party_code="REP", party_name="Republican Party")
    _, party, _ = map_candidate(row)
    assert party == "Republican Party"


def test_map_candidate_falls_back_to_party_code():
    row = _make_row(party_code="NPA", party_name="")
    _, party, _ = map_candidate(row)
    assert party == "NPA"
