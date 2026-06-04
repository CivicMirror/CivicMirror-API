"""
Unit tests for the NC SBE results adapter (results/adapters/nc.py).
All HTTP calls are mocked — no network access required.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.nc import (
    NorthCarolinaAdapter,
    _aggregate_rows,
    _date_str_from_url,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_zip(tsv_content: str) -> bytes:
    """Create an in-memory ZIP containing a results TSV file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("results_pct_20241105.txt", tsv_content.encode("latin-1"))
    return buf.getvalue()


_TSV_HEADER = (
    "County\tElection Date\tPrecinct\tContest Group ID\tContest Type\t"
    "Contest Name\tChoice\tChoice Party\tVote For\tElection Day\t"
    "Early Voting\tAbsentee by Mail\tProvisional\tTotal Votes\tReal Precinct\n"
)

_TSV_ROWS = (
    "WAKE\t11/05/2024\t01-01\t100\tS\tNC GOVERNOR\tTom Jones\tDEM\t1\t1000\t500\t200\t10\t1710\tY\n"
    "WAKE\t11/05/2024\t01-02\t100\tS\tNC GOVERNOR\tTom Jones\tDEM\t1\t800\t400\t100\t5\t1305\tY\n"
    "WAKE\t11/05/2024\t01-01\t100\tS\tNC GOVERNOR\tSally Brown\tREP\t1\t900\t450\t150\t8\t1508\tY\n"
    "BUNCOMBE\t11/05/2024\t01.1\t22\tC\tCITY OF ASHEVILLE TRANSPORTATION BONDS REFERENDUM\tNo\t\t1\t62\t215\t20\t1\t298\tY\n"
    "BUNCOMBE\t11/05/2024\t01.1\t22\tC\tCITY OF ASHEVILLE TRANSPORTATION BONDS REFERENDUM\tYes\t\t1\t120\t410\t50\t5\t585\tY\n"
    "WAKE\t11/05/2024\t01-01\t200\tS\tNC GOVERNOR\tWrite-In (Miscellaneous)\t\t1\t5\t2\t0\t0\t7\tY\n"
)

_SAMPLE_ZIP = _make_zip(_TSV_HEADER + _TSV_ROWS)


# ---------------------------------------------------------------------------
# _aggregate_rows
# ---------------------------------------------------------------------------

def test_aggregate_rows_sums_precinct_votes():
    from integrations.nc_sbe.client import parse_results_tsv
    raw = parse_results_tsv(_SAMPLE_ZIP)
    rows = _aggregate_rows(raw)

    gov_jones = next((r for r in rows if r.office_title == "NC GOVERNOR" and r.candidate_name == "Tom Jones"), None)
    assert gov_jones is not None
    assert gov_jones.vote_count == 1710 + 1305  # summed across two precincts


def test_aggregate_rows_marks_write_in():
    from integrations.nc_sbe.client import parse_results_tsv
    raw = parse_results_tsv(_SAMPLE_ZIP)
    rows = _aggregate_rows(raw)

    write_in = next((r for r in rows if r.is_write_in_aggregate), None)
    assert write_in is not None
    assert write_in.candidate_name is None
    assert write_in.office_title == "NC GOVERNOR"


def test_aggregate_rows_result_type_is_official():
    from integrations.nc_sbe.client import parse_results_tsv
    raw = parse_results_tsv(_SAMPLE_ZIP)
    rows = _aggregate_rows(raw)

    assert all(r.result_type == "official" for r in rows)


def test_aggregate_rows_ballot_measure_uses_candidate_name():
    """Ballot measure choices (Yes/No) should appear as candidate_name (framework coerces later)."""
    from integrations.nc_sbe.client import parse_results_tsv
    raw = parse_results_tsv(_SAMPLE_ZIP)
    rows = _aggregate_rows(raw)

    measure_rows = [r for r in rows if "REFERENDUM" in (r.office_title or "")]
    assert len(measure_rows) == 2  # Yes + No
    labels = {r.candidate_name for r in measure_rows}
    assert labels == {"Yes", "No"}


def test_aggregate_rows_empty_input():
    assert _aggregate_rows([]) == []


def test_aggregate_rows_skips_rows_without_contest_or_choice():
    raw = [
        {"Contest Name": "", "Choice": "Tom Jones", "Total Votes": "100", "Contest Type": "S"},
        {"Contest Name": "NC GOVERNOR", "Choice": "", "Total Votes": "100", "Contest Type": "S"},
    ]
    assert _aggregate_rows(raw) == []


# ---------------------------------------------------------------------------
# _date_str_from_url
# ---------------------------------------------------------------------------

def test_date_str_from_url():
    url = "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2024_11_05/results_pct_20241105.zip"
    assert _date_str_from_url(url) == "2024_11_05"


def test_date_str_from_url_unknown():
    assert _date_str_from_url("https://example.com/unknown.zip") == ""


# ---------------------------------------------------------------------------
# NorthCarolinaAdapter.fetch_results
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_adapter_returns_unchanged_when_etag_matches():
    from results.adapters.nc import NorthCarolinaAdapter
    from elections.models import Election

    election = Election.objects.create(
        source_id="nc_sbe_2024_11_05",
        name="2024 NC General",
        state="NC",
        election_type="general",
        election_date=date(2024, 11, 5),
        status="RESULTS_PENDING",
        jurisdiction_level="STATE",
        source_metadata={"nc_date_str": "2024_11_05", "results_url": "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2024_11_05/results_pct_20241105.zip"},
    )

    adapter = NorthCarolinaAdapter()
    cached_etag = "abc123"

    with patch("results.adapters.nc.cache") as mock_cache, \
         patch("results.adapters.nc.NcSbeClient") as MockClient:
        mock_cache.get.return_value = cached_etag
        MockClient.return_value.fetch_results_etag.return_value = cached_etag

        result = adapter.fetch_results(election.election_date, election.pk)

    assert result.unchanged is True
    assert result.source_version == cached_etag


@pytest.mark.django_db
def test_adapter_fetches_and_parses_when_etag_differs():
    from results.adapters.nc import NorthCarolinaAdapter
    from elections.models import Election

    election = Election.objects.create(
        source_id="nc_sbe_2024_11_05_v2",
        name="2024 NC General",
        state="NC",
        election_type="general",
        election_date=date(2024, 11, 5),
        status="RESULTS_PENDING",
        jurisdiction_level="STATE",
        source_metadata={"nc_date_str": "2024_11_05", "results_url": "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2024_11_05/results_pct_20241105.zip"},
    )

    adapter = NorthCarolinaAdapter()

    with patch("results.adapters.nc.cache") as mock_cache, \
         patch("results.adapters.nc.NcSbeClient") as MockClient, \
         patch("results.adapters.nc._fetch_zip", return_value=_SAMPLE_ZIP):
        mock_cache.get.return_value = "old_etag"
        MockClient.return_value.fetch_results_etag.return_value = "new_etag"

        result = adapter.fetch_results(election.election_date, election.pk)

    assert result.unchanged is False
    assert len(result.rows) > 0
    assert result.mapping_confidence == "full"


@pytest.mark.django_db
def test_adapter_handles_missing_election():
    from results.adapters.nc import NorthCarolinaAdapter

    adapter = NorthCarolinaAdapter()
    result = adapter.fetch_results(date(2024, 11, 5), 999999)

    assert result.rows == []
    assert result.mapping_confidence == "none"


def test_nc_adapter_is_registered():
    """NC must be in list_supported_states() so poll_pending_results queues it."""
    from results.adapters import list_supported_states

    assert "NC" in list_supported_states()
