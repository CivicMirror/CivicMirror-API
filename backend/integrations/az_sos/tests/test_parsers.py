"""Unit tests for az_sos HTML parsers. No network access."""
import textwrap
import pytest

from integrations.az_sos.parsers import (
    CandidateDetailData,
    CandidateListEntry,
    parse_candidate_detail,
    parse_candidate_list,
)

_CANDIDATE_LIST_HTML = textwrap.dedent("""\
    <section id="secBL1">
      <h3 class="branch">FEDERAL - LEGISLATIVE</h3>
      <section>
        <h3>U.S. House of Rep. - District 1</h3>
        <ul class="people">
          <li>
            <img class="viewmore" onclick="myPopup.ViewCand(5780);" />
            <div>
              <b>Amish Shah</b>
              <span class="office">U.S. House of Rep. - District 1</span>
              <span class="party">Democratic</span>
            </div>
          </li>
          <li>
            <img class="viewmore" onclick="myPopup.ViewCand(5834);" />
            <div>
              <b>Alex Flores (Write-In)</b>
              <span class="party">Libertarian</span>
            </div>
          </li>
          <li>
            <img class="viewmore" onclick="myPopup.ViewCand(5621);" />
            <div>
              <b>Marlene Gal&#225;n-Woods</b>
              <span class="party">Democratic</span>
            </div>
          </li>
        </ul>
      </section>
    </section>
    <section id="secBL2">
      <h3 class="branch">STATE - EXECUTIVE</h3>
      <section>
        <h3>Governor</h3>
        <ul class="people">
          <li>
            <img class="viewmore" onclick="myPopup.ViewCand(5577);" />
            <div>
              <b>Katie Hobbs</b>
              <span class="party">Democratic</span>
            </div>
          </li>
        </ul>
      </section>
    </section>
    <section id="secBL4">
      <h3 class="branch">COUNTY</h3>
      <section>
        <h3>La Paz Supervisor</h3>
        <ul class="people">
          <li>
            <img class="viewmore" onclick="myPopup.ViewCand(9999);" />
            <div><b>Some Person</b><span class="party">Republican</span></div>
          </li>
        </ul>
      </section>
    </section>
""").encode()

_DETAIL_FULL_HTML = textwrap.dedent("""\
    <article class="person">
      <figure><img src="/custom/Picture/2380" alt="Joseph Chaplik"></figure>
      <h4>Joseph Chaplik</h4>
      <p>
        U.S. House of Rep. - District 1<br />
        Republican<br />
        Traditional Funding
      </p>
      <p>Website:&nbsp;&nbsp;<a href="https://www.josephchaplik.com/" target="_blank">www.josephchaplik.com/</a></p>
      <p>Donations:&nbsp;&nbsp;<a href="https://donate.example.com" target="_blank">donate.example.com</a></p>
      <p class="social">
        <a href="https://www.facebook.com/josephchaplik" target="_blank"><i class="fa-brands fa-facebook-f"></i></a>
        <a href="https://www.x.com/JosephChaplik" target="_blank"><i class="fa-brands fa-x-twitter"></i></a>
        <a href="https://www.youtube.com/@josephchaplik" target="_blank"><i class="fa-brands fa-youtube"></i></a>
      </p>
      <br style="clear:both;" />
      <p>Joseph Chaplik has 28 years of executive leadership experience.</p>
      <p><b>Statement</b><br />Representative Joseph Chaplik has a proven 3 term record.</p>
      <br />
    </article>
""").encode()

_DETAIL_SPARSE_HTML = textwrap.dedent("""\
    <article class="person">
      <figure><img src="/custom/Picture/0" alt="Alex Flores (Write-In)"></figure>
      <h4>Alex Flores (Write-In)</h4>
      <p>
        U.S. House of Rep. - District 2<br />
        Libertarian<br />
        Traditional Funding
      </p>
      <p class="social"></p>
      <br style="clear:both;" />
      <br />
    </article>
""").encode()


def test_parse_list_skips_county_branches():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    county = [e for e in entries if e.branch == "COUNTY"]
    assert county == [], "County races should be excluded from Stage 1"

