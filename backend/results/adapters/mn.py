"""
Minnesota (MN) results adapter — Minnesota Secretary of State.

Source: electionresultsfiles.sos.mn.gov (positional semicolon-delimited
flat files, hosted separately from the bot-protected electionresults.sos.mn.gov
human-facing pages — see integrations/mn_sos/client.py).

Data notes:
    - Federal + State offices only this build (see
      docs/superpowers/specs/2026-07-13-mn-adapter-design.md).
    - Confirmed live: MN's statewide/by-district files are already
      pre-aggregated to their stated granularity — no precinct-summing pass
      is needed here, unlike Illinois's il_aggregate.py.
    - No version endpoint exists; change detection uses a checksum of the
      concatenated bytes of all in-scope files fetched this run.
"""
from __future__ import annotations

import hashlib
import logging

from django.core.cache import cache

from integrations.mn_sos.client import MnSosClient
from integrations.mn_sos.mappers import is_in_scope_file, is_write_in
from integrations.mn_sos.parsers import parse_file_index, parse_result_file

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days


def _safe_float(value: str):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@register
class MinnesotaAdapter(StateResultsAdapter):
    state = "MN"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"mn_sos:checksum:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("mn_sos.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        meta = election.source_metadata or {}
        ers_election_id = meta.get("mn_ers_election_id")
        if not ers_election_id:
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"No mn_ers_election_id metadata for election {election.source_id}",
            )

        client = MnSosClient()
        index_html = client.fetch_file_index(ers_election_id)
        in_scope_files = [f for f in parse_file_index(index_html) if is_in_scope_file(f["label"])]

        if not in_scope_files:
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"No in-scope MN SOS files found for election {election.source_id}",
            )

        all_rows: list[ResultRow] = []
        file_bytes_for_checksum = bytearray()
        source_url = ""

        for file_entry in in_scope_files:
            url = file_entry["url"]
            try:
                text = client.fetch_file(url)
            except Exception as exc:
                logger.warning("mn_sos.adapter.file_fetch_failed url=%s err=%s", url, exc)
                continue
            file_bytes_for_checksum.extend(text.encode("utf-8", errors="ignore"))
            source_url = url
            for row in parse_result_file(text):
                try:
                    result_row = ResultRow(
                        candidate_name=row["candidate_name"] or None,
                        option_label=None,
                        vote_count=int(row["candidate_votes"] or 0),
                        vote_pct=_safe_float(row["candidate_pct"]),
                        is_winner=None,
                        result_type="unofficial",
                        office_title=row["office_name"],
                        is_write_in_aggregate=is_write_in(row["candidate_order_code"]),
                        raw=row,
                    )
                except (ValueError, TypeError) as exc:
                    logger.warning(
                        "mn_sos.adapter.malformed_row_skipped office_id=%s "
                        "candidate_name=%s err=%s",
                        row.get("office_id"), row.get("candidate_name"), exc,
                    )
                    continue
                all_rows.append(result_row)

        if not all_rows:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="none",
                notes=f"No result rows parsed for election {election.source_id}",
            )

        checksum = hashlib.md5(bytes(file_bytes_for_checksum)).hexdigest()
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == checksum:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="full",
                unchanged=True, source_version=checksum,
            )

        return AdapterResult(
            rows=all_rows, source_url=source_url,
            mapping_confidence="full", source_version=checksum,
        )
