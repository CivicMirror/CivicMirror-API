"""
Kentucky SOS Candidate Filings HTTP client (web.sos.ky.gov/CandidateFilings/).

Plain GET requests, no authentication, no ASP.NET postback needed — office
groups and the withdrawn list are addressable by query string
(Default.aspx?id=N / Default.aspx?withdrawn=1). Confirmed live 2026-07-14; no
bot protection observed on this host (unlike vrsws.sos.ky.gov's live-results
system, which is explicitly out of scope for this adapter).
"""
from __future__ import annotations

import logging

import requests

from .exceptions import KySosRetryableError

logger = logging.getLogger(__name__)

BASE_URL = "https://web.sos.ky.gov/CandidateFilings"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_RETRYABLE_STATUSES = {403, 429, 500, 502, 503, 504}


class KentuckySosClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _get(self, url: str) -> str:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise KySosRetryableError(f"KY SOS GET failed: {exc}") from exc
                logger.warning("ky_sos.client.retry attempt=%d url=%s err=%s", attempt, url, exc)
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise KySosRetryableError(f"KY SOS returned {resp.status_code} for {url}")
                logger.warning(
                    "ky_sos.client.retry attempt=%d url=%s status=%d",
                    attempt, url, resp.status_code,
                )
                continue
            resp.raise_for_status()
            return resp.text
        raise KySosRetryableError("KY SOS request retries exhausted")

    def fetch_directory(self) -> str:
        return self._get(f"{BASE_URL}/")

    def fetch_office(self, office_id: int) -> str:
        return self._get(f"{BASE_URL}/Default.aspx?id={office_id}")

    def fetch_withdrawn(self) -> str:
        return self._get(f"{BASE_URL}/Default.aspx?withdrawn=1")
