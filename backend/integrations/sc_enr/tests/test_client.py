"""
Tests for the SC ENR client.
"""
from unittest.mock import MagicMock, patch

import pytest

from integrations.sc_enr.client import ENR_ELECTIONS_URL, ENRClient
from integrations.sc_enr.exceptions import SCEnrError, SCEnrRetryableError


def _mock_resp(status: int, json_data=None, url="https://www.enr-scvotes.org/SC/125820/web.345435/"):
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = json_data if json_data is not None else []
    mock.url = url
    mock.raise_for_status = MagicMock()
    return mock


@pytest.fixture
def client():
    return ENRClient(timeout=5, max_retries=1)


# ------------------------------------------------------------------
# get_elections
# ------------------------------------------------------------------

def test_get_elections_returns_empty_list(client):
    with patch("integrations.sc_enr.client.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(200, json_data=[])
        result = client.get_elections()
    assert result == []


def test_get_elections_returns_entries(client):
    feed = [
        {"ElectionName": "2026 General", "Date": "11/03/2026 07:00:00", "State": "SC", "County": None, "EID": 130000},
        {"ElectionName": "2026 General", "Date": "11/03/2026 07:00:00", "State": "SC", "County": "Charleston", "EID": 121000},
    ]
    with patch("integrations.sc_enr.client.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(200, json_data=feed)
        result = client.get_elections()
    assert len(result) == 2
    assert result[0]["EID"] == 130000
    assert result[1]["County"] == "Charleston"


def test_get_elections_retryable_on_503(client):
    with patch("integrations.sc_enr.client.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(503)
        with pytest.raises(SCEnrRetryableError):
            client.get_elections()


def test_get_elections_raises_on_non_json(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.side_effect = ValueError("not json")
    with patch("integrations.sc_enr.client.requests.get", return_value=mock_resp):
        with pytest.raises(SCEnrError, match="non-JSON"):
            client.get_elections()


def test_get_elections_raises_on_non_list(client):
    with patch("integrations.sc_enr.client.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(200, json_data={"error": "unexpected"})
        with pytest.raises(SCEnrError, match="unexpected shape"):
            client.get_elections()


def test_get_elections_includes_cache_buster(client):
    with patch("integrations.sc_enr.client.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(200, json_data=[])
        client.get_elections()
    call_kwargs = mock_get.call_args
    assert "params" in call_kwargs.kwargs
    assert "v" in call_kwargs.kwargs["params"]


# ------------------------------------------------------------------
# resolve_url
# ------------------------------------------------------------------

def test_resolve_url_state_level(client):
    resolved = "https://www.enr-scvotes.org/SC/125820/web.345435/"
    with patch("integrations.sc_enr.client.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(200, url=resolved)
        result = client.resolve_url(125820)
    assert result == resolved


def test_resolve_url_county_level(client):
    resolved = "https://www.enr-scvotes.org/SC/Charleston/119138/web.317647/"
    with patch("integrations.sc_enr.client.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(200, url=resolved)
        result = client.resolve_url(119138, county="Charleston")
    assert result == resolved


def test_resolve_url_adds_trailing_slash(client):
    resolved_no_slash = "https://www.enr-scvotes.org/SC/125820/web.345435"
    with patch("integrations.sc_enr.client.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(200, url=resolved_no_slash)
        result = client.resolve_url(125820)
    assert result.endswith("/")


def test_resolve_url_county_spaces_replaced(client):
    resolved = "https://www.enr-scvotes.org/SC/New_York/99999/web.111111/"
    with patch("integrations.sc_enr.client.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(200, url=resolved)
        client.resolve_url(99999, county="New York")
    call_url = mock_get.call_args.args[0]
    assert "New_York" in call_url


def test_resolve_url_retryable_on_503(client):
    with patch("integrations.sc_enr.client.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(503)
        with pytest.raises(SCEnrRetryableError):
            client.resolve_url(125820)
