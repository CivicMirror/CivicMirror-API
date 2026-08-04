import datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

from integrations.md_sbe.client import MdSbeClient
from integrations.md_sbe.exceptions import MdSbeRetryableError


def test_county_codes_span_01_through_24():
    assert MdSbeClient.COUNTY_CODES[0] == "01"
    assert MdSbeClient.COUNTY_CODES[-1] == "24"
    assert len(MdSbeClient.COUNTY_CODES) == 24


@patch("integrations.md_sbe.client.requests.Session.get")
def test_fetch_county_results_builds_expected_url_and_decodes_utf8_sig(mock_get):
    response = MagicMock(status_code=200)
    # utf-8-sig decoding must strip a BOM if present, and be a no-op if absent.
    # encode("utf-8-sig") already prepends a single leading BOM to the bytes —
    # the source string itself must NOT also contain a literal BOM character,
    # or this would simulate an unrealistic double-BOM byte stream.
    response.content = "Office Name,Total Votes\r\nU.S. Senator,100\r\n".encode("utf-8-sig")
    mock_get.return_value = response

    text = MdSbeClient().fetch_county_results(year=2024, cycle_prefix="PG", county_code="01")

    assert text == "Office Name,Total Votes\r\nU.S. Senator,100\r\n"
    called_url = mock_get.call_args[0][0]
    assert called_url == (
        "https://elections.maryland.gov/elections/archive/2024/election_data/"
        "PG24_01CountyResults.csv"
    )


@patch("integrations.md_sbe.client.requests.Session.get")
def test_fetch_county_results_treats_soft_404_as_retryable(mock_get):
    """MD SBE returns HTTP 200 with a ~14KB 'Page Not Found' HTML body for missing
    pages instead of a real 404 — must be detected by content, not status code."""
    response = MagicMock(status_code=200)
    response.content = ("<html><body>Page Not Found</body></html>" + "x" * 14400).encode("utf-8")
    mock_get.return_value = response

    with pytest.raises(MdSbeRetryableError):
        MdSbeClient().fetch_county_results(year=2024, cycle_prefix="PG", county_code="99")


@patch("integrations.md_sbe.client.requests.Session.get")
def test_fetch_county_results_raises_on_connection_error(mock_get):
    mock_get.side_effect = requests.ConnectionError("boom")

    with pytest.raises(MdSbeRetryableError):
        MdSbeClient().fetch_county_results(year=2024, cycle_prefix="PG", county_code="01")


@patch("integrations.md_sbe.client.requests.Session.get")
def test_fetch_statewide_candidate_csv_primary_phase(mock_get):
    """Fetch primary candidate list and build correct URL with full year and cycle prefix."""
    response = MagicMock(status_code=200)
    response.content = "Office Name,Candidate Name\r\nGovernor,Jane Doe\r\n".encode("utf-8-sig")
    mock_get.return_value = response

    text = MdSbeClient().fetch_statewide_candidate_csv(year=2026, cycle_prefix="GP", phase="primary")

    assert text == "Office Name,Candidate Name\r\nGovernor,Jane Doe\r\n"
    called_url = mock_get.call_args[0][0]
    assert called_url == (
        "https://elections.maryland.gov/elections/2026/primary_candidates/"
        "2026_GP_statewide_candidatelist.csv"
    )


@patch("integrations.md_sbe.client.requests.Session.get")
def test_fetch_statewide_candidate_csv_general_phase(mock_get):
    """Fetch general candidate list and build correct URL with full year and cycle prefix."""
    response = MagicMock(status_code=200)
    response.content = "Office Name,Candidate Name\r\nSenator,John Smith\r\n".encode("utf-8-sig")
    mock_get.return_value = response

    text = MdSbeClient().fetch_statewide_candidate_csv(year=2026, cycle_prefix="GG", phase="general")

    assert text == "Office Name,Candidate Name\r\nSenator,John Smith\r\n"
    called_url = mock_get.call_args[0][0]
    assert called_url == (
        "https://elections.maryland.gov/elections/2026/general_candidates/"
        "2026_GG_statewide_candidatelist.csv"
    )


