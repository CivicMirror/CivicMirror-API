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
    assert len(groups[("House of Delegates", "Legislative District 1A")]) == 2


def test_map_race_identity_district_office():
    from integrations.md_sbe.mappers import map_race_identity
    identity, fields = map_race_identity("House of Delegates", "Legislative District 1A")
    assert identity["office_title"] == "House of Delegates - Legislative District 1A"
    assert identity["contest_variant"] == "md:House of Delegates:Legislative District 1A"
    assert fields["geography_scope"] == "district"
    assert fields["source"] == "md_sbe"


def test_map_race_identity_statewide_office():
    from integrations.md_sbe.mappers import map_race_identity
    identity, fields = map_race_identity("Governor / Lt. Governor", "State Of Maryland")
    assert identity["office_title"] == "Governor / Lt. Governor"
    assert fields["geography_scope"] == "statewide"


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
    assert candidate_display_name(row) == "Wes Moore / Aruna Miller"


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
