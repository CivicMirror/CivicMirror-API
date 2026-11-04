import datetime as dt
import io
from pathlib import Path

import pytest
from openpyxl import load_workbook

from integrations.al_sos.parsers import (
    _rotated_table_rows_from_tsv,
    _table_rows_from_tsv,
    _two_column_table_rows_from_tsv,
    normalize_contest_title,
    parse_candidate_certification_pdf,
    parse_candidate_certification_table,
    parse_election_year_page,
    parse_enr_workbook,
    parse_fcpa_committee_detail,
    parse_fcpa_race_search_response,
    parse_independent_candidate_certificate,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_candidate_certification_table_normalizes_offices_and_keeps_party():
    parsed = parse_candidate_certification_table(
        [
            ("Office", "Name"),
            ("U.S. Senate", "Barry Moore"),
            ("U.S. Congress Congressional District 3", "Mike Rogers"),
            ("Alabama State Senate District 10", "J.T. Smith"),
            ("County Sheriff", "Pat Smith"),
            ("Governor", "Jane Smith RECEIVED"),
        ],
        party="REP",
        document_label="State Certification of Republican Candidates",
        source_url="https://www.sos.alabama.gov/cert.pdf",
        sha256="abc123",
    )

    assert parsed == [
        {
            "office_title": "U.S. Senate",
            "candidate_name": "Barry Moore",
            "party": "REP",
            "document_label": "State Certification of Republican Candidates",
            "source_url": "https://www.sos.alabama.gov/cert.pdf",
            "source_sha256": "abc123",
        },
        {
            "office_title": "U.S. House - District 3",
            "candidate_name": "Mike Rogers",
            "party": "REP",
            "document_label": "State Certification of Republican Candidates",
            "source_url": "https://www.sos.alabama.gov/cert.pdf",
            "source_sha256": "abc123",
        },
        {
            "office_title": "State Senate - District 10",
            "candidate_name": "J.T. Smith",
            "party": "REP",
            "document_label": "State Certification of Republican Candidates",
            "source_url": "https://www.sos.alabama.gov/cert.pdf",
            "source_sha256": "abc123",
        },
        {
            "office_title": "Governor",
            "candidate_name": "Jane Smith",
            "party": "REP",
            "document_label": "State Certification of Republican Candidates",
            "source_url": "https://www.sos.alabama.gov/cert.pdf",
            "source_sha256": "abc123",
        },
    ]


def test_rotated_certification_table_joins_district_and_place_columns():
    headers = (
        "level", "page_num", "block_num", "par_num", "line_num", "word_num",
        "left", "top", "width", "height", "conf", "text",
    )
    entries = [
        (1, 1, 1, 1, 378, 192, 106, 41, "Office"),
        (1, 1, 1, 2, 1040, 192, 220, 41, "District/Jurisdiction"),
        (1, 1, 1, 3, 1388, 192, 90, 41, "|Place"),
        (1, 1, 1, 4, 1494, 192, 120, 41, "|Ballot"),
        (2, 1, 1, 1, 379, 300, 80, 30, "State"),
        (2, 1, 1, 2, 470, 300, 120, 30, "Senator"),
        (2, 1, 1, 3, 1100, 300, 20, 30, "2"),
        (2, 1, 1, 4, 1494, 300, 100, 30, "Jane"),
        (2, 1, 1, 5, 1598, 300, 100, 30, "Smith"),
    ]
    tsv = "\t".join(headers) + "\n" + "\n".join(
        "\t".join(map(str, (5, 1, *entry[:8], 95, entry[8])))
        for entry in entries
    )

    assert _rotated_table_rows_from_tsv(tsv) == [("State Senator District 2", "Jane Smith")]


def test_two_column_certification_table_uses_office_and_name_header_without_grid_rules():
    headers = (
        "level", "page_num", "block_num", "par_num", "line_num", "word_num",
        "left", "top", "width", "height", "conf", "text",
    )
    words = (
        (1, 1, 1, 1, 100, 100, 70, 20, "Office"),
        (1, 1, 1, 2, 600, 100, 60, 20, "Name"),
        (2, 1, 1, 1, 100, 150, 100, 20, "Governor"),
        (2, 1, 1, 2, 600, 150, 60, 20, "Jane"),
        (2, 1, 1, 3, 665, 150, 70, 20, "Smith"),
    )
    tsv = "\t".join(headers) + "\n" + "\n".join(
        "\t".join(map(str, (5, 1, *word[:8], 95, word[8])))
        for word in words
    )

    assert _two_column_table_rows_from_tsv(tsv) == [("Governor", "Jane Smith")]


def test_two_column_certification_continuation_uses_widest_cell_gap_without_header():
    headers = (
        "level", "page_num", "block_num", "par_num", "line_num", "word_num",
        "left", "top", "width", "height", "conf", "text",
    )
    words = (
        (1, 1, 1, 1, 100, 100, 70, 20, "U.S."),
        (1, 1, 1, 2, 180, 100, 85, 20, "Senate"),
        (1, 1, 1, 3, 600, 100, 60, 20, "Barry"),
        (1, 1, 1, 4, 665, 100, 70, 20, "Moore"),
        (2, 1, 1, 1, 100, 140, 90, 20, "Governor"),
        (2, 1, 1, 2, 600, 140, 60, 20, "Jane"),
        (2, 1, 1, 3, 665, 140, 70, 20, "Smith"),
        (3, 1, 1, 1, 100, 180, 130, 20, "Attorney"),
        (3, 1, 1, 2, 235, 180, 80, 20, "General"),
        (3, 1, 1, 3, 600, 180, 70, 20, "Alex"),
        (3, 1, 1, 4, 675, 180, 70, 20, "Jones"),
    )
    tsv = "\t".join(headers) + "\n" + "\n".join(
        "\t".join(map(str, (5, 1, *word[:8], 95, word[8])))
        for word in words
    )

    assert _two_column_table_rows_from_tsv(tsv, allow_headerless=True) == [
        ("U.S. Senate", "Barry Moore"),
        ("Governor", "Jane Smith"),
        ("Attorney General", "Alex Jones"),
    ]


def test_parse_independent_candidate_certificate_reads_office_name_pairs():
    parsed = parse_independent_candidate_certificate(
        [
            "STATE OF ALABAMA",
            "Alabama State Senate, District 10",
            "Jesse Battles",
            "Alabama State House of Representatives, District 7",
            "Trent Ford",
        ],
        document_label="State Certification of Independent Candidate",
        source_url="https://www.sos.alabama.gov/independent.pdf",
        sha256="def456",
    )

    assert [(row["office_title"], row["candidate_name"], row["party"]) for row in parsed] == [
        ("State Senate - District 10", "Jesse Battles", "IND"),
        ("State House - District 7", "Trent Ford", "IND"),
    ]


def test_candidate_certification_pdf_rejects_non_pdf_bytes():
    with pytest.raises(ValueError, match="not a PDF"):
        parse_candidate_certification_pdf(
            b"not a PDF",
            party="REP",
            document_label="State Certification of Republican Candidates",
            source_url="https://www.sos.alabama.gov/cert.pdf",
            sha256="abc123",
        )


def test_table_rows_from_tsv_keeps_cells_separate_across_continued_rows():
    headers = (
        "level", "page_num", "block_num", "par_num", "line_num", "word_num",
        "left", "top", "width", "height", "conf", "text",
    )
    words = (
        (1, 105, 1, 100, 70, "U.S."),
        (1, 105, 2, 175, 90, "Senate"),
        (1, 105, 3, 520, 90, "Barry"),
        (1, 100, 4, 615, 70, "Moore"),
        (2, 145, 1, 100, 70, "State"),
        (2, 145, 2, 175, 80, "Senate"),
        (2, 145, 3, 260, 100, "District"),
        (2, 145, 4, 365, 20, "10"),
        (2, 145, 5, 520, 80, "Jane"),
        (2, 145, 6, 605, 70, "Smith"),
    )
    tsv = "\t".join(headers) + "\n" + "\n".join(
        "\t".join(map(str, ("5", "1", "1", "1", line, word, left, top, width, "12", "95", text)))
        for line, top, word, left, width, text in words
    )

    assert _table_rows_from_tsv(tsv, [100, 130, 140, 180], 500) == [
        ("U.S. Senate", "Barry Moore"),
        ("State Senate District 10", "Jane Smith"),
    ]


def test_normalize_contest_title_strips_party_suffix():
    assert normalize_contest_title("LIEUTENANT GOVERNOR (REP)") == ("LIEUTENANT GOVERNOR", "REP")
    assert normalize_contest_title("STATE REPRESENTATIVE, DISTRICT 63") == (
        "STATE REPRESENTATIVE, DISTRICT 63",
        "",
    )


def test_parse_enr_workbook_aggregates_county_rows():
    content = (FIXTURES / "al_sos_enr_export.xlsx").read_bytes()

    parsed = parse_enr_workbook(content)

    lieutenant_governor = [
        row
        for row in parsed.rows
        if row.office_title == "LIEUTENANT GOVERNOR" and row.raw["party_code"] == "REP"
    ]
    by_candidate = {row.candidate_name: row for row in lieutenant_governor}

    assert "Wes Allen" in by_candidate
    assert "John Wahl" in by_candidate
    assert by_candidate["Wes Allen"].vote_count > 13036
    assert by_candidate["John Wahl"].vote_count > 15588
    assert all(row.result_type == "official" for row in parsed.rows)
    assert parsed.is_complete is True
    assert parsed.source_version.startswith("1001295:")
    assert parsed.county_stats["01"]["precincts_reported"] == 177


def test_parse_enr_workbook_preserves_party_from_column_when_title_has_suffix():
    content = (FIXTURES / "al_sos_enr_export.xlsx").read_bytes()

    parsed = parse_enr_workbook(content)
    row = next(row for row in parsed.rows if row.candidate_name == "Wes Allen")

    assert row.raw["party_code"] == "REP"
    assert row.raw["contest_code"] == "00100892"
    assert row.raw["source"] == "al_sos_enr"


def test_source_version_changes_when_raw_workbook_row_counts_change():
    content = (FIXTURES / "al_sos_enr_export.xlsx").read_bytes()
    parsed = parse_enr_workbook(content)

    all_results_extra = _with_appended_row(content, "AllResults", row_number=2)
    statistics_extra = _with_appended_row(content, "Statistics", row_number=2)

    assert parse_enr_workbook(all_results_extra).source_version != parsed.source_version
    assert parse_enr_workbook(statistics_extra).source_version != parsed.source_version


def test_parse_enr_workbook_treats_overreported_precincts_as_complete():
    content = (FIXTURES / "al_sos_enr_export.xlsx").read_bytes()
    workbook = load_workbook(io.BytesIO(content))
    statistics = workbook["Statistics"]
    headers = [cell.value for cell in statistics[1]]
    precincts_reported_column = headers.index("Precincts Reported") + 1
    total_precincts_column = headers.index("Total Precincts") + 1
    statistics.cell(row=2, column=precincts_reported_column).value = (
        statistics.cell(row=2, column=total_precincts_column).value + 1
    )

    parsed = parse_enr_workbook(_save_workbook(workbook))

    assert parsed.is_complete is True
    assert all(row.result_type == "official" for row in parsed.rows)


def _with_appended_row(content: bytes, sheet_name: str, row_number: int) -> bytes:
    workbook = load_workbook(io.BytesIO(content))
    sheet = workbook[sheet_name]
    sheet.append([cell.value for cell in sheet[row_number]])
    return _save_workbook(workbook)


def _save_workbook(workbook) -> bytes:
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _year_page_html() -> str:
    return (FIXTURES / "al_year_page_2026.html").read_text()


def test_parse_election_year_page_finds_all_headings():
    elections = parse_election_year_page(_year_page_html())

    assert len(elections) == 4
    names = [e["name"] for e in elections]
    assert "Special General Election House District 63" in names
    assert "Primary Election" in names
    assert "Primary Runoff Election" in names
    assert "General Election" in names


def test_parse_election_year_page_extracts_dates_and_types():
    elections = parse_election_year_page(_year_page_html())
    by_name = {e["name"]: e for e in elections}

    assert by_name["Primary Election"]["election_date"] == dt.date(2026, 5, 19)
    assert by_name["Primary Election"]["election_type"] == "primary"
    assert by_name["Primary Runoff Election"]["election_date"] == dt.date(2026, 6, 16)
    assert by_name["Primary Runoff Election"]["election_type"] == "primary_runoff"
    assert by_name["General Election"]["election_date"] == dt.date(2026, 11, 3)
    assert by_name["General Election"]["election_type"] == "general"
    assert by_name["Special General Election House District 63"]["election_type"] == "special"


def test_parse_election_year_page_extracts_document_links():
    elections = parse_election_year_page(_year_page_html())
    by_name = {e["name"]: e for e in elections}

    primary_links = by_name["Primary Election"]["document_links"]
    assert {"label": "Sample Ballots", "url": "https://www.sos.alabama.gov/alabama-votes/2026-primary-election-sample-ballots"} in primary_links
    republican_cert = next(link for link in primary_links if "Republican Party Certification" in link["label"])
    assert republican_cert["url"] == "https://www.sos.alabama.gov/sites/default/files/election-2026/2026RepublicanCertification.pdf"


def test_parse_election_year_page_source_id_is_stable_and_unique():
    elections = parse_election_year_page(_year_page_html())
    source_ids = [e["source_id"] for e in elections]

    assert len(source_ids) == len(set(source_ids))
    assert all(sid.startswith("al_sos_2026_") for sid in source_ids)


def test_parse_election_year_page_does_not_split_on_plain_hyphen_in_name():
    html = (
        "<h3>City Council District 63 - Runoff – January 13, 2026</h3>"
        "<blockquote><p><a href=\"/x.pdf\">Doc</a></p></blockquote>"
    )
    elections = parse_election_year_page(html)

    assert len(elections) == 1
    assert elections[0]["name"] == "City Council District 63 - Runoff"
    assert elections[0]["election_date"] == dt.date(2026, 1, 13)


def test_parse_election_year_page_classifies_general_runoff():
    html = "<h3>General Election Runoff – December 1, 2026</h3><blockquote></blockquote>"
    elections = parse_election_year_page(html)

    assert elections[0]["election_type"] == "general_runoff"


def test_parse_election_year_page_distinguishes_same_date_specials_by_jurisdiction():
    html = (
        "<h3>Special Primary Election, Congressional Districts 1, 2, 6, and 7 "
        "– August 11, 2026</h3><blockquote></blockquote>"
        "<h3>Special Primary Election, State Senate Districts 25 and 26 "
        "– August 11, 2026</h3><blockquote></blockquote>"
    )
    elections = parse_election_year_page(html)
    by_name = {e["name"]: e for e in elections}

    assert by_name["Special Primary Election, Congressional Districts 1, 2, 6, and 7"]["jurisdiction_level"] == "national"
    assert by_name["Special Primary Election, State Senate Districts 25 and 26"]["jurisdiction_level"] == "state"


def test_parse_election_year_page_non_congressional_defaults_to_state_jurisdiction():
    elections = parse_election_year_page(_year_page_html())

    assert all(e["jurisdiction_level"] == "state" for e in elections)


def _search_results_json() -> str:
    return (FIXTURES / "al_fcpa_search_results_page1.json").read_text()


def _committee_detail_html() -> str:
    return (FIXTURES / "al_fcpa_committee_detail_4834.html").read_text()


def test_parse_fcpa_race_search_response_returns_rows_and_total():
    rows, total_records = parse_fcpa_race_search_response(_search_results_json())

    assert total_records == 848
    assert len(rows) == 3
    assert rows[0]["committee_id"] == 4834
    assert rows[0]["candidate_name"] == "ABBETT, JIMMY"
    assert rows[0]["candidate_status"] == "Active"
    assert rows[0]["year"] == 2026


def test_parse_fcpa_committee_detail_extracts_structured_fields():
    detail = parse_fcpa_committee_detail(_committee_detail_html())

    assert detail["committee_id"] == 4834
    assert detail["candidateFirstName"] == "JIMMY"
    assert detail["candidateLastName"] == "ABBETT"
    assert detail["suffix"] == ""
    assert detail["office"] == "Sheriff"
    assert detail["jurisdiction"] == "TALLAPOOSA COUNTY"
    assert detail["district"] == ""
    assert detail["party"] == "Republican"
    assert detail["committeeStatus"] == "Active"
    assert detail["dissolved"] is False
