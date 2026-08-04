from __future__ import annotations

import pytest


@pytest.mark.parametrize("office_name", [
    "Governor / Lt. Governor",
    "Attorney General",
    "Comptroller",
    "Representative in Congress",
    "State Senator",
    "House of Delegates",
])
def test_is_in_scope_office_true_for_federal_and_state(office_name):
    from integrations.md_sbe.mappers import is_in_scope_office
    assert is_in_scope_office(office_name) is True


@pytest.mark.parametrize("office_name", [
    "Judge of the Circuit Court",
    "Board of Education",
    "County Council",
    "",
])
def test_is_in_scope_office_false_for_judicial_and_local(office_name):
    from integrations.md_sbe.mappers import is_in_scope_office
    assert is_in_scope_office(office_name) is False


def test_parse_statewide_candidate_csv_maps_by_header_name():
    from integrations.md_sbe.mappers import parse_statewide_candidate_csv
    csv_text = (
        "﻿Office Name,Contest Run By District Name and Number,"
        "Candidate Ballot Last Name and Suffix,Candidate First Name and Middle Name,"
        "Office Political Party,Candidate Status,Has Related Candidate\r\n"
        "Governor / Lt. Governor,State Of Maryland,Moore,Wes,Democratic,Active,Yes\r\n"
    )
    rows = parse_statewide_candidate_csv(csv_text)
    assert len(rows) == 1
    assert rows[0]["Office Name"] == "Governor / Lt. Governor"
    assert rows[0]["Candidate Ballot Last Name and Suffix"] == "Moore"


def test_group_candidate_rows_groups_by_office_and_district():
    from integrations.md_sbe.mappers import group_candidate_rows
    rows = [
        {"Office Name": "House of Delegates", "Contest Run By District Name and Number": "Legislative District 1A"},
        {"Office Name": "House of Delegates", "Contest Run By District Name and Number": "Legislative District 1A"},
        {"Office Name": "House of Delegates", "Contest Run By District Name and Number": "Legislative District 1B"},
    ]
    groups = group_candidate_rows(rows)
    assert len(groups) == 2
    assert len(groups[("House of Delegates", "Legislative District 1A", "")]) == 2


def _primary_rows():
    return [
        {"Office Name": "Governor / Lt. Governor",
         "Contest Run By District Name and Number": "State Of Maryland",
         "Office Political Party": "Democratic"},
        {"Office Name": "Governor / Lt. Governor",
         "Contest Run By District Name and Number": "State Of Maryland",
         "Office Political Party": "Democratic"},
        {"Office Name": "Governor / Lt. Governor",
         "Contest Run By District Name and Number": "State Of Maryland",
         "Office Political Party": "Republican"},
    ]


def test_group_candidate_rows_splits_primary_contests_by_party():
    """MD files every party's candidates for a primary contest under one
    Office Name/district — only "Office Political Party" tells them apart, so
    without the split the Democratic and Republican Governor primaries would
    become ONE race."""
    from integrations.md_sbe.mappers import group_candidate_rows
    groups = group_candidate_rows(_primary_rows(), split_by_party=True)

    assert len(groups) == 2
    assert len(groups[("Governor / Lt. Governor", "State Of Maryland", "Democratic")]) == 2
    assert len(groups[("Governor / Lt. Governor", "State Of Maryland", "Republican")]) == 1


def test_group_candidate_rows_keeps_general_contest_parties_together():
    """The general CSV lists one nominee per party for the SAME race — splitting
    would wrongly create one single-candidate race per party."""
    from integrations.md_sbe.mappers import group_candidate_rows
    groups = group_candidate_rows(_primary_rows(), split_by_party=False)

    assert len(groups) == 1
    assert len(groups[("Governor / Lt. Governor", "State Of Maryland", "")]) == 3


def test_map_race_identity_district_office():
    from integrations.md_sbe.mappers import map_race_identity
    identity, fields = map_race_identity("House of Delegates", "Legislative District 1A")
    assert identity["office_title"] == "House of Delegates - Legislative District 1A"
    assert identity["contest_variant"] == "md:House of Delegates:01A:general"
    assert fields["geography_scope"] == "district"
    assert fields["source"] == "md_sbe"
    assert fields["source_metadata"]["contest_code"] == "md:House of Delegates:01A"
    # A general-election race stays party-agnostic so every nominee's result
    # rows match it.
    assert "party_code" not in fields["source_metadata"]


def test_map_race_identity_statewide_office():
    from integrations.md_sbe.mappers import map_race_identity
    identity, fields = map_race_identity("Governor / Lt. Governor", "State Of Maryland")
    assert identity["office_title"] == "Governor / Lt. Governor"
    assert fields["geography_scope"] == "statewide"


