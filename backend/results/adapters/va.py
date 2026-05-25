"""
Virginia results adapter using the Enhanced Voting ENR API.

Unlike all other state adapters (which are Clarity thin wrappers), Virginia uses
Enhanced Voting (app.enhancedvoting.com) — a completely different platform.

Election slug is stored in Election.source_metadata["enr_slug"] and is
populated programmatically by the sync_va_elections task (no manual admin entry
required, unlike Clarity adapters).

Version cache key: "va_elect:ver:{election_id}:{slug}"
Cache value:       the asOf ISO timestamp from the lightweight metadata endpoint.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests
from django.core.cache import cache

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_ENR_BASE = "https://app.enhancedvoting.com/results/public/api"
_CACHE_TTL = 86400 * 30  # 30 days
_TIMEOUT_META = 15
_TIMEOUT_DATA = 60


@register
class VirginiaAdapter(StateResultsAdapter):
    state = "VA"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("va_elect.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        slug = (election.source_metadata or {}).get("enr_slug")
        if not slug:
            logger.warning(
                "va_elect.adapter.no_slug election=%s pk=%d",
                election.source_id, election_id,
            )
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes="No ENR slug in election.source_metadata — populate enr_slug to enable results",
            )

        meta_url = f"{_ENR_BASE}/elections/Virginia/{slug}"

        try:
            meta_resp = requests.get(meta_url, timeout=_TIMEOUT_META)
            meta_resp.raise_for_status()
            meta = meta_resp.json()
        except requests.RequestException as exc:
            logger.error("va_elect.adapter.meta_fetch_error slug=%s: %s", slug, exc)
            return AdapterResult(
                rows=[],
                source_url=meta_url,
                mapping_confidence="none",
                notes=f"Meta fetch failed: {exc}",
            )

        as_of = meta.get("asOf", "")
        cache_key = f"va_elect:ver:{election_id}:{slug}"
        if cache.get(cache_key) == as_of and as_of:
            logger.debug("va_elect.adapter.unchanged slug=%s as_of=%s", slug, as_of)
            return AdapterResult(
                rows=[],
                source_url=meta_url,
                mapping_confidence="full",
                unchanged=True,
                source_version=as_of,
            )

        data_url = f"{_ENR_BASE}/elections/Virginia/{slug}/data"
        try:
            data_resp = requests.get(data_url, timeout=_TIMEOUT_DATA)
            data_resp.raise_for_status()
            data = data_resp.json()
        except requests.RequestException as exc:
            logger.error("va_elect.adapter.data_fetch_error slug=%s: %s", slug, exc)
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
            "va_elect.adapter.fetched slug=%s rows=%d official=%s",
            slug, len(rows), is_official,
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
