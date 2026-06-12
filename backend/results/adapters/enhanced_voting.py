"""
Generic Enhanced Voting Results adapter.

Enhanced Voting (app.enhancedvoting.com) powers official results for Virginia (VA),
Washington (WA), and potentially other states.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests
from django.core.cache import cache

from .base import AdapterResult, ResultRow, StateResultsAdapter

logger = logging.getLogger(__name__)


class EnhancedVotingAdapter(StateResultsAdapter):
    """
    Base adapter for states running on the Enhanced Voting platform.

    Subclasses must define `state` and `state_name` (e.g. "Virginia" or "washington")
    and apply the @register decorator.
    """

    state: str
    state_name: str
    base_url: str = "https://app.enhancedvoting.com/results/public/api"

    FETCH_TIMEOUT_META = 15
    FETCH_TIMEOUT_DATA = 60
    VERSION_CACHE_TIMEOUT = 86400 * 30  # 30 days

    def version_cache_key(self, election_id: int) -> str:
        return f"{self.state.lower()}_elect:ver:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("%sAdapter: election %s not found", self.state.upper(), election_id)
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes=f"Election {election_id} not found",
            )

        slug = (election.source_metadata or {}).get("enr_slug")
        if not slug:
            logger.warning(
                "%sAdapter: no slug in election.source_metadata for election=%s pk=%d",
                self.state.upper(), election.source_id, election_id,
            )
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes="No ENR slug in election.source_metadata — populate enr_slug to enable results",
            )

        meta_url = f"{self.base_url}/elections/{self.state_name}/{slug}"

        try:
            meta_resp = requests.get(meta_url, timeout=self.FETCH_TIMEOUT_META)
            meta_resp.raise_for_status()
            meta = meta_resp.json()
        except requests.RequestException as exc:
            logger.error("%sAdapter: failed to fetch meta for slug=%s: %s", self.state.upper(), slug, exc)
            return AdapterResult(
                rows=[],
                source_url=meta_url,
                mapping_confidence="none",
                notes=f"Meta fetch failed: {exc}",
            )

        as_of = meta.get("asOf", "")
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == as_of and as_of:
            logger.debug("%sAdapter: version unchanged slug=%s as_of=%s", self.state.upper(), slug, as_of)
            return AdapterResult(
                rows=[],
                source_url=meta_url,
                mapping_confidence="full",
                unchanged=True,
                source_version=as_of,
            )

        data_url = f"{self.base_url}/elections/{self.state_name}/{slug}/data"
        try:
            data_resp = requests.get(data_url, timeout=self.FETCH_TIMEOUT_DATA)
            data_resp.raise_for_status()
            data = data_resp.json()
        except requests.RequestException as exc:
            logger.error("%sAdapter: failed to fetch data for slug=%s: %s", self.state.upper(), slug, exc)
            return AdapterResult(
                rows=[],
                source_url=data_url,
                mapping_confidence="none",
                notes=f"Data fetch failed: {exc}",
            )

        is_official = meta.get("isOfficialResults", False)
        result_type = "official" if is_official else "unofficial"

        rows = _parse_ballot_items(data.get("ballotItems", []), result_type)

        logger.info(
            "%sAdapter: fetched slug=%s rows=%d official=%s",
            self.state.upper(), slug, len(rows), is_official,
        )

        return AdapterResult(
            rows=rows,
            source_url=data_url,
            mapping_confidence="full",
            source_version=as_of,
        )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_ballot_items(ballot_items: list, result_type: str) -> list[ResultRow]:
    rows: list[ResultRow] = []
    for item in ballot_items:
        contest_type = item.get("contestType", "")
        office_title = _get_text(item.get("name", []))
        ballot_options = (item.get("summaryResults") or {}).get("ballotOptions", [])

        for opt in ballot_options:
            opt_name = _get_text(opt.get("name", []))
            vote_count = _safe_int(opt.get("voteCount"))
            vote_pct = _safe_float(opt.get("votePercent"))
            is_winner = opt.get("isWinner")
            is_write_in = bool(opt.get("isWriteIn", False))

            if contest_type == "BallotMeasure":
                rows.append(ResultRow(
                    candidate_name=None,
                    option_label=opt_name or None,
                    vote_count=vote_count,
                    vote_pct=vote_pct,
                    is_winner=None,  # ballot measures carry no winner flag
                    result_type=result_type,
                    office_title=office_title or None,
                    raw={
                        "ballot_item_id": item.get("id"),
                        "native_id": opt.get("nativeId"),
                        "contest_type": contest_type,
                    },
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
                    raw={
                        "ballot_item_id": item.get("id"),
                        "native_id": opt.get("nativeId"),
                        "party": party_abbr,
                        "contest_type": contest_type,
                    },
                ))
    return rows


def _get_text(names: list, lang: str = "en") -> str:
    """Extract text for a given language from an Enhanced Voting multilingual name list."""
    for n in names:
        if n.get("languageId") == lang:
            return (n.get("text") or "").strip()
    return ((names[0].get("text") or "").strip()) if names else ""


def _safe_int(value) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