def test_map_race_identity_folds_party_into_contest_variant_for_primaries():
    from integrations.md_sbe.mappers import map_race_identity
    dem_identity, dem_fields = map_race_identity(
        "Governor / Lt. Governor", "State Of Maryland", "Democratic",
    )
    rep_identity, rep_fields = map_race_identity(
        "Governor / Lt. Governor", "State Of Maryland", "Republican",
    )

    assert dem_identity["contest_variant"] == "md:Governor / Lt. Governor::DEM"
    assert rep_identity["contest_variant"] == "md:Governor / Lt. Governor::REP"
    assert dem_identity["contest_variant"] != rep_identity["contest_variant"]
    # Same office title — they are told apart by contest_variant, as in nc_sbe.
    assert dem_identity["office_title"] == rep_identity["office_title"]
    assert dem_fields["party"] == "Democratic"
    assert dem_fields["ballot_type"] == "Democratic"
    assert dem_fields["source_metadata"]["party_code"] == "DEM"
    assert rep_fields["source_metadata"]["party_code"] == "REP"
    # ...but they share a party-agnostic contest_code.
    assert (
        dem_fields["source_metadata"]["contest_code"]
        == rep_fields["source_metadata"]["contest_code"]
    )


@pytest.mark.parametrize("raw,expected", [
    ("Legislative District 1A", "01A"),   # candidate CSV spelling
    ("01A", "01A"),                       # results CSV spelling
    ("Congressional District 6", "06"),
    ("06", "06"),
    ("Legislative District 10", "10"),
    ("State Of Maryland", ""),
    ("", ""),
])
def test_normalize_district_key_bridges_both_feeds(raw, expected):
    from integrations.md_sbe.mappers import normalize_district_key
    assert normalize_district_key(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Democratic", "DEM"), ("DEM", "DEM"),
    ("Republican", "REP"), ("REP", "REP"),
    ("Green", "GRN"), ("Unaffiliated", "UNA"), ("", ""),
])
def test_normalize_party_key_bridges_both_feeds(raw, expected):
    from integrations.md_sbe.mappers import normalize_party_key
    assert normalize_party_key(raw) == expected


@pytest.mark.parametrize("office,district,expected", [
    # Both feeds' district spellings must produce the SAME race title.
    ("House of Delegates", "Legislative District 1A", "House of Delegates - Legislative District 1A"),
    ("House of Delegates", "01A", "House of Delegates - Legislative District 1A"),
    ("State Senator", "Legislative District 1", "State Senator - Legislative District 1"),
    ("State Senator", "01", "State Senator - Legislative District 1"),
    ("Representative in Congress", "Congressional District 6",
     "Representative in Congress - Congressional District 6"),
    ("Representative in Congress", "06", "Representative in Congress - Congressional District 6"),
    ("Governor / Lt. Governor", "State Of Maryland", "Governor / Lt. Governor"),
    ("U.S. Senator", "", "U.S. Senator"),
])
def test_race_office_title_is_identical_from_either_feeds_district_spelling(office, district, expected):
    from integrations.md_sbe.mappers import race_office_title
    assert race_office_title(office, district) == expected


def test_candidate_display_name_builds_ticket_for_governor():
    from integrations.md_sbe.mappers import candidate_display_name
    row = {
        "Office Name": "Governor / Lt. Governor",
        "Candidate Ballot Last Name and Suffix": "Moore",
        "Candidate First Name and Middle Name": "Wes",
        "Has Related Candidate": "Yes",
        "Related Candidate Last Name and Suffix": "Miller",
        "Related Candidate First Name and Middle Name": "Aruna",
    }
    # MD's own results CSVs render the ticket with " and " — matching that
    # exactly is what lets name_match_key reconcile the two feeds.
    assert candidate_display_name(row) == "Wes Moore and Aruna Miller"


def test_candidate_display_name_single_candidate_office():
    from integrations.md_sbe.mappers import candidate_display_name
    row = {
        "Office Name": "Attorney General",
        "Candidate Ballot Last Name and Suffix": "Brown",
        "Candidate First Name and Middle Name": "Anthony",
        "Has Related Candidate": "",
    }
    assert candidate_display_name(row) == "Anthony Brown"


def test_map_candidate_preserves_status():
    from integrations.md_sbe.mappers import map_candidate
    row = {"Candidate Status": "Active", "Filing Type and Date": "Regular - 02/13/2026"}
    fields = map_candidate(row)
    assert fields["candidate_status"] == "running"
    assert fields["source_metadata"]["md_status"] == "Active"


def test_map_candidate_preserves_both_halves_of_a_ticket():
    """The display name is a join, so the Governor's own raw names must be
    stored too — not only the running mate's."""
    from integrations.md_sbe.mappers import map_candidate
    row = {
        "Candidate Status": "Active",
        "Candidate Ballot Last Name and Suffix": "Moore",
        "Candidate First Name and Middle Name": "Wes",
        "Related Candidate Last Name and Suffix": "Miller",
        "Related Candidate First Name and Middle Name": "Aruna",
    }
    metadata = map_candidate(row)["source_metadata"]
    assert metadata["primary_candidate_first_name"] == "Wes"
    assert metadata["primary_candidate_last_name"] == "Moore"
    assert metadata["related_candidate_first_name"] == "Aruna"
    assert metadata["related_candidate_last_name"] == "Miller"
