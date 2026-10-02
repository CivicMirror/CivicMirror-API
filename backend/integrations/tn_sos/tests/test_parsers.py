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
    """Statuses are a denylist, not a qualified-only allowlist: live TN
    workbooks say "Signatures Approved" during filing season and nobody is
    marked Qualified yet (2026-07-15 production finding)."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Office", "Candidate Name", "Party", "Status"])
    sheet.append(["Governor", "Qualified Candidate", "Independent", "Qualified"])
    sheet.append(["Governor", "Approved Candidate", "Republican", "Signatures Approved"])
    sheet.append(["Governor", "Active Candidate", "Democratic", "Active"])
    sheet.append(["Governor", "Nominee Candidate", "Republican", "Nominee"])
    sheet.append(["Governor", "Withdrawn Candidate", "Independent", "Withdrawn"])
    sheet.append(["Governor", "Withdrew Candidate", "Independent", "Withdrew 3/1/2026"])
    sheet.append(["Governor", "Disqualified Candidate", "Independent", "Disqualified"])
    sheet.append(["Governor", "Rejected Candidate", "Independent", "Signatures Not Approved"])
    sheet.append(["Governor", "Deceased Candidate", "Independent", "Deceased"])
    content = io.BytesIO()
    workbook.save(content)

    records = parse_candidate_workbook(content.getvalue(), "https://sos.tn.gov/elections/candidates.xlsx")

    assert [record.candidate_name for record in records] == [
        "Qualified Candidate",
        "Approved Candidate",
        "Active Candidate",
        "Nominee Candidate",
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


SOFFICEL_URL = "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/20260806AllbyPrecinct.xlsx"


def test_parse_precinct_xlsx_reads_wide_sofficel_export():
    """
    The real TN export (20260806AllbyPrecinct.xlsx, sheet SOFFICEL) is "wide": one row per
    county/precinct/office/ballot style, candidates in RNAMEn/PARTYn/PVTALLYn groups. The fixture
    uses the file's real 50-column header.
    """
    records = parse_precinct_xlsx((FIXTURES / "results_20260806_sofficel_sample.xlsx").read_bytes(), SOFFICEL_URL)

    first = records[0]
    assert (first.county, first.precinct, first.office_title) == ("Anderson", "Andersonville", "Governor")
    assert (first.candidate_name, first.party, first.vote_count) == ("Marsha Blackburn", "Republican", 296)
    assert first.contest_type == "Republican Primary"
    # 3 + 2 + 3 + 3 + 2 non-empty candidate slots; empty slots 4..10 are skipped.
    assert len(records) == 13
    assert {r.contest_type for r in records} == {"Republican Primary", "Democratic Primary", "Judicial Retention"}
    assert all(r.source_url == SOFFICEL_URL for r in records)


def test_parse_precinct_xlsx_still_reads_long_format():
    records = parse_precinct_xlsx(
        (FIXTURES / "results_20251202_precinct_sample.xlsx").read_bytes(),
        "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/20251202AllbyPrecinct.xlsx",
    )
    assert [r.candidate_name for r in records] == ["Jane Candidate", "Alex Example"]
    assert all(r.contest_type == "" for r in records)


def test_parse_candidate_workbook_skips_no_candidate_qualified_placeholder():
    """TN lists 'No Candidate Qualified' for offices nobody filed for; it must not become a candidate."""
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Office", "District", "Candidate Name", "Party", "Status"])
    ws.append(["Tennessee House of Representatives", "93", "No Candidate Qualified", "", ""])
    ws.append(["Tennessee House of Representatives", "94", "Real Person", "Republican", "Qualified"])
    buf = io.BytesIO()
    wb.save(buf)

    records = parse_candidate_workbook(buf.getvalue(), "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/house.xlsx")

    assert [r.candidate_name for r in records] == ["Real Person"]
