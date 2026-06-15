"""
North Carolina (NC) results adapter — NC State Board of Elections S3 bucket.

Source: https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/{YYYY_MM_DD}/results_pct_{YYYYMMDD}.zip
Access: Public HTTPS, no authentication required.
Schema: Tab-delimited .txt file inside ZIP with one precinct-level row per
        (county, precinct, contest, choice).

Data notes:
    - Precinct-level rows are aggregated to contest totals by summing Total Votes
      across all precincts for each (Contest Name, Choice) pair.
    - NC S3 data represents post-canvass certified results → result_type="official".
    - Contest Type "S" = statewide; "C" = county/city (name includes county/city).
    - Ballot measures (bonds, referendums, amendments) are identified by keywords
      in the Contest Name.  candidate_name is set for all choices; the results
      task framework coerces it to option_label for detected measure races.
    - Write-ins: "Write-In" in the Choice string → is_write_in_aggregate=True.

Version caching:
    Cache key: nc_sbe:etag:{election_pk}
    Value:     ETag header from S3 HEAD request (stripped of quotes)
    TTL:       30 days (written by ingest task after successful DB work)

results_url:
    Auto-derived from Election.election_date (no manual admin entry required).
    Override by setting Election.source_metadata["results_url"].
"""
from __future__ import annotations

import logging
from collections import defaultdict

import requests
from django.core.cache import cache

from integrations.nc_sbe.client import NcSbeClient, _results_zip_url, parse_results_tsv
from integrations.nc_sbe.mappers import is_write_in

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days


@register
class NorthCarolinaAdapter(StateResultsAdapter):
    state = "NC"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"nc_sbe:etag:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("nc_sbe.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        meta = election.source_metadata or {}
        # Allow override via source_metadata; fall back to date-derived URL.
        source_url = (meta.get("results_url") or "").strip()
        if not source_url:
            date_str = (meta.get("nc_date_str") or "").strip()
            if not date_str:
                # Derive from election_date if metadata is missing.
                d = election.election_date
                date_str = f"{d.year}_{d.month:02d}_{d.day:02d}"
            source_url = _results_zip_url(date_str)

        # --- Version check via ETag -------------------------------------------
        cache_key = self.version_cache_key(election_id)
        try:
            client = NcSbeClient()
            etag = client.fetch_results_etag(_date_str_from_url(source_url))
        except Exception as exc:
            logger.warning("nc_sbe.adapter.etag_check_failed url=%s: %s", source_url, exc)
            etag = None

        if etag and cache.get(cache_key) == etag:
            logger.debug("nc_sbe.adapter.unchanged election=%d etag=%s", election_id, etag)
            return AdapterResult(
                rows=[],
                source_url=source_url,
                mapping_confidence="full",
                unchanged=True,
                source_version=etag,
            )

        # --- Download ZIP and parse -------------------------------------------
        try:
            zip_bytes = _fetch_zip(source_url)
        except Exception as exc:
            logger.error("nc_sbe.adapter.fetch_failed url=%s: %s", source_url, exc)
            raise

        raw_rows = parse_results_tsv(zip_bytes)
        if not raw_rows:
            logger.warning("nc_sbe.adapter.empty_zip url=%s", source_url)
            return AdapterResult(
                rows=[],
                source_url=source_url,
                mapping_confidence="none",
                notes="ZIP parsed but contained no rows",
            )

        rows = _aggregate_rows(raw_rows)

        logger.info(
            "nc_sbe.adapter.fetched election=%d rows=%d etag=%s",
            election_id, len(rows), etag,
        )

        return AdapterResult(
            rows=rows,
            source_url=source_url,
            mapping_confidence="full",
            source_version=etag or "",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_zip(url: str) -> bytes:
    resp = requests.get(
        url,
        timeout=120,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"
        },
    )
    resp.raise_for_status()
    return resp.content


def _date_str_from_url(url: str) -> str:
    """Extract YYYY_MM_DD from a results ZIP URL."""
    parts = url.rstrip("/").split("/")
    # URL structure: .../ENRS/YYYY_MM_DD/results_pct_YYYYMMDD.zip
    for part in parts:
        if len(part) == 10 and part[4] == "_" and part[7] == "_":
            return part
    return ""


def _aggregate_rows(raw_rows: list[dict]) -> list[ResultRow]:
    """
    Aggregate precinct-level rows to contest totals.

    Groups by (Contest Name, Contest Type, Choice) and sums Total Votes.
    Each aggregated group becomes one ResultRow with result_type="official".
    """
    # key: (contest_name, choice) → accumulated vote_count
    totals: dict[tuple[str, str], int] = defaultdict(int)
    # key: (contest_name, choice) → first-seen contest_type (S or C)
    contest_types: dict[tuple[str, str], str] = {}

    for row in raw_rows:
        contest_name = (row.get("Contest Name") or "").strip()
        choice = (row.get("Choice") or "").strip()
        if not contest_name or not choice:
            continue

        try:
            votes = int(row.get("Total Votes") or 0)
        except (ValueError, TypeError):
            votes = 0

        key = (contest_name, choice)
        totals[key] += votes
        if key not in contest_types:
            contest_types[key] = (row.get("Contest Type") or "").strip().upper()

    result_rows: list[ResultRow] = []
    for (contest_name, choice), vote_count in totals.items():
        write_in = is_write_in(choice)
        result_rows.append(ResultRow(
            office_title=contest_name,
            candidate_name=choice if not write_in else None,
            option_label=None,
            vote_count=vote_count,
            vote_pct=None,
            is_winner=None,
            result_type="official",
            is_write_in_aggregate=write_in,
            raw={
                "contest_type": contest_types.get((contest_name, choice), ""),
                "source": "nc_sbe",
            },
        ))

    return result_rows
