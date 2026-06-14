"""
Unit tests for WaVoteWaClient. HTTP calls are fully mocked — no network required.
"""
from unittest.mock import MagicMock, patch

import pytest

from integrations.wa_votewa.client import (
    KNOWN_ELECTION_SLUGS,
    WaVoteWaClient,
)
from integrations.wa_votewa.exceptions import WaVoteWaError, WaVoteWaRetryableError


# ---------------------------------------------------------------------------
# KNOWN_ELECTION_SLUGS
# ---------------------------------------------------------------------------

def test_known_slugs_are_yyyymmdd():
    import re
    for slug in KNOWN_ELECTION_SLUGS:
        assert re.fullmatch(r"\d{8}", slug), f"Slug {slug!r} is not yyyymmdd"


def test_known_slugs_include_confirmed_har_date():
    assert "20260428" in KNOWN_ELECTION_SLUGS


# ---------------------------------------------------------------------------
# get_election_metadata
# ---------------------------------------------------------------------------

def test_get_election_metadata_returns_json():
    client = WaVoteWaClient()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"electionDate": "2026-04-28", "isOfficialResults": True}

    with patch.object(client, "_get", return_value=mock_resp) as mock_get:
        result = client.get_election_metadata("20260428")

    mock_get.assert_called_once()
    called_url = mock_get.call_args[0][0]
    assert "elections/washington/20260428" in called_url
    assert result["electionDate"] == "2026-04-28"


def test_get_election_metadata_retryable_error_propagates():
    client = WaVoteWaClient()
    with patch.object(client, "_get", side_effect=WaVoteWaRetryableError("timeout")):
        with pytest.raises(WaVoteWaRetryableError):
            client.get_election_metadata("20260428")


# ---------------------------------------------------------------------------
# get_election_data
# ---------------------------------------------------------------------------

def test_get_election_data_returns_json():
    client = WaVoteWaClient()
    payload = {"jurisdiction": {"shortName": "washington"}, "ballotItems": []}
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload

    with patch.object(client, "_get", return_value=mock_resp):
        result = client.get_election_data("20260428")

    assert result["jurisdiction"]["shortName"] == "washington"


# ---------------------------------------------------------------------------
# get_county_data
# ---------------------------------------------------------------------------

def test_get_county_data_returns_json():
    client = WaVoteWaClient()
    payload = {"jurisdiction": {"shortName": "mason-county-wa"}, "ballotItems": []}
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload

    with patch.object(client, "_get", return_value=mock_resp) as mock_get:
        result = client.get_county_data("mason-county-wa", "20260428")

    called_url = mock_get.call_args[0][0]
    assert "elections/mason-county-wa/20260428/data" in called_url
    assert result["jurisdiction"]["shortName"] == "mason-county-wa"


def test_get_county_data_returns_empty_on_error():
    """County 404 / network error -> returns {} without raising."""
    client = WaVoteWaClient()
    with patch.object(client, "_get", side_effect=WaVoteWaError("404")):
        result = client.get_county_data("unknown-county-wa", "20260428")
    assert result == {}


# ---------------------------------------------------------------------------
# _get retries
# ---------------------------------------------------------------------------

def test_get_raises_retryable_on_network_error():
    client = WaVoteWaClient(max_retries=1)
    import requests as req
    with patch.object(client._session, "get", side_effect=req.ConnectionError("refused")):
        with pytest.raises(WaVoteWaRetryableError):
            client._get("https://results.votewa.gov/fake")


def test_get_raises_retryable_on_503():
    client = WaVoteWaClient(max_retries=1)
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    with patch.object(client._session, "get", return_value=mock_resp):
        with pytest.raises(WaVoteWaRetryableError):
            client._get("https://results.votewa.gov/fake")


def test_get_raises_on_404():
    client = WaVoteWaClient(max_retries=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch.object(client._session, "get", return_value=mock_resp):
        with pytest.raises(WaVoteWaError):
            client._get("https://results.votewa.gov/fake")
