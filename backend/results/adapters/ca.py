"""
California SOS results adapter.

Fetches live/certified results from the CA SOS Election Night Reporting
REST API (api.sos.ca.gov).

Each Race built by the ca_sos integration stores the API endpoint path in
  Race.source_metadata["ca_endpoint"]

This adapter fetches that endpoint and maps the JSON response to ResultRow
objects. Results are treated as UNOFFICIAL until the election is manually
certified (following the same convention as the Clarity adapter).

Version cache key: "ca_sos:version:{election_id}:{endpoint_path_hash}"
Cache value: MD5 of raw JSON response body.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

import requests
from django.core.cache import cache

from elections.models import Election, Race

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_API_BASE = "https://api.sos.ca.gov"
_TIMEOUT = 60
_CACHE_TTL = 86400 * 7  # 7 days
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CivicMirror/1.0; "
        "+https://civicmirror.welshrd.com)"
    ),
    "Accept": "application/json",
}


def _parse_reporting_pct(reporting_str: str) -> float:
    """
    Extract the percentage from a CA SOS reporting string.
    e.g. "100.0% (27,188 of 27,188) precincts reporting" → 100.0
    Returns 0.0 if not parseable.
    """
    if not reporting_str:
        return 0.0
    m = re.search(r"([\d.]+)\s*%", reporting_str)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return 0.0


def _path_hash(endpoint_path: str) -> str:
    return hashlib.md5(endpoint_path.encode()).hexdigest()[:12]


@register
class CaliforniaAdapter(StateResultsAdapter):
    state = "CA"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("ca_sos.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        # Collect all CA SOS races for this election.
        # source_metadata__has_key='ca_endpoint' is the portable filter: only ca_sos
        # writes this key, and the adapter requires it to fetch results — so this
        # replaces both the legacy Race.source filter and the empty source_metadata exclude.
        races = list(
            Race.objects.filter(
                election=election,
                source_metadata__has_key='ca_endpoint',
            )
        )
        if not races:
            logger.warning(
                "ca_sos.adapter.no_races election=%s pk=%d",
                election.source_id, election_id,
            )
            return AdapterResult(
                rows=[],
                source_url=_API_BASE,
                mapping_confidence="none",
                notes="No CA SOS races found for this election",
            )

        all_rows: list[ResultRow] = []
        notes_parts: list[str] = []

        for race in races:
            endpoint_path = (race.source_metadata or {}).get("ca_endpoint")
            if not endpoint_path:
                logger.warning(
                    "ca_sos.adapter.no_endpoint race=%s pk=%d",
                    race.office_title, race.pk,
                )
                continue

            rows, note = self._fetch_race_results(race, endpoint_path, election_id)
            all_rows.extend(rows)
            if note:
                notes_parts.append(note)

        return AdapterResult(
            rows=all_rows,
            source_url=_API_BASE,
            mapping_confidence="high",
            notes="; ".join(notes_parts) if notes_parts else "",
        )

    def _fetch_race_results(
        self,
        race: Race,
        endpoint_path: str,
        election_id: int,
    ) -> tuple[list[ResultRow], str]:
        url = f"{_API_BASE}{endpoint_path}"
        cache_key = f"ca_sos:version:{election_id}:{_path_hash(endpoint_path)}"

        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning(
                "ca_sos.adapter.fetch_error endpoint=%s err=%s", endpoint_path, exc
            )
            return [], f"fetch_error:{endpoint_path}"

        body = resp.content
        current_hash = hashlib.md5(body).hexdigest()
        last_hash = cache.get(cache_key)

        if current_hash == last_hash:
            logger.info(
                "ca_sos.adapter.unchanged endpoint=%s", endpoint_path
            )
            return [], ""

        try:
            data = resp.json()
        except ValueError as exc:
            logger.warning(
                "ca_sos.adapter.json_error endpoint=%s err=%s", endpoint_path, exc
            )
            return [], f"json_error:{endpoint_path}"

        if not isinstance(data, list):
            data = [data]

        rows: list[ResultRow] = []
        for contest in data:
            reporting_str = contest.get("Reporting") or ""
            reporting_pct = _parse_reporting_pct(reporting_str)
            # All results treated as UNOFFICIAL unless manually overridden
            result_type = "UNOFFICIAL"

            raw_candidates = contest.get("candidates") or []
            for raw_cand in raw_candidates:
                name = (raw_cand.get("Name") or "").strip()
                if not name:
                    continue

                vote_str = (raw_cand.get("Votes") or "").replace(",", "").strip()
                pct_str = (raw_cand.get("Percent") or "").strip()

                try:
                    vote_count = int(vote_str)
                except (ValueError, TypeError):
                    vote_count = 0

                try:
                    vote_pct = float(pct_str)
                except (ValueError, TypeError):
                    vote_pct = None

                is_winner_raw = raw_cand.get("W") or raw_cand.get("winner")
                is_winner: Optional[bool] = None
                if is_winner_raw is not None:
                    is_winner = bool(is_winner_raw)

                rows.append(ResultRow(
                    candidate_name=name,
                    option_label=None,
                    vote_count=vote_count,
                    vote_pct=vote_pct,
                    is_winner=is_winner,
                    result_type=result_type,
                    office_title=race.office_title,
                    raw={
                        "Party": raw_cand.get("Party", ""),
                        "incumbent": raw_cand.get("incumbent", False),
                        "reporting_pct": reporting_pct,
                        "endpoint": endpoint_path,
                    },
                ))

        # Store hash after successful parse
        cache.set(cache_key, current_hash, _CACHE_TTL)

        logger.info(
            "ca_sos.adapter.parsed endpoint=%s rows=%d reporting_pct=%.1f",
            endpoint_path, len(rows), reporting_pct,
        )
        return rows, ""
