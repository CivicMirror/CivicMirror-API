import os

from integrations.mn_sos.parsers import parse_candidate_table, parse_file_index, parse_result_file

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="iso-8859-1") as f:
        return f.read()


def test_parse_file_index_extracts_label_url_pairs():
    html = _load_fixture("file_index.html")
    files = parse_file_index(html)

    labels = {f["label"] for f in files}
    assert "U.S. Senator Statewide" in labels
    assert "U.S. Representative by District" in labels
    assert "County Races" in labels  # out-of-scope label must still be parsed here;
    # scope filtering is mappers.is_in_scope_file's job, not the parser's.

    by_label = {f["label"]: f["url"] for f in files}
    assert by_label["U.S. Senator Statewide"] == (
        "https://electionresultsfiles.sos.mn.gov/20241105/ussenate.txt"
    )


def test_parse_file_index_returns_empty_list_for_no_matches():
    assert parse_file_index("<html><body>no links here</body></html>") == []


def test_parse_result_file_maps_16_positional_fields():
    text = _load_fixture("ussenate.txt")
    rows = parse_result_file(text)

    klobuchar = next(r for r in rows if r["candidate_name"] == "Amy Klobuchar")
    assert klobuchar["office_id"] == "0102"
    assert klobuchar["office_name"] == "U.S. Senator"
    assert klobuchar["district"] == ""
    assert klobuchar["candidate_order_code"] == "0202"
    assert klobuchar["party"] == "DFL"
    assert klobuchar["precincts_reporting"] == "4103"
    assert klobuchar["total_precincts"] == "4103"
    assert klobuchar["candidate_votes"] == "1792441"
    assert klobuchar["candidate_pct"] == "56.20"
    assert klobuchar["total_office_votes"] == "3189323"


def test_parse_result_file_identifies_write_in_row():
    text = _load_fixture("ussenate.txt")
    rows = parse_result_file(text)
    write_in = next(r for r in rows if r["candidate_order_code"] == "9901")
    assert write_in["candidate_name"] == "WRITE-IN"


def test_parse_result_file_by_district_carries_district_in_office_name():
    text = _load_fixture("ushouse.txt")
    rows = parse_result_file(text)
    district_1_office_ids = {r["office_id"] for r in rows if "District 1" in r["office_name"]}
    assert district_1_office_ids == {"0104"}


def test_parse_result_file_skips_malformed_lines():
    text = "not;enough;fields\nMN;;;0102;U.S. Senator;;0202;Amy Klobuchar;;;DFL;4103;4103;1792441;56.20;3189323\n"
    rows = parse_result_file(text)
    assert len(rows) == 1
    assert rows[0]["candidate_name"] == "Amy Klobuchar"


def test_parse_result_file_handles_empty_text():
    assert parse_result_file("") == []


def test_parse_candidate_table_maps_7_positional_fields():
    text = _load_fixture("cand.txt")
    rows = parse_candidate_table(text)

    klobuchar = next(r for r in rows if r["candidate_name"] == "Amy Klobuchar")
    assert klobuchar["candidate_id"] == "01020202"
    assert klobuchar["office_id"] == "0102"
    assert klobuchar["office_title"] == "U.S. Senator"
    assert klobuchar["party"] == "DFL"


def test_parse_candidate_table_skips_malformed_lines():
    text = "too;few\n01020202;Amy Klobuchar;0102;U.S. Senator;88;02;DFL\n"
    rows = parse_candidate_table(text)
    assert len(rows) == 1
