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
from integrations.tn_sos.parsers import NO_CANDIDATE_PLACEHOLDERS, document_checksum, parse_precinct_xlsx

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)


WRITE_IN_LABEL = "Write-In"


def _is_write_in(name: str) -> bool:
    return name.strip().lower().startswith("write-in")


def _aggregate_rows(records, source_url: str) -> list[ResultRow]:
    """
    Roll precinct records up to one row per (office, candidate, county) plus a statewide total.

    Precinct names repeat across counties and split precincts appear once per ballot style, so
    precinct-level rows would collide on OfficialResult's natural key. County rows use the county
    name as jurisdiction_fragment; the statewide total uses '' (the aggregate row the results
    endpoint prefers).

    "No Candidate Qualified" placeholder slots are dropped. Named write-ins ("Write-In - Jane Doe")
    aren't on the candidate lists, so, as in the IL/MD adapters, they're summed into one combined
    "Write-In" row per office and county with is_write_in_aggregate=True. Their names are kept in raw.
    """
    by_county: dict[tuple, int] = {}
    totals: dict[tuple, int] = {}
    party_for: dict[tuple, str] = {}
    contest_for: dict[tuple, str] = {}
    write_in_names: dict[str, set] = {}
    for record in records:
        name = record.candidate_name
        if name.strip().lower() in NO_CANDIDATE_PLACEHOLDERS:
            continue
        if _is_write_in(name):
            write_in_names.setdefault(record.office_title, set()).add(name)
            name = WRITE_IN_LABEL
        key = (record.office_title, name)
        by_county[key + (record.county,)] = by_county.get(key + (record.county,), 0) + record.vote_count
        totals[key] = totals.get(key, 0) + record.vote_count
        party_for.setdefault(key, record.party)
        contest_for.setdefault(key, record.contest_type)

    def _row(office, candidate, votes, fragment, county):
        is_write_in = candidate == WRITE_IN_LABEL
        raw = {
            "county": county,
            "party": "" if is_write_in else party_for[(office, candidate)],
            "contest_type": contest_for[(office, candidate)],
            "source_url": source_url,
        }
        if is_write_in:
            raw["write_in_names"] = sorted(write_in_names.get(office, ()))
        return ResultRow(
            candidate_name=candidate,
            option_label=None,
            vote_count=votes,
            vote_pct=None,
            is_winner=None,
            result_type="official",
            office_title=office,
            jurisdiction_fragment=fragment,
            is_write_in_aggregate=is_write_in,
            raw=raw,
        )

    rows = [_row(office, candidate, votes, "", "") for (office, candidate), votes in totals.items()]
    rows += [
        _row(office, candidate, votes, county, county)
        for (office, candidate, county), votes in by_county.items()
        if county
    ]
    return rows

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

        rows = _aggregate_rows(parse_precinct_xlsx(content, source_url), source_url)

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
