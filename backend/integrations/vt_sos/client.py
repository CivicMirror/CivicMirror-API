"""
Vermont Secretary of State HTTP client.

Base URL: https://static.electionresults.vermont.gov
No authentication required. Responses are served as application/octet-stream,
so the client must parse the body as JSON without requiring a JSON
Content-Type header.

Discovery sequence (do not construct category timestamps — always fetch the
election manifest and use the current path it publishes; the same category
content has been observed under two timestamped paths five minutes apart):

    GET /elections/elections.json          -> select electionGuid
    GET /elections/{electionGuid}.json      -> election manifest (category paths)
    GET /{manifest.category.path}           -> party ballots / contests / candidates

Manifest category paths use backslashes (Windows-style, e.g.
"elections\\{guid}-f-{timestamp}.json") and must be normalized to forward
slashes before being resolved against BASE_URL.
"""
from __future__ import annotations

import logging

import requests

from .exceptions import VtSosError, VtSosRetryableError

logger = logging.getLogger(__name__)

BASE_URL = "https://static.electionresults.vermont.gov"
_ELECTIONS_INDEX_PATH = "elections/elections.json"

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"
    ),
    "Accept": "application/json, application/octet-stream, */*",
}


def normalize_category_path(path: str) -> str:
    """Manifest paths use backslashes; normalize to forward slashes."""
    return (path or "").replace("\\", "/").lstrip("/")


class VermontSosClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _get_json(self, url: str) -> dict | list:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise VtSosRetryableError(f"Vermont SOS GET failed: {exc}") from exc
                logger.warning("vt_sos.client.retry attempt=%d url=%s err=%s", attempt, url, exc)
                continue

            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise VtSosRetryableError(
                        f"Vermont SOS returned {resp.status_code} for {url}"
                    )
                logger.warning(
                    "vt_sos.client.retry attempt=%d url=%s status=%d",
                    attempt, url, resp.status_code,
                )
                continue

            if resp.status_code == 404:
                # Category files can 404 transiently around a manifest's
                # publication transition (new timestamped path not yet live).
                raise VtSosRetryableError(f"Vermont SOS category not found: {url}")

            resp.raise_for_status()

            # Server sends application/octet-stream; parse as JSON regardless
            # of the declared Content-Type.
            try:
                return resp.json()
            except ValueError as exc:
                raise VtSosError(f"Vermont SOS returned non-JSON for {url}: {exc}") from exc

        raise VtSosRetryableError("Vermont SOS GET retries exhausted")

    def list_elections(self) -> list[dict]:
        """GET elections/elections.json — the statewide + local election index."""
        url = f"{BASE_URL}/{_ELECTIONS_INDEX_PATH}"
        data = self._get_json(url)
        if not isinstance(data, list):
            raise VtSosError(f"Expected a list from {url}, got {type(data).__name__}")
        return data

    def get_election_manifest(self, election_guid: str) -> dict:
        """GET elections/{electionGuid}.json — per-election category paths."""
        url = f"{BASE_URL}/elections/{election_guid}.json"
        data = self._get_json(url)
        if not isinstance(data, dict):
            raise VtSosError(f"Expected a dict from {url}, got {type(data).__name__}")
        return data

    def get_category(self, path: str) -> dict:
        """
        GET a manifest-published category path (federal/statewide/senate/
        house/county/town/turnout). `path` is normalized (backslash -> slash)
        and resolved against BASE_URL.
        """
        normalized = normalize_category_path(path)
        url = f"{BASE_URL}/{normalized}"
        data = self._get_json(url)
        if not isinstance(data, dict):
            raise VtSosError(f"Expected a dict from {url}, got {type(data).__name__}")
        return data
