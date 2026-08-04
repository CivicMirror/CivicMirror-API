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
