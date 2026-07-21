import os
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from elections.models import Election
from results.adapters.mo import MissouriAdapter, MoSosRetryableError
from results.adapters.mo_parse import parse_grand_totals_text

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


_STATEWIDE_OFFICES = frozenset({
    "U.S. President and Vice President", "U.S. Senator", "Governor", "Lieutenant Governor",
})


def test_parse_grand_totals_text_extracts_all_candidate_rows_for_allowlisted_offices():
    text = _load_fixture("mo_grand_totals_page1_excerpt.txt")
    rows = parse_grand_totals_text(text, office_allowlist=_STATEWIDE_OFFICES)

    # 8 (President) + 6 (Senator) + 5 (Governor) + 4 (Lt. Governor) = 23
    assert len(rows) == 23
    by_office = {}
    for row in rows:
        by_office.setdefault(row.office_title, []).append(row)
    assert len(by_office["U.S. President and Vice President"]) == 8
    assert len(by_office["U.S. Senator"]) == 6
    assert len(by_office["Governor"]) == 5
    assert len(by_office["Lieutenant Governor"]) == 4


def test_parse_grand_totals_text_handles_names_with_commas_and_parens():
    text = _load_fixture("mo_grand_totals_page1_excerpt.txt")
    rows = parse_grand_totals_text(text, office_allowlist=_STATEWIDE_OFFICES)
    by_name = {r.candidate_name: r for r in rows}

    trump = by_name["Donald J. Trump, JD Vance"]
    assert trump.vote_count == 1751986
    assert trump.raw["party"] == "Republican"
    assert trump.office_title == "U.S. President and Vice President"

    brown = by_name["Theo (Ted) Brown Sr"]
    assert brown.vote_count == 24
    assert brown.raw["party"] == "Write-in"


def test_parse_grand_totals_text_keeps_multiple_write_in_rows_distinct():
    """MO's Grand Totals report lists each write-in filer individually with
    their own vote count — unlike MD's adapter, there is no single collapsed
    'Write-In' aggregate row to worry about here."""
    text = _load_fixture("mo_grand_totals_page1_excerpt.txt")
    rows = parse_grand_totals_text(text, office_allowlist=_STATEWIDE_OFFICES)
    president_write_ins = [
        r for r in rows
        if r.office_title == "U.S. President and Vice President" and r.raw["party"] == "Write-in"
    ]
    assert len(president_write_ins) == 4
    names = {r.candidate_name for r in president_write_ins}
    assert names == {
        "Peter Sonski, Lauren Onak", "Claudia De la Cruz, Karina Garcia",
        "Shiva Ayyadurai, Crystal Ellis", "Future Madam Potus, Jessica Kennedy",
    }
    assert all(r.is_write_in_aggregate is False for r in president_write_ins)


def test_parse_grand_totals_text_sets_result_type_and_vote_pct():
    text = _load_fixture("mo_grand_totals_page1_excerpt.txt")
    rows = parse_grand_totals_text(text, office_allowlist=_STATEWIDE_OFFICES)
    hawley = next(r for r in rows if r.candidate_name == "Josh Hawley")
    assert hawley.result_type == "official"
    assert hawley.vote_pct == 55.6


def test_parse_grand_totals_text_excludes_offices_not_in_allowlist():
    text = _load_fixture("mo_grand_totals_page1_excerpt.txt")
    rows = parse_grand_totals_text(text, office_allowlist=frozenset({"Attorney General"}))
    assert rows == []


def test_parse_grand_totals_text_ignores_total_votes_lines():
    text = "Governor (1 of 1 Precincts Reported)\nJane Doe Republican 100 100.0%\nTotal Votes 100\n"
    rows = parse_grand_totals_text(text, office_allowlist=frozenset({"Governor"}))
    assert len(rows) == 1
    assert rows[0].candidate_name == "Jane Doe"


