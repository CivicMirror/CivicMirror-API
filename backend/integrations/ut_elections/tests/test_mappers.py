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
