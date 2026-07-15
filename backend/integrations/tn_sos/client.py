from __future__ import annotations

import logging
import time

import requests

from .exceptions import TnSosError, TnSosRetryableError

logger = logging.getLogger(__name__)

ELECTION_CALENDAR_URL = "https://sos.tn.gov/elections/calendar"
CANDIDATE_LIST_URL = "https://sos.tn.gov/elections/2026-candidate-lists"
RESULTS_INDEX_URL = "https://sos.tn.gov/elections/results"
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class TnSosClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3, backoff_seconds: float = 1.0):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "CivicMirror-TN-SOS/1.0"})

    def _get(self, url: str, timeout: int | None = None) -> requests.Response:
        effective_timeout = timeout or self.timeout
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=effective_timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise TnSosRetryableError(f"GET {url} failed: {exc}") from exc
                time.sleep(self.backoff_seconds * (2**attempt))
                continue
            if resp.status_code == 404:
                raise TnSosError(f"GET {url} returned 404")
            if resp.status_code in RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise TnSosRetryableError(f"GET {url} returned {resp.status_code}")
                time.sleep(self.backoff_seconds * (2**attempt))
                continue
            try:
                resp.raise_for_status()
            except requests.RequestException as exc:
                raise TnSosError(f"GET {url} returned {resp.status_code}") from exc
            return resp
        raise TnSosRetryableError(f"GET {url} retries exhausted")

    def get_calendar_html(self) -> str:
        return self._get(ELECTION_CALENDAR_URL, timeout=20).text

    def get_candidate_list_html(self) -> str:
        return self._get(CANDIDATE_LIST_URL, timeout=20).text

    def get_results_index_html(self) -> str:
        return self._get(RESULTS_INDEX_URL, timeout=30).text

    def download_file(self, url: str) -> tuple[bytes, str]:
        resp = self._get(url, timeout=60)
        return resp.content, resp.url
