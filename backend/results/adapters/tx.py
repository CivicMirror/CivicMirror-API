"""
Texas GoElect ENR results adapter.

Per poll cycle:
  1. GET /election/{id} — check Version integer n for changes
  2. GET /election/{id} (full data) — parse OfficeSummary + StateWideQ for statewide rows
  3. GET /election/countyInfo/{id} — parse per-county race results

result_type:
  'complete_unofficial' — all counties and precincts reported (CR==CT and PR==PT)
  'unofficial'          — partial reporting
  'official'            — reserved; GoElect has no certification flag yet
"""
from __future__ import annotations

import logging

from django.core.cache import cache

from integrations.tx_goelect.client import TxGoElectClient

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

@register
class TxAdapter(StateResultsAdapter):
    state = "TX"
    VERSION_CACHE_TIMEOUT = 86400 * 30  # 30 days

    def version_cache_key(self, election_id: int) -> str:
        return f"tx_goelect:ver:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("TXAdapter: election %d not found", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election {election_id} not found",
            )

        tx_election_id = (election.source_metadata or {}).get("tx_election_id")
        if not tx_election_id:
            logger.warning("TXAdapter: no tx_election_id for election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes="No tx_election_id in election.source_metadata — run sync_tx_elections first",
            )

        client = TxGoElectClient()
        base_url = f"https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/election/{tx_election_id}"

        version = client.get_version(tx_election_id)
        cache_key = self.version_cache_key(election_id)
        if version is not None and cache.get(cache_key) == str(version):
            logger.debug("TXAdapter: version unchanged tx_id=%d n=%d", tx_election_id, version)
            return AdapterResult(
                rows=[], source_url=base_url, mapping_confidence="full",
                unchanged=True, source_version=str(version),
            )

        try:
            data = client.get_election_data(tx_election_id)
            county_data = client.get_county_results(tx_election_id)
        except Exception as exc:
            logger.error("TXAdapter: fetch failed tx_id=%d: %s", tx_election_id, exc)
            return AdapterResult(
                rows=[], source_url=base_url, mapping_confidence="none",
                notes=f"Fetch failed: {exc}",
            )

        home = data.get("home") or {}
        cr = (home.get("CountiesReporting") or {})
        pr = (home.get("PrecinctsReporting") or {})
        all_complete = (
            cr.get("CR", 0) == cr.get("CT", -1) and
            pr.get("PR", 0) == pr.get("PT", -1) and
            cr.get("CT", 0) > 0
        )
        result_type = "complete_unofficial" if all_complete else "unofficial"

        rows: list[ResultRow] = []

        # ── Statewide candidate rows from OfficeSummary ──────────────────────
        for os_entry in (data.get("office_summary") or {}).get("OS") or []:
            office_id = os_entry.get("OID")
            office_name = os_entry.get("ON") or os_entry.get("N") or ""
            candidates_raw = os_entry.get("C") or []
            if isinstance(candidates_raw, dict):
                candidates_raw = list(candidates_raw.values())

            for cand in candidates_raw:
                cand_id = cand.get("ID") or cand.get("id")
                name = cand.get("BN") or cand.get("N") or ""
                rows.append(ResultRow(
                    candidate_name=name or None,
                    option_label=None,
                    vote_count=int(cand.get("V") or 0),
                    vote_pct=float(cand.get("PE") or 0) or None,
                    is_winner=None,
                    result_type=result_type,
                    office_title=office_name or None,
                    jurisdiction_fragment="",
                    raw={
                        "tx_candidate_id": cand_id,
                        "tx_election_id": tx_election_id,
                        "tx_office_id": office_id,
                        "party": cand.get("P", ""),
                        "early_votes": int(cand.get("EV") or 0),
                    },
                ))

        # ── Statewide proposition rows from StateWideQ ───────────────────────
        for q_entry in (data.get("statewide_q") or {}).get("Q") or []:
            office_id = q_entry.get("OID")
            office_name = q_entry.get("ON") or q_entry.get("N") or ""
            options_raw = q_entry.get("C") or []
            if isinstance(options_raw, dict):
                options_raw = list(options_raw.values())

            for opt in options_raw:
                opt_id = opt.get("ID") or opt.get("id")
                label = opt.get("N") or opt.get("BN") or ""
                rows.append(ResultRow(
                    candidate_name=None,
                    option_label=label or None,
                    vote_count=int(opt.get("V") or 0),
                    vote_pct=float(opt.get("PE") or 0) or None,
                    is_winner=None,
                    result_type=result_type,
                    office_title=office_name or None,
                    jurisdiction_fragment="",
                    raw={
                        "tx_candidate_id": opt_id,
                        "tx_election_id": tx_election_id,
                        "tx_office_id": office_id,
                        "early_votes": int(opt.get("EV") or 0),
                    },
                ))

        # ── County rows from countyInfo ───────────────────────────────────────
        for county_id_str, county in (county_data or {}).items():
            county_name = (county.get("N") or "").lower()
            county_mid = county.get("MID")
            fragment = county_name or county_id_str

            for race_id_str, race in (county.get("Races") or {}).items():
                office_id = race.get("OID")
                office_name = race.get("N") or ""
                candidates_raw = race.get("C") or {}
                if isinstance(candidates_raw, dict):
                    candidates_raw = list(candidates_raw.values())

                for cand in candidates_raw:
                    cand_id = cand.get("id") or cand.get("ID")
                    name = cand.get("N") or cand.get("BN") or ""
                    rows.append(ResultRow(
                        candidate_name=name or None,
                        option_label=None,
                        vote_count=int(cand.get("V") or 0),
                        vote_pct=float(cand.get("PE") or 0) or None,
                        is_winner=None,
                        result_type=result_type,
                        office_title=office_name or None,
                        jurisdiction_fragment=fragment,
                        raw={
                            "tx_candidate_id": cand_id,
                            "tx_election_id": tx_election_id,
                            "tx_office_id": office_id,
                            "county_mid": county_mid,
                            "party": cand.get("P", ""),
                            "early_votes": int(cand.get("EV") or 0),
                        },
                    ))

        logger.info(
            "TXAdapter: tx_id=%d rows=%d result_type=%s version=%s",
            tx_election_id, len(rows), result_type, version,
        )

        return AdapterResult(
            rows=rows,
            source_url=base_url,
            mapping_confidence="full",
            source_version=str(version) if version is not None else "",
        )
