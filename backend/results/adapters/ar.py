"""
Arkansas (AR) results adapter — TotalVote / TotalResults ENR platform.

Vendor: BPro Inc. (Pierre, SD), acquired by KNOWiNK (2020).
API:    https://enr-results-api.totalresults.com  (public, unauthenticated, multi-tenant)
Swagger: https://enr-results-api.totalresults.com/swagger/v1/swagger.json

Required Election.source_metadata key:
    totalvote_election_id  str  TotalResults election ID — GUID or legacy numeric string

Optional:
    totalvote_cid          str  API client ID (defaults to "arkansas")

Ingestion paths:
    GUID elections (post-2024):
        GET /{cid}/{eid}/download — single AP-style JSON; resultsType="certified" → official
    Numeric elections (legacy, pre-2025):
        GetContestSearchList builds a contest/choice name map, then
        GetContestResults?contestType=<type> is called per present contestTypeCode;
        results are joined on contestID + choiceID.

Version caching:
    CheckCurrentVersion returns lastUpdated + isOfficial; lastUpdated is used as
    the version string.  Cache key: totalvote:ver:{election_pk}
    The ingest task writes the version after successful DB work.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests
from django.core.cache import cache

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_API_BASE = "https://enr-results-api.totalresults.com"
_DEFAULT_CID = "arkansas"
_TIMEOUT_SHORT = 15   # version poll
_TIMEOUT_LONG = 90    # download / bulk contest results


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _safe_int(val, default: int = 0) -> int:
    try:
        return int(str(val).replace(',', '').strip())
    except (ValueError, TypeError):
        return default


def _safe_float(val) -> Optional[float]:
    try:
        s = str(val).strip().rstrip('%')
        return float(s) if s else None
    except (ValueError, TypeError):
        return None


def _parse_download(data: dict) -> list[ResultRow]:
    """Parse a /download AP-style response into ResultRow objects.

    Only the state-level reporting unit (statewide totals) is used.
    AP winner field: 'X' = winner declared, '' = not winner.
    resultsType 'certified' → result_type 'official'; anything else → 'unofficial'.
    """
    rows: list[ResultRow] = []
    for race in data.get('races') or []:
        office = (race.get('officeName') or '').strip() or None
        results_type = race.get('resultsType', '')
        result_type = 'official' if results_type == 'certified' else 'unofficial'

        for ru in race.get('reportingUnits') or []:
            if ru.get('level') != 'state':
                continue
            for cand in ru.get('candidates') or []:
                first = (cand.get('first') or '').strip()
                last = (cand.get('last') or '').strip()
                name = ' '.join(filter(None, [first, last])) or None

                rows.append(ResultRow(
                    office_title=office,
                    candidate_name=name,
                    option_label=None,
                    vote_count=_safe_int(cand.get('voteCount', 0)),
                    vote_pct=_safe_float(cand.get('votePct')),
                    is_winner=(cand.get('winner', '') == 'X'),
                    result_type=result_type,
                    raw={
                        'candidateID': cand.get('candidateID', ''),
                        'resultsType': results_type,
                        'ballotOrder': cand.get('ballotOrder'),
                    },
                ))

    return rows


def _build_name_map(search_data: dict) -> tuple[dict, set[str]]:
    """Build a contest/choice name map from GetContestSearchList.

    Returns:
        name_map:      {contest_id: {'name': str, 'choices': {choice_id: {'name': str, 'isWriteIn': bool}}}}
        contest_types: set of contestTypeCode strings found (used to drive the GetContestResults loop)
    """
    name_map: dict = {}
    contest_types: set[str] = set()

    contests = (search_data.get('response') or {}).get('contests') or {}
    if not isinstance(contests, dict):
        return name_map, contest_types

    for cid_key, contest in contests.items():
        ct = contest.get('contestTypeCode', '')
        if ct:
            contest_types.add(ct)

        choices: dict = {}
        raw_choices = contest.get('choices') or {}
        if isinstance(raw_choices, dict):
            for choice_id, choice in raw_choices.items():
                choices[str(choice_id)] = {
                    'name': (choice.get('name') or '').strip(),
                    'isWriteIn': bool(choice.get('isWriteIn', False)),
                }

        name_map[str(cid_key)] = {
            'name': (contest.get('contestName') or '').strip(),
            'choices': choices,
        }

    return name_map, contest_types


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register
class ArkansasAdapter(StateResultsAdapter):
    state = "AR"
    VERSION_CACHE_TIMEOUT = 86400 * 30  # 30 days

    @classmethod
    def version_cache_key(cls, election_id: int) -> str:
        return f"totalvote:ver:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("ar_elect.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url='', mapping_confidence='none',
                notes=f'Election pk={election_id} not found',
            )

        meta = election.source_metadata or {}
        cid = (meta.get('totalvote_cid') or _DEFAULT_CID).strip()
        tr_id = str(meta.get('totalvote_election_id', '')).strip()

        if not tr_id:
            logger.warning(
                "ar_elect.adapter.no_election_id election=%s pk=%d",
                getattr(election, 'source_id', '?'), election_id,
            )
            return AdapterResult(
                rows=[], source_url='', mapping_confidence='none',
                notes='Set totalvote_election_id in Election.source_metadata',
            )

        # --- Version poll (cheap) ------------------------------------------------
        ver_url = (
            f"{_API_BASE}/Contest/CheckCurrentVersion"
            f"?cId={cid}&electionID={tr_id}"
        )
        try:
            ver_resp = requests.get(ver_url, timeout=_TIMEOUT_SHORT)
            ver_resp.raise_for_status()
            ver_data = ver_resp.json()
        except requests.RequestException as exc:
            logger.error(
                "ar_elect.adapter.version_check_failed cid=%s eid=%s: %s",
                cid, tr_id, exc,
            )
            raise

        current_ver = ver_data.get('lastUpdated', '')
        is_official = bool(ver_data.get('isOfficial', False))

        cache_key = self.version_cache_key(election_id)
        if current_ver and cache.get(cache_key) == current_ver:
            logger.debug(
                "ar_elect.adapter.unchanged cid=%s eid=%s ver=%s",
                cid, tr_id, current_ver,
            )
            return AdapterResult(
                rows=[], source_url=ver_url, mapping_confidence='full',
                unchanged=True, source_version=current_ver,
            )

        # --- Fetch results -------------------------------------------------------
        # GUIDs contain hyphens (e.g. b412bdef-f97a-…); legacy IDs are plain integers.
        is_guid = '-' in tr_id

        if is_guid:
            source_url, rows = self._fetch_download(cid, tr_id)
        else:
            source_url, rows = self._fetch_granular(cid, tr_id, is_official)

        logger.info(
            "ar_elect.adapter.fetched cid=%s eid=%s rows=%d official=%s guid=%s",
            cid, tr_id, len(rows), is_official, is_guid,
        )

        return AdapterResult(
            rows=rows,
            source_url=source_url,
            mapping_confidence='full',
            source_version=current_ver,
        )

    # -------------------------------------------------------------------------
    # GUID path: single bulk /download
    # -------------------------------------------------------------------------

    def _fetch_download(self, cid: str, tr_id: str) -> tuple[str, list[ResultRow]]:
        url = f"{_API_BASE}/{cid}/{tr_id}/download"
        resp = requests.get(url, timeout=_TIMEOUT_LONG)
        resp.raise_for_status()
        return url, _parse_download(resp.json())

    # -------------------------------------------------------------------------
    # Numeric (legacy) path: GetContestSearchList + per-type GetContestResults
    # -------------------------------------------------------------------------

    def _fetch_granular(
        self, cid: str, tr_id: str, is_official: bool,
    ) -> tuple[str, list[ResultRow]]:
        result_type = 'official' if is_official else 'unofficial'

        search_url = (
            f"{_API_BASE}/Contest/GetContestSearchList"
            f"?cId={cid}&electionID={tr_id}"
        )
        search_resp = requests.get(search_url, timeout=_TIMEOUT_LONG)
        search_resp.raise_for_status()

        name_map, contest_types = _build_name_map(search_resp.json())
        rows: list[ResultRow] = []

        for ct in sorted(contest_types):
            results_url = (
                f"{_API_BASE}/Contest/GetContestResults"
                f"?cId={cid}&electionID={tr_id}&contestType={ct}"
            )
            try:
                r = requests.get(results_url, timeout=_TIMEOUT_LONG)
                r.raise_for_status()
            except requests.RequestException as exc:
                logger.warning(
                    "ar_elect.adapter.granular_fetch_failed contestType=%s: %s",
                    ct, exc,
                )
                continue

            contests = (r.json().get('response') or {}).get('contests') or {}
            if not isinstance(contests, dict):
                continue

            for contest_id, contest in contests.items():
                name_info = name_map.get(str(contest_id), {})
                office = (name_info.get('name') or '').strip() or None
                choice_name_map = name_info.get('choices', {})

                for choice in contest.get('choices') or []:
                    choice_id = str(choice.get('choiceID', ''))
                    choice_info = choice_name_map.get(choice_id, {})
                    candidate_name = (choice_info.get('name') or '').strip() or None
                    is_write_in = bool(choice_info.get('isWriteIn', False))

                    rows.append(ResultRow(
                        office_title=office,
                        candidate_name=candidate_name,
                        option_label=None,
                        vote_count=_safe_int(choice.get('totalVotes', 0)),
                        vote_pct=_safe_float(choice.get('votePercent')),
                        is_winner=choice.get('isWinner'),
                        result_type=result_type,
                        is_write_in_aggregate=is_write_in,
                        raw={
                            'contestID': contest_id,
                            'choiceID': choice_id,
                            'contestType': ct,
                        },
                    ))

        return search_url, rows
