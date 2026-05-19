from unittest.mock import MagicMock, patch

import pytest

from integrations.civic.client import CivicAPIClient
from integrations.civic.exceptions import CivicAPIForbidden, CivicAPIRetryableError


@pytest.fixture
def client(settings):
    settings.CIVIC_API_KEY = "test-key"
    settings.CIVIC_MAX_RETRIES = 1
    settings.CIVIC_RETRY_BACKOFF_SECONDS = 0
    return CivicAPIClient()


def _mock_response(status_code, json_data=None):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data or {}
    mock.raise_for_status = MagicMock()
    return mock


@patch("integrations.civic.client.time.sleep")
def test_list_elections_success(mock_sleep, client):
    payload = {
        "elections": [
            {"id": "9530", "name": "Louisiana 2026 Primary", "electionDay": "2026-03-21", "ocdDivisionId": "ocd-division/country:us/state:la"}
        ]
    }
    with patch.object(client.session, "get", return_value=_mock_response(200, payload)):
        result = client.list_elections()
    assert len(result) == 1
    assert result[0]["source_id"] == "9530"
    assert result[0]["election_date"] == "2026-03-21"


def test_list_elections_no_api_key():
    from django.test import override_settings
    with override_settings(CIVIC_API_KEY=""):
        c = CivicAPIClient()
        with pytest.raises(CivicAPIForbidden):
            c.list_elections()


@patch("integrations.civic.client.time.sleep")
def test_403_raises_forbidden(mock_sleep, client):
    with patch.object(client.session, "get", return_value=_mock_response(403)):
        with pytest.raises(CivicAPIForbidden):
            client.list_elections()


@patch("integrations.civic.client.time.sleep")
def test_429_retries_then_raises(mock_sleep, client):
    with patch.object(client.session, "get", return_value=_mock_response(429)):
        with pytest.raises(CivicAPIRetryableError):
            client.list_elections()
    assert client.session.get.call_count == 2  # initial + 1 retry


@patch("integrations.civic.client.time.sleep")
def test_get_voter_info_400_returns_empty(mock_sleep, client):
    with patch.object(client.session, "get", return_value=_mock_response(400)):
        result = client.get_voter_info("123 Main St, Anytown, WV 25301", "9530")
    assert result == {}
