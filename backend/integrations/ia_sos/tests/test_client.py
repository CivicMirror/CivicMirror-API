"""
Tests for the Iowa SOS HTTP client.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from integrations.ia_sos.client import IowaSosClient
from integrations.ia_sos.exceptions import IowaSosError, IowaSosRetryableError


def _mock_response(status_code=200, content=b"PDF", text="<html></html>", headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.text = text
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    return resp


def _calendar_page_html(href="/sites/default/files/2026-01/Cal3yr2025-27_Final.pdf"):
    return f'<html><body><p><a href="{href}">Printable Calendar</a></p></body></html>'


@pytest.fixture
def mock_proxy_request():
    """Patch proxy_request in ia_sos.client — no network calls made."""
    with patch("integrations.ia_sos.client.proxy_request") as m:
        yield m


class TestFetchCalendarPdf:
    def test_returns_bytes_on_success(self, mock_proxy_request):
        mock_proxy_request.side_effect = [
            _mock_response(text=_calendar_page_html()),
            _mock_response(content=b"%PDF-1.4 calendar"),
        ]
        result = IowaSosClient().fetch_calendar_pdf()
        assert result == b"%PDF-1.4 calendar"

    def test_raises_when_no_pdf_link_on_page(self, mock_proxy_request):
        mock_proxy_request.return_value = _mock_response(
            text="<html><body><p>No PDFs here</p></body></html>"
        )
        with pytest.raises(IowaSosError):
            IowaSosClient().fetch_calendar_pdf()

    def test_retries_on_503(self, mock_proxy_request):
        mock_proxy_request.side_effect = [
            _mock_response(status_code=503),
            _mock_response(status_code=503),
            _mock_response(status_code=503),
            _mock_response(status_code=503),  # 4th call — exceeds retries
        ]
        with pytest.raises(IowaSosRetryableError):
            IowaSosClient(max_retries=3).fetch_calendar_pdf()

    def test_raises_on_connection_error(self, mock_proxy_request):
        mock_proxy_request.side_effect = requests.ConnectionError("network down")
        with pytest.raises(IowaSosRetryableError):
            IowaSosClient(max_retries=0).fetch_calendar_pdf()


class TestGetCandidatePdfInfo:
    def _html_with_link(self, href):
        return f'<html><body><a href="{href}">Candidate List</a></body></html>'

    def test_returns_pdf_info_when_found(self, mock_proxy_request):
        mock_proxy_request.side_effect = [
            # First call: GET the election page
            _mock_response(
                text=self._html_with_link("/elections/pdf/candidate-list.pdf"),
            ),
            # Second call: HEAD the PDF for ETag/Last-Modified
            _mock_response(
                headers={"ETag": '"abc123"', "Last-Modified": "Mon, 01 Jan 2026 00:00:00 GMT"},
            ),
        ]
        result = IowaSosClient().get_candidate_pdf_info("primary")
        assert result is not None
        assert result["url"].endswith("candidate-list.pdf")
        assert result["etag"] == '"abc123"'

    def test_returns_none_when_no_pdf_link(self, mock_proxy_request):
        mock_proxy_request.return_value = _mock_response(
            text='<html><body><p>No PDFs here</p></body></html>'
        )
        result = IowaSosClient().get_candidate_pdf_info("primary")
        assert result is None

    def test_returns_none_on_retryable_error(self, mock_proxy_request):
        mock_proxy_request.side_effect = [
            _mock_response(status_code=403),
            _mock_response(status_code=403),
            _mock_response(status_code=403),
            _mock_response(status_code=403),
        ]
        result = IowaSosClient(max_retries=3).get_candidate_pdf_info("primary")
        assert result is None

    def test_invalid_election_type_raises(self):
        with pytest.raises(IowaSosError):
            IowaSosClient().get_candidate_pdf_info("municipal")


@patch("integrations.ia_sos.client.IowaSosClient._get")
def test_get_results_url_matches_year_and_type(mock_get):
    html = """
    <html><body>
      <a href="/IA/123456/web.345435/#/summary">2026 Primary Election</a>
      <a href="/IA/123457/web.345436/#/summary">2026 General Election</a>
    </body></html>
    """
    json_response = MagicMock()
    json_response.json.side_effect = ValueError("not JSON")
    html_response = MagicMock()
    html_response.text = html
    mock_get.side_effect = [json_response, html_response]

    from integrations.ia_sos.client import IowaSosClient

    assert (
        IowaSosClient().get_results_url(2026, "general")
        == "https://electionresults.iowa.gov/IA/123457/"
    )
    assert mock_get.call_args_list == [
        (("https://electionresults.iowa.gov/IA/elections.json",), {}),
        (("https://electionresults.iowa.gov/IA/",), {}),
    ]


@patch("integrations.ia_sos.client.IowaSosClient._get")
def test_get_results_url_falls_back_to_html_when_json_feed_request_fails(mock_get):
    html_response = MagicMock()
    html_response.text = '<a href="/IA/123456/web.345435/#/summary">2026 Primary Election</a>'
    mock_get.side_effect = [IowaSosRetryableError("feed down"), html_response]

    assert (
        IowaSosClient().get_results_url(2026, "primary")
        == "https://electionresults.iowa.gov/IA/123456/"
    )
    assert mock_get.call_args_list == [
        (("https://electionresults.iowa.gov/IA/elections.json",), {}),
        (("https://electionresults.iowa.gov/IA/",), {}),
    ]


@patch("integrations.ia_sos.client.IowaSosClient._get")
def test_get_results_url_matches_election_from_json_feed(mock_get):
    response = MagicMock()
    response.json.return_value = [
        {
            "State": "IA",
            "EID": "126082",
            "ElectionName": "2026 Primary Election",
            "Date": "6/2/2026 12:00:00 AM",
        },
        {
            "State": "IA",
            "EID": "126083",
            "ElectionName": "2026 General Election",
            "Date": "11/3/2026 12:00:00 AM",
        },
    ]
    mock_get.return_value = response

    assert (
        IowaSosClient().get_results_url(2026, "primary")
        == "https://electionresults.iowa.gov/IA/126082/"
    )


class TestFetchPdf:
    def test_returns_bytes(self, mock_proxy_request):
        mock_proxy_request.return_value = _mock_response(content=b"%PDF-1.4 candidates")
        result = IowaSosClient().fetch_pdf("https://sos.iowa.gov/elections/pdf/candidates.pdf")
        assert result == b"%PDF-1.4 candidates"


class TestProxyRouting:
    """Verify that requests always use use_proxy=True and target sos.iowa.gov URLs."""

    def test_calendar_pdf_uses_proxy(self, mock_proxy_request):
        mock_proxy_request.side_effect = [
            _mock_response(text=_calendar_page_html()),
            _mock_response(content=b"%PDF-1.4 calendar"),
        ]
        IowaSosClient().fetch_calendar_pdf()
        call = mock_proxy_request.call_args
        assert call[1].get("use_proxy") is True

    def test_calendar_pdf_targets_discovered_url(self, mock_proxy_request):
        mock_proxy_request.side_effect = [
            _mock_response(text=_calendar_page_html()),
            _mock_response(content=b"%PDF-1.4 calendar"),
        ]
        IowaSosClient().fetch_calendar_pdf()
        first_call, second_call = mock_proxy_request.call_args_list
        assert first_call[0][1] == "https://sos.iowa.gov/three-year-election-calendar"
        assert second_call[0][1] == (
            "https://sos.iowa.gov/sites/default/files/2026-01/Cal3yr2025-27_Final.pdf"
        )

    def test_proxy_401_raises_config_error(self, mock_proxy_request):
        from core.http import ProxyAuthError
        mock_proxy_request.side_effect = ProxyAuthError("401")
        with pytest.raises(IowaSosError) as exc_info:
            IowaSosClient(max_retries=0).fetch_calendar_pdf()
        assert "CIVICMIRROR_PROXY_SECRET" in str(exc_info.value)

    def test_proxy_500_retries_then_raises(self, mock_proxy_request):
        mock_proxy_request.side_effect = [
            _mock_response(status_code=500),
            _mock_response(status_code=500),
            _mock_response(status_code=500),
            _mock_response(status_code=500),
        ]
        with pytest.raises(IowaSosRetryableError):
            IowaSosClient(max_retries=3).fetch_calendar_pdf()
        assert mock_proxy_request.call_count == 4

    def test_head_uses_proxy_for_etag(self, mock_proxy_request):
        """HEAD request for ETag discovery must go through the proxy (not direct)."""
        html = '<html><body><a href="/elections/pdf/candidates.pdf">Candidate List</a></body></html>'
        mock_proxy_request.side_effect = [
            _mock_response(text=html),
            _mock_response(headers={"ETag": '"xyz"', "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT"}),
        ]
        IowaSosClient().get_candidate_pdf_info("primary")

        calls = mock_proxy_request.call_args_list
        assert len(calls) == 2
        # Second call must be HEAD
        head_call = calls[1]
        assert head_call[0][0] == "HEAD"
        assert head_call[1].get("use_proxy") is True
