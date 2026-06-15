# backend/results/adapters/fl.py
"""
Florida Election Watch results adapter.

Fetches the tab-delimited results file from flelectionfiles.floridados.gov
and maps each row to a ResultRow with:
  - candidate_name from CanNameFirst/CanNameMiddle/CanNameLast
  - vote_count from CanVotes
  - result_type: 'official' if PrecinctsReporting == Precincts, else 'unofficial'
  - jurisdiction_fragment: CountyCode.lower() (e.g. 'hil' for Hillsborough)
  - vote_pct: None (not provided in this file)

Version detection: Last-Modified header cached in Redis by election_id.
"""
from __future__ import annotations

import logging

from django.core.cache import cache

from integrations.fl_ew.client import FlEwClient
from integrations.fl_ew.mappers import build_candidate_name
from integrations.fl_ew.parsers import parse_results_file

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_VERSION_CACHE_TTL = 86400 * 30  # 30 days


@register
class FloridaAdapter(StateResultsAdapter):
    state = "FL"

    def _version_cache_key(self, election_id: int) -> str:
        return f"fl_ew:ver:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("FLAdapter: election %d not found", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election {election_id} not found",
            )

        slug = (election.source_metadata or {}).get("fl_ew_slug")
        if not slug:
            logger.warning("FLAdapter: no fl_ew_slug for election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes="No fl_ew_slug in election.source_metadata — run sync_fl_elections first",
            )

        client = FlEwClient()
        source_url = client.file_url(slug)

        last_modified = client.get_last_modified(slug)
        cache_key = self._version_cache_key(election_id)
        if last_modified and cache.get(cache_key) == last_modified:
            logger.debug("FLAdapter: version unchanged slug=%s", slug)
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="full",
                unchanged=True, source_version=last_modified,
            )

        try:
            text = client.fetch_results_file(slug)
        except Exception as exc:
            logger.error("FLAdapter: fetch failed slug=%s: %s", slug, exc)
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="none",
                notes=f"Fetch failed: {exc}",
            )

        rows_data = parse_results_file(text)
        if not rows_data:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="none",
                notes="File fetched but contained no data rows",
            )

        result_rows: list[ResultRow] = []
        for row in rows_data:
            candidate_name = build_candidate_name(row)
            is_complete = row.precincts > 0 and row.precincts_reporting >= row.precincts
            result_type = "official" if is_complete else "unofficial"

            result_rows.append(ResultRow(
                candidate_name=candidate_name or None,
                option_label=None,
                vote_count=row.can_votes,
                vote_pct=None,
                is_winner=None,
                result_type=result_type,
                office_title=row.race_name or None,
                jurisdiction_fragment=row.county_code.lower(),
                raw={
                    "party_code": row.party_code,
                    "party_name": row.party_name,
                    "race_code": row.race_code,
                    "county_name": row.county_name,
                    "juris1_num": row.juris1_num,
                    "juris2_num": row.juris2_num,
                    "precincts": row.precincts,
                    "precincts_reporting": row.precincts_reporting,
                    "fl_ew_slug": slug,
                },
            ))

        logger.info(
            "FLAdapter: slug=%s rows=%d", slug, len(result_rows),
        )

        cache.set(cache_key, last_modified, _VERSION_CACHE_TTL)

        return AdapterResult(
            rows=result_rows,
            source_url=source_url,
            mapping_confidence="full",
            source_version=last_modified,
        )
