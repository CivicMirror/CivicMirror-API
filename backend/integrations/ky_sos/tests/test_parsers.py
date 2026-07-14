import os

from integrations.ky_sos.parsers import (
    parse_candidate_rows,
    parse_current_election,
    parse_office_directory,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_current_election_reads_selected_option():
    html = _load_fixture("office_directory.html")
    result = parse_current_election(html)
    assert result == {"value": "87", "label": "2026 General Election"}


def test_parse_office_directory_extracts_ids_labels_counts():
    html = _load_fixture("office_directory.html")
    offices = parse_office_directory(html)
    by_id = {o["office_id"]: o for o in offices}
    assert by_id[3]["label"] == "US Senator"
    assert by_id[3]["count"] == 4
    assert by_id[4]["label"] == "US Representative"
    assert by_id[4]["count"] == 21
    assert by_id[11]["label"] == "State Senator"
    assert by_id[11]["count"] == 30
    assert by_id[12]["label"] == "State Representative"
    assert by_id[12]["count"] == 150
    # Out-of-scope groups are still parsed (filtering happens in mappers/tasks) —
    # this parser is a faithful extraction, not a scope filter.
    assert 14 in by_id  # Justice of the Supreme Court


def test_parse_candidate_rows_statewide_office_has_empty_district():
    html = _load_fixture("office_us_senator.html")
    rows = parse_candidate_rows(html)
    assert len(rows) == 4
    andy_barr = next(r for r in rows if r["name"] == "Andy Barr")
    assert andy_barr["office"] == "US Senator"
    assert andy_barr["district"] == ""
    assert andy_barr["party"] == "Republican Party"
    assert andy_barr["date_filed"] == "11/7/2025"


def test_parse_candidate_rows_district_office_extracts_district_text():
    html = _load_fixture("office_us_representative.html")
    rows = parse_candidate_rows(html)
    assert len(rows) == 21
    comer = next(r for r in rows if r["name"] == "James R. Comer")
    assert comer["office"] == "US Representative"
    assert comer["district"] == "1st"
    assert comer["party"] == "Republican Party"


def test_parse_candidate_rows_withdrawn_group_has_no_date_filed():
    html = _load_fixture("withdrawn.html")
    rows = parse_candidate_rows(html)
    assert len(rows) == 1
    chaffin = rows[0]
    assert chaffin["name"] == "Alisha Dawn Chaffin"
    assert chaffin["office"] == "State Representative"
    assert chaffin["district"] == "88th"
    assert chaffin["party"] == "Democratic Party"
    assert chaffin["date_filed"] == ""
