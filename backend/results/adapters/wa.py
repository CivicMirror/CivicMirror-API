"""
Washington results adapter using the VoteWA public results API.

Extends EnhancedVotingAdapter with:
  - WA-specific version detection: prefers asOf, falls back to lastUpdated
  - County fan-out via localityElections[]; each county slug triggers a
    county /data fetch, and county ResultRows get jurisdiction_fragment=county_slug
  - Full raw ID preservation: votewa_ballot_item_id, votewa_parent_ballot_item_id,
    votewa_native_id, votewa_jurisdiction_slug
"""
from __future__ import annotations

import logging

import requests
from django.core.cache import cache

from .base import AdapterResult, ResultRow
from .enhanced_voting import EnhancedVotingAdapter, _get_text, _safe_float, _safe_int
from .registry import register

logger = logging.getLogger(__name__)

_WA_API_BASE = "https://results.votewa.gov/results/public/api"
_FETCH_TIMEOUT_META = 15
_FETCH_TIMEOUT_DATA = 60


@register
class WashingtonAdapter(EnhancedVotingAdapter):
    state = "WA"
    state_name = "washington"
    base_url = _WA_API_BASE

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("WAAdapter: election %s not found", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election {election_id} not found",
            )

        slug = (election.source_metadata or {}).get("enr_slug")
        if not slug:
            logger.warning("WAAdapter: no enr_slug for election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes="No ENR slug in election.source_metadata — populate enr_slug to enable results",
            )

        meta_url = f"{_WA_API_BASE}/elections/washington/{slug}"
        try:
            meta_resp = requests.get(meta_url, timeout=_FETCH_TIMEOUT_META)
            meta_resp.raise_for_status()
            meta = meta_resp.json()
        except requests.RequestException as exc:
            logger.error("WAAdapter: meta fetch failed slug=%s: %s", slug, exc)
            return AdapterResult(
                rows=[], source_url=meta_url, mapping_confidence="none",
                notes=f"Meta fetch failed: {exc}",
            )

        # Prefer asOf; fall back to lastUpdated
        as_of = meta.get("asOf") or meta.get("lastUpdated") or ""
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == as_of and as_of:
            logger.debug("WAAdapter: version unchanged slug=%s as_of=%s", slug, as_of)
            return AdapterResult(
                rows=[], source_url=meta_url, mapping_confidence="full",
                unchanged=True, source_version=as_of,
            )

        data_url = f"{_WA_API_BASE}/elections/washington/{slug}/data"
        try:
            data_resp = requests.get(data_url, timeout=_FETCH_TIMEOUT_DATA)
            data_resp.raise_for_status()
            data = data_resp.json()
        except requests.RequestException as exc:
            logger.error("WAAdapter: data fetch failed slug=%s: %s", slug, exc)
            return AdapterResult(
                rows=[], source_url=data_url, mapping_confidence="none",
                notes=f"Data fetch failed: {exc}",
            )

        is_official = meta.get("isOfficialResults", False)
        result_type = "official" if is_official else "unofficial"

        rows: list[ResultRow] = []

        # State-level rows (jurisdiction_fragment is empty string)
        rows.extend(
            _parse_ballot_items(data.get("ballotItems", []), result_type, jurisdiction_fragment="")
        )

        # County fan-out: one /data call per participating county
        for locality_election in (data.get("localityElections") or []):
            county_slug = _county_slug(locality_election)
            if not county_slug:
                continue
            county_url = f"{_WA_API_BASE}/elections/{county_slug}/{slug}/data"
            try:
                county_resp = requests.get(county_url, timeout=_FETCH_TIMEOUT_DATA)
                county_resp.raise_for_status()
                county_data = county_resp.json()
            except requests.RequestException as exc:
                logger.warning(
                    "WAAdapter: county fetch failed county=%s slug=%s: %s",
                    county_slug, slug, exc,
                )
                continue
            rows.extend(
                _parse_ballot_items(
                    county_data.get("ballotItems", []),
                    result_type,
                    jurisdiction_fragment=county_slug,
                )
            )

        logger.info(
            "WAAdapter: slug=%s rows=%d official=%s counties=%d",
            slug, len(rows), is_official, len(data.get("localityElections") or []),
        )

        return AdapterResult(
            rows=rows,
            source_url=data_url,
            mapping_confidence="full",
            source_version=as_of,
        )


def _county_slug(locality_election: dict) -> str | None:
    """Extract county jurisdiction slug from a localityElections[] entry."""
    jurisdiction = locality_election.get("jurisdiction") or {}
    slug = jurisdiction.get("shortName") or ""
    return slug or None


def _parse_ballot_items(
    ballot_items: list,
    result_type: str,
    jurisdiction_fragment: str,
) -> list[ResultRow]:
    """
    Parse VoteWA ballotItems[] into ResultRow list.

    Sets jurisdiction_fragment on each row and preserves VoteWA-specific
    IDs in ResultRow.raw.
    """
    rows: list[ResultRow] = []
    for item in ballot_items:
        contest_type = item.get("contestType", "")
        office_title = _get_text(item.get("name", []))
        ballot_item_id = item.get("id")
        parent_id = item.get("parentId") or item.get("parentBallotItemId")
        ballot_options = (item.get("summaryResults") or {}).get("ballotOptions", [])

        for opt in ballot_options:
            opt_name = _get_text(opt.get("name", []))
            vote_count = _safe_int(opt.get("voteCount"))
            vote_pct = _safe_float(opt.get("votePercent"))
            is_winner = opt.get("isWinner")
            is_write_in = bool(opt.get("isWriteIn", False))
            native_id = opt.get("nativeId")

            base_raw = {
                "votewa_ballot_item_id": ballot_item_id,
                "votewa_parent_ballot_item_id": parent_id,
                "votewa_native_id": native_id,
                "votewa_jurisdiction_slug": jurisdiction_fragment or "washington",
                "contest_type": contest_type,
            }

            if contest_type == "BallotMeasure":
                rows.append(ResultRow(
                    candidate_name=None,
                    option_label=opt_name or None,
                    vote_count=vote_count,
                    vote_pct=vote_pct,
                    is_winner=None,
                    result_type=result_type,
                    office_title=office_title or None,
                    jurisdiction_fragment=jurisdiction_fragment,
                    raw=base_raw,
                ))
            else:
                party_abbr = (opt.get("party") or {}).get("abbreviation", "")
                rows.append(ResultRow(
                    candidate_name=opt_name or None,
                    option_label=None,
                    vote_count=vote_count,
                    vote_pct=vote_pct,
                    is_winner=bool(is_winner) if is_winner is not None else None,
                    result_type=result_type,
                    office_title=office_title or None,
                    is_write_in_aggregate=is_write_in,
                    jurisdiction_fragment=jurisdiction_fragment,
                    raw={**base_raw, "party": party_abbr},
                ))
    return rows
