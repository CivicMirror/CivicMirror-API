"""
Vermont results adapter — reads the same static JSON feed used by Stage 1
(integrations/vt_sos), instead of the previous ClarityAdapter subclass.

Confirmed live (2026-07-22, see docs/state-research/VT/VT-Creation-Pipeline-Review.md):
Vermont's current election-results site does not use Clarity's
current_ver.txt/summary.json contract at all — it serves a static JSON feed
at static.electionresults.vermont.gov. The previous `VermontAdapter(ClarityAdapter)`
had no matching results_url configured in production and could not have
fetched anything.

Each contest's `cs` array contains one row per reporting town/district plus
a single statewide/district-total row (tid=0). This adapter only ingests
the tid=0 row — matching the review's simpler recommended option ("ingest
[tid=0] as the race total with an empty fragment and skip town fragments")
rather than also ingesting per-town rows, to avoid producing two
indistinguishable totals. Per-town drill-down is Enhanced Coverage, not
required for Full Core.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.core.cache import cache

from integrations.vt_sos.client import VermontSosClient
from integrations.vt_sos.exceptions import VtSosError, VtSosRetryableError
from results.models import OfficialResult

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_OTHER_WRITE_IN_CID = 0


def _find_contest(category_data: dict, party_code: str, office_id, district_code: str) -> Optional[dict]:
    for wrapper in category_data.get("d") or []:
        wrapper_party = (wrapper.get("pc") or "").strip()
        if wrapper_party != (party_code or ""):
            continue
        for contest in wrapper.get("o") or []:
            if contest.get("oid") != office_id:
                continue
            contest_district = (contest.get("dc") or "").strip()
            if contest_district == (district_code or ""):
                return contest
    return None


def _total_row(contest: dict) -> Optional[dict]:
    for cs_row in contest.get("cs") or []:
        if cs_row.get("tid") == 0:
            return cs_row
    return None


def _candidate_rows(
    total_row: dict, office_title: str, result_type: str, contest_code: str, party_code: str,
) -> list[ResultRow]:
    """
    contest_code/party_code are echoed into every row's `raw` dict because
    results/tasks.py::_row_source_identity() requires a `contest_code` key
    there to match rows back to the Race that has the same values in its
    own source_metadata (_race_source_identity()) — without it, rows never
    match a race and every VT race stalls at PARTIAL_RESULTS.
    """
    rows: list[ResultRow] = []
    base_raw = {"contest_code": contest_code, "party_code": party_code}

    for cand in total_row.get("rc") or []:
        name = (cand.get("cn") or "").strip()
        if not name:
            continue
        rows.append(ResultRow(
            candidate_name=name,
            option_label=None,
            vote_count=int(cand.get("vc") or 0),
            vote_pct=None,
            is_winner=bool(cand.get("isWinner", False)),
            result_type=result_type,
            office_title=office_title,
            raw={**base_raw, "candidate_id": cand.get("cid"), "party_name": cand.get("pn", "")},
        ))
    for cand in total_row.get("wc") or []:
        cid = cand.get("cid")
        if cid == _OTHER_WRITE_IN_CID:
            rows.append(ResultRow(
                candidate_name=None,
                option_label="Write-in",
                vote_count=int(cand.get("vc") or 0),
                vote_pct=None,
                is_winner=False,
                result_type=result_type,
                office_title=office_title,
                is_write_in_aggregate=True,
                raw={**base_raw, "candidate_id": cid},
            ))
            continue
        name = (cand.get("cn") or "").strip()
        if not name:
            continue
        rows.append(ResultRow(
            candidate_name=name,
            option_label=None,
            vote_count=int(cand.get("vc") or 0),
            vote_pct=None,
            is_winner=bool(cand.get("isWinner", False)),
            result_type=result_type,
            office_title=office_title,
            raw={**base_raw, "candidate_id": cid, "party_name": cand.get("pn", "")},
        ))
    return rows


@register
class VermontAdapter(StateResultsAdapter):
    state = "VT"
    VERSION_CACHE_TIMEOUT = 86400 * 30

    @classmethod
    def version_cache_key(cls, election_id: int) -> str:
        return f"vt_sos:results_version:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election, Race

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("vt_results.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        election_guid = (election.source_metadata or {}).get("election_guid")
        source_url = f"https://static.electionresults.vermont.gov/elections/{election_guid}.json" if election_guid else ""

        if not election_guid:
            logger.warning("vt_results.adapter.no_election_guid pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes="Election missing vt_sos election_guid in source_metadata",
            )

        races = list(Race.objects.filter(election=election, source_metadata__has_key="contest_variant"))
        if not races:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="none",
                notes="No VT SOS races found for this election",
            )

        client = VermontSosClient()
        try:
            manifest = client.get_election_manifest(election_guid)
        except VtSosRetryableError:
            raise
        except VtSosError as exc:
            logger.error("vt_results.adapter.manifest_fetch_failed election=%d: %s", election_id, exc)
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="none",
                notes=f"Failed to fetch VT election manifest: {exc}",
            )

        fingerprint = manifest.get("lastUpdatedDate", "")
        cache_key = self.version_cache_key(election_id)
        if fingerprint and cache.get(cache_key) == fingerprint:
            return AdapterResult(
                rows=[], source_url=source_url, mapping_confidence="full",
                unchanged=True, source_version=fingerprint,
            )

        is_official = bool((manifest.get("electionDetails") or {}).get("isOfficial", False))
        result_type = OfficialResult.ResultType.OFFICIAL if is_official else OfficialResult.ResultType.UNOFFICIAL

        category_cache: dict[str, Optional[dict]] = {}
        all_rows: list[ResultRow] = []
        notes_parts: list[str] = []

        for race in races:
            rmeta = race.source_metadata or {}
            category = rmeta.get("category")
            party_code = rmeta.get("party_code", "")
            office_id = rmeta.get("office_id")
            district_code = rmeta.get("district_code", "")

            if category not in category_cache:
                category_meta = manifest.get(category) or {}
                if not category_meta.get("isEnable"):
                    category_cache[category] = None
                else:
                    try:
                        category_cache[category] = client.get_category(category_meta["path"])
                    except VtSosError as exc:
                        logger.warning(
                            "vt_results.adapter.category_error category=%s election=%d err=%s",
                            category, election_id, exc,
                        )
                        category_cache[category] = None
                        notes_parts.append(f"category_error:{category}")

            category_data = category_cache.get(category)
            if not category_data:
                continue

            contest = _find_contest(category_data, party_code, office_id, district_code)
            if not contest:
                continue

            total_row = _total_row(contest)
            if not total_row:
                continue

            contest_code = rmeta.get("contest_code", "")
            all_rows.extend(
                _candidate_rows(total_row, race.office_title, result_type, contest_code, party_code)
            )

        return AdapterResult(
            rows=all_rows,
            source_url=source_url,
            mapping_confidence="full",
            notes="; ".join(notes_parts),
            source_version=fingerprint,
        )