def test_candidate_csv_url_uses_the_phase_specific_prefix():
    """MD's prefix is [cycle letter][phase letter]. The 2026 gubernatorial
    cycle's primary list is GP, its general list GG — reusing GP for the
    general soft-404s (verified live 2026-08-04)."""
    from integrations.md_sbe.calendar import get_active_cycle
    cycle = get_active_cycle(datetime.date(2026, 3, 1))

    assert MdSbeClient.build_candidate_csv_url(
        year=cycle.year, cycle_prefix=cycle.prefix_for_phase("primary"), phase="primary",
    ) == (
        "https://elections.maryland.gov/elections/2026/primary_candidates/"
        "2026_GP_statewide_candidatelist.csv"
    )
    assert MdSbeClient.build_candidate_csv_url(
        year=cycle.year, cycle_prefix=cycle.prefix_for_phase("general"), phase="general",
    ) == (
        "https://elections.maryland.gov/elections/2026/general_candidates/"
        "2026_GG_statewide_candidatelist.csv"
    )


def test_build_url_serves_current_cycle_from_non_archive_path():
    """A cycle only moves under /elections/archive/ once it is over."""
    assert MdSbeClient.build_url(
        year=2026, cycle_prefix="GG", county_code="01", archived=False,
    ) == (
        "https://elections.maryland.gov/elections/2026/election_data/"
        "GG26_01CountyResults.csv"
    )
    assert MdSbeClient.build_url(
        year=2024, cycle_prefix="PG", county_code="01", archived=True,
    ) == (
        "https://elections.maryland.gov/elections/archive/2024/election_data/"
        "PG24_01CountyResults.csv"
    )


def test_build_party_results_url_matches_live_primary_filename_shape():
    """Verified live 2026-08-04 against
    /elections/2026/election_data/index.html, which lists
    GP26_01DemocraticResults.csv / GP26_01RepublicanResults.csv but no
    GP26_01CountyResults.csv."""
    assert MdSbeClient.build_party_results_url(
        year=2026, cycle_prefix="GP", county_code="01", party="Democratic", archived=False,
    ) == (
        "https://elections.maryland.gov/elections/2026/election_data/"
        "GP26_01DemocraticResults.csv"
    )
    assert MdSbeClient.build_party_results_url(
        year=2026, cycle_prefix="GP", county_code="12", party="Republican", archived=False,
    ) == (
        "https://elections.maryland.gov/elections/2026/election_data/"
        "GP26_12RepublicanResults.csv"
    )


@patch("integrations.md_sbe.client.requests.Session.get")
def test_fetch_county_party_results_fetches_the_per_party_file(mock_get):
    response = MagicMock(status_code=200)
    response.content = (
        '"Office Name","Office District","Candidate Name","Party","Winner","Total Votes"\r\n'
        '"Governor / Lt. Governor","","Wes Moore and Aruna Miller","DEM","Y","559"\r\n'
    ).encode("utf-8-sig")
    mock_get.return_value = response

    text = MdSbeClient().fetch_county_party_results(
        year=2026, cycle_prefix="GP", county_code="01", party="Democratic", archived=False,
    )

    assert "Wes Moore and Aruna Miller" in text
    assert mock_get.call_args[0][0] == (
        "https://elections.maryland.gov/elections/2026/election_data/"
        "GP26_01DemocraticResults.csv"
    )


@patch("integrations.md_sbe.client.requests.Session.get")
def test_fetch_county_party_results_treats_soft_404_as_retryable(mock_get):
    response = MagicMock(status_code=200)
    response.content = ("<html><body>Page Not Found</body></html>" + "x" * 14400).encode("utf-8")
    mock_get.return_value = response

    with pytest.raises(MdSbeRetryableError):
        MdSbeClient().fetch_county_party_results(
            year=2026, cycle_prefix="GP", county_code="01", party="Green", archived=False,
        )


@patch("integrations.md_sbe.client.requests.Session.get")
def test_fetch_statewide_candidate_csv_soft_404(mock_get):
    """Detect soft-404 in candidate list response."""
    response = MagicMock(status_code=200)
    response.content = ("<html><body>Page Not Found</body></html>" + "x" * 14400).encode("utf-8")
    mock_get.return_value = response

    with pytest.raises(MdSbeRetryableError):
        MdSbeClient().fetch_statewide_candidate_csv(year=2026, cycle_prefix="GP", phase="primary")
