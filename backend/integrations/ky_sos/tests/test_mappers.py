import datetime

from elections.models import Candidate, Election, Race

from integrations.ky_sos.mappers import (
    IN_SCOPE_OFFICE_IDS,
    ky_general_election_date,
    map_candidate,
    map_election,
    map_race,
)


def test_in_scope_office_ids_are_federal_and_state_legislative_only():
    assert IN_SCOPE_OFFICE_IDS == {3, 4, 11, 12}


def test_ky_general_election_date_2026():
    # Ky. Const. §148 / KRS 118.025(4): first Tuesday after first Monday in
    # November. Confirmed against docs/state-research/KY/2026_Kentucky_Election_Calendar.md
    # ("GENERAL ELECTION DAY: Tuesday, November 3, 2026").
    assert ky_general_election_date(2026) == datetime.date(2026, 11, 3)


def test_map_election_general_election():
    result = map_election("2026 General Election")
    assert result["source_id"] == "ky_sos_2026_general"
    assert result["name"] == "2026 Kentucky General Election"
    assert result["election_date"] == datetime.date(2026, 11, 3)
    assert result["election_type"] == "general"
    assert result["jurisdiction_level"] == Election.JurisdictionLevel.STATE
    assert result["state"] == "KY"


def test_map_race_statewide_office_no_district():
    result = map_race("US Senator", "")
    assert result["office_title"] == "US Senator"
    assert result["geography_scope"] == "statewide"
    assert result["jurisdiction"] == "Kentucky"
    assert result["race_type"] == Race.RaceType.CANDIDATE
    assert result["source"] == Race.Source.KY_SOS
    assert result["ocd_division_id"] == ""


def test_map_race_district_office_includes_district_in_title():
    result = map_race("US Representative", "1st")
    assert result["office_title"] == "US Representative District 1st"
    assert result["geography_scope"] == "district"
    assert result["jurisdiction"] == "Kentucky District 1st"


def test_map_candidate_active_row():
    row = {
        "name": "Andy Barr", "office": "US Senator", "district": "",
        "party": "Republican Party", "date_filed": "11/7/2025",
    }
    name, party, fields = map_candidate(row, Candidate.CandidateStatus.RUNNING)
    assert name == "Andy Barr"
    assert party == "Republican Party"
    assert fields["candidate_status"] == Candidate.CandidateStatus.RUNNING
    assert fields["source_metadata"]["ky_sos_date_filed"] == "11/7/2025"


def test_map_candidate_withdrawn_row_has_withdrawn_status():
    row = {
        "name": "Alisha Dawn Chaffin", "office": "State Representative",
        "district": "88th", "party": "Democratic Party", "date_filed": "",
    }
    name, party, fields = map_candidate(row, Candidate.CandidateStatus.WITHDRAWN)
    assert fields["candidate_status"] == Candidate.CandidateStatus.WITHDRAWN
