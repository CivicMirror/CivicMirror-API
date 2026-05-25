"""
Tests for the Colorado SOS HTTP client.
"""
import hashlib
from unittest.mock import MagicMock, patch

import pytest
import requests

from integrations.co_sos.client import ColoradoSosClient
from integrations.co_sos.exceptions import CoSosError, CoSosRetryableError


@pytest.fixture()
def client():
    return ColoradoSosClient(timeout=5, max_retries=1)


def _mock_response(status_code=200, text="<html>ok</html>"):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text
    resp.content = text.encode()
    resp.raise_for_status = MagicMock()
    return resp


class TestGetCandidatePageFingerprint:
    def test_returns_md5_of_response_body(self, client):
        html = "<html>candidate list</html>"
        mock_resp = _mock_response(text=html)
        with patch.object(client._session, "get", return_value=mock_resp):
            fp = client.get_candidate_page_fingerprint("primary")
        expected = hashlib.md5(html.encode()).hexdigest()
        assert fp == expected

    def test_returns_none_when_page_unavailable(self, client):
        with patch.object(client._session, "get", side_effect=requests.ConnectionError):
            fp = client.get_candidate_page_fingerprint("primary")
        assert fp is None

    def test_raises_for_unknown_election_type(self, client):
        with pytest.raises(CoSosError):
            client.get_candidate_page_fingerprint("general_petition")

    def test_returns_none_on_retryable_status(self, client):
        mock_resp = _mock_response(status_code=503)
        with patch.object(client._session, "get", return_value=mock_resp):
            fp = client.get_candidate_page_fingerprint("primary")
        assert fp is None


class TestFetchCandidateHtml:
    def test_returns_html_text(self, client):
        html = "<html><table></table></html>"
        mock_resp = _mock_response(text=html)
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.fetch_candidate_html("primary")
        assert result == html

    def test_raises_for_unknown_election_type(self, client):
        with pytest.raises(CoSosError):
            client.fetch_candidate_html("unknown")

    def test_raises_retryable_on_server_error(self, client):
        mock_resp = _mock_response(status_code=503)
        with patch.object(client._session, "get", return_value=mock_resp):
            with pytest.raises(CoSosRetryableError):
                client.fetch_candidate_html("primary")