def test_parse_list_total_count_federal_and_state_only():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    assert len(entries) == 4

def test_parse_list_branch_assigned():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    assert any(e.branch == "FEDERAL - LEGISLATIVE" for e in entries)
    assert any(e.branch == "STATE - EXECUTIVE" for e in entries)

def test_parse_list_race_name():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    assert any(e.race_name == "U.S. House of Rep. - District 1" for e in entries)

def test_parse_list_candidate_id():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    amish = next(e for e in entries if "Amish" in e.name)
    assert amish.candidate_id == 5780

def test_parse_list_name_unescape():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    galán = next(e for e in entries if "Gal" in e.name)
    assert galán.name == "Marlene Galán-Woods"

def test_parse_list_write_in_flag():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    write_in = next(e for e in entries if e.is_write_in)
    assert write_in.name == "Alex Flores"

def test_parse_list_write_in_suffix_stripped():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    write_in = next(e for e in entries if e.is_write_in)
    assert "(Write-In)" not in write_in.name

def test_parse_list_party():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    amish = next(e for e in entries if "Amish" in e.name)
    assert amish.party == "Democratic"

def test_parse_list_governor():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    gov = next(e for e in entries if e.race_name == "Governor")
    assert gov.name == "Katie Hobbs"
    assert gov.candidate_id == 5577

def test_parse_list_empty():
    assert parse_candidate_list(b"<html><body></body></html>") == []

def test_parse_detail_name():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).name == "Joseph Chaplik"

def test_parse_detail_office():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).office == "U.S. House of Rep. - District 1"

def test_parse_detail_party():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).party == "Republican"

def test_parse_detail_funding_type():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).funding_type == "Traditional Funding"

def test_parse_detail_website():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).website_url == "https://www.josephchaplik.com/"

def test_parse_detail_facebook():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).facebook == "https://www.facebook.com/josephchaplik"

def test_parse_detail_twitter():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).twitter == "https://www.x.com/JosephChaplik"

def test_parse_detail_youtube():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).youtube == "https://www.youtube.com/@josephchaplik"

def test_parse_detail_bio():
    assert "28 years" in parse_candidate_detail(_DETAIL_FULL_HTML).bio

def test_parse_detail_statement():
    d = parse_candidate_detail(_DETAIL_FULL_HTML)
    assert "proven 3 term record" in d.campaign_statement
    assert "Statement" not in d.campaign_statement

def test_parse_detail_photo():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).photo_url == "/custom/Picture/2380"

def test_parse_detail_sparse_no_website():
    assert parse_candidate_detail(_DETAIL_SPARSE_HTML).website_url == ""

def test_parse_detail_sparse_no_social():
    d = parse_candidate_detail(_DETAIL_SPARSE_HTML)
    assert d.facebook == "" and d.twitter == ""

def test_parse_detail_sparse_no_bio():
    assert parse_candidate_detail(_DETAIL_SPARSE_HTML).bio == ""

def test_parse_detail_sparse_photo_zero():
    assert parse_candidate_detail(_DETAIL_SPARSE_HTML).photo_url == "/custom/Picture/0"

def test_parse_detail_missing_article():
    d = parse_candidate_detail(b"<html><body></body></html>")
    assert d.name == "" and d.bio == ""


# ---------------------------------------------------------------------------
# mappers
# ---------------------------------------------------------------------------

from integrations.az_sos.mappers import AZ_ELECTIONS, normalize_contest_name, party_abbrev


def test_az_elections_primary_date():
    primary = next(e for e in AZ_ELECTIONS if e["election_type"] == "primary")
    assert primary["election_date"].isoformat() == "2026-07-21"


def test_az_elections_general_date():
    general = next(e for e in AZ_ELECTIONS if e["election_type"] == "general")
    assert general["election_date"].isoformat() == "2026-11-03"


# normalize_contest_name — party suffix stripping
def test_normalize_strips_dem_suffix():
    assert normalize_contest_name("Governor (DEM)") == "Governor"

def test_normalize_strips_rep_suffix():
    assert normalize_contest_name("Governor (REP)") == "Governor"

