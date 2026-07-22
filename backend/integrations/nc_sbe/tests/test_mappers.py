"""
Unit tests for NC SBE Stage 1 candidate-filing mappers.
"""
from __future__ import annotations

import datetime

import pytest

# ---------------------------------------------------------------------------
# is_in_scope_contest
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("contest_name", [
    "US SENATE",
    "US HOUSE OF REPRESENTATIVES DISTRICT 04",
    "NC STATE SENATE DISTRICT 01",
    "NC HOUSE OF REPRESENTATIVES DISTRICT 001",
    "GOVERNOR",
    "LIEUTENANT GOVERNOR",
    "ATTORNEY GENERAL",
])
def test_is_in_scope_contest_true_for_federal_and_state(contest_name):
    from integrations.nc_sbe.mappers import is_in_scope_contest
    assert is_in_scope_contest(contest_name) is True


@pytest.mark.parametrize("contest_name", [
    "NC SUPREME COURT ASSOCIATE JUSTICE SEAT 01",
    "NC COURT OF APPEALS JUDGE SEAT 01",
    "NC DISTRICT COURT JUDGE DISTRICT 01 SEAT 01",
    "DISTRICT ATTORNEY DISTRICT 01",
    "COUNTY COMMISSIONER DISTRICT 3",
    "SOIL AND WATER CONSERVATION DISTRICT SUPERVISOR",
    "MAYOR",
])
def test_is_in_scope_contest_false_for_judicial_and_local(contest_name):
    from integrations.nc_sbe.mappers import is_in_scope_contest
    assert is_in_scope_contest(contest_name) is False


# ---------------------------------------------------------------------------
# parse_candidate_filing_date
# ---------------------------------------------------------------------------

def test_parse_candidate_filing_date_parses_mmddyyyy():
    from integrations.nc_sbe.mappers import parse_candidate_filing_date
    assert parse_candidate_filing_date("11/03/2026") == datetime.date(2026, 11, 3)


def test_parse_candidate_filing_date_returns_none_for_blank():
    from integrations.nc_sbe.mappers import parse_candidate_filing_date
    assert parse_candidate_filing_date("") is None


# ---------------------------------------------------------------------------
# contest_variant_key
# ---------------------------------------------------------------------------

def test_contest_variant_key_distinguishes_party_primaries():
    from integrations.nc_sbe.mappers import contest_variant_key
    rep = contest_variant_key("NC STATE SENATE DISTRICT 01", "REP")
    dem = contest_variant_key("NC STATE SENATE DISTRICT 01", "DEM")
    assert rep != dem


def test_contest_variant_key_general_election_has_no_party():
    from integrations.nc_sbe.mappers import contest_variant_key
    general = contest_variant_key("NC STATE SENATE DISTRICT 01", "")
    primary = contest_variant_key("NC STATE SENATE DISTRICT 01", "REP")
    assert general != primary


def test_contest_variant_key_same_inputs_are_stable():
    from integrations.nc_sbe.mappers import contest_variant_key
    assert (
        contest_variant_key("US SENATE", "REP")
        == contest_variant_key("US SENATE", "REP")
    )


# ---------------------------------------------------------------------------
# geography_scope_for_contest
# ---------------------------------------------------------------------------

def test_geography_scope_district_for_districted_office():
    from integrations.nc_sbe.mappers import geography_scope_for_contest
    assert geography_scope_for_contest("NC STATE SENATE DISTRICT 01") == "district"


def test_geography_scope_statewide_for_no_district():
    from integrations.nc_sbe.mappers import geography_scope_for_contest
    assert geography_scope_for_contest("US SENATE") == "statewide"


# ---------------------------------------------------------------------------
# map_race_identity
# ---------------------------------------------------------------------------

