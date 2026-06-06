"""
Unit tests for pa_sos JSON/HTML parsers and mappers. No network access.
"""
from __future__ import annotations

import pytest

from integrations.pa_sos.mappers import geography_scope, normalize_contest_name, party_abbrev
from integrations.pa_sos.parsers import parse_candidate_detail, parse_candidate_list

_MOCK_JSON_LIST = """[
  {
    "CandidateID": 161838,
    "CandidateIDNum": "2026C0020",
    "CandidateName": "CHANGE, REP IN GA STG",
    "PartyName": "Republican",
    "CandidateStatusValue": "Approved",
    "CandidateTypeValue": "Petition",
    "OfficeName": "REPRESENTATIVE IN THE GENERAL ASSEMBLY ",
    "DistrictName": "55th Legislative District",
    "ElectionName": "2026 Primary Election",
    "Municipality": "102 MAIN ST",
    "CountyName": "YORK",
    "PrimaryResult": "false",
    "GeneralResult": "false",
    "CFOnlineURL": "www.campaignfinanceonline.beta.pa.gov/Pages/CFAnnualTotals.aspx?Filer=2026C0020"
  }
]"""

_MOCK_DETAIL_HTML = """
<html>
<body>
  <span id="ctl00_ContentPlaceHolder1_tabs_TabPanel1_lblApprovedDate">02/10/2026 13:16:00</span>
  <span id="ctl00_ContentPlaceHolder1_tabs_TabPanel1_lblCandidateType">Petition</span>
  <span id="ctl00_ContentPlaceHolder1_tabs_TabPanel1_lblBallotLottery">28</span>
  <span id="ctl00_ContentPlaceHolder1_tabs_TabPanel1_lblBallotPosition">2</span>
  <span id="ctl00_ContentPlaceHolder1_tabs_TabPanel1_lblCrossFiled">No</span>
  <span id="ctl00_ContentPlaceHolder1_tabs_TabPanel1_lblCounty">YORK</span>
  <span id="ctl00_ContentPlaceHolder1_tabs_TabPanel1_lblMunicipality">102 MAIN ST</span>
  <a id="ctl00_ContentPlaceHolder1_tabs_TabPanel5_hlnkRptCan" href="https://campaignfinanceonline.beta.pa.gov/?Filer=2026C0020">View Totals</a>
</body>
</html>
"""


def test_parse_candidate_list():
    entries = parse_candidate_list(_MOCK_JSON_LIST)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.candidate_id == 161838
    assert entry.candidate_id_num == "2026C0020"
    assert entry.name == "CHANGE, REP IN GA STG"
    assert entry.party == "Republican"
    assert entry.status == "Approved"
    assert entry.type_val == "Petition"
    assert entry.office == "REPRESENTATIVE IN THE GENERAL ASSEMBLY"
    assert entry.district == "55th Legislative District"
    assert entry.election_name == "2026 Primary Election"
    assert entry.municipality == "102 MAIN ST"
    assert entry.county == "YORK"
    assert entry.primary_result is False
    assert entry.general_result is False
    assert "2026C0020" in entry.cf_online_url


def test_parse_candidate_detail():
    detail = parse_candidate_detail(_MOCK_DETAIL_HTML)
    assert detail.approved_date == "02/10/2026 13:16:00"
    assert detail.candidate_type == "Petition"
    assert detail.ballot_lottery == "28"
    assert detail.ballot_position == "2"
    assert detail.cross_filed == "No"
    assert detail.county == "YORK"
    assert detail.municipality == "102 MAIN ST"
    assert "2026C0020" in detail.cf_annual_totals_url


# ---------------------------------------------------------------------------
# Mappers
# ---------------------------------------------------------------------------

def test_party_abbrev():
    assert party_abbrev("Democratic") == "DEM"
    assert party_abbrev("Republican") == "REP"
    assert party_abbrev("Green") == "GRN"
    assert party_abbrev("Libertarian") == "LIB"
    assert party_abbrev("Non-partisan") == "NPA"
    assert party_abbrev("SomethingElse") == "SOM"


def test_normalize_contest_name():
    assert normalize_contest_name("GOVERNOR ", "Statewide") == "Governor"
    assert normalize_contest_name("REPRESENTATIVE IN THE GENERAL ASSEMBLY", "55th Legislative District") == "State House - District 55"
    assert normalize_contest_name("SENATOR IN THE GENERAL ASSEMBLY", "37th Legislative District") == "State Senate - District 37"
    assert normalize_contest_name("LOCAL OFFICE", "District 1") == "LOCAL OFFICE - District 1"


def test_geography_scope():
    assert geography_scope("Governor") == "statewide"
    assert geography_scope("State House - District 55") == "state_legislative_district"
    assert geography_scope("State Senate - District 37") == "state_legislative_district"
