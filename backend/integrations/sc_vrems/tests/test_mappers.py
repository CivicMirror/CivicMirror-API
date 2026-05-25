"""
Tests for SC VREMS mappers.
"""
from datetime import date

import pytest

from elections.models import Candidate, Election, Race
from integrations.sc_vrems.mappers import (
    build_canonical_key,
    build_race_groups,
    is_filing_open,
    is_primary_election,
    is_referendum,
    map_candidate,
    map_candidate_status,
    map_election,
    map_jurisdiction_level,
    normalize,
)

# ------------------------------------------------------------------
# is_referendum
# ------------------------------------------------------------------

def test_is_referendum_when_null_filing():
    assert is_referendum({"filingPeriodBeginDate": None}) is True


def test_not_referendum_when_has_filing():
    assert is_referendum({"filingPeriodBeginDate": "2026-03-16T12:00:00"}) is False


# ------------------------------------------------------------------
# is_filing_open
# ------------------------------------------------------------------

def test_filing_open_for_past_date_no_election_date():
    # Filing started in the past; no electionDate field → still considered open.
    assert is_filing_open({"filingPeriodBeginDate": "2020-01-01T00:00:00"}) is True


def test_filing_closed_for_past_election():
    # Filing started in the past AND election date has already passed → skip.
    assert is_filing_open({
        "filingPeriodBeginDate": "2024-03-01T00:00:00",
        "electionDate": "2024-11-05T00:00:00",
    }) is False


def test_filing_open_for_upcoming_election():
    # Filing started in the past, election date is in the future → sync needed.
    assert is_filing_open({
        "filingPeriodBeginDate": "2026-03-01T00:00:00",
        "electionDate": "2026-11-03T00:00:00",
    }) is True


def test_filing_closed_for_future_date():
    assert is_filing_open({"filingPeriodBeginDate": "2099-01-01T00:00:00"}) is False


def test_filing_open_when_null():
    assert is_filing_open({"filingPeriodBeginDate": None}) is True


# ------------------------------------------------------------------
# jurisdiction level
# ------------------------------------------------------------------

def test_jurisdiction_local_type():
    assert map_jurisdiction_level("Local", "City of Columbia Election") == Election.JurisdictionLevel.LOCAL


def test_jurisdiction_state_general():
    assert map_jurisdiction_level("General", "Statewide General") == Election.JurisdictionLevel.STATE


def test_jurisdiction_federal_special():
    assert map_jurisdiction_level("Special", "U.S. House District 5 Special Election") == Election.JurisdictionLevel.NATIONAL


def test_jurisdiction_state_special():
    assert map_jurisdiction_level("Special", "SC House District 98 Special Election") == Election.JurisdictionLevel.STATE


# ------------------------------------------------------------------
# map_election
# ------------------------------------------------------------------

def test_map_election_source_id():
    vrems = {
        "electionId": "22598",
        "electionName": "Statewide Primary",
        "displayName": "6/9/2026 Statewide Primary",
        "electionDate": "2026-06-09T00:00:00",
        "filingPeriodBeginDate": "2026-03-16T12:00:00",
        "electionType": "General",
    }
    mapped = map_election(vrems)
    assert mapped["source_id"] == "vrems_sc_22598"
    assert mapped["state"] == "SC"
    assert mapped["election_date"] == date(2026, 6, 9)


def test_map_election_local_jurisdiction():
    vrems = {
        "electionId": "22700",
        "electionName": "City of Columbia Municipal Election",
        "displayName": "11/3/2026 City of Columbia Municipal Election",
        "electionDate": "2026-11-03T00:00:00",
        "filingPeriodBeginDate": "2026-07-01T00:00:00",
        "electionType": "Local",
    }
    mapped = map_election(vrems)
    assert mapped["jurisdiction_level"] == Election.JurisdictionLevel.LOCAL


# ------------------------------------------------------------------
# is_primary_election
# ------------------------------------------------------------------

