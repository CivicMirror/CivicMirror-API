import io
from pathlib import Path

from openpyxl import Workbook

from integrations.tn_sos.parsers import (
    parse_calendar,
    parse_candidate_workbook,
    parse_candidate_workbook_links,
    parse_precinct_xlsx,
    parse_results_index,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_calendar_finds_august_and_november_statewide_elections():
    rows = parse_calendar((FIXTURES / "calendar_2026.html").read_text())

    names = {row.name for row in rows}
    assert any("August 6, 2026" in name for name in names)
    assert any("November 3, 2026" in name for name in names)
    assert any(row.county == "Haywood" and "Stanton" in row.jurisdiction for row in rows)


def test_parse_candidate_workbook_links_prefers_xlsx_office_files():
    links = parse_candidate_workbook_links((FIXTURES / "candidate_lists_2026.html").read_text())

    names = {link.filename for link in links}
    assert "Governor_2026.xlsx" in names
    assert "USSenate_2026.xlsx" in names
    assert "TNHouse_2026.xlsx" in names
    assert all(link.url.endswith(".xlsx") for link in links)


def test_parse_candidate_workbook_links_rejects_external_workbook_url():
    html = '<a href="https://example.com/candidates.xlsx">Excel</a>'

    assert parse_candidate_workbook_links(html) == []


def test_parse_candidate_workbook_returns_qualified_candidates():
    records = parse_candidate_workbook(
        (FIXTURES / "candidates_us_senate_2026.xlsx").read_bytes(),
        "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/USSenate_2026.xlsx",
    )

    assert records[0].office == "United States Senate"
    assert records[0].candidate_name == "Jane Candidate"
    assert records[0].party == "Republican"


def test_parse_candidate_workbook_skips_negative_statuses():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Office", "Candidate Name", "Party", "Status"])
    sheet.append(["Governor", "Qualified Candidate", "Independent", "Qualified"])
    sheet.append(["Governor", "Qualified Another", "Democratic", "Qualified Candidate"])
    sheet.append(["Governor", "Active Candidate", "Democratic", "Active"])
    sheet.append(["Governor", "Nominee Candidate", "Republican", "Nominee"])
    sheet.append(["Governor", "Withdrawn Candidate", "Independent", "Withdrawn"])
    sheet.append(["Governor", "Disqualified Candidate", "Independent", "Disqualified"])
    content = io.BytesIO()
    workbook.save(content)

    records = parse_candidate_workbook(content.getvalue(), "https://sos.tn.gov/elections/candidates.xlsx")

    assert [record.candidate_name for record in records] == [
        "Qualified Candidate",
        "Qualified Another",
    ]


def test_parse_results_index_finds_recent_precinct_spreadsheets():
    links = parse_results_index((FIXTURES / "results_index_sample.html").read_text())

    urls = {link.url for link in links}
    assert any("20251202AllbyPrecinct.xlsx" in url for url in urls)
    assert any("20241105AllbyPrecinct.xlsx" in url for url in urls)


def test_parse_results_index_rejects_external_result_url():
    html = '<a href="https://example.com/results.xlsx">Results by Precinct</a>'

    assert parse_results_index(html) == []


def test_parse_precinct_xlsx_returns_result_records():
    records = parse_precinct_xlsx(
        (FIXTURES / "results_20251202_precinct_sample.xlsx").read_bytes(),
        "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/20251202AllbyPrecinct.xlsx",
    )

    assert records[0].county == "Davidson"
    assert records[0].precinct == "101"
    assert records[0].office_title == "U.S. House District 7"
    assert records[0].candidate_name == "Jane Candidate"
    assert records[0].vote_count == 123
