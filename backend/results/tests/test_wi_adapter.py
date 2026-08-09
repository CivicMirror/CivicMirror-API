"""Tests for the Wisconsin results adapter (WEC Canvass Reporting System)."""

from __future__ import annotations

import io
from datetime import date
from unittest.mock import MagicMock, patch

import openpyxl
import pytest

from elections.models import Election

pytestmark = pytest.mark.django_db


def _build_workbook(sheets: list[dict]) -> bytes:
    """Build a WEC "County by County Report" workbook in the real shape:

    Sheet 1 ("Document map"): title row + one contest-title row per sheet.
    Sheet N: title rows, blank, contest title, blank, header row ("County",
    "", "Total Votes Cast", <party per candidate column>...), candidate-name
    row, then one row per county with vote counts aligned to candidate cols.
    """
    wb = openpyxl.Workbook()
    doc_map = wb.active
    doc_map.title = "Document map"
    doc_map.append(["County by County Report"])
    for sheet in sheets:
        doc_map.append([None, sheet["office_title"]])

    for i, sheet in enumerate(sheets, start=2):
        ws = wb.create_sheet(f"Sheet{i}")
        ws.append(["WEC Canvass Reporting System\nCounty by County Report"])
        ws.append([None, sheet.get("election_name", "2026 Fall Primary")])
        ws.append([])
        ws.append([sheet["office_title"]])
        ws.append([])
        header = ["County", None, "Total Votes Cast"] + [c["party"] for c in sheet["candidates"]]
        ws.append(header)
        names = [None, None, None] + [c["name"] for c in sheet["candidates"]]
        ws.append(names)
        for county_row in sheet["counties"]:
            county_name, votes = county_row
            total = sum(votes)
            ws.append([county_name, None, total, *votes])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_SAMPLE_SHEETS = [
    {
        "office_title": "STATE SUPERINTENDENT OF PUBLIC INSTRUCTION",
        "candidates": [
            {"party": "NP", "name": "Brittany  Kinser"},
            {"party": "NP", "name": "Jill  Underly"},
            {"party": "", "name": "SCATTERING"},
        ],
        "counties": [
            ("ADAMS ", [4785, 3541, 54]),
            ("ASHLAND ", [2578, 3296, 42]),
        ],
    },
]


@pytest.fixture
def wi_election(db):
    return Election.objects.create(
        state="WI",
        election_date=date(2026, 8, 11),
        election_type="primary",
        name="2026 Wisconsin Primary Election",
        source_metadata={
            "wi_results_xlsx_url": "https://elections.wi.gov/sites/default/files/documents/sample.xlsx",
        },
    )


def test_parse_workbook_sums_county_rows_into_statewide_totals():
    from results.adapters.wi import _parse_workbook

    file_bytes = _build_workbook(_SAMPLE_SHEETS)
    rows = _parse_workbook(file_bytes)

    kinser = next(r for r in rows if r.candidate_name == "Brittany  Kinser")
    underly = next(r for r in rows if r.candidate_name == "Jill  Underly")

    assert kinser.vote_count == 4785 + 2578
    assert underly.vote_count == 3541 + 3296
    assert kinser.office_title == "STATE SUPERINTENDENT OF PUBLIC INSTRUCTION"


def test_parse_workbook_marks_scattering_as_write_in_aggregate():
    from results.adapters.wi import _parse_workbook

    file_bytes = _build_workbook(_SAMPLE_SHEETS)
    rows = _parse_workbook(file_bytes)

    scattering = next(r for r in rows if r.is_write_in_aggregate)
    assert scattering.candidate_name is None
    assert scattering.vote_count == 54 + 42


def test_parse_workbook_marks_highest_vote_getter_as_winner_excluding_scattering():
    from results.adapters.wi import _parse_workbook

    file_bytes = _build_workbook(_SAMPLE_SHEETS)
    rows = _parse_workbook(file_bytes)

    winners = [r for r in rows if r.is_winner]
    assert len(winners) == 1
    assert winners[0].candidate_name == "Brittany  Kinser"

    scattering = next(r for r in rows if r.is_write_in_aggregate)
    assert scattering.is_winner is False


def test_parse_workbook_computes_vote_pct_from_contest_total():
    from results.adapters.wi import _parse_workbook

    file_bytes = _build_workbook(_SAMPLE_SHEETS)
    rows = _parse_workbook(file_bytes)

    contest_total = sum(r.vote_count for r in rows)
    for row in rows:
        assert row.vote_pct == pytest.approx(row.vote_count / contest_total * 100, abs=0.01)


def test_parse_workbook_handles_multiple_contests():
    from results.adapters.wi import _parse_workbook

    sheets = _SAMPLE_SHEETS + [
        {
            "office_title": "ATTORNEY GENERAL",
            "candidates": [
                {"party": "DEM", "name": "SMITH, Jane"},
                {"party": "REP", "name": "DOE, John"},
            ],
            "counties": [
                ("ADAMS ", [100, 200]),
            ],
        },
    ]
    file_bytes = _build_workbook(sheets)
    rows = _parse_workbook(file_bytes)

    titles = {r.office_title for r in rows}
    assert titles == {"STATE SUPERINTENDENT OF PUBLIC INSTRUCTION", "ATTORNEY GENERAL"}


def test_parse_workbook_skips_document_map_sheet():
    from results.adapters.wi import _parse_workbook

    file_bytes = _build_workbook(_SAMPLE_SHEETS)
    rows = _parse_workbook(file_bytes)

    assert all(r.office_title != "County by County Report" for r in rows)


@patch("results.adapters.wi.requests.get")
def test_fetch_results_returns_no_url_when_metadata_missing(mock_get, db):
    from results.adapters.wi import WisconsinAdapter

    election = Election.objects.create(
        state="WI",
        election_date=date(2026, 8, 11),
        election_type="primary",
        name="2026 Wisconsin Primary Election",
        source_metadata={},
    )

    adapter = WisconsinAdapter()
    result = adapter.fetch_results(election.election_date, election.pk)

    assert result.rows == []
    assert result.mapping_confidence == "none"
    mock_get.assert_not_called()


@patch("results.adapters.wi.requests.get")
def test_fetch_results_fetches_and_parses_configured_url(mock_get, wi_election):
    from results.adapters.wi import WisconsinAdapter

    file_bytes = _build_workbook(_SAMPLE_SHEETS)
    mock_resp = MagicMock()
    mock_resp.content = file_bytes
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    adapter = WisconsinAdapter()
    result = adapter.fetch_results(wi_election.election_date, wi_election.pk)

    assert result.mapping_confidence == "full"
    assert len(result.rows) == 3
    mock_get.assert_called_once()
    called_url = mock_get.call_args[0][0]
    assert called_url == "https://elections.wi.gov/sites/default/files/documents/sample.xlsx"


@patch("results.adapters.wi.requests.get")
def test_fetch_results_unchanged_when_fingerprint_matches_cache(mock_get, wi_election):
    from results.adapters.wi import WisconsinAdapter

    file_bytes = _build_workbook(_SAMPLE_SHEETS)
    mock_resp = MagicMock()
    mock_resp.content = file_bytes
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    adapter = WisconsinAdapter()
    first = adapter.fetch_results(wi_election.election_date, wi_election.pk)
    from django.core.cache import cache
    cache.set(adapter.version_cache_key(wi_election.pk), first.source_version, timeout=60)

    second = adapter.fetch_results(wi_election.election_date, wi_election.pk)

    assert second.unchanged is True
    assert second.rows == []
