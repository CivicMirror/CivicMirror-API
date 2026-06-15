# backend/integrations/fl_ew/client.py
"""
Florida Election Watch HTTP client.

Public tab-delimited results file:
  https://flelectionfiles.floridados.gov/enightfilespublic/{YYYYMMDD}_ElecResultsFL.txt

No auth required. Version detection via Last-Modified header.
"""
from __future__ import annotations

import logging

import requests

from .exceptions import FlEwError, FlEwRetryableError

logger = logging.getLogger(__name__)

_BASE = "https://flelectionfiles.floridados.gov/enightfilespublic"
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_UA = "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"

KNOWN_ELECTION_SLUGS: list[str] = [
    "20260818",  # August 18, 2026 Primary
    "20261103",  # November 3, 2026 General Election
]


class FlEwClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers["User-Agent"] = _UA

    def file_url(self, slug: str) -> str:
        return f"{_BASE}/{slug}_ElecResultsFL.txt"

    def get_last_modified(self, slug: str) -> str:
        """
        HEAD the results file and return the Last-Modified header value,
        or '' on any error (404, network failure, missing header).
        """
        url = self.file_url(slug)
        try:
            resp = self._session.head(url, timeout=15)
            if resp.status_code != 200:
                return ""
            return resp.headers.get("Last-Modified", "")
        except requests.RequestException as exc:
            logger.warning("fl_ew.client.head_failed slug=%s: %s", slug, exc)
            return ""

    def fetch_results_file(self, slug: str) -> str:
        """
        GET the tab-delimited results file and return its text content.
        Raises FlEwRetryableError on transient failures; FlEwError on 404.
        """
        url = self.file_url(slug)
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise FlEwRetryableError(f"GET {url} failed: {exc}") from exc
                continue

            if resp.status_code == 404:
                raise FlEwError(f"GET {url} returned 404 — file not yet published")
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise FlEwRetryableError(
                        f"GET {url} returned {resp.status_code} after {self.max_retries} retries"
                    )
                continue

            resp.raise_for_status()
            logger.info("fl_ew.client.fetched slug=%s bytes=%d", slug, len(resp.content))
            return resp.text

        raise FlEwRetryableError(f"GET {url} retries exhausted")
