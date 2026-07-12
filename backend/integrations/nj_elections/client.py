"""
New Jersey Division of Elections HTTP client.

Source: https://nj.gov/state/elections/election-night-results.shtml
No authentication required. A single page lists all 21 counties' results
URLs — no per-election postback or token resolution needed (unlike IL).
"""
from __future__ import annotations

import logging

import requests

from .exceptions import NjElectionsRetryableError

logger = logging.getLogger(__name__)

ENR_PAGE_URL = "https://nj.gov/state/elections/election-night-results.shtml"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_RETRYABLE_STATUSES = {403, 429, 500, 502, 503, 504}


class NewJerseyElectionsClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def fetch_enr_page(self) -> str:
        """GET the election-night-results county table page."""
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(ENR_PAGE_URL, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise NjElectionsRetryableError(f"NJ ENR page GET failed: {exc}") from exc
                logger.warning("nj_elections.client.retry attempt=%d err=%s", attempt, exc)
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise NjElectionsRetryableError(f"NJ ENR page returned {resp.status_code}")
                logger.warning(
                    "nj_elections.client.retry attempt=%d status=%d", attempt, resp.status_code,
                )
                continue
            resp.raise_for_status()
            return resp.text
        raise NjElectionsRetryableError("NJ ENR page GET retries exhausted")