def test_normalize_strips_nol_suffix():
    assert normalize_contest_name("NOL Partisan Notice (NOL)") == "NOL Partisan Notice"

def test_normalize_no_suffix_unchanged():
    assert normalize_contest_name("Governor") == "Governor"

# normalize_contest_name — US House join (real strings from both sources)
def test_normalize_xml_us_house():
    result = normalize_contest_name("U.S. Representative in Congress - District No. 1 (DEM)")
    assert result == "U.S. House - District 1"

def test_normalize_list_us_house():
    result = normalize_contest_name("U.S. House of Rep. - District 1")
    assert result == "U.S. House - District 1"

def test_normalize_us_house_joins():
    xml = normalize_contest_name("U.S. Representative in Congress - District No. 7 (REP)")
    lst = normalize_contest_name("U.S. House of Rep. - District 7")
    assert xml == lst

# normalize_contest_name — state senator (double space in XML)
def test_normalize_xml_state_senator_double_space():
    result = normalize_contest_name("State Senator - District No.  1 (DEM)")
    assert result == "State Senator - District 1"

def test_normalize_list_state_senator():
    result = normalize_contest_name("State Senator - District 1")
    assert result == "State Senator - District 1"

def test_normalize_state_senator_joins():
    xml = normalize_contest_name("State Senator - District No.  5 (REP)")
    lst = normalize_contest_name("State Senator - District 5")
    assert xml == lst

# normalize_contest_name — state representative (double space in XML)
def test_normalize_xml_state_rep_double_space():
    result = normalize_contest_name("State Representative - District No.  1 (DEM)")
    assert result == "State Representative - District 1"

def test_normalize_state_rep_joins():
    xml = normalize_contest_name("State Representative - District No.  12 (GRN)")
    lst = normalize_contest_name("State Representative - District 12")
    assert xml == lst

# normalize_contest_name — statewide races
def test_normalize_corporation_commissioner():
    assert normalize_contest_name("Corporation Commissioner (DEM)") == "Corporation Commissioner"

# party_abbrev
def test_party_abbrev_democratic():
    assert party_abbrev("Democratic") == "DEM"

def test_party_abbrev_republican():
    assert party_abbrev("Republican") == "REP"

def test_party_abbrev_libertarian():
    assert party_abbrev("Libertarian") == "LIB"

def test_party_abbrev_no_labels():
    assert party_abbrev("No Labels") == "NOL"

def test_party_abbrev_nonpartisan():
    assert party_abbrev("Non-partisan") == "NPA"

def test_party_abbrev_green():
    assert party_abbrev("Green") == "GRN"

# geography_scope
from integrations.az_sos.mappers import geography_scope

def test_geography_scope_federal():
    assert geography_scope("FEDERAL - LEGISLATIVE") == "congressional_district"

def test_geography_scope_state_executive():
    assert geography_scope("STATE - EXECUTIVE") == "statewide"

def test_geography_scope_state_legislative():
    assert geography_scope("STATE - LEGISLATIVE") == "state_legislative_district"

# normalize_candidate_name
from integrations.az_sos.mappers import normalize_candidate_name

def test_normalize_candidate_regular():
    name, is_wi = normalize_candidate_name("Gallego, Ruben")
    assert name == "Ruben Gallego"
    assert is_wi is False

def test_normalize_candidate_diacritic():
    name, is_wi = normalize_candidate_name("Galán-Woods, Marlene")
    assert name == "Marlene Galán-Woods"
    assert is_wi is False

def test_normalize_candidate_no_comma_unchanged():
    name, is_wi = normalize_candidate_name("Governor")
    assert name == "Governor"
    assert is_wi is False

def test_normalize_candidate_generic_write_in():
    name, is_wi = normalize_candidate_name("Write-In")
    assert name is None
    assert is_wi is True

def test_normalize_candidate_named_write_in():
    name, is_wi = normalize_candidate_name("Flores, Alex (Write-In)")
    assert name == "Alex Flores"
    assert is_wi is True

def test_normalize_candidate_named_write_in_suffix_stripped():
    name, _ = normalize_candidate_name("Flores, Alex (Write-In)")
    assert "(Write-In)" not in name
