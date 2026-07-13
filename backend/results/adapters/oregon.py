from __future__ import annotations

import logging

from django.core.cache import cache

from integrations.or_sos.client import OrSosClient, find_result_links, select_history_row
from integrations.or_sos.exceptions import OrSosUnsupportedDocumentError
from integrations.or_sos.parsers import document_checksum, parse_result_document

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30


@register
class OregonAdapter(StateResultsAdapter):
    state = "OR"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"or_sos:document:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("or_sos.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        meta = election.source_metadata or {}
        client = OrSosClient()
        source_url = (meta.get("or_results_url") or "").strip()
        history_version = ""

        if not source_url:
            try:
                history_rows = client.get_history_rows()
            except Exception as exc:
                logger.warning("or_sos.adapter.history_unavailable: %s", exc)
                return AdapterResult(
                    rows=[],
                    source_url="",
                    mapping_confidence="none",
                    notes=f"Oregon SOS history index unavailable: {exc}",
                )
            history_row = select_history_row(history_rows, election.election_date, election.election_type)
            if not history_row:
                return AdapterResult(
                    rows=[],
                    source_url="",
                    mapping_confidence="none",
                    notes="No Oregon SOS history row matched this election date/type",
                )
            history_version = history_row.source_version
            links = find_result_links(history_row.results_html)
            if not links:
                return AdapterResult(
                    rows=[],
                    source_url="",
                    mapping_confidence="none",
                    notes="Oregon SOS history row has no official result links",
                )
            source_url = _select_result_link(links)

        content, resolved_url = client.download_document(source_url)
        checksum = document_checksum(content)
        source_version = f"{history_version}|{checksum}" if history_version else checksum

        cache_key = self.version_cache_key(election_id)
        if source_version and cache.get(cache_key) == source_version:
            return AdapterResult(
                rows=[],
                source_url=resolved_url,
                mapping_confidence="full",
                unchanged=True,
                source_version=source_version,
            )

        try:
            records = parse_result_document(content, resolved_url)
        except OrSosUnsupportedDocumentError as exc:
            logger.warning("or_sos.adapter.unsupported_document url=%s: %s", resolved_url, exc)
            return AdapterResult(
                rows=[],
                source_url=resolved_url,
                mapping_confidence="partial",
                notes=str(exc),
                source_version=source_version,
            )

        rows = [
            ResultRow(
                office_title=record.office_title,
                candidate_name=record.choice,
                option_label=None,
                vote_count=record.vote_count,
                vote_pct=record.vote_pct,
                is_winner=None,
                result_type="official",
                jurisdiction_fragment=record.jurisdiction.lower().replace(" ", "-") if record.jurisdiction else "",
                raw={
                    "source": "or_sos",
                    "party": record.party,
                    "source_file": record.source_file,
                    "checksum": checksum,
                },
            )
            for record in records
        ]

        return AdapterResult(
            rows=rows,
            source_url=resolved_url,
            mapping_confidence="full" if rows else "partial",
            notes="" if rows else "Oregon result document parsed but contained no supported rows",
            source_version=source_version,
        )


def _select_result_link(links: list[str]) -> str:
    for suffix in (".zip", ".csv", ".tsv", ".txt", ".xlsx", ".xls", ".pdf"):
        for link in links:
            if link.lower().split("?", 1)[0].endswith(suffix):
                return link
    return links[0]