def test_primary_detection():
    assert is_primary_election("Statewide Primary") is True
    assert is_primary_election("Statewide General") is False
    assert is_primary_election("HD98 Special Election") is False


# ------------------------------------------------------------------
# build_race_groups
# ------------------------------------------------------------------

_GOVERNOR_R = {
    "office": "Governor", "filing_location": "State",
    "associated_counties": "", "party": "Republican",
    "name_on_ballot": "Candidate A", "status": "Active",
    "candidate_id": "1", "candidate_detail_id": "1",
    "candidate_detail_election_id": None, "running_mate": "",
}
_GOVERNOR_D = {
    "office": "Governor", "filing_location": "State",
    "associated_counties": "", "party": "Democratic",
    "name_on_ballot": "Candidate B", "status": "Active",
    "candidate_id": "2", "candidate_detail_id": "2",
    "candidate_detail_election_id": None, "running_mate": "",
}
_MAYOR_R = {
    "office": "Mayor", "filing_location": "Charleston",
    "associated_counties": "Charleston", "party": "Republican",
    "name_on_ballot": "Candidate C", "status": "Active",
    "candidate_id": "3", "candidate_detail_id": "3",
    "candidate_detail_election_id": None, "running_mate": "",
}


def test_primary_splits_by_party():
    election = {"electionName": "Statewide Primary"}
    groups = build_race_groups(election, [_GOVERNOR_R, _GOVERNOR_D])
    assert len(groups) == 2
    parties = {g["party_group"] for g in groups}
    assert parties == {"Republican", "Democratic"}


def test_general_merges_parties():
    election = {"electionName": "Statewide General"}
    groups = build_race_groups(election, [_GOVERNOR_R, _GOVERNOR_D])
    assert len(groups) == 1
    assert groups[0]["party_group"] == ""
    assert len(groups[0]["candidates"]) == 2


def test_different_offices_are_separate_races():
    election = {"electionName": "Statewide Primary"}
    groups = build_race_groups(election, [_GOVERNOR_R, _MAYOR_R])
    assert len(groups) == 2


# ------------------------------------------------------------------
# build_canonical_key
# ------------------------------------------------------------------

def test_canonical_key_format():
    key = build_canonical_key("vrems_sc_22598", "Governor", "State", "", "Republican")
    assert key.startswith("sc_vrems:vrems_sc_22598:governor:")
    assert "republican" in key


def test_canonical_key_empty_party_normalized():
    key = build_canonical_key("vrems_sc_22598", "Governor", "State", "", "")
    assert key.endswith(":nonpartisan")


# ------------------------------------------------------------------
# candidate status mapping
# ------------------------------------------------------------------

def test_candidate_status_active():
    assert map_candidate_status("Active") == Candidate.CandidateStatus.RUNNING


def test_candidate_status_withdrew():
    assert map_candidate_status("Withdrew Before Primary") == Candidate.CandidateStatus.WITHDRAWN


def test_candidate_status_disqualified():
    assert map_candidate_status("Disqualified before Primary") == Candidate.CandidateStatus.DISQUALIFIED


def test_candidate_status_elected_stays_running():
    assert map_candidate_status("Elected") == Candidate.CandidateStatus.RUNNING


def test_candidate_status_defeated_stays_running():
    assert map_candidate_status("Defeated In Primary") == Candidate.CandidateStatus.RUNNING


# ------------------------------------------------------------------
# map_candidate preserves vrems_status in source_metadata
# ------------------------------------------------------------------

def test_map_candidate_preserves_vrems_status():
    row = {
        "party": "Republican",
        "status": "Elected",
        "candidate_id": "12345",
        "candidate_detail_id": "999",
        "running_mate": "",
    }
    mapped = map_candidate(row)
    assert mapped["source_metadata"]["vrems_status"] == "Elected"
    assert mapped["candidate_status"] == Candidate.CandidateStatus.RUNNING
