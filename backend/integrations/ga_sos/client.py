from __future__ import annotations

import logging
import time

import requests

from .exceptions import GaSosError, GaSosRetryableError

logger = logging.getLogger(__name__)

API_BASE = "https://results.sos.ga.gov/results/public/api"
CDN_BASE = "https://results.sos.ga.gov/cdn/results"
JURISDICTION = "Georgia"
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class GaSosClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3, backoff_seconds: float = 1.0):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "CivicMirror-GA-SOS/1.0"})

    def _get_json(self, url: str, timeout: int | None = None) -> dict:
        effective_timeout = timeout or self.timeout
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=effective_timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise GaSosRetryableError(f"GET {url} failed: {exc}") from exc
                time.sleep(self.backoff_seconds * (2**attempt))
                continue

            if resp.status_code == 404:
                raise GaSosError(f"GET {url} returned 404")

            if resp.status_code in RETRYABLE_STATUSES:
                logger.warning(
                    "Retrying Georgia SOS request status=%s attempt=%s url=%s",
                    resp.status_code,
                    attempt + 1,
                    url,
                )
                if attempt >= self.max_retries:
                    raise GaSosRetryableError(f"GET {url} returned {resp.status_code}")
                time.sleep(self.backoff_seconds * (2**attempt))
                continue

            try:
                resp.raise_for_status()
            except requests.RequestException as exc:
                raise GaSosError(f"GET {url} returned {resp.status_code}") from exc

            try:
                return resp.json()
            except ValueError as exc:
                raise GaSosError(f"Invalid JSON from {url}: {exc}") from exc

        raise GaSosRetryableError(f"GET {url} retries exhausted")

    def get_jurisdiction(self) -> dict:
        return self._get_json(f"{API_BASE}/jurisdictions/{JURISDICTION}", timeout=15)

    def list_elections(self) -> list[dict]:
        return self.get_jurisdiction().get("elections") or []

    def get_election_metadata(self, public_election_id: str) -> dict:
        return self._get_json(f"{API_BASE}/elections/{JURISDICTION}/{public_election_id}", timeout=15)

    def get_election_data(self, public_election_id: str) -> dict:
        return self._get_json(f"{API_BASE}/elections/{JURISDICTION}/{public_election_id}/data", timeout=60)

    def get_ballot_item_detail(self, public_election_id: str, ballot_item_id: str) -> dict:
        return self._get_json(
            f"{API_BASE}/elections/{JURISDICTION}/{public_election_id}/data/ballot-item/{ballot_item_id}",
            timeout=60,
        )

    def get_media_export(self, media_export_path: str) -> dict:
        return self._get_json(f"{CDN_BASE}/{media_export_path.lstrip('/')}", timeout=120)
