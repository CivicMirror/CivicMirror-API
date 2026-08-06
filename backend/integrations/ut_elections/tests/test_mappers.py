from __future__ import annotations

import io

import openpyxl
import pytest


def _build_workbook(rows: list[tuple]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.parametrize("section", ["Federal Offices", "State Offices", "State Senate", "State House"])
def test_is_in_scope_section_true_for_federal_and_state(section):
    from integrations.ut_elections.mappers import is_in_scope_section
    assert is_in_scope_section(section) is True


@pytest.mark.parametrize("section", ["State School Board", "State Judicial", "", "Unknown Section"])
def test_is_in_scope_section_false_for_school_board_and_judicial(section):
    from integrations.ut_elections.mappers import is_in_scope_section
    assert is_in_scope_section(section) is False


def test_parse_candidate_filing_workbook_extracts_in_scope_rows_only():
    from integrations.ut_elections.mappers import parse_candidate_filing_workbook

    content = _build_workbook([
        (None, None, None, None),
        ("Federal Offices | State Offices | Utah Senate | Utah House | State School Board | Judicial Retention", None, None, None),
        (None, None, None, None),
        ("Federal Offices", None, None, None),
        (None, None, None, None),
        ("Candidate", "Office", "Party", "Status"),
        ("BEN MCADAMS", "U.S. House District 1", "Democratic", "Election Candidate"),
        ("RILEY OWEN", "U.S. House District 1", "Republican", "Election Candidate"),
        (None, None, None, None),
        ("State School Board", None, None, None),
        (None, None, None, None),
        ("Candidate", "Office", "Party", "Status"),
        ("TRACY J. NUTTALL", "State School Board Distrct 11 (Multi-County)", "Republican", "Election Candidate"),
        (None, None, None, None),
        ("State Judicial", None, None, None),
        (None, None, None, None),
        ("Judicial Retention", "Status", None, None),
        ("Shall AARON FLATER be retained...?", "Election Candidate", None, None),
    ])

    rows = parse_candidate_filing_workbook(content)

    assert len(rows) == 2
    assert rows[0] == {
        "section": "Federal Offices", "name": "BEN MCADAMS",
        "office": "U.S. House District 1", "party": "Democratic",
        "status": "Election Candidate",
    }
    assert rows[1]["name"] == "RILEY OWEN"
    assert all(r["section"] != "State School Board" for r in rows)
    assert all(r["section"] != "State Judicial" for r in rows)


def test_parse_candidate_filing_workbook_handles_blank_party():
    from integrations.ut_elections.mappers import parse_candidate_filing_workbook

    content = _build_workbook([
        ("State Senate", None, None, None),
        (None, None, None, None),
        ("Candidate", "Office", "Party", "Status"),
        ("FRED HAYES", "State Senate District 1 (Multi-County)", None, "Disqualified"),
    ])

    rows = parse_candidate_filing_workbook(content)
    assert rows[0]["party"] == ""


def test_parse_candidate_filing_workbook_skips_row_with_blank_office():
    from integrations.ut_elections.mappers import parse_candidate_filing_workbook

    content = _build_workbook([
        ("Federal Offices", None, None, None),
        (None, None, None, None),
        ("Candidate", "Office", "Party", "Status"),
        ("BEN MCADAMS", "U.S. House District 1", "Democratic", "Election Candidate"),
        ("NO OFFICE LISTED", None, "Democratic", "Election Candidate"),
    ])

    rows = parse_candidate_filing_workbook(content)

    assert len(rows) == 1
    assert rows[0]["name"] == "BEN MCADAMS"
    assert all(r["name"] != "NO OFFICE LISTED" for r in rows)


def test_parse_candidate_filing_workbook_subheader_detection_is_whitespace_and_case_tolerant():
    from integrations.ut_elections.mappers import parse_candidate_filing_workbook

    content = _build_workbook([
        ("Federal Offices", None, None, None),
        (None, None, None, None),
        ("candidate", "Office ", "Party", "Status"),
        ("BEN MCADAMS", "U.S. House District 1", "Democratic", "Election Candidate"),
    ])

    rows = parse_candidate_filing_workbook(content)

    assert len(rows) == 1
    assert rows[0]["name"] == "BEN MCADAMS"
    assert all(r["name"] not in ("candidate", "Candidate") for r in rows)


def test_titlecase_name_ordinary_names():
    from integrations.ut_elections.mappers import titlecase_name
    assert titlecase_name("RILEY OWEN") == "Riley Owen"


def test_titlecase_name_apostrophe_name():
    from integrations.ut_elections.mappers import titlecase_name
    assert titlecase_name("JASON O'DELL") == "Jason O'Dell"


def test_titlecase_name_does_not_special_case_mc_surnames():
    # Known, documented limitation: no name dictionary available.
    from integrations.ut_elections.mappers import titlecase_name
    assert titlecase_name("BEN MCADAMS") == "Ben Mcadams"


@pytest.mark.parametrize("status_raw,expected", [
    ("Election Candidate", "running"),
    ("Primary", "running"),
    ("Withdrew", "withdrawn"),
    ("Out in Convention", "withdrawn"),
    ("Out in Primary", "withdrawn"),
    ("Disqualified", "disqualified"),
])
def test_candidate_status_for_maps_known_statuses(status_raw, expected):
    from integrations.ut_elections.mappers import candidate_status_for
    assert candidate_status_for(status_raw) == expected


def test_candidate_status_for_filed_returns_none_to_skip():
    from integrations.ut_elections.mappers import candidate_status_for
    assert candidate_status_for("Filed") is None


def test_candidate_status_for_unknown_status_defaults_to_running():
    from integrations.ut_elections.mappers import candidate_status_for
    assert candidate_status_for("Some New Status UT Adds Later") == "running"


def test_map_race_identity_district_office():
    from integrations.ut_elections.mappers import map_race_identity
    identity, fields = map_race_identity("U.S. House District 1")
    assert identity["office_title"] == "U.S. House District 1"
    assert identity["contest_variant"] == "ut:U.S. House District 1"
    assert fields["geography_scope"] == "district"
    assert fields["source"] == "ut_elections"


def test_map_race_identity_statewide_office():
    from integrations.ut_elections.mappers import map_race_identity
    identity, fields = map_race_identity("Governor / Lieutenant Governor")
    assert identity["office_title"] == "Governor / Lieutenant Governor"
    assert fields["geography_scope"] == "statewide"


def test_map_candidate_running_status():
    from integrations.ut_elections.mappers import map_candidate
    row = {"name": "BEN MCADAMS", "status": "Election Candidate"}
    fields = map_candidate(row)
    assert fields is not None
    assert fields["candidate_status"] == "running"
    assert fields["source_metadata"]["ut_status"] == "Election Candidate"


def test_map_candidate_filed_returns_none():
    from integrations.ut_elections.mappers import map_candidate
    row = {"name": "SOMEONE NEW", "status": "Filed"}
    assert map_candidate(row) is None


def test_map_candidate_withdrawn_status():
    from integrations.ut_elections.mappers import map_candidate
    row = {"name": "KATHLEEN A. RIEBE", "status": "Withdrew"}
    fields = map_candidate(row)
    assert fields["candidate_status"] == "withdrawn"
