"""
Maryland (MD) results adapter — Maryland State Board of Elections (SBE).

Source: https://elections.maryland.gov/elections/{year}/election_data/ while a
        cycle is current, moving to .../elections/archive/{year}/election_data/
        once it is over (both verified live 2026-08-04).
Access: Public HTTPS, no authentication required. NOT Clarity — homegrown
        static CSVs (confirmed via HAR capture; see
        docs/state-research/MD/MD-Election_Research.md).
Schema: per-county CSV, already county-aggregated (no precinct summing) —
        this adapter sums Total Votes for each (office, district, party,
        candidate) tuple across all 24 counties' files.

Phase matters — MD publishes two different result-file shapes:

    general  {prefix}{yy}_{county}CountyResults.csv   (all parties, one file)
    primary  {prefix}{yy}_{county}{Party}Results.csv  (one file per ballot
             party; {prefix}{yy}_{county}CountyResults.csv does NOT exist)

so fetch_results picks the shape from the Election's own election_type,
falling back to comparing election_date against the cycle's primary date.

Scope: offices matching integrations.md_sbe.mappers.IN_SCOPE_OFFICES — the
same office set Stage 1 uses to create races (Governor/Lt. Governor,
Attorney General, Comptroller, U.S. Senator, Representative in Congress,
State Senator, House of Delegates). Judicial and county/local offices are
out of scope for both stages (see ADR-005/COVERAGE-CLARIFICATION).

Cycle year/prefix resolution: sourced live from
integrations.md_sbe.calendar.get_active_cycle(election_date) — the same
statutory-dates table Stage 1 (Task 1) uses. The cycle carries only the CYCLE
letter; the phase letter is appended per-fetch via prefix_for_phase(), so the
2026 primary reads GP26_* and the 2026 general reads GG26_*. The hardcoded
2024/"PG" constants are used only when the table has no entry covering
election_date's year, which keeps the historical 2024 fixture-based tests
(results/tests/fixtures/md_county*.csv) working and is also what production
would need to resync an election whose cycle predates the maintained table.

Office-name reconciliation: the results CSVs say "U.S. Congress" where the
candidate CSV says "Representative in Congress" (every other in-scope office
name matches exactly). That single alias is applied on the results side in
md_aggregate.canonical_office_name — IN_SCOPE_OFFICES stays the single source
of truth for Stage 1 and is never widened or renamed to accommodate results.
"""
from __future__ import annotations

import hashlib
import logging

from django.core.cache import cache

from integrations.md_sbe.calendar import GENERAL, PRIMARY, get_active_cycle
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
_PRIMARY_PARTY_FILE_LABELS: tuple[str, ...] = MdSbeClient.PRIMARY_PARTY_FILE_LABELS


def _phase_for(election, election_date, active_cycle) -> str:
    """Which MD result-file shape this election uses.

    Prefer the Election's own election_type — integrations.md_sbe.tasks
    stamps it "primary"/"general" from the same calendar table. Fall back to
    the cycle's primary date for elections created by another path (e.g.
    bootstrapped from results), and to "general" when neither is available.
    """
    election_type = (getattr(election, "election_type", "") or "").strip().lower()
    if election_type in (PRIMARY, GENERAL):
        return election_type
    if active_cycle is not None and election_date is not None:
        return active_cycle.phase_for_date(election_date)
    return GENERAL


@register
class MarylandAdapter(StateResultsAdapter):
    state = "MD"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"md_sbe:checksum:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
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
        if active_cycle is not None and active_cycle.year != election_date.year:
            # The table has no entry covering this election's cycle.
            active_cycle = None
        phase = _phase_for(election, election_date, active_cycle)
        if active_cycle is not None:
            year = active_cycle.year
            cycle_prefix = active_cycle.prefix_for_phase(phase)
            # The current cycle is still served from /elections/{year}/;
            # only past cycles live under /elections/archive/{year}/.
            archived = False
        else:
            year, cycle_prefix, archived = _YEAR, _CYCLE_PREFIX, True

        client = MdSbeClient()
        all_rows: list[dict] = []
        csv_bytes_for_checksum = bytearray()
        source_url = ""

        # A primary has no consolidated CountyResults.csv — it publishes one
        # file per ballot party per county, so fan out over parties too.
        fetch_plan: list[tuple[str, str]] = (
            [(c, p) for c in _COUNTY_CODES for p in _PRIMARY_PARTY_FILE_LABELS]
            if phase == PRIMARY
            else [(c, "") for c in _COUNTY_CODES]
        )

        for county_code, party_label in fetch_plan:
            try:
                if party_label:
                    csv_text = client.fetch_county_party_results(
                        year=year, cycle_prefix=cycle_prefix, county_code=county_code,
                        party=party_label, archived=archived,
                    )
                    url = MdSbeClient.build_party_results_url(
                        year=year, cycle_prefix=cycle_prefix, county_code=county_code,
                        party=party_label, archived=archived,
                    )
                else:
                    csv_text = client.fetch_county_results(
                        year=year, cycle_prefix=cycle_prefix, county_code=county_code,
                        archived=archived,
                    )
                    url = MdSbeClient.build_url(
                        year=year, cycle_prefix=cycle_prefix, county_code=county_code,
                        archived=archived,
                    )
            except MdSbeRetryableError as exc:
                logger.warning(
                    "md_sbe.adapter.county_fetch_failed county=%s party=%s err=%s",
                    county_code, party_label or "-", exc,
                )
                continue
            csv_bytes_for_checksum.extend(csv_text.encode("utf-8", errors="ignore"))
            source_url = url
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
