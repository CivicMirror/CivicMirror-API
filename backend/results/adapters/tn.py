"""
Tennessee (TN) results adapter — Tennessee Secretary of State.

Certified-results-only: parses official precinct XLSX result files indexed by
integrations.tn_sos.tasks.sync_tn_result_index (or pinned manually via
Election.source_metadata["tn_results_url"]). Live election-night polling is
deferred until an active-election HAR exposes the dashboard transport — see
docs/superpowers/plans/2026-07-14-tn-sos-adapter.md.
"""
from __future__ import annotations

import logging

from django.core.cache import cache

from integrations.tn_sos.client import TnSosClient
from integrations.tn_sos.parsers import document_checksum, parse_precinct_xlsx

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days


@register
class TennesseeAdapter(StateResultsAdapter):
    state = "TN"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"tn_sos:document:{election_id}"

    def _result_url(self, meta: dict) -> str:
        url = meta.get("tn_results_url", "")
        if url:
            return url
        for entry in meta.get("tn_result_links", []):
            if entry.get("url", "").lower().endswith(".xlsx"):
                return entry["url"]
        return ""

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("tn_sos.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        meta = election.source_metadata or {}
        url = self._result_url(meta)
        if not url:
            if meta.get("tn_result_links"):
                return AdapterResult(
                    rows=[], source_url="", mapping_confidence="partial",
                    notes="tn_result_links has no XLSX document; PDF/other fallback not implemented",
                )
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes="No tn_results_url or tn_result_links metadata for this election",
            )

        client = TnSosClient()
        content, source_url = client.download_file(url)
        checksum = document_checksum(content)

        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == checksum:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="full",
                unchanged=True, source_version=checksum,
            )

        rows = [
            ResultRow(
                candidate_name=record.candidate_name,
                option_label=None,
                vote_count=record.vote_count,
                vote_pct=None,
                is_winner=None,
                result_type="official",
                office_title=record.office_title,
                jurisdiction_fragment=record.precinct,
                raw={
                    "county": record.county,
                    "precinct": record.precinct,
                    "party": record.party,
                    "source_url": record.source_url,
                },
            )
            for record in parse_precinct_xlsx(content, source_url)
        ]

        if not rows:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="partial",
                notes=f"No result rows parsed from {source_url}",
                source_version=checksum,
            )

        return AdapterResult(
            rows=rows, source_url=source_url,
            mapping_confidence="full", source_version=checksum,
        )
