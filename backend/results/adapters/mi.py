from __future__ import annotations

import hashlib
import logging

from django.core.cache import cache

from integrations.mi_sos.client import MiSosClient
from integrations.mi_sos.exceptions import MiSosRetryableError
from integrations.mi_sos.mappers import is_write_in, result_office_title
from integrations.mi_sos.parsers import parse_mvic_county_results_html, parse_mvic_result_file

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30


def _safe_int(value) -> int:
    try:
        return int(str(value or "0").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0


def _safe_float(value):
    try:
        return float(str(value or "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _to_result_rows(raw_rows: list[dict], result_type: str) -> list[ResultRow]:
    rows = []
    for raw in raw_rows:
        name = (raw.get("candidate_name") or "").strip()
        write_in = is_write_in(name)
        rows.append(ResultRow(
            candidate_name=name if name else None,
            option_label=None,
            vote_count=_safe_int(raw.get("votes")),
            vote_pct=_safe_float(raw.get("vote_pct")),
            is_winner=None,
            result_type=result_type,
            office_title=result_office_title(raw.get("contest", "")),
            is_write_in_aggregate=write_in,
            jurisdiction_fragment=(raw.get("county") or "").strip(),
            raw=raw,
        ))
    return rows


@register
class MichiganAdapter(StateResultsAdapter):
    state = "MI"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"mi_mvic:checksum:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes=f"Election {election_id} not found",
            )

        mvic_id = (election.source_metadata or {}).get("mi_mvic_election_id")
        if not mvic_id:
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes="Missing mi_mvic_election_id in election.source_metadata",
            )

        client = MiSosClient()
        source_url = f"https://mvic.sos.state.mi.us/VoteHistory/GetElectionResultFile?electionId={mvic_id}"
        mapping_confidence = "full"
        try:
            text = client.fetch_result_file(int(mvic_id))
            raw_rows = parse_mvic_result_file(text)
        except MiSosRetryableError as exc:
            logger.warning("mi_mvic.bulk_fetch_failed election=%s: %s", mvic_id, exc)
            source_url = f"https://mvic.sos.state.mi.us/VoteHistory/GetCountyVoteRecords?electionId={mvic_id}"
            text = client.fetch_county_vote_records(int(mvic_id))
            raw_rows = parse_mvic_county_results_html(text)
            mapping_confidence = "partial"

        checksum = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
        if cache.get(self.version_cache_key(election_id)) == checksum:
            return AdapterResult(
                rows=[],
                source_url=source_url,
                mapping_confidence=mapping_confidence,
                unchanged=True,
                source_version=checksum,
            )

        rows = _to_result_rows(raw_rows, "official")
        return AdapterResult(
            rows=rows,
            source_url=source_url,
            mapping_confidence=mapping_confidence,
            source_version=checksum,
        )
