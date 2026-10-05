import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from cm2_ingestion.contracts import ContractValidationError
from cm2_nc.constants import CANDIDATE_LIST_URL, UPCOMING_ELECTIONS_URL
from cm2_nc.sources.candidate_filings import NcCandidateRowsSource, parse_candidate_rows
from cm2_nc.sources.results import NcResultsZipSource, parse_results_rows, results_zip_url
from cm2_nc.sources.upcoming_elections import NcUpcomingElectionsSource, parse_upcoming_elections

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content
        self.status_checked = False

    def raise_for_status(self):
        self.status_checked = True


class FakeSession:
    def __init__(self, content: bytes):
        self.response = FakeResponse(content)
        self.calls = []

    def get(self, url, *, timeout):
        self.calls.append((url, timeout))
        return self.response


def test_upcoming_parser_uses_explicit_sections_and_ignores_deadline_dates():
    records = parse_upcoming_elections(
        (FIXTURES / "upcoming_elections_2026.html").read_bytes(),
        source_artifact_public_id="artifact/upcoming-2026",
    )

    assert [(record.name, record.election_date, record.election_type) for record in records] == [
        ("Statewide Primary Election", date(2026, 3, 3), "primary"),
        ("Statewide General Election", date(2026, 11, 3), "general"),
    ]
    assert {record.source_artifact_public_id for record in records} == {"artifact/upcoming-2026"}
    assert all(record.lifecycle_status == "upcoming" for record in records)


def test_upcoming_parser_uses_label_not_month_to_classify_election():
    content = b"""
        <h2>May General Election</h2>
        <p>Election Day is May 12, 2026.</p>
        <h2>November Special Election</h2>
        <p>Election Day is November 17, 2026.</p>
    """

    records = parse_upcoming_elections(content)

    assert [(record.election_date, record.election_type) for record in records] == [
        (date(2026, 5, 12), "general"),
        (date(2026, 11, 17), "special"),
    ]


def test_candidate_parser_returns_typed_rows_and_preserves_protected_evidence():
    rows = parse_candidate_rows((FIXTURES / "candidate_listing_2026_sanitized.csv").read_bytes())

    assert len(rows) == 13
    first = rows[0]
    assert first.row_number == 2
    assert first.election_date == date(2026, 11, 3)
    assert first.contest_name == "US HOUSE OF REPRESENTATIVES DISTRICT 09"
    assert first.is_unexpired is False
    assert first.has_primary is False
    assert first.is_partisan is True
    assert first.vote_for == 1
    assert first.term_years == 2
    assert first.protected_address == "REDACTED ADDRESS 1, REDACTED, NC 00000"
    assert first.protected_phone == "0000000000"
    assert first.protected_email == "redacted1@example.invalid"


def test_candidate_parser_rejects_missing_required_header():
    content = b"election_dt,county_name\n11/03/2026,WAKE\n"

    with pytest.raises(ContractValidationError, match="candidate CSV is missing required columns"):
        parse_candidate_rows(content)


def test_candidate_parser_error_identifies_structure_without_echoing_private_value():
    private_value = "private-person@example.test"
    columns = (FIXTURES / "candidate_listing_2026_sanitized.csv").read_text().splitlines()[0]
    raw = (FIXTURES / "candidate_listing_2026_sanitized.csv").read_text().splitlines()[1].split(",")
    raw[22] = "NOT-BOOLEAN"
    raw[16] = private_value
    content = (columns + "\n" + ",".join(raw) + "\n").encode()

    with pytest.raises(ContractValidationError) as exc_info:
        parse_candidate_rows(content)

    assert "row 2 field is_partisan" in str(exc_info.value)
    assert private_value not in str(exc_info.value)


@pytest.mark.parametrize(
    ("source_class", "url", "payload"),
    [
        (NcUpcomingElectionsSource, UPCOMING_ELECTIONS_URL, b"<html></html>"),
        (NcCandidateRowsSource, CANDIDATE_LIST_URL, b"candidate,data\n"),
    ],
)
def test_source_acquisition_uses_official_url_timeout_and_status_check(source_class, url, payload):
    session = FakeSession(payload)
    source = source_class(session=session)

    assert source.acquire() == payload
    assert session.calls == [(url, 60)]
    assert session.response.status_checked is True


def _zip_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("results_pct_20260303.txt", text)
    return buffer.getvalue()


def test_parse_results_rows_reads_tab_delimited_zip_entry():
    content = (FIXTURES / "results_pct_sanitized.txt").read_text()
    rows = parse_results_rows(_zip_bytes(content))

    assert len(rows) == 11
    first = rows[0]
    assert first.county_name == "BUNCOMBE"
    assert first.election_date == date(2026, 3, 3)
    assert first.precinct == "19.1"
    assert first.contest_type == "S"
    assert first.contest_name == "US HOUSE OF REPRESENTATIVES DISTRICT 11 (REP)"
    assert first.choice == "Chuck Edwards"
    assert first.choice_party == "REP"
    assert first.vote_for == 1
    assert first.total_votes == 33
    assert first.is_real_precinct is True


def test_parse_results_rows_handles_blank_choice_party():
    content = (FIXTURES / "results_pct_sanitized.txt").read_text()
    rows = parse_results_rows(_zip_bytes(content))
    nonpartisan = next(row for row in rows if row.choice == "Nina Ireland")
    assert nonpartisan.choice_party == ""


def test_parse_results_rows_treats_data_unavailable_placeholder_as_empty():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Readme.txt", "Data Unavailable")
    assert parse_results_rows(buffer.getvalue()) == ()


def test_results_zip_url_uses_enrs_prefix():
    assert results_zip_url(date(2026, 3, 3)) == (
        "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2026_03_03/results_pct_20260303.zip"
    )


def test_nc_results_zip_source_builds_url_from_election_date():
    source = NcResultsZipSource(election_date=date(2026, 3, 3))
    assert source.url.endswith("ENRS/2026_03_03/results_pct_20260303.zip")
