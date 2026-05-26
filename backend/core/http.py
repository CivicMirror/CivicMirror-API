"""
Shared HTTP utilities for CivicMirror adapters and integrations.

proxy_request() / proxy_get() route requests through the CivicMirror Cloudflare
proxy worker when use_proxy=True, bypassing GCP datacenter IP blocks that affect
CDN-protected election data sites (Akamai on Iowa SOS, CloudFront on SC ENR).

When CIVICMIRROR_PROXY_URL is not configured (local dev), both functions fall
back to direct requests so local development works without a deployed worker.

Usage (opt-in per call — never use use_proxy=True globally):
    from core.http import proxy_get, proxy_request

    # For a known-blocked host:
    resp = proxy_get(url, headers=_MY_HEADERS, use_proxy=True)

    # For a direct-only host:
    resp = proxy_get(url, headers=_MY_HEADERS)

    # HEAD request through proxy (e.g. IA SOS ETag check):
    resp = proxy_request("HEAD", url, use_proxy=True)
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class ProxyError(requests.RequestException):
    """Base class for proxy worker errors."""


class ProxyAuthError(ProxyError):
    """Proxy returned 401 — missing or incorrect X-Proxy-Secret."""


class ProxyDomainNotAllowedError(ProxyError):
    """Proxy returned 403 — target hostname is not in CF Worker ALLOWED_HOSTS secret."""


class UpstreamBlockedError(ProxyError):
    """
    Direct request returned 403 — the upstream host is blocking GCP Cloud Run IPs.

    This indicates the host needs proxy routing. To fix:
      1. Add the hostname to the adapter's proxy host set (e.g. CLARITY_PROXY_HOSTS).
      2. Add the hostname to the CF Worker ALLOWED_HOSTS secret.
      3. Set use_proxy=True on the relevant proxy_get() / proxy_request() call.
    """


def proxy_request(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    use_proxy: bool = False,
    timeout: int = 30,
) -> requests.Response:
    """
    Make an HTTP GET or HEAD request, optionally routing through the proxy worker.

    When use_proxy=True and CIVICMIRROR_PROXY_URL is configured, the request is
    sent to the Cloudflare Worker which forwards it from a CF edge IP. When
    CIVICMIRROR_PROXY_URL is empty, falls back to a direct request (local dev).

    Args:
        method: HTTP method — "GET" or "HEAD".
        url: Target URL.
        headers: Headers forwarded to the upstream on direct requests. Ignored
            when proxied (the CF Worker supplies its own browser headers).
        use_proxy: Set True only for hosts known to block GCP datacenter IPs.
        timeout: Request timeout in seconds.

    Raises:
        ProxyAuthError: Proxy returned 401 (bad/missing secret).
        ProxyDomainNotAllowedError: Proxy returned 403 (host not in CF Worker ALLOWED_HOSTS).
        UpstreamBlockedError: Direct request returned 403 — host likely blocks GCP IPs.
        requests.RequestException: Any network or upstream HTTP error.
    """
    method = method.upper()
    proxy_url = getattr(settings, "CIVICMIRROR_PROXY_URL", "") or ""

    if use_proxy and proxy_url:
        proxy_secret = getattr(settings, "CIVICMIRROR_PROXY_SECRET", "") or ""
        logger.debug("proxy_request via CF worker method=%s url=%s", method, url)
        resp = requests.request(
            method,
            proxy_url,
            params={"url": url},
            headers={"X-Proxy-Secret": proxy_secret},
            timeout=timeout,
        )
        if resp.status_code == 401:
            raise ProxyAuthError(
                f"Proxy returned 401 for {url!r} — check CIVICMIRROR_PROXY_SECRET"
            )
        if resp.status_code == 403:
            hostname = urlparse(url).hostname or url
            logger.warning(
                "PROXY_DOMAIN_BLOCKED: CF Worker returned 403 for host '%s'. "
                "ACTION REQUIRED: add '%s' to the CF Worker ALLOWED_HOSTS secret.",
                hostname, hostname,
            )
            raise ProxyDomainNotAllowedError(
                f"Proxy returned 403 for {url!r} — host '{hostname}' not in CF Worker ALLOWED_HOSTS"
            )
        return resp

    logger.debug("proxy_request direct method=%s url=%s", method, url)
    resp = requests.request(method, url, headers=headers, timeout=timeout)
    if resp.status_code == 403:
        hostname = urlparse(url).hostname or url
        logger.warning(
            "UPSTREAM_BLOCKED: 403 received directly from '%s' — GCP Cloud Run IP "
            "is likely blocked. ACTION REQUIRED: "
            "(1) add '%s' to the adapter's proxy host set (e.g. CLARITY_PROXY_HOSTS), "
            "(2) add '%s' to the CF Worker ALLOWED_HOSTS secret, "
            "(3) set use_proxy=True on the proxy_get() / proxy_request() call.",
            hostname, hostname, hostname,
        )
        raise UpstreamBlockedError(
            f"403 from {url!r} — host '{hostname}' is blocking GCP IPs. "
            "Add to adapter proxy host set + CF Worker ALLOWED_HOSTS and set use_proxy=True."
        )
    return resp


def proxy_get(
    url: str,
    *,
    headers: dict | None = None,
    use_proxy: bool = False,
    timeout: int = 30,
) -> requests.Response:
    """Convenience wrapper — proxy_request with method='GET'."""
    return proxy_request("GET", url, headers=headers, use_proxy=use_proxy, timeout=timeout)
