"""
Illinois (IL) results adapter — Illinois State Board of Elections (SBE).

Source: https://www.elections.il.gov/electionoperations/
Access: Public HTTPS, no authentication required.
Schema: precinct-level CSV per office, aggregated to contest totals by
        summing VoteCount across all precincts for each CandidateName.

Data notes:
    - Federal + State offices only this build (Judicial, ballot measures
      deferred — see docs/superpowers/specs/2026-07-11-il-adapter-design.md).
    - Non-candidate CSV rows (Under Votes, Over Votes, Blank Ballots) and
      write-ins are excluded/aggregated separately — see aggregate_csv_rows
      in this module.
    - No version endpoint exists (unlike Clarity's current_ver.txt); change
      detection uses a checksum of the concatenated CSV bytes fetched this run.

Election ID token:
    Resolved and cached by Stage 1 (integrations.il_sbe.tasks.sync_il_races)
    onto Election.source_metadata["il_sbe_election_id_token"]. If absent,
    this adapter resolves and caches it itself so Stage 2 can run standalone.
"""
from __future__ import annotations

import hashlib
import logging

from django.core.cache import cache

from integrations.il_sbe.client import OFFICE_TYPE_FEDERAL_STATEWIDE, OFFICE_TYPE_SENATE, IllinoisSbeClient
from integrations.il_sbe.mappers import is_federal_or_state_office
from integrations.il_sbe.parsers import parse_category_offices, parse_election_id_token

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register
from .il_aggregate import aggregate_csv_rows

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days


@register
class IllinoisAdapter(StateResultsAdapter):
    state = "IL"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"il_sbe:checksum:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("il_sbe.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        client = IllinoisSbeClient()
        meta = election.source_metadata or {}
        id_token = meta.get("il_sbe_election_id_token")
        election_value = meta.get("il_sbe_election_value", "")

        if not id_token:
            election_page_html = client.fetch_election_page(election_value)
            id_token = parse_election_id_token(election_page_html)
            if not id_token:
                return AdapterResult(
                    rows=[], source_url="", mapping_confidence="none",
                    notes=f"No IL SBE results category page yet for election {election.source_id}",
                )
            meta["il_sbe_election_id_token"] = id_token
            election.source_metadata = meta
            election.save(update_fields=["source_metadata"])

        offices: list[dict] = []
        for office_type_token in (OFFICE_TYPE_FEDERAL_STATEWIDE, OFFICE_TYPE_SENATE):
            category_html = client.fetch_category_page(id_token, office_type_token)
            offices.extend(parse_category_offices(category_html))

        if not offices:
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"No offices found on IL SBE category pages for election {election.source_id}",
            )

        all_rows: list[ResultRow] = []
        csv_bytes_for_checksum = bytearray()
        source_url = ""

        for office in offices:
            office_name = office["office_name"]
            if not is_federal_or_state_office(office_name):
                continue
            csv_url = office["csv_url"]
            try:
                csv_text = client.fetch_office_csv(csv_url)
            except Exception as exc:
                logger.warning(
                    "il_sbe.adapter.csv_fetch_failed office=%s url=%s err=%s",
                    office_name, csv_url, exc,
                )
                continue
            csv_bytes_for_checksum.extend(csv_text.encode("utf-8", errors="ignore"))
            source_url = csv_url
            all_rows.extend(aggregate_csv_rows(csv_text, office_name))

        if not all_rows:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="none",
                notes=f"No result rows parsed for election {election.source_id}",
            )

        checksum = hashlib.md5(bytes(csv_bytes_for_checksum)).hexdigest()
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == checksum:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="full",
                unchanged=True, source_version=checksum,
            )

        return AdapterResult(
            rows=all_rows,
            source_url=source_url,
            mapping_confidence="full",
            source_version=checksum,
        )
