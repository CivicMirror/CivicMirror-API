"""
Maryland (MD) results adapter — Maryland State Board of Elections (SBE).

Source: https://elections.maryland.gov/elections/archive/{year}/election_data/
Access: Public HTTPS, no authentication required. NOT Clarity — homegrown
        static CSVs (confirmed via HAR capture; see
        docs/state-research/MD/MD-Election_Research.md).
Schema: per-county CSV, already county-aggregated (no precinct summing) —
        this adapter sums Total Votes for each (office, candidate) pair
        across all 24 counties' files.

Scope: offices matching integrations.md_sbe.mappers.IN_SCOPE_OFFICES — the
same office set Stage 1 uses to create races (Governor/Lt. Governor,
Attorney General, Comptroller, U.S. Senator, Representative in Congress,
State Senator, House of Delegates). Judicial and county/local offices are
out of scope for both stages (see ADR-005/COVERAGE-CLARIFICATION).

Cycle year/prefix resolution: sourced live from
integrations.md_sbe.calendar.get_active_cycle(election_date) — the same
statutory-dates table Stage 1 (Task 1) uses — falling back to the hardcoded
2024/"PG" (Presidential General) constants only when the table has no entry
covering election_date's year. That fallback keeps the historical 2024
fixture-based tests (results/tests/fixtures/md_county*.csv) working, and is
also what production would need if this adapter is ever asked to resync an
election whose cycle predates the maintained table.

KNOWN UNKNOWN: whether the per-county RESULTS CSV's "Office Name" values
exactly match the candidate-list CSV's "Office Name" values that
IN_SCOPE_OFFICES was built from (e.g. does the results file say "House of
Delegates" or something more specific like "Delegate District 1A"?) has not
been verified — no 2026 results exist yet since the election hasn't
happened, and the 2024 fixtures only cover "President - Vice Pres" and
"U.S. Senator". If a live 2026 results CSV later turns out to use different
Office Name strings than the candidate CSV for the same office, add a small
alias map in md_aggregate.py at that point — do not widen or rename
IN_SCOPE_OFFICES itself, since it must stay in sync with Stage 1's race
office_titles exactly as defined.
"""
from __future__ import annotations

import hashlib
import logging

from django.core.cache import cache

from integrations.md_sbe.calendar import get_active_cycle
from integrations.md_sbe.client import MdSbeClient
from integrations.md_sbe.exceptions import MdSbeRetryableError
from integrations.md_sbe.mappers import IN_SCOPE_OFFICES
from integrations.md_sbe.parsers import parse_county_results_csv

from .base import AdapterResult, StateResultsAdapter
from .md_aggregate import aggregate_county_rows
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days
_OFFICE_ALLOWLIST = IN_SCOPE_OFFICES  # replaces the old {"President - Vice Pres", "U.S. Senator"}
# Fallback constants for elections whose cycle predates the maintained
# MD_ELECTION_CYCLES table (see integrations/md_sbe/calendar.py) — currently
# only exercised by the historical 2024 fixture-based tests.
_CYCLE_PREFIX = "PG"
_YEAR = 2024
# Read off the real class attribute once at module-import time (before any
# `@patch("results.adapters.md.MdSbeClient")` in a test can swap the name),
# so the adapter's fetch loop count doesn't depend on a mocked MdSbeClient
# exposing a real COUNTY_CODES attribute at call-time.
_COUNTY_CODES: tuple[str, ...] = MdSbeClient.COUNTY_CODES


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

        # Resolve the cycle year/prefix live from the maintained statutory-dates
        # table (same one Stage 1 uses), falling back to the hardcoded 2024/PG
        # constants only when no table entry covers election_date's year — this
        # keeps the historical 2024 fixture-based tests passing unmodified.
        active_cycle = get_active_cycle(election_date)
        if active_cycle is not None and active_cycle.year == election_date.year:
            year, cycle_prefix = active_cycle.year, active_cycle.cycle_prefix
        else:
            year, cycle_prefix = _YEAR, _CYCLE_PREFIX

        client = MdSbeClient()
        all_rows: list[dict] = []
        csv_bytes_for_checksum = bytearray()
        source_url = ""

        for county_code in _COUNTY_CODES:
            try:
                csv_text = client.fetch_county_results(
                    year=year, cycle_prefix=cycle_prefix, county_code=county_code,
                )
            except MdSbeRetryableError as exc:
                logger.warning(
                    "md_sbe.adapter.county_fetch_failed county=%s err=%s", county_code, exc,
                )
                continue
            csv_bytes_for_checksum.extend(csv_text.encode("utf-8", errors="ignore"))
            source_url = MdSbeClient.build_url(
                year=year, cycle_prefix=cycle_prefix, county_code=county_code,
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