def test_map_race_identity_returns_identity_and_fields():
    from elections.models import Race
    from integrations.nc_sbe.mappers import map_race_identity

    identity, fields = map_race_identity(
        contest_name="NC STATE SENATE DISTRICT 01",
        party_contest="REP",
        is_partisan=True,
        vote_for=1,
        term="2",
    )

    assert identity["office_title"] == "NC STATE SENATE DISTRICT 01"
    assert identity["race_type"] == Race.RaceType.CANDIDATE
    assert identity["contest_variant"]
    assert fields["source"] == Race.Source.NC_SBE
    assert fields["geography_scope"] == "district"
    assert fields["max_selections"] == 1
    assert fields["source_metadata"]["party_contest"] == "REP"


def test_map_race_identity_multi_seat_vote_for():
    from elections.models import Race
    from integrations.nc_sbe.mappers import map_race_identity

    _, fields = map_race_identity(
        contest_name="NC COURT OF APPEALS JUDGE SEAT 01",
        party_contest="",
        is_partisan=True,
        vote_for=2,
        term="8",
    )
    assert fields["vote_method"] == Race.VoteMethod.MULTI_SEAT
    assert fields["max_selections"] == 2


# ---------------------------------------------------------------------------
# map_candidate
# ---------------------------------------------------------------------------

def test_map_candidate_sets_running_status_and_metadata():
    from elections.models import Candidate
    from integrations.nc_sbe.mappers import map_candidate

    fields = map_candidate({"candidacy_dt": "12/11/2025"})
    assert fields["candidate_status"] == Candidate.CandidateStatus.RUNNING
    assert fields["source_metadata"]["candidacy_date"] == "12/11/2025"


# ---------------------------------------------------------------------------
# group_candidate_rows / dedupe_candidate_rows
# ---------------------------------------------------------------------------

_ROWS = [
    {
        "election_dt": "03/03/2026", "county_name": "BERTIE",
        "contest_name": "NC STATE SENATE DISTRICT 01", "name_on_ballot": "Dave Forsythe",
        "party_contest": "REP", "party_candidate": "REP", "has_primary": "TRUE",
        "is_partisan": "TRUE", "vote_for": "1", "term": "2", "candidacy_dt": "12/11/2025",
    },
    {
        "election_dt": "03/03/2026", "county_name": "CAMDEN",
        "contest_name": "NC STATE SENATE DISTRICT 01", "name_on_ballot": "Dave Forsythe",
        "party_contest": "REP", "party_candidate": "REP", "has_primary": "TRUE",
        "is_partisan": "TRUE", "vote_for": "1", "term": "2", "candidacy_dt": "12/11/2025",
    },
    {
        "election_dt": "11/03/2026", "county_name": "BERTIE",
        "contest_name": "NC STATE SENATE DISTRICT 01", "name_on_ballot": "Melissa Zehner",
        "party_contest": "", "party_candidate": "DEM", "has_primary": "FALSE",
        "is_partisan": "TRUE", "vote_for": "1", "term": "2", "candidacy_dt": "12/19/2025",
    },
]


def test_group_candidate_rows_splits_primary_from_general():
    from integrations.nc_sbe.mappers import group_candidate_rows

    groups = group_candidate_rows(_ROWS)

    assert ("03/03/2026", "NC STATE SENATE DISTRICT 01", "REP") in groups
    assert ("11/03/2026", "NC STATE SENATE DISTRICT 01", "") in groups
    assert len(groups[("03/03/2026", "NC STATE SENATE DISTRICT 01", "REP")]) == 2


def test_dedupe_candidate_rows_collapses_repeated_counties():
    from integrations.nc_sbe.mappers import dedupe_candidate_rows, group_candidate_rows

    groups = group_candidate_rows(_ROWS)
    primary_group = groups[("03/03/2026", "NC STATE SENATE DISTRICT 01", "REP")]

    deduped = dedupe_candidate_rows(primary_group)

    assert len(deduped) == 1
    assert deduped[0]["name_on_ballot"] == "Dave Forsythe"
