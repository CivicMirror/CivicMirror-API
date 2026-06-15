"""
HTTP client for azcleanelections.gov.
No auth required. No Cloudflare gate observed.
Rate-limit: 1 req/sec enforced in fetch_candidate_detail.
"""
from __future__ import annotations

import logging
import time

import requests

from .exceptions import AzSosRetryableError

logger = logging.getLogger(__name__)

_BASE = "https://www.azcleanelections.gov"
_CANDIDATE_LIST_URL = f"{_BASE}/Custom/CandidateList"
_CANDIDATE_DETAIL_URL = f"{_BASE}/Custom/CandidateDetail/"
_TIMEOUT = 30
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class AzSosClient:
    def __init__(self, max_retries: int = 3, detail_req_interval: float = 1.0):
        self.max_retries = max_retries
        self.detail_req_interval = detail_req_interval
        self._session = requests.Session()
        self._session.headers["User-Agent"] = (
            "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"
        )
        self._last_detail_at: float | None = None

    def _get(self, url: str, params: dict | None = None) -> bytes:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=_TIMEOUT)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise AzSosRetryableError(f"AZ SOS GET failed: {exc}") from exc
                time.sleep(2 ** attempt)
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise AzSosRetryableError(f"AZ SOS returned {resp.status_code} for {url}")
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.content
        raise AzSosRetryableError(f"AZ SOS retries exhausted for {url}")

    def fetch_candidate_list(self) -> bytes:
        return self._get(_CANDIDATE_LIST_URL)

    def fetch_candidate_detail(self, candidate_id: int) -> bytes:
        """Fetch with per-request 1 req/sec throttle."""
        if self._last_detail_at is not None:
            elapsed = time.monotonic() - self._last_detail_at
            if elapsed < self.detail_req_interval:
                time.sleep(self.detail_req_interval - elapsed)
        content = self._get(_CANDIDATE_DETAIL_URL, params={"id": candidate_id})
        self._last_detail_at = time.monotonic()
        return content
