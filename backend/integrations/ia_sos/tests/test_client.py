"""
Tests for the Iowa SOS HTTP client.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from integrations.ia_sos.client import IowaSosClient
from integrations.ia_sos.exceptions import IowaSosRetryableError


def _mock_response(status_code=200, content=b"PDF", text="<html></html>", headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.text = text
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    return resp


class TestFetchCalendarPdf:
    @patch("integrations.ia_sos.client.requests.Session")
    def test_returns_bytes_on_success(self, MockSession):
        session = MockSession.return_value
        session.get.return_value = _mock_response(content=b"%PDF-1.4 calendar")
        client = IowaSosClient()
        result = client.fetch_calendar_pdf()
        assert result == b"%PDF-1.4 calendar"

    @patch("integrations.ia_sos.client.requests.Session")
    def test_retries_on_503(self, MockSession):
        session = MockSession.return_value
        session.get.side_effect = [
            _mock_response(status_code=503),
            _mock_response(status_code=503),
            _mock_response(status_code=503),
            _mock_response(status_code=503),  # 4th call — exceeds retries
        ]
        client = IowaSosClient(max_retries=3)
        with pytest.raises(IowaSosRetryableError):
            client.fetch_calendar_pdf()

    @patch("integrations.ia_sos.client.requests.Session")
    def test_raises_on_connection_error(self, MockSession):
        session = MockSession.return_value
        session.get.side_effect = requests.ConnectionError("network down")
        client = IowaSosClient(max_retries=0)
        with pytest.raises(IowaSosRetryableError):
            client.fetch_calendar_pdf()


class TestGetCandidatePdfInfo:
    def _html_with_link(self, href):
        return f'<html><body><a href="{href}">Candidate List</a></body></html>'

    @patch("integrations.ia_sos.client.requests.Session")
    def test_returns_pdf_info_when_found(self, MockSession):
        session = MockSession.return_value
        session.get.return_value = _mock_response(
            text=self._html_with_link("/elections/pdf/candidate-list.pdf"),
            headers={"ETag": '"abc123"', "Last-Modified": "Mon, 01 Jan 2026 00:00:00 GMT"},
        )
        session.head.return_value = _mock_response(
            headers={"ETag": '"abc123"', "Last-Modified": "Mon, 01 Jan 2026 00:00:00 GMT"},
        )
        client = IowaSosClient()
        result = client.get_candidate_pdf_info("primary")
        assert result is not None
        assert result["url"].endswith("candidate-list.pdf")
        assert result["etag"] == '"abc123"'

    @patch("integrations.ia_sos.client.requests.Session")
    def test_returns_none_when_no_pdf_link(self, MockSession):
        session = MockSession.return_value
        session.get.return_value = _mock_response(
            text='<html><body><p>No PDFs here</p></body></html>'
        )
        client = IowaSosClient()
        result = client.get_candidate_pdf_info("primary")
        assert result is None

    @patch("integrations.ia_sos.client.requests.Session")
    def test_returns_none_on_retryable_error(self, MockSession):
        session = MockSession.return_value
        session.get.side_effect = [
            _mock_response(status_code=403),
            _mock_response(status_code=403),
            _mock_response(status_code=403),
            _mock_response(status_code=403),
        ]
        client = IowaSosClient(max_retries=3)
        result = client.get_candidate_pdf_info("primary")
        assert result is None

    def test_invalid_election_type_raises(self):
        client = IowaSosClient()
        from integrations.ia_sos.exceptions import IowaSosError
        with pytest.raises(IowaSosError):
            client.get_candidate_pdf_info("municipal")


class TestFetchPdf:
    @patch("integrations.ia_sos.client.requests.Session")
    def test_returns_bytes(self, MockSession):
        session = MockSession.return_value
        session.get.return_value = _mock_response(content=b"%PDF-1.4 candidates")
        client = IowaSosClient()
        result = client.fetch_pdf("https://sos.iowa.gov/elections/pdf/candidates.pdf")
        assert result == b"%PDF-1.4 candidates"
