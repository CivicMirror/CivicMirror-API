"""
Connecticut (CT) results adapter — PCC Technology EMS (ctemspublic.tgstg.net).

Vendor: PCC Technology / tgstg.net, operated by CT Secretary of the State.
Source: https://ctemspublic.tgstg.net  (AngularJS SPA, public, no auth)

The EMS serves pre-generated static JSON files refreshed every ~3 minutes
during live elections.  60+ elections are available from Nov 2016 onward.

Migration note: CT purchased TotalVote (same vendor/API as the AR adapter) in
June 2024.  Deployment timeline is TBD; the PCC EMS is confirmed active through
Nov 2026.  When CT goes TotalVote, update source_metadata to use
totalvote_election_id instead.

Required Election.source_metadata key:
    ct_election_id   str  PCC EMS election ID (e.g. "91", "97")

Ingestion flow:
    1. GET /election/{id}/Version.json       → {"Version": 70782}
    2. Version cache check (unchanged → skip)
    3. GET reports_Electiondata.json         → IO flag (certified = official)
    4. GET Lookupdata.json                   → offices, candidates, parties (~1 MB)
    5. GET stateVotes_Electiondata.json      → all vote totals
    6. GET candidateGrouping_Electiondata.json → winner candidates per office
    7. GET ballotQuestion_Electiondata.json  → statewide ballot measures

Version caching:
    Cache key:  ct_elect:ver:{election_pk}
    Cache value: str(version_int)  e.g. "70782"
    TTL:        30 days (written by ingest task after successful DB work)

Data quirks:
    - officeList is a *list of single-key dicts*, not a plain dict; must be flattened.
    - candidateGrouping defines winner set; offices absent from it → is_winner=None.
    - V/TO fields are strings ("5,290", "55.78%"); must be cleaned before parsing.
    - Candidate NM="." indicates anonymized / placeholder rows; they are skipped.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests
from django.core.cache import cache

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_EMS_BASE = "https://ctemspublic.tgstg.net/ng-app/data"
_TIMEOUT_SHORT = 15   # Version.json
_TIMEOUT_LONG = 60    # Lookupdata.json (~1 MB), stateVotes (~250 KB)


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


def _flatten_office_list(office_list: list) -> dict:
    """Flatten [{officeID: {ID,NM,OT,...}}, ...] into {officeID: {ID,NM,OT,...}}."""
    result: dict = {}
    for item in office_list or []:
        if isinstance(item, dict):
            for oid, odata in item.items():
                result[str(oid)] = odata
    return result


def _build_winner_set(candidate_grouping: dict) -> tuple[set, set]:
    """
    Parse candidateGrouping into a set of (officeID, candidateID) winner pairs
    and a set of officeIDs that have winner data at all.

    Offices absent from candidateGrouping receive is_winner=None (e.g. presidential).
    """
    winner_pairs: set = set()
    offices_with_winners: set = set()
    for oid, cand_list in (candidate_grouping or {}).items():
        oid = str(oid)
        offices_with_winners.add(oid)
        for entry in cand_list or []:
            if isinstance(entry, dict):
                for cid in entry.keys():
                    winner_pairs.add((oid, str(cid)))
    return winner_pairs, offices_with_winners


def _parse_state_votes(
    state_votes: dict,
    office_map: dict,
    candidate_map: dict,
    winner_pairs: set,
    offices_with_winners: set,
    result_type: str,
) -> list[ResultRow]:
    """Convert stateVotes_Electiondata into ResultRow objects."""
    rows: list[ResultRow] = []
    for oid, cand_list in state_votes.items():
        oid = str(oid)
        office_info = office_map.get(oid, {})
        office_title = (office_info.get('NM') or '').strip() or None

        if not isinstance(cand_list, list):
            continue

        for entry in cand_list:
            if not isinstance(entry, dict):
                continue
            for cid, cv in entry.items():
                cid = str(cid)
                cinfo = candidate_map.get(cid, {})
                name = (cinfo.get('NM') or '').strip()
                if not name or name == '.':
                    continue

                # Offices with grouping data → True/False; absent offices → None
                if oid in offices_with_winners:
                    is_winner = (oid, cid) in winner_pairs
                else:
                    is_winner = None

                rows.append(ResultRow(
                    office_title=office_title,
                    candidate_name=name,
                    option_label=None,
                    vote_count=_safe_int(cv.get('V', 0)),
                    vote_pct=_safe_float(cv.get('TO')),
                    is_winner=is_winner,
                    result_type=result_type,
                    raw={'officeID': oid, 'candidateID': cid, 'OT': office_info.get('OT', '')},
                ))

    return rows


def _parse_ballot_questions(ballot_data: dict, result_type: str) -> list[ResultRow]:
    """Convert statewide ballot questions into ResultRow objects (YES/NO options)."""
    rows: list[ResultRow] = []
    statewide = ballot_data.get('State Wide') or []
    for question in statewide:
        office_title = (question.get('QN') or '').strip() or None
        for label in ('YES', 'NO'):
            raw_val = question.get(label, '0')
            if raw_val == '-':
                continue
            rows.append(ResultRow(
                office_title=office_title,
                candidate_name=None,
                option_label=label,
                vote_count=_safe_int(raw_val),
                vote_pct=None,
                is_winner=None,
                result_type=result_type,
                raw={'question': office_title, 'option': label},
            ))
    return rows


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register
class ConnecticutAdapter(StateResultsAdapter):
    state = "CT"
    VERSION_CACHE_TIMEOUT = 86400 * 30  # 30 days

    @classmethod
    def version_cache_key(cls, election_id: int) -> str:
        return f"ct_elect:ver:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("ct_elect.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url='', mapping_confidence='none',
                notes=f'Election pk={election_id} not found',
            )

        meta = election.source_metadata or {}
        ct_id = str(meta.get('ct_election_id', '')).strip()

        if not ct_id:
            logger.warning(
                "ct_elect.adapter.no_election_id election=%s pk=%d",
                getattr(election, 'source_id', '?'), election_id,
            )
            return AdapterResult(
                rows=[], source_url='', mapping_confidence='none',
                notes='Set ct_election_id in Election.source_metadata',
            )

        # --- Version poll --------------------------------------------------------
        ver_url = f"{_EMS_BASE}/election/{ct_id}/Version.json"
        try:
            ver_resp = requests.get(ver_url, timeout=_TIMEOUT_SHORT)
            ver_resp.raise_for_status()
            ver_data = ver_resp.json()
        except requests.RequestException as exc:
            logger.error(
                "ct_elect.adapter.version_fetch_failed ct_id=%s: %s", ct_id, exc,
            )
            raise

        current_ver = str(ver_data.get('Version', ''))
        cache_key = self.version_cache_key(election_id)
        if current_ver and cache.get(cache_key) == current_ver:
            logger.debug(
                "ct_elect.adapter.unchanged ct_id=%s ver=%s", ct_id, current_ver,
            )
            return AdapterResult(
                rows=[], source_url=ver_url, mapping_confidence='full',
                unchanged=True, source_version=current_ver,
            )

        # --- Fetch data files ----------------------------------------------------
        base = f"{_EMS_BASE}/election/{ct_id}/{current_ver}"

        try:
            reports = requests.get(
                f"{base}/reports_Electiondata.json", timeout=_TIMEOUT_SHORT,
            )
            reports.raise_for_status()
            report_data = reports.json()

            lookup_resp = requests.get(
                f"{base}/Lookupdata.json", timeout=_TIMEOUT_LONG,
            )
            lookup_resp.raise_for_status()
            lookup = lookup_resp.json()

            sv_url = f"{base}/stateVotes_Electiondata.json"
            sv_resp = requests.get(sv_url, timeout=_TIMEOUT_LONG)
            sv_resp.raise_for_status()
            state_votes = sv_resp.json()

            cg_resp = requests.get(
                f"{base}/candidateGrouping_Electiondata.json", timeout=_TIMEOUT_LONG,
            )
            cg_resp.raise_for_status()
            candidate_grouping = cg_resp.json()

            bq_resp = requests.get(
                f"{base}/ballotQuestion_Electiondata.json", timeout=_TIMEOUT_SHORT,
            )
            bq_resp.raise_for_status()
            ballot_questions = bq_resp.json()

        except requests.RequestException as exc:
            logger.error(
                "ct_elect.adapter.data_fetch_failed ct_id=%s ver=%s: %s",
                ct_id, current_ver, exc,
            )
            raise

        # --- Build reference maps -----------------------------------------------
        is_official = str(report_data.get('IO', 'False')).lower() == 'true'
        result_type = 'official' if is_official else 'unofficial'

        office_map = _flatten_office_list(lookup.get('officeList', []))
        candidate_map = lookup.get('candidateIds', {})
        winner_pairs, offices_with_winners = _build_winner_set(candidate_grouping)

        # --- Parse ---------------------------------------------------------------
        rows = _parse_state_votes(
            state_votes, office_map, candidate_map,
            winner_pairs, offices_with_winners, result_type,
        )
        rows += _parse_ballot_questions(ballot_questions, result_type)

        logger.info(
            "ct_elect.adapter.fetched ct_id=%s ver=%s rows=%d official=%s",
            ct_id, current_ver, len(rows), is_official,
        )

        return AdapterResult(
            rows=rows,
            source_url=sv_url,
            mapping_confidence='full',
            source_version=current_ver,
        )
