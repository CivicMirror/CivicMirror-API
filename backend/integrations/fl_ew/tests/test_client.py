"""
Unit tests for FlEwClient. HTTP calls are fully mocked — no network required.
"""
import re
from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib

from integrations.fl_ew.client import KNOWN_ELECTION_SLUGS, FlEwClient
from integrations.fl_ew.exceptions import FlEwError, FlEwRetryableError


# ---------------------------------------------------------------------------
# KNOWN_ELECTION_SLUGS
# ---------------------------------------------------------------------------

def test_known_slugs_are_yyyymmdd():
    for slug in KNOWN_ELECTION_SLUGS:
        assert re.fullmatch(r"\d{8}", slug), f"Slug {slug!r} is not yyyymmdd"


def test_known_slugs_include_august_primary():
    assert "20260818" in KNOWN_ELECTION_SLUGS


def test_known_slugs_include_november_general():
    assert "20261103" in KNOWN_ELECTION_SLUGS


# ---------------------------------------------------------------------------
# results_url / file_url
# ---------------------------------------------------------------------------

def test_file_url_pattern():
    client = FlEwClient()
    url = client.file_url("20260818")
    assert url == (
        "https://flelectionfiles.floridados.gov/enightfilespublic/"
        "20260818_ElecResultsFL.txt"
    )


# ---------------------------------------------------------------------------
# get_last_modified
# ---------------------------------------------------------------------------

def test_get_last_modified_returns_header():
    client = FlEwClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Last-Modified": "Mon, 18 Aug 2026 01:00:00 GMT"}

    with patch.object(client._session, "head", return_value=mock_resp):
        result = client.get_last_modified("20260818")

    assert result == "Mon, 18 Aug 2026 01:00:00 GMT"


def test_get_last_modified_returns_empty_on_404():
    client = FlEwClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch.object(client._session, "head", return_value=mock_resp):
        result = client.get_last_modified("20260818")

    assert result == ""


def test_get_last_modified_returns_empty_on_network_error():
    client = FlEwClient()
    with patch.object(client._session, "head", side_effect=req_lib.ConnectionError("refused")):
        result = client.get_last_modified("20260818")
    assert result == ""


# ---------------------------------------------------------------------------
# fetch_results_file
# ---------------------------------------------------------------------------

def test_fetch_results_file_returns_text():
    client = FlEwClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ElectionDate\tPartyCode\n03/24/2026\tREP\n"

    with patch.object(client._session, "get", return_value=mock_resp):
        text = client.fetch_results_file("20260324")

    assert "ElectionDate" in text


def test_fetch_results_file_raises_retryable_on_503():
    client = FlEwClient(max_retries=1)
    mock_resp = MagicMock()
    mock_resp.status_code = 503

    with patch.object(client._session, "get", return_value=mock_resp):
        with pytest.raises(FlEwRetryableError):
            client.fetch_results_file("20260818")


def test_fetch_results_file_raises_on_404():
    client = FlEwClient(max_retries=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch.object(client._session, "get", return_value=mock_resp):
        with pytest.raises(FlEwError):
            client.fetch_results_file("20260818")


def test_fetch_results_file_raises_retryable_on_network_error():
    client = FlEwClient(max_retries=1)
    with patch.object(client._session, "get", side_effect=req_lib.ConnectionError("down")):
        with pytest.raises(FlEwRetryableError):
            client.fetch_results_file("20260818")
