"""
Maryland (MD) results adapter — Maryland State Board of Elections (SBE).

Source: https://elections.maryland.gov/elections/archive/{year}/election_data/
Access: Public HTTPS, no authentication required. NOT Clarity — homegrown
        static CSVs (confirmed via HAR capture; see
        docs/state-research/MD/MD-Election_Research.md).
Schema: per-county CSV, already county-aggregated (no precinct summing) —
        this adapter sums Total Votes for each (office, candidate) pair
        across all 24 counties' files.

Scope (this build): statewide offices on the historical Nov 5, 2024 general
election only — "President - Vice Pres" and "U.S. Senator". U.S. House,
State Senate/House of Delegates, judicial, and ballot questions are
follow-up work (need the separate CongressionalBreakDown/LegislativeBreakDown
files and district-to-race mapping).

Cycle prefix resolution: hardcoded to "PG" (Presidential General) + year 2024
for this historical POC. Live discovery of the current cycle's prefix for
future elections is out of scope — see the plan's "Follow-up work" section.
"""
from __future__ import annotations

import hashlib
import logging

from django.core.cache import cache

from integrations.md_sbe.client import MdSbeClient
from integrations.md_sbe.exceptions import MdSbeRetryableError
from integrations.md_sbe.parsers import parse_county_results_csv

from .base import AdapterResult, StateResultsAdapter
from .md_aggregate import aggregate_county_rows
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days
_OFFICE_ALLOWLIST = frozenset({"President - Vice Pres", "U.S. Senator"})
_CYCLE_PREFIX = "PG"
_YEAR = 2024
# Defined locally (rather than read off the client instance) so the adapter's
# fetch loop count doesn't depend on a mocked MdSbeClient exposing a real
# COUNTY_CODES attribute in tests.
_COUNTY_CODES: tuple[str, ...] = tuple(f"{i:02d}" for i in range(1, 25))


@register
class MarylandAdapter(StateResultsAdapter):
    state = "MD"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"md_sbe:checksum:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("md_sbe.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        client = MdSbeClient()
        all_rows: list[dict] = []
        csv_bytes_for_checksum = bytearray()
        source_url = ""

        for county_code in _COUNTY_CODES:
            try:
                csv_text = client.fetch_county_results(
                    year=_YEAR, cycle_prefix=_CYCLE_PREFIX, county_code=county_code,
                )
            except MdSbeRetryableError as exc:
                logger.warning(
                    "md_sbe.adapter.county_fetch_failed county=%s err=%s", county_code, exc,
                )
                continue
            csv_bytes_for_checksum.extend(csv_text.encode("utf-8", errors="ignore"))
            source_url = (
                f"https://elections.maryland.gov/elections/archive/{_YEAR}/election_data/"
                f"{_CYCLE_PREFIX}{_YEAR % 100:02d}_{county_code}CountyResults.csv"
            )
            all_rows.extend(parse_county_results_csv(csv_text))

        if not all_rows:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="none",
                notes=f"No county results parsed for election {election_id}",
            )

        checksum = hashlib.md5(bytes(csv_bytes_for_checksum)).hexdigest()
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == checksum:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="full",
                unchanged=True, source_version=checksum,
            )

        rows = aggregate_county_rows(all_rows, office_allowlist=_OFFICE_ALLOWLIST)

        return AdapterResult(
            rows=rows,
            source_url=source_url,
            mapping_confidence="full",
            source_version=checksum,
        )
