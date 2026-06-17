"""
Texas GoElect ENR API client.

Public API — no auth required.
Base: https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr
"""
from __future__ import annotations

import base64
import json
import logging

import requests

from .exceptions import TxGoElectError, TxGoElectRetryableError

logger = logging.getLogger(__name__)

_BASE = "https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr"
_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Known sub-fields on GET /election/{id} that are individually base64-encoded.
_B64_FIELDS = ("Home", "Lookups", "Race", "OfficeSummary", "Federal",
               "StateWide", "StateWideQ", "Districted", "ReportList")


def _b64d(value: str) -> dict | list:
    """Decode a base64-encoded JSON string. Returns {} on empty/missing."""
    if not value:
        return {}
    try:
        return json.loads(base64.b64decode(value).decode("utf-8"))
    except Exception as exc:
        logger.warning("tx_goelect: b64 decode failed: %s", exc)
        return {}


class TxGoElectClient:
    def __init__(self, max_retries: int = 3, timeout: int = 30):
        self.max_retries = max_retries
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _get(self, url: str) -> requests.Response:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise TxGoElectRetryableError(f"GET {url} failed: {exc}") from exc
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise TxGoElectRetryableError(f"GET {url} returned {resp.status_code}")
                continue
            if not resp.ok:
                raise TxGoElectError(f"GET {url} returned {resp.status_code}")
            return resp
        raise TxGoElectRetryableError(f"GET {url}: retries exhausted")

    def get_election_constants(self) -> dict:
        """GET /electionConstants → decoded electionInfo dict."""
        resp = self._get(f"{_BASE}/electionConstants")
        return _b64d(resp.json().get("upload", ""))

    def get_election_data(self, election_id: int) -> dict:
        """
        GET /election/{id} → dict with keys:
          version (int|None), home, lookups, race, office_summary,
          federal, statewide, statewide_q, districted, report_list
        """
        resp = self._get(f"{_BASE}/election/{election_id}")
        raw = resp.json()

        # Log any unexpected top-level keys for schema-drift visibility.
        known = {"Version"} | set(_B64_FIELDS)
        for key in raw:
            if key not in known:
                logger.debug("tx_goelect: unknown field in election/%d response: %s", election_id, key)

        version_str = raw.get("Version", "")
        version = None
        if version_str:
            try:
                version = int(version_str.split("/")[2])
            except (IndexError, ValueError):
                logger.warning("tx_goelect: could not parse Version string: %s", version_str)

        return {
            "version": version,
            "home": _b64d(raw.get("Home", "")),
            "lookups": _b64d(raw.get("Lookups", "")),
            "race": _b64d(raw.get("Race", "")),
            "office_summary": _b64d(raw.get("OfficeSummary", "")),
            "federal": _b64d(raw.get("Federal", "")),
            "statewide": _b64d(raw.get("StateWide", "")),
            "statewide_q": _b64d(raw.get("StateWideQ", "")),
            "districted": _b64d(raw.get("Districted", "")),
            "report_list": _b64d(raw.get("ReportList", "")),
        }

    def get_county_results(self, election_id: int) -> dict:
        """GET /election/countyInfo/{id} → decoded county dict keyed by CivixApps county ID str."""
        resp = self._get(f"{_BASE}/election/countyInfo/{election_id}")
        return _b64d(resp.json().get("upload", ""))

    def get_version(self, election_id: int) -> int | None:
        """Return integer n from 'enr/{id}/{n}/' or None if election is not yet live."""
        resp = self._get(f"{_BASE}/election/{election_id}")
        version_str = resp.json().get("Version", "")
        if not version_str:
            return None
        try:
            return int(version_str.split("/")[2])
        except (IndexError, ValueError):
            return None

    def probe_election(self, election_id: int) -> bool:
        """True if this election ID is live (Version non-empty)."""
        return self.get_version(election_id) is not None
