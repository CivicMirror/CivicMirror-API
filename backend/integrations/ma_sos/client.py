"""
HTTP client for Massachusetts SOS election data.

Provides access to:
  - electionstats.state.ma.us — election/BQ ID discovery and CSV downloads
  - api.ocpf.us — OCPF candidate and schedule data (secondary/enrichment)

No authentication is required for either source.

NOTE: The sec.state.ma.us apex domain is Incapsula-blocked.
      Only electionstats.state.ma.us is accessible without bot protection.
"""
from __future__ import annotations

import logging

import requests

from . import parsers
from .exceptions import MaSosError, MaSosRetryableError

logger = logging.getLogger(__name__)

_ELECTIONSTATS_BASE = "https://electionstats.state.ma.us"
_OCPF_BASE = "https://api.ocpf.us"
_UA = "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class MaSosClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _UA})

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, url: str, timeout: int | None = None) -> requests.Response:
        effective_timeout = timeout or self.timeout
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=effective_timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise MaSosRetryableError(f"GET {url} failed: {exc}") from exc
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise MaSosRetryableError(f"GET {url} returned {resp.status_code}")
                continue
            if resp.status_code == 400:
                logger.warning("ma_sos.client.400 url=%s", url)
                raise MaSosError(f"400 from {url}")
            if resp.status_code == 403:
                logger.error("ma_sos.client.403 url=%s — access denied", url)
                raise MaSosError(f"403 Access Denied: {url}")
            resp.raise_for_status()
            return resp
        raise MaSosRetryableError(f"GET {url} retries exhausted")

    # ------------------------------------------------------------------
    # electionstats — election discovery
    # ------------------------------------------------------------------

    def get_election_ids(self, year: int, stage: str) -> list[dict]:
        """
        Fetch election search page and parse into a list of election dicts.

        Returns:
            [{"election_id": int, "office": str, "district": str, "stage": str, "year": int}, ...]
        """
        url = f"{_ELECTIONSTATS_BASE}/elections/search/year_from:{year}/year_to:{year}/stage:{stage}"
        try:
            resp = self._get(url, timeout=30)
        except MaSosRetryableError as exc:
            logger.warning("ma_sos.client.get_election_ids_failed year=%d stage=%s: %s", year, stage, exc)
            return []
        rows = parsers.parse_election_search_html(resp.text)
        for row in rows:
            row["year"] = year
            row["stage"] = stage
        return rows

    def get_ballot_question_ids(self, year: int) -> list[int]:
        """Fetch BQ search page → list of ballot question ID ints."""
        url = f"{_ELECTIONSTATS_BASE}/ballot_questions/search/year_from:{year}/year_to:{year}/"
        try:
            resp = self._get(url, timeout=30)
        except MaSosRetryableError as exc:
            logger.warning("ma_sos.client.get_bq_ids_failed year=%d: %s", year, exc)
            return []
        return parsers.parse_bq_search_html(resp.text)

    # ------------------------------------------------------------------
    # electionstats — CSV downloads
    # ------------------------------------------------------------------

    def download_election_csv(self, election_id: int, precincts: bool = False) -> bytes:
        """
        Download election results CSV. Returns raw bytes for SHA-256 fingerprinting.

        precincts=False → town-level aggregates (default)
        precincts=True  → precinct-level breakdown
        """
        flag = 1 if precincts else 0
        url = f"{_ELECTIONSTATS_BASE}/elections/download/{election_id}/precincts_include:{flag}/"
        try:
            resp = self._get(url, timeout=60)
        except MaSosRetryableError as exc:
            raise MaSosRetryableError(f"CSV download failed for election_id={election_id}: {exc}") from exc
        return resp.content

    def download_bq_csv(self, bq_id: int) -> bytes:
        """Download ballot question results CSV. Returns raw bytes."""
        url = f"{_ELECTIONSTATS_BASE}/ballot_questions/download/{bq_id}/precincts_include:0/"
        try:
            resp = self._get(url, timeout=60)
        except MaSosRetryableError as exc:
            raise MaSosRetryableError(f"BQ CSV download failed for bq_id={bq_id}: {exc}") from exc
        return resp.content

    def get_ballot_question_metadata(self, bq_id: int) -> dict:
        """
        Fetch BQ view page and parse the inline JS election_data object.

        Returns the parsed metadata dict, or raises MaSosError on parse failure.
        """
        url = f"{_ELECTIONSTATS_BASE}/ballot_questions/view/{bq_id}/"
        try:
            resp = self._get(url, timeout=30)
        except MaSosRetryableError as exc:
            raise MaSosRetryableError(f"BQ view fetch failed for bq_id={bq_id}: {exc}") from exc
        metadata = parsers.parse_bq_metadata_js(resp.text)
        if not metadata:
            raise MaSosError(f"No election_data JS found on BQ view page for bq_id={bq_id}")
        return metadata

    # ------------------------------------------------------------------
    # OCPF — candidate/schedule data
    # ------------------------------------------------------------------

    def get_ocpf_schedule(self, year: int) -> dict:
        """
        Fetch OCPF filing schedule for a given year.

        Returns: {"year": int, "primaryElectionDate": "M/D/YYYY", "generalElectionDate": "M/D/YYYY"}
        Returns {} on failure (non-fatal — schedule is supplementary).
        """
        url = f"{_OCPF_BASE}/filingSchedules/{year}"
        try:
            resp = self._get(url, timeout=15)
            return resp.json()
        except (MaSosRetryableError, MaSosError, ValueError) as exc:
            logger.warning("ma_sos.client.ocpf_schedule_failed year=%d: %s", year, exc)
            return {}

    def get_all_candidate_filers(self) -> list[dict]:
        """
        Fetch complete OCPF candidate committee listing (no query params = full dataset).

        NOTE: pageSize, isActive, officeSought, OnlyIncumbents params are silently
        ignored server-side — always fetch without params and filter client-side.
        """
        url = f"{_OCPF_BASE}/filers/listings/C"
        try:
            resp = self._get(url, timeout=60)
            return resp.json()
        except (MaSosRetryableError, MaSosError, ValueError) as exc:
            logger.warning("ma_sos.client.ocpf_filers_failed: %s", exc)
            return []

    def get_incumbents_by_municipality(self) -> list[dict]:
        """Fetch all 351 MA municipalities with their electedFilers (incumbents only)."""
        url = f"{_OCPF_BASE}/municipalities"
        try:
            resp = self._get(url, timeout=30)
            return resp.json()
        except (MaSosRetryableError, MaSosError, ValueError) as exc:
            logger.warning("ma_sos.client.ocpf_municipalities_failed: %s", exc)
            return []
