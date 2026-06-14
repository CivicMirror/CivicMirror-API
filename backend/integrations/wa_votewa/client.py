"""
Washington VoteWA public results API client.

Public API base: https://results.votewa.gov/results/public/api
No auth required. Cache-Control: public, max-age=60.

Confirmed endpoints (from 2026-04-28 HAR):
  GET /api/elections/washington/{yyyymmdd}
  GET /api/elections/washington/{yyyymmdd}/data
  GET /api/elections/{county_slug}/{yyyymmdd}/data
"""
from __future__ import annotations

import logging

import requests

from .exceptions import WaVoteWaError, WaVoteWaRetryableError

logger = logging.getLogger(__name__)

_API_BASE = "https://results.votewa.gov/results/public/api"
_STATE_SLUG = "washington"
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Known WA election date keys (yyyymmdd). Seeded from SOS calendar research.
# Archive discovery is a future improvement; these cover 2026 elections.
KNOWN_ELECTION_SLUGS: list[str] = [
    "20260210",  # February 2026 (public route observed in VoteWA)
    "20260428",  # April 28, 2026 Special Election (confirmed in HAR)
    "20260804",  # August 4, 2026 Top-2 Primary
    "20261103",  # November 3, 2026 General Election
]


class WaVoteWaClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "CivicMirror-WA-VoteWA/1.0"})

    def _get(self, url: str, timeout: int | None = None) -> requests.Response:
        effective_timeout = timeout or self.timeout
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=effective_timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise WaVoteWaRetryableError(f"GET {url} failed: {exc}") from exc
                continue
            if resp.status_code == 404:
                raise WaVoteWaError(f"GET {url} returned 404")
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise WaVoteWaRetryableError(f"GET {url} returned {resp.status_code}")
                continue
            resp.raise_for_status()
            return resp
        raise WaVoteWaRetryableError(f"GET {url} retries exhausted")

    def get_election_metadata(self, slug: str) -> dict:
        """
        GET /api/elections/washington/{slug}

        Lightweight. Returns: id, electionDate, asOf, lastUpdated,
        isOfficialResults, publicReportCategories, ...
        """
        url = f"{_API_BASE}/elections/{_STATE_SLUG}/{slug}"
        try:
            resp = self._get(url, timeout=15)
        except WaVoteWaRetryableError as exc:
            raise WaVoteWaRetryableError(f"Metadata fetch failed slug={slug}: {exc}") from exc
        try:
            return resp.json()
        except ValueError as exc:
            raise WaVoteWaError(f"Invalid JSON from {url}: {exc}") from exc

    def get_election_data(self, slug: str) -> dict:
        """
        GET /api/elections/washington/{slug}/data

        Full statewide composite (~1-3 MB). Returns: jurisdiction, election,
        localityElections[], ballotItems[], statistics[], voterRegistration[], ...
        """
        url = f"{_API_BASE}/elections/{_STATE_SLUG}/{slug}/data"
        try:
            resp = self._get(url, timeout=60)
        except WaVoteWaRetryableError as exc:
            raise WaVoteWaRetryableError(f"Data fetch failed slug={slug}: {exc}") from exc
        try:
            return resp.json()
        except ValueError as exc:
            raise WaVoteWaError(f"Invalid JSON from {url}: {exc}") from exc

    def get_county_data(self, county_slug: str, slug: str) -> dict:
        """
        GET /api/elections/{county_slug}/{slug}/data

        County-local data (confirmed for mason-county-wa). Returns: ballotItems[],
        precincts[], voterTurnout[], ...
        On any error returns {} so a single county failure doesn't abort the sync.
        """
        url = f"{_API_BASE}/elections/{county_slug}/{slug}/data"
        try:
            resp = self._get(url, timeout=60)
        except (WaVoteWaRetryableError, WaVoteWaError):
            logger.warning(
                "wa_votewa.client.county_data_failed county=%s slug=%s", county_slug, slug
            )
            return {}
        try:
            return resp.json()
        except ValueError:
            logger.warning(
                "wa_votewa.client.county_data_invalid_json county=%s slug=%s", county_slug, slug
            )
            return {}
