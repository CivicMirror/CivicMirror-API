from unittest.mock import MagicMock

import pytest

from integrations.tn_sos.client import (
    CANDIDATE_LIST_URL,
    ELECTION_CALENDAR_URL,
    RESULTS_INDEX_URL,
    TnSosClient,
)
from integrations.tn_sos.exceptions import TnSosError, TnSosRetryableError


def _response(text="", content=b"", status_code=200, url="https://example.test/file"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.content = content or text.encode()
    resp.url = url
    resp.raise_for_status.side_effect = None
    return resp


def test_get_calendar_html_uses_official_url():
    client = TnSosClient()
    client._session.get = MagicMock(return_value=_response("<html>calendar</html>"))

    assert "calendar" in client.get_calendar_html()
    assert client._session.get.call_args.args[0] == ELECTION_CALENDAR_URL


def test_get_candidate_list_html_uses_official_url():
    client = TnSosClient()
    client._session.get = MagicMock(return_value=_response("<html>candidates</html>"))

    assert "candidates" in client.get_candidate_list_html()
    assert client._session.get.call_args.args[0] == CANDIDATE_LIST_URL


def test_get_results_index_html_uses_official_url():
    client = TnSosClient()
    client._session.get = MagicMock(return_value=_response("<html>results</html>"))

    assert "results" in client.get_results_index_html()
    assert client._session.get.call_args.args[0] == RESULTS_INDEX_URL


def test_download_file_returns_bytes_and_resolved_url():
    client = TnSosClient()
    client._session.get = MagicMock(return_value=_response(content=b"xlsx", url="https://cdn.test/file.xlsx"))

    content, resolved_url = client.download_file("https://cdn.test/file.xlsx")

    assert content == b"xlsx"
    assert resolved_url == "https://cdn.test/file.xlsx"


def test_404_is_non_retryable():
    client = TnSosClient(max_retries=0)
    resp = _response(status_code=404)
    client._session.get = MagicMock(return_value=resp)

    with pytest.raises(TnSosError):
        client.get_calendar_html()


def test_503_is_retryable():
    client = TnSosClient(max_retries=0)
    client._session.get = MagicMock(return_value=_response(status_code=503))

    with pytest.raises(TnSosRetryableError):
        client.get_calendar_html()


def test_client_sends_browser_headers_not_custom_user_agent():
    """
    Regression test for #208: CloudFront in front of sos.tn.gov returns 403 for the old
    'CivicMirror-TN-SOS/1.0' User-Agent. The session must send browser-style headers.
    """
    client = TnSosClient()
    headers = client._session.headers
    assert headers["User-Agent"].startswith("Mozilla/5.0")
    assert "CivicMirror" not in headers["User-Agent"]
    assert "text/html" in headers["Accept"]
    assert headers["Accept-Language"].startswith("en-US")


def test_403_is_non_retryable_error():
    """A 403 (e.g. a CDN block) fails fast as TnSosError rather than retrying."""
    import requests

    blocked = _response(status_code=403)
    blocked.raise_for_status.side_effect = requests.HTTPError("403 Client Error")
    client = TnSosClient(backoff_seconds=0)
    client._session.get = MagicMock(return_value=blocked)

    with pytest.raises(TnSosError, match="403"):
        client.get_calendar_html()
    assert client._session.get.call_count == 1
