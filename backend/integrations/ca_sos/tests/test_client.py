"""Tests for CaSosClient."""
import hashlib
from unittest.mock import MagicMock, patch

import pytest
import requests

from integrations.ca_sos.client import CaSosClient
from integrations.ca_sos.exceptions import CaSosError, CaSosRetryableError


@pytest.fixture
def client():
    return CaSosClient(timeout=5, max_retries=1)


class TestFetchContest:
    def test_returns_list_on_success(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"raceTitle": "Governor", "candidates": [{"Name": "Alice"}]}
        ]
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.fetch_contest("/returns/governor")
        assert len(result) == 1
        assert result[0]["raceTitle"] == "Governor"

    def test_wraps_dict_response_in_list(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"raceTitle": "Governor", "candidates": []}
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.fetch_contest("/returns/governor")
        assert isinstance(result, list)
        assert len(result) == 1

    def test_returns_empty_list_on_404(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.fetch_contest("/returns/nonexistent")
        assert result == []

    def test_raises_retryable_on_503(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch.object(client._session, "get", return_value=mock_resp):
            with pytest.raises(CaSosRetryableError):
                client.fetch_contest("/returns/governor")

    def test_raises_error_on_non_json(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("not json")
        with patch.object(client._session, "get", return_value=mock_resp):
            with pytest.raises(CaSosError):
                client.fetch_contest("/returns/governor")

    def test_raises_retryable_on_network_error(self, client):
        with patch.object(
            client._session, "get",
            side_effect=requests.RequestException("connection refused"),
        ):
            with pytest.raises(CaSosRetryableError):
                client.fetch_contest("/returns/governor")


class TestFetchEndpointCatalog:
    def test_returns_bytes_on_success(self, client):
        csv_content = b"RaceID,ContestName,EndpointURL\n01,Governor,/returns/governor\n"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = csv_content
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.fetch_endpoint_catalog_csv()
        assert result == csv_content

    def test_raises_error_on_404(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch.object(client._session, "get", return_value=mock_resp):
            with pytest.raises(CaSosError):
                client.fetch_endpoint_catalog_csv()

    def test_fingerprint_returns_md5(self, client):
        csv_content = b"test,content"
        expected = hashlib.md5(csv_content).hexdigest()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = csv_content
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.get_endpoint_catalog_fingerprint()
        assert result == expected

    def test_fingerprint_returns_none_on_network_error(self, client):
        with patch.object(
            client._session, "get",
            side_effect=requests.RequestException("timeout"),
        ):
            result = client.get_endpoint_catalog_fingerprint()
        assert result is None


def test_fetch_catalog_defaults_to_api_endpoints_csv():
    client = CaSosClient()
    with patch.object(client, "_get") as mock_get:
        resp = MagicMock(status_code=200, content=b"https://api.sos.ca.gov\n")
        mock_get.return_value = resp
        client.fetch_endpoint_catalog_csv()
        called_url = mock_get.call_args[0][0]
        assert called_url.endswith("/api-endpoints.csv")
