"""
Alabama (AL) results adapter - Alabama Votes ENR WebForms export.

Required Election.source_metadata:
    al_ecode       str  Alabama ENR election code, e.g. "1001295"

Optional Election.source_metadata:
    results_url    str  Full statewideResultsByContest.aspx?ecode=<ecode> URL
"""
from __future__ import annotations

import logging

from django.core.cache import cache

from integrations.al_sos.client import AlSosClient, ecode_from_results_url, enr_url_for_ecode
from integrations.al_sos.parsers import parse_enr_workbook

from .base import AdapterResult, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30


@register
class AlabamaAdapter(StateResultsAdapter):
    state = "AL"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"al_sos:enr:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("al_sos.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        meta = election.source_metadata or {}
        results_url = (meta.get("results_url") or "").strip()
        ecode = (meta.get("al_ecode") or ecode_from_results_url(results_url)).strip()
        if not ecode and not results_url:
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes='Alabama adapter requires Election.source_metadata["al_ecode"] or ["results_url"]',
            )

        source_url = results_url or enr_url_for_ecode(ecode)
        client = AlSosClient()
        content = (
            client.fetch_enr_export_from_url(source_url)
            if results_url
            else client.fetch_enr_export(ecode)
        )
        parsed = parse_enr_workbook(content)
        if cache.get(self.version_cache_key(election_id)) == parsed.source_version:
            return AdapterResult(
                rows=[],
                source_url=source_url,
                mapping_confidence="full",
                unchanged=True,
                source_version=parsed.source_version,
            )

        return AdapterResult(
            rows=parsed.rows,
            source_url=source_url,
            mapping_confidence="full",
            source_version=parsed.source_version,
            notes=f"counties={len(parsed.county_stats)} complete={parsed.is_complete}",
        )
