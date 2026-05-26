"""
Unit tests for core.http proxy utilities.
No network calls — requests.request is fully mocked.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.test import override_settings

from core.http import (
    ProxyAuthError,
    ProxyDomainNotAllowedError,
    ProxyError,
    UpstreamBlockedError,
    proxy_get,
    proxy_request,
)

PROXY_URL = "https://civicmirror-proxy.test.workers.dev/"
PROXY_SECRET = "test-secret-xyz"


def _mock_response(status_code=200, content=b"data", text="ok", headers=None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.content = content
    resp.text = text
    resp.headers = headers or {}
    return resp


# ---------------------------------------------------------------------------
# Direct path (no proxy configured)
# ---------------------------------------------------------------------------


class TestProxyRequestDirect:
    @patch("core.http.requests.request")
    def test_get_direct(self, mock_req):
        mock_req.return_value = _mock_response()
        with override_settings(CIVICMIRROR_PROXY_URL="", CIVICMIRROR_PROXY_SECRET=""):
            proxy_request("GET", "https://example.com/data")
        mock_req.assert_called_once_with(
            "GET", "https://example.com/data", headers=None, timeout=30
        )

    @patch("core.http.requests.request")
    def test_head_direct(self, mock_req):
        mock_req.return_value = _mock_response()
        with override_settings(CIVICMIRROR_PROXY_URL=""):
            proxy_request("HEAD", "https://example.com/file.pdf")
        assert mock_req.call_args[0][0] == "HEAD"
        assert mock_req.call_args[0][1] == "https://example.com/file.pdf"

    @patch("core.http.requests.request")
    def test_forwards_headers_on_direct(self, mock_req):
        mock_req.return_value = _mock_response()
        hdrs = {"User-Agent": "TestBot/1.0"}
        with override_settings(CIVICMIRROR_PROXY_URL=""):
            proxy_request("GET", "https://example.com/", headers=hdrs)
        assert mock_req.call_args[1]["headers"] == hdrs

    @patch("core.http.requests.request")
    def test_use_proxy_true_but_no_url_falls_back_to_direct(self, mock_req):
        mock_req.return_value = _mock_response()
        with override_settings(CIVICMIRROR_PROXY_URL=""):
            proxy_request("GET", "https://example.com/", use_proxy=True)
        assert mock_req.call_args[0][1] == "https://example.com/"

    @patch("core.http.requests.request")
    def test_403_direct_raises_upstream_blocked_error(self, mock_req):
        """Direct 403 should raise UpstreamBlockedError with hostname in message."""
        mock_req.return_value = _mock_response(status_code=403)
        with override_settings(CIVICMIRROR_PROXY_URL=""):
            with pytest.raises(UpstreamBlockedError) as exc_info:
                proxy_request("GET", "https://new-blocked-host.gov/results/")
        assert "new-blocked-host.gov" in str(exc_info.value)

    @patch("core.http.requests.request")
    def test_403_direct_logs_action_required(self, mock_req, caplog):
        """Direct 403 should emit a WARNING with ACTION REQUIRED instructions."""
        mock_req.return_value = _mock_response(status_code=403)
        import logging
        with caplog.at_level(logging.WARNING, logger="core.http"):
            with override_settings(CIVICMIRROR_PROXY_URL=""):
                with pytest.raises(UpstreamBlockedError):
                    proxy_request("GET", "https://new-blocked-host.gov/results/")
        assert "UPSTREAM_BLOCKED" in caplog.text
        assert "new-blocked-host.gov" in caplog.text
        assert "ACTION REQUIRED" in caplog.text

    @patch("core.http.requests.request")
    def test_upstream_blocked_error_is_requests_exception(self, mock_req):
        """UpstreamBlockedError must be catchable as requests.RequestException."""
        mock_req.return_value = _mock_response(status_code=403)
        with override_settings(CIVICMIRROR_PROXY_URL=""):
            with pytest.raises(requests.RequestException):
                proxy_request("GET", "https://new-blocked-host.gov/")
        assert issubclass(UpstreamBlockedError, ProxyError)
        assert issubclass(UpstreamBlockedError, requests.RequestException)

    @patch("core.http.requests.request")
    def test_non_403_status_returned_as_is_direct(self, mock_req):
        """Non-403 status codes on the direct path are returned without raising."""
        mock_req.return_value = _mock_response(status_code=404)
        with override_settings(CIVICMIRROR_PROXY_URL=""):
            resp = proxy_request("GET", "https://example.com/missing")
        assert resp.status_code == 404




# ---------------------------------------------------------------------------
# Proxy path (CIVICMIRROR_PROXY_URL configured)
# ---------------------------------------------------------------------------


class TestProxyRequestViaWorker:
    @patch("core.http.requests.request")
    def test_routes_to_proxy_url(self, mock_req):
        mock_req.return_value = _mock_response()
        with override_settings(
            CIVICMIRROR_PROXY_URL=PROXY_URL,
            CIVICMIRROR_PROXY_SECRET=PROXY_SECRET,
        ):
            proxy_request("GET", "https://sos.iowa.gov/file.pdf", use_proxy=True)
        assert mock_req.call_args[0][1] == PROXY_URL

    @patch("core.http.requests.request")
    def test_passes_target_url_as_param(self, mock_req):
        mock_req.return_value = _mock_response()
        target = "https://sos.iowa.gov/file.pdf"
        with override_settings(
            CIVICMIRROR_PROXY_URL=PROXY_URL,
            CIVICMIRROR_PROXY_SECRET=PROXY_SECRET,
        ):
            proxy_request("GET", target, use_proxy=True)
        assert mock_req.call_args[1]["params"] == {"url": target}

    @patch("core.http.requests.request")
    def test_sends_proxy_secret_header(self, mock_req):
        mock_req.return_value = _mock_response()
        with override_settings(
            CIVICMIRROR_PROXY_URL=PROXY_URL,
            CIVICMIRROR_PROXY_SECRET=PROXY_SECRET,
        ):
            proxy_request("GET", "https://sos.iowa.gov/file.pdf", use_proxy=True)
        assert mock_req.call_args[1]["headers"] == {"X-Proxy-Secret": PROXY_SECRET}

    @patch("core.http.requests.request")
    def test_head_method_preserved(self, mock_req):
        mock_req.return_value = _mock_response()
        with override_settings(
            CIVICMIRROR_PROXY_URL=PROXY_URL,
            CIVICMIRROR_PROXY_SECRET=PROXY_SECRET,
        ):
            proxy_request("HEAD", "https://sos.iowa.gov/file.pdf", use_proxy=True)
        assert mock_req.call_args[0][0] == "HEAD"

    @patch("core.http.requests.request")
    def test_401_raises_proxy_auth_error(self, mock_req):
        mock_req.return_value = _mock_response(status_code=401)
        with override_settings(
            CIVICMIRROR_PROXY_URL=PROXY_URL,
            CIVICMIRROR_PROXY_SECRET=PROXY_SECRET,
        ):
            with pytest.raises(ProxyAuthError):
                proxy_request("GET", "https://sos.iowa.gov/", use_proxy=True)

    @patch("core.http.requests.request")
    def test_403_raises_proxy_domain_not_allowed(self, mock_req):
        mock_req.return_value = _mock_response(status_code=403)
        with override_settings(
            CIVICMIRROR_PROXY_URL=PROXY_URL,
            CIVICMIRROR_PROXY_SECRET=PROXY_SECRET,
        ):
            with pytest.raises(ProxyDomainNotAllowedError) as exc_info:
                proxy_request(
                    "GET", "https://unlisted-domain.com/", use_proxy=True
                )
        assert "unlisted-domain.com" in str(exc_info.value)

    @patch("core.http.requests.request")
    def test_403_proxy_logs_action_required(self, mock_req, caplog):
        """Proxy 403 should log PROXY_DOMAIN_BLOCKED with ACTION REQUIRED."""
        mock_req.return_value = _mock_response(status_code=403)
        import logging
        with caplog.at_level(logging.WARNING, logger="core.http"):
            with override_settings(
                CIVICMIRROR_PROXY_URL=PROXY_URL,
                CIVICMIRROR_PROXY_SECRET=PROXY_SECRET,
            ):
                with pytest.raises(ProxyDomainNotAllowedError):
                    proxy_request("GET", "https://unlisted-domain.com/data", use_proxy=True)
        assert "PROXY_DOMAIN_BLOCKED" in caplog.text
        assert "unlisted-domain.com" in caplog.text

    @patch("core.http.requests.request")
    def test_proxy_errors_are_requests_exception_subclasses(self, mock_req):
        """ProxyAuthError and ProxyDomainNotAllowedError are catchable as RequestException."""
        mock_req.return_value = _mock_response(status_code=401)
        with override_settings(
            CIVICMIRROR_PROXY_URL=PROXY_URL,
            CIVICMIRROR_PROXY_SECRET=PROXY_SECRET,
        ):
            with pytest.raises(requests.RequestException):
                proxy_request("GET", "https://sos.iowa.gov/", use_proxy=True)
        assert issubclass(ProxyAuthError, ProxyError)
        assert issubclass(ProxyDomainNotAllowedError, ProxyError)
        assert issubclass(ProxyError, requests.RequestException)

    @patch("core.http.requests.request")
    def test_non_error_status_returned_as_is(self, mock_req):
        """Non-error status codes (including 4xx from upstream) are returned transparently."""
        mock_req.return_value = _mock_response(status_code=404)
        with override_settings(
            CIVICMIRROR_PROXY_URL=PROXY_URL,
            CIVICMIRROR_PROXY_SECRET=PROXY_SECRET,
        ):
            resp = proxy_request(
                "GET", "https://sos.iowa.gov/missing", use_proxy=True
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# proxy_get convenience wrapper
# ---------------------------------------------------------------------------


class TestProxyGet:
    @patch("core.http.requests.request")
    def test_uses_get_method(self, mock_req):
        mock_req.return_value = _mock_response()
        with override_settings(CIVICMIRROR_PROXY_URL=""):
            proxy_get("https://example.com/data")
        assert mock_req.call_args[0][0] == "GET"

    @patch("core.http.requests.request")
    def test_passes_headers(self, mock_req):
        mock_req.return_value = _mock_response()
        with override_settings(CIVICMIRROR_PROXY_URL=""):
            proxy_get("https://example.com/", headers={"X-Test": "1"})
        assert mock_req.call_args[1]["headers"] == {"X-Test": "1"}

    @patch("core.http.requests.request")
    def test_use_proxy_forwarded(self, mock_req):
        mock_req.return_value = _mock_response()
        with override_settings(
            CIVICMIRROR_PROXY_URL=PROXY_URL,
            CIVICMIRROR_PROXY_SECRET=PROXY_SECRET,
        ):
            proxy_get("https://sos.iowa.gov/file", use_proxy=True)
        assert mock_req.call_args[0][1] == PROXY_URL
