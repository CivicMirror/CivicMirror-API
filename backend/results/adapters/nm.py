"""
New Mexico (NM) results adapter — BPro TotalVote Election Night Reporting.

Source: https://electionresults.sos.nm.gov/resultsCSV.aspx
Access: Public HTTPS. Cloudflare/bot-protection status is UNVERIFIED — a
        defensive browser User-Agent header is sent (Missouri's SOS needed
        one, Maryland's did not); confirm live when deploying.
Schema: election-wide CSV, one row per (race, candidate-or-ballot-choice),
        combined (non-precinct) vote totals for the whole election. See
        nm_parse.py for the parsing logic, including the office-title
        collision fix required for NM's hyper-local municipal races.

This is the BPro side only. New Mexico also runs Civera ElectionStats (a
separate, unrelated historical GraphQL database) — deliberately NOT built
here per docs/state-research/NM/NM-Election_ResearchV4.md's explicit
recommendation not to collapse the two systems into one adapter. Tracked
as follow-up work in GitHub issue #84.

Election ID (eid) resolution: hardcoded to eid=2897 (the 2025 Regular Local
Election) for this historical-snapshot POC. Live eid discovery for future
elections is out of scope — the research doc flags this as an open,
unresolved question.
"""
from __future__ import annotations

import hashlib
import logging

import requests
from django.core.cache import cache

from .base import AdapterResult, StateResultsAdapter
from .nm_parse import parse_election_wide_csv
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days
_ELECTION_WIDE_CSV_URL = (
    "https://electionresults.sos.nm.gov/resultsCSV.aspx?text=All&type=STATE&map=CTY&eid=2897"
)
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_EXPECTED_CSV_HEADER_PREFIX = b"RaceID,RaceName"


class NmBproError(Exception):
    """Non-retryable New Mexico BPro TotalVote integration error."""


class NmBproRetryableError(NmBproError):
    """Transient error that warrants a retry (network/non-CSV response)."""


@register
class NewMexicoAdapter(StateResultsAdapter):
    state = "NM"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"nm_bpro:checksum:{election_id}"

    def _fetch_csv_bytes(self, url: str) -> bytes:
        try:
            response = requests.get(url, headers={"User-Agent": _BROWSER_USER_AGENT}, timeout=30)
        except requests.RequestException as exc:
            raise NmBproRetryableError(f"NM BPro GET failed: {exc}") from exc

        if response.status_code != 200 or not response.content.startswith(_EXPECTED_CSV_HEADER_PREFIX):
            raise NmBproRetryableError(
                f"NM BPro did not return the expected CSV (status={response.status_code}) for url={url}"
            )

        return response.content

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("nm_bpro.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        try:
            csv_bytes = self._fetch_csv_bytes(_ELECTION_WIDE_CSV_URL)
        except NmBproRetryableError as exc:
            logger.warning("nm_bpro.adapter.csv_fetch_failed err=%s", exc)
            return AdapterResult(
                rows=[], source_url=_ELECTION_WIDE_CSV_URL, mapping_confidence="none",
                notes=f"Failed to fetch election-wide CSV for election {election_id}",
            )

        checksum = hashlib.md5(csv_bytes).hexdigest()
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == checksum:
            return AdapterResult(
                rows=[], source_url=_ELECTION_WIDE_CSV_URL, mapping_confidence="full",
                unchanged=True, source_version=checksum,
            )

        rows = parse_election_wide_csv(csv_bytes.decode("utf-8"))

        if not rows:
            return AdapterResult(
                rows=[], source_url=_ELECTION_WIDE_CSV_URL, mapping_confidence="none",
                notes=f"No result rows parsed for election {election_id}",
            )

        return AdapterResult(
            rows=rows,
            source_url=_ELECTION_WIDE_CSV_URL,
            mapping_confidence="full",
            source_version=checksum,
        )
