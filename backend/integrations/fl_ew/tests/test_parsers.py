"""
Unit tests for the FL EW tab-delimited file parser. No DB, no HTTP.
"""
import pytest

from integrations.fl_ew.parsers import ElectionRow, parse_results_file

# Minimal valid file text — two candidates in one race across one county.
_SAMPLE = (
    "ElectionDate\tPartyCode\tPartyName\tRaceCode\tRaceName\tCountyCode\t"
    "CountyName\tJuris1num\tJuris2num\tPrecincts\tPrecinctsReporting\t"
    "CanNameLast\tCanNameFirst\tCanNameMiddle\tCanVotes\n"
    "03/24/2026\tREP\tRepublican Party\tSTS\tState Senator, District 14\t"
    "HIL\tHillsborough\t014\t \t152\t152\tTomkow\tJosie\t\t39836\n"
    "03/24/2026\tDEM\tDemocratic Party\tSTS\tState Senator, District 14\t"
    "HIL\tHillsborough\t014\t \t152\t152\tNathan\tBrian\t\t40245\n"
)

_MULTI_RACE_SAMPLE = (
    "ElectionDate\tPartyCode\tPartyName\tRaceCode\tRaceName\tCountyCode\t"
    "CountyName\tJuris1num\tJuris2num\tPrecincts\tPrecinctsReporting\t"
    "CanNameLast\tCanNameFirst\tCanNameMiddle\tCanVotes\n"
    "08/18/2026\tREP\tRepublican Party\tGOV\tGovernor\t"
    "ALA\tAlachua\t000\t \t100\t80\tSmith\tAlice\t\t5000\n"
    "08/18/2026\tREP\tRepublican Party\tGOV\tGovernor\t"
    "ALA\tAlachua\t000\t \t100\t80\tJones\tBob\t\t4200\n"
    "08/18/2026\tDEM\tDemocratic Party\tGOV\tGovernor\t"
    "ALA\tAlachua\t000\t \t100\t80\tWilliams\tCarol\t\t6100\n"
)


# ---------------------------------------------------------------------------
# parse_results_file
# ---------------------------------------------------------------------------

def test_parse_returns_election_rows():
    rows = parse_results_file(_SAMPLE)
    assert len(rows) == 2
    assert all(isinstance(r, ElectionRow) for r in rows)


def test_parse_election_date():
    rows = parse_results_file(_SAMPLE)
    from datetime import date
    assert rows[0].election_date == date(2026, 3, 24)


def test_parse_party_fields():
    rows = parse_results_file(_SAMPLE)
    assert rows[0].party_code == "REP"
    assert rows[0].party_name == "Republican Party"
    assert rows[1].party_code == "DEM"


def test_parse_race_fields():
    rows = parse_results_file(_SAMPLE)
    assert rows[0].race_code == "STS"
    assert rows[0].race_name == "State Senator, District 14"


def test_parse_county_fields():
    rows = parse_results_file(_SAMPLE)
    assert rows[0].county_code == "HIL"
    assert rows[0].county_name == "Hillsborough"


def test_parse_juris_fields():
    rows = parse_results_file(_SAMPLE)
    assert rows[0].juris1_num == "014"
    assert rows[0].juris2_num == ""   # stripped whitespace → empty string


def test_parse_precinct_counts():
    rows = parse_results_file(_SAMPLE)
    assert rows[0].precincts == 152
    assert rows[0].precincts_reporting == 152


def test_parse_candidate_name_fields():
    rows = parse_results_file(_SAMPLE)
    assert rows[0].can_name_last == "Tomkow"
    assert rows[0].can_name_first == "Josie"
    assert rows[0].can_name_middle == ""


def test_parse_can_votes():
    rows = parse_results_file(_SAMPLE)
    assert rows[0].can_votes == 39836
    assert rows[1].can_votes == 40245


def test_parse_skips_header_row():
    rows = parse_results_file(_SAMPLE)
    # No row should have election_date=None or race_name="RaceName"
    assert all(r.race_name != "RaceName" for r in rows)


def test_parse_empty_file_returns_empty_list():
    rows = parse_results_file("ElectionDate\tPartyCode\n")
    assert rows == []


def test_parse_multi_race_returns_all_rows():
    rows = parse_results_file(_MULTI_RACE_SAMPLE)
    assert len(rows) == 3


def test_parse_incomplete_results_precincts():
    rows = parse_results_file(_MULTI_RACE_SAMPLE)
    # 80 of 100 precincts reporting
    assert rows[0].precincts == 100
    assert rows[0].precincts_reporting == 80
