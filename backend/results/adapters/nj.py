"""
New Jersey (NJ) results adapter — multi-county Clarity aggregation.

NJ has no state-level results aggregator. Unlike every other Clarity-based
adapter in this codebase, this one does NOT use ClarityAdapter.fetch_results()
directly (that method is built around exactly one results_url per election).
Instead it fans out to each in-scope county's Clarity JSON API (discovered
by integrations.nj_elections.tasks.sync_nj_county_urls and cached on
Election.source_metadata["nj_county_urls"]), reusing the inherited
_parse_contests() for the JSON-to-ResultRow parsing, then normalizes and
aggregates across counties.

Scope: ~16 Clarity-pattern counties only (see nj_elections/parsers.py's
CLARITY_HOSTS). The 5 off-platform counties (Bergen, Camden, Sussex,
Warren, Hunterdon) are explicitly out of scope — NJ statewide totals from
this adapter are PARTIAL coverage, not full-state accuracy, until those
are built. See docs/superpowers/specs/2026-07-12-nj-adapter-design.md.

Office/candidate normalization: see nj_normalize.py — office titles and
candidate names are not consistent strings across counties; naive string
aggregation would produce duplicate races/candidates.
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict

import requests
from django.core.cache import cache

from core.http import UpstreamBlockedError, proxy_get
from integrations.nj_elections.parsers import CLARITY_HOSTS  # noqa: F401 (documents scope)

from .base import AdapterResult, ResultRow
from .clarity import _CLARITY_HEADERS, ClarityAdapter
from .nj_normalize import canonical_office_title, normalize_candidate_name, normalize_office
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days

# Offices that plausibly appear on every county's ballot — aggregate across
# ALL in-scope counties. District races (US_HOUSE_NN) only aggregate across
# counties that actually returned that key — no fabricated cross-county sums.
_STATEWIDE_OFFICE_KEYS = frozenset({"US_SENATE", "GOVERNOR"})


@register
class NewJerseyAdapter(ClarityAdapter):
    state = "NJ"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"nj_clarity:checksum:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("nj.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        counties = (election.source_metadata or {}).get("nj_county_urls") or []
        counties = [c for c in counties if c.get("election_id")]
        if not counties:
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes="No NJ county Clarity URLs with a posted election ID",
            )

        # (canonical_key, party) -> {normalized_candidate_name: total_votes}
        aggregated: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # (canonical_key, party) -> counties contributing (for district-race scoping)
        contributing_counties: dict[tuple[str, str], set[str]] = defaultdict(set)
        current_vers: list[str] = []
        source_url = ""

        for county in counties:
            county_name = county["county"]
            base_url = county["url"].split("web.")[0].rstrip("/") + "/"
            use_proxy = False  # NJ counties not yet known to block GCP IPs; add to
                                # CLARITY_PROXY_HOSTS in clarity.py if one is found to.

            try:
                ver_resp = proxy_get(
                    f"{base_url}current_ver.txt",
                    headers=_CLARITY_HEADERS, use_proxy=use_proxy,
                    timeout=self.FETCH_TIMEOUT_SHORT,
                )
                ver_resp.raise_for_status()
                current_ver = ver_resp.text.strip()
            except (UpstreamBlockedError, requests.RequestException) as exc:
                logger.warning("nj.adapter.county_version_failed county=%s err=%s", county_name, exc)
                continue

            current_vers.append(f"{county_name}:{current_ver}")

            try:
                summary_url = f"{base_url}{current_ver}/json/en/summary.json"
                data_resp = proxy_get(
                    summary_url, headers=_CLARITY_HEADERS, use_proxy=use_proxy,
                    timeout=self.FETCH_TIMEOUT_LONG,
                )
                data_resp.raise_for_status()
                payload = data_resp.json()
            except (UpstreamBlockedError, requests.RequestException, ValueError) as exc:
                logger.warning("nj.adapter.county_summary_failed county=%s err=%s", county_name, exc)
                continue

            contests = payload if isinstance(payload, list) else payload.get("Contests", payload.get("contests", []))
            county_rows = self._parse_contests(contests, current_ver)
            source_url = summary_url

            for row in county_rows:
                canonical_key, party = normalize_office(row.office_title or "")
                name = normalize_candidate_name(row.candidate_name or "")
                if name is None:
                    continue  # write-in / bookkeeping row — not aggregated as a candidate total

                group_key = (canonical_key, party)
                if canonical_key not in _STATEWIDE_OFFICE_KEYS:
                    # District race: only counties that actually have this
                    # district contribute — no cross-district fabrication.
                    contributing_counties[group_key].add(county_name)

                aggregated[group_key][name] += row.vote_count

        if not aggregated:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="none",
                notes="No result rows parsed from any in-scope NJ county",
            )

        all_rows: list[ResultRow] = []
        for (canonical_key, party), candidate_totals in aggregated.items():
            office_title = canonical_office_title(canonical_key, party)
            for candidate_name, vote_count in candidate_totals.items():
                all_rows.append(ResultRow(
                    candidate_name=candidate_name,
                    option_label=None,
                    vote_count=vote_count,
                    vote_pct=None,
                    is_winner=None,
                    result_type="unofficial",
                    office_title=office_title,
                    is_write_in_aggregate=False,
                    raw={"canonical_key": canonical_key, "party": party},
                ))

        checksum = hashlib.md5("|".join(sorted(current_vers)).encode()).hexdigest()
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == checksum:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="partial",
                unchanged=True, source_version=checksum,
            )

        return AdapterResult(
            rows=all_rows,
            source_url=source_url,
            mapping_confidence="partial",  # partial county coverage — see module docstring
            notes=f"counties_polled={len(current_vers)}/{len(counties)}",
            source_version=checksum,
        )