@patch("results.adapters.mo.requests.get")
def test_fetch_grand_totals_pdf_sends_browser_user_agent(mock_get):
    response = MagicMock(status_code=200, content=b"%PDF-1.4\n...")
    mock_get.return_value = response

    result = MissouriAdapter()._fetch_grand_totals_pdf_bytes("https://www.sos.mo.gov/example.pdf")

    assert result == b"%PDF-1.4\n..."
    called_headers = mock_get.call_args.kwargs["headers"]
    assert "Mozilla" in called_headers["User-Agent"]


@patch("results.adapters.mo.requests.get")
def test_fetch_grand_totals_pdf_rejects_non_pdf_content(mock_get):
    """MO SOS returns HTTP 200 with a Cloudflare challenge-page body when the
    request lacks a browser User-Agent — must be detected by content
    (missing %PDF magic bytes), never trusted by status code alone."""
    response = MagicMock(status_code=200, content=b"<!DOCTYPE html><html>Just a moment...</html>")
    mock_get.return_value = response

    with pytest.raises(MoSosRetryableError):
        MissouriAdapter()._fetch_grand_totals_pdf_bytes("https://www.sos.mo.gov/example.pdf")


@pytest.mark.django_db
@patch("results.adapters.mo.MissouriAdapter._fetch_grand_totals_pdf_bytes")
@patch("results.adapters.mo.pdfplumber")
def test_fetch_results_extracts_text_and_parses_statewide_offices(mock_pdfplumber, mock_fetch):
    election = Election.objects.create(
        name="2024 Missouri General Election",
        election_date=date(2024, 11, 5),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MO",
        source_id="mo-2024-general",
        status=Election.Status.RESULTS_CERTIFIED,
    )
    mock_fetch.return_value = b"%PDF-1.4\n..."

    fixture_text = _load_fixture("mo_grand_totals_page1_excerpt.txt")
    mock_page = MagicMock()
    mock_page.extract_text.return_value = fixture_text
    mock_pdf_context = MagicMock()
    mock_pdf_context.__enter__.return_value.pages = [mock_page]
    mock_pdfplumber.open.return_value = mock_pdf_context

    result = MissouriAdapter().fetch_results(election_date=election.election_date, election_id=election.pk)

    assert result.mapping_confidence == "full"
    assert len(result.rows) == 23
    offices = {r.office_title for r in result.rows}
    assert offices == {"U.S. President and Vice President", "U.S. Senator", "Governor", "Lieutenant Governor"}


@pytest.mark.django_db
@patch("results.adapters.mo.MissouriAdapter._fetch_grand_totals_pdf_bytes")
@patch("results.adapters.mo.pdfplumber")
def test_fetch_results_returns_unchanged_when_checksum_matches_cache(mock_pdfplumber, mock_fetch):
    from django.core.cache import cache

    election = Election.objects.create(
        name="2024 Missouri General Election",
        election_date=date(2024, 11, 5),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MO",
        source_id="mo-2024-general-2",
        status=Election.Status.RESULTS_CERTIFIED,
    )
    mock_fetch.return_value = b"%PDF-1.4\n..."
    fixture_text = _load_fixture("mo_grand_totals_page1_excerpt.txt")
    mock_page = MagicMock()
    mock_page.extract_text.return_value = fixture_text
    mock_pdf_context = MagicMock()
    mock_pdf_context.__enter__.return_value.pages = [mock_page]
    mock_pdfplumber.open.return_value = mock_pdf_context

    adapter = MissouriAdapter()
    first = adapter.fetch_results(election_date=election.election_date, election_id=election.pk)
    cache.set(adapter.version_cache_key(election.pk), first.source_version)

    second = adapter.fetch_results(election_date=election.election_date, election_id=election.pk)
    assert second.unchanged is True
    assert second.rows == []


@pytest.mark.django_db
def test_fetch_results_returns_empty_for_missing_election():
    result = MissouriAdapter().fetch_results(election_date=date(2024, 11, 5), election_id=999999)
    assert result.rows == []
    assert result.mapping_confidence == "none"
