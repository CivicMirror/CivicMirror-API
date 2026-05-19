"""
Generic Clarity Elections adapter (JSON API).

Clarity Elections powers official results for WV, CO, IA, SC, and others.
State-specific adapters subclass this and set `state`.

Data flow:
  1. GET {results_url}current_ver.txt → numeric version (e.g. "371599")
  2. Compare with cached version via Django cache
  3. If unchanged: return AdapterResult(unchanged=True) — task skips DB work
  4. GET {results_url}{version}/json/en/summary.json → all contest results
  5. Parse each contest into ResultRow objects
  6. Return AdapterResult with source_version set; task writes version to cache on success

The results_url field on Election is set manually in Django admin.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests
from django.core.cache import cache

from elections.models import Election
from results.models import OfficialResult

from .base import AdapterResult, ResultRow, StateResultsAdapter

logger = logging.getLogger(__name__)


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


def _is_winner(val) -> Optional[bool]:
    try:
        return int(val) == 1
    except (ValueError, TypeError):
        return None


class ClarityAdapter(StateResultsAdapter):
    """
    Base adapter for any state running Clarity Elections (ENR Web 4.x).

    Subclasses set `state` and apply @register.
    """

    state: str  # overridden by concrete subclass

    FETCH_TIMEOUT_SHORT = 15   # current_ver.txt
    FETCH_TIMEOUT_LONG = 60    # summary.json
    VERSION_CACHE_TIMEOUT = 86400 * 30  # 30 days

    @classmethod
    def version_cache_key(cls, election_id: int) -> str:
        return f"clarity:ver:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("ClarityAdapter: election %s not found", election_id)
            return AdapterResult(
                rows=[], source_url='', mapping_confidence='none',
                notes='election not found',
            )

        raw_url = (election.results_url or '').strip()
        if not raw_url:
            logger.warning("ClarityAdapter: no results_url set for election %s", election_id)
            return AdapterResult(
                rows=[], source_url='', mapping_confidence='none',
                notes='no results_url set on election',
            )

        results_url = raw_url.rstrip('/') + '/'

        # --- Fetch current version ------------------------------------------------
        ver_url = f"{results_url}current_ver.txt"
        try:
            ver_resp = requests.get(ver_url, timeout=self.FETCH_TIMEOUT_SHORT)
            ver_resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("ClarityAdapter: failed to fetch version for election %s: %s", election_id, exc)
            raise

        current_ver = ver_resp.text.strip()
        if not current_ver.isdigit():
            logger.warning("ClarityAdapter: unexpected version string '%s' for election %s", current_ver, election_id)

        # --- Version change check (read-only; write happens in task after DB commit) ---
        cache_key = self.version_cache_key(election_id)
        cached_ver = cache.get(cache_key)
        if cached_ver == current_ver:
            logger.debug("ClarityAdapter: version unchanged (%s) for election %s", current_ver, election_id)
            return AdapterResult(
                rows=[], source_url=results_url, mapping_confidence='full',
                notes=f"version unchanged ({current_ver})",
                unchanged=True, source_version=current_ver,
            )

        # --- Fetch summary.json ---------------------------------------------------
        summary_url = f"{results_url}{current_ver}/json/en/summary.json"
        try:
            data_resp = requests.get(summary_url, timeout=self.FETCH_TIMEOUT_LONG)
            data_resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("ClarityAdapter: failed to fetch summary for election %s: %s", election_id, exc)
            raise

        payload = data_resp.json()
        if isinstance(payload, dict):
            contests = payload.get('Contests', payload.get('contests', []))
        elif isinstance(payload, list):
            contests = payload
        else:
            logger.error("ClarityAdapter: unexpected summary.json shape for election %s", election_id)
            return AdapterResult(
                rows=[], source_url=summary_url, mapping_confidence='none',
                notes='unexpected summary.json shape',
                source_version=current_ver,
            )

        rows = self._parse_contests(contests, current_ver)

        pr_total = sum(_safe_int(c.get('PR', 0)) for c in contests if isinstance(c, dict))
        tp_total = sum(_safe_int(c.get('TP', 1)) for c in contests if isinstance(c, dict))

        logger.info(
            "ClarityAdapter: parsed %d rows from %d contests for election %s (ver=%s, pr=%d/%d)",
            len(rows), len(contests), election_id, current_ver, pr_total, tp_total,
        )

        return AdapterResult(
            rows=rows,
            source_url=summary_url,
            mapping_confidence='full',
            notes=f"version={current_ver} contests={len(contests)} precincts={pr_total}/{tp_total}",
            source_version=current_ver,
        )

    def _parse_contests(self, contests: list, current_ver: str) -> list[ResultRow]:
        rows: list[ResultRow] = []
        for contest in contests:
            if not isinstance(contest, dict):
                continue

            office_title = contest.get('C', '') or ''
            candidates: list = contest.get('CH', []) or []
            votes: list = contest.get('V', []) or []
            pcts: list = contest.get('PCT', []) or []
            winners: list = contest.get('W', []) or []
            pr = _safe_int(contest.get('PR', 0))
            tp = _safe_int(contest.get('TP', 1))

            for i, name in enumerate(candidates):
                if name is None:
                    continue
                rows.append(ResultRow(
                    office_title=office_title,
                    candidate_name=str(name).strip() or None,
                    option_label=None,
                    vote_count=_safe_int(votes[i] if i < len(votes) else 0),
                    vote_pct=_safe_float(pcts[i] if i < len(pcts) else None),
                    is_winner=_is_winner(winners[i] if i < len(winners) else None),
                    result_type=OfficialResult.ResultType.UNOFFICIAL,
                    raw={'C': office_title, 'PR': pr, 'TP': tp, 'ver': current_ver},
                ))

        return rows
