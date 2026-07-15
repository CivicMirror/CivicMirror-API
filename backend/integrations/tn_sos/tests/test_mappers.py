from datetime import date
from types import SimpleNamespace

from elections.models import Candidate, Election, Race
from integrations.tn_sos.mappers import (
    is_in_scope_office,
    map_candidate,
    map_election,
    map_race,
    normalized_office_title,
)
from integrations.tn_sos.parsers import TnCandidateRecord, TnElectionRow


def test_party_executive_committee_offices_are_out_of_scope():
    assert not is_in_scope_office("State Executive Committeeman District 1")
    assert not is_in_scope_office("State Executive Committeewoman District 1")
    assert is_in_scope_office("United States Senate")
    assert is_in_scope_office("Governor")
    assert is_in_scope_office("Tennessee House of Representatives District 52")


def test_map_statewide_election_uses_tn_identity():
    row = TnElectionRow(
        name="Thursday, August 6, 2026 - Primary and General Election",
        election_date=date(2026, 8, 6),
        county="",
        jurisdiction="Tennessee",
        source_url="https://sos.tn.gov/elections/calendar",
        is_statewide=True,
    )

    mapped = map_election(row)

    assert mapped["source_id"] == "tn_sos:2026-08-06:statewide"
    assert mapped["state"] == "TN"
    assert mapped["election_type"] == Election.ElectionType.PRIMARY
    assert mapped["jurisdiction_level"] == Election.JurisdictionLevel.STATE


def test_normalized_office_title_keeps_district():
    assert normalized_office_title("Tennessee House", "District 52") == "tennessee house district 52"


def test_map_race_uses_tn_source():
    election = SimpleNamespace(status=Election.Status.RESULTS_PENDING, source_metadata={})
    record = TnCandidateRecord(
        office="United States Senate",
        district="",
        candidate_name="Jane Candidate",
        party="Republican",
        status="Qualified",
        source_url="https://example.test/USSenate_2026.xlsx",
        source_row=2,
    )

    mapped = map_race(election, record)

    assert mapped["source"] == Race.Source.TN_SOS
    assert mapped["office_title"] == "United States Senate"
    assert mapped["geography_scope"] == "federal"
    assert mapped["race_type"] == Race.RaceType.CANDIDATE


def test_map_candidate_preserves_workbook_metadata():
    record = TnCandidateRecord(
        office="United States Senate",
        district="",
        candidate_name="Jane Candidate",
        party="Republican",
        status="Qualified",
        source_url="https://example.test/USSenate_2026.xlsx",
        source_row=2,
    )

    mapped = map_candidate(record)

    assert mapped["party"] == "Republican"
    assert mapped["candidate_status"] == Candidate.CandidateStatus.RUNNING
    assert mapped["source_metadata"]["tn_source_row"] == 2
