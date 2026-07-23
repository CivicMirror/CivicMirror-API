"""
New York (NY) results adapter using Dr. John L. Flateau Database API (flateau.elections.ny.gov).

Access: Cloudflare protected. Uses Playwright with stealth mode.
Required Election.source_metadata key:
    election_name: str (exact election name, e.g. "Wyoming CSD - Budget Election - 05/19/2026 - Certified 05/19/2026")
"""
from __future__ import annotations

import hashlib
import json
import logging
import urllib.parse
from dataclasses import dataclass
from typing import Any

from django.core.cache import cache
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from elections.models import Election
from integrations.ny_boe.mappers import normalize_ny_office, normalize_ny_party

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_FLATEAU_BASE = "https://flateau.elections.ny.gov"
_TIMEOUT_MS = 60000  # 60 seconds
_CACHE_TTL = 86400 * 30


@dataclass
class FetchOutcome:
    url: str
    ok: bool
    data: Any = None
    error: str = ""


def _normalize_token(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalize_party_code(value: Any) -> str:
    return normalize_ny_party(value)


def _contest_code_for_row(row: dict[str, Any]) -> str:
    office = normalize_ny_office(row.get("office"))
    district = _normalize_token(row.get("district") or row.get("contestDistrict"))
    district2 = _normalize_token(row.get("district2") or row.get("contestDistrict2"))
    return f"{office}|{district}|{district2}"


def resolve_flateau_election_names(election) -> list[str]:
    metadata = election.source_metadata or {}
    names = metadata.get("flateau_election_names")
    if isinstance(names, str):
        names = [names]
    if names:
        return sorted({str(name).strip() for name in names if str(name).strip()})

    legacy_name = metadata.get("election_name")
    if legacy_name:
        return [str(legacy_name).strip()]

    return []


@register
class NewYorkAdapter(StateResultsAdapter):
    state = "NY"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    @classmethod
    def version_cache_key(cls, election_id: int) -> str:
        return f"ny_sos:hash:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("ny_sos.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        election_names = resolve_flateau_election_names(election)
        if not election_names:
            logger.warning(
                "ny_sos.adapter.no_election_name election=%s pk=%d",
                election.source_id, election_id,
            )
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes="No election_name in election.source_metadata",
            )

        api_urls = [_download_url(name) for name in election_names]
        source_url = _FLATEAU_BASE

        try:
            logger.info("ny_sos.adapter.fetching election_id=%d using Playwright", election_id)
            outcomes = self._fetch_json_many(api_urls)
        except Exception as exc:
            logger.error("ny_sos.adapter.fetch_failed: %s", exc)
            return AdapterResult(
                rows=[],
                source_url=source_url,
                mapping_confidence="none",
                notes=f"Playwright fetch failed: {exc}",
            )

        successes: list[tuple[str, list[dict[str, Any]]]] = []
        failures = []
        for election_name, outcome in zip(election_names, outcomes):
            if not outcome.ok:
                failures.append((election_name, outcome.error))
                continue
            if not isinstance(outcome.data, list):
                failures.append((election_name, f"Expected list, got {type(outcome.data)}"))
                continue
            enriched = [_enrich_row(row, election_name) for row in outcome.data]
            successes.append((election_name, enriched))

        if not successes:
            logger.error("ny_sos.adapter.all_fetches_failed election_id=%d", election_id)
            return AdapterResult(
                rows=[],
                source_url=source_url,
                mapping_confidence="none",
                notes=f"All Flateau fetches failed; failed={len(failures)}",
            )

        data = []
        for _, payload in successes:
            data.extend(payload)

        rows = _parse_ny_results(data)
        mapping_confidence = "partial" if failures else "full"
        notes = f"fetched={len(successes)} failed={len(failures)}"
        if failures:
            return AdapterResult(
                rows=rows,
                source_url=source_url,
                mapping_confidence=mapping_confidence,
                notes=notes,
                unchanged=False,
                source_version="",
            )

        new_hash = self._source_version_for_payloads(successes)
        cache_key = self.version_cache_key(election_id)
        cached_hash = cache.get(cache_key)

        if cached_hash == new_hash:
            logger.debug("ny_sos.adapter.unchanged election_id=%d", election_id)
            return AdapterResult(
                rows=[],
                source_url=source_url,
                mapping_confidence="full",
                unchanged=True,
                source_version=new_hash,
            )

        logger.info(
            "ny_sos.adapter.fetched election_id=%d rows=%d",
            election_id, len(rows),
        )

        return AdapterResult(
            rows=rows,
            source_url=source_url,
            mapping_confidence="full",
            notes=notes,
            source_version=new_hash,
        )

    def _source_version_for_payloads(self, payloads: list[tuple[str, Any]]) -> str:
        normalized = [
            {"election_name": election_name, "data": data}
            for election_name, data in sorted(payloads, key=lambda item: item[0])
        ]
        payload_bytes = json.dumps(normalized, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload_bytes).hexdigest()

    def _fetch_json_many(self, urls: list[str]) -> list[FetchOutcome]:
        results = []
        with Stealth().use_sync(sync_playwright()) as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            try:
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                page.goto(_FLATEAU_BASE, timeout=_TIMEOUT_MS)
                page.wait_for_load_state("networkidle", timeout=_TIMEOUT_MS)
                for url in urls:
                    try:
                        data = page.evaluate(
                            """async (apiUrl) => {
                                const response = await fetch(apiUrl);
                                if (!response.ok) {
                                    throw new Error(`API fetch failed with status ${response.status}`);
                                }
                                return await response.json();
                            }""",
                            url,
                        )
                        results.append(FetchOutcome(url=url, ok=True, data=data))
                    except Exception as exc:
                        results.append(FetchOutcome(url=url, ok=False, error=str(exc)))
            finally:
                browser.close()
        return results

    def _fetch_via_playwright_stealth(self, url: str) -> Any:
        outcomes = self._fetch_json_many([url])
        outcome = outcomes[0]
        if not outcome.ok:
            raise RuntimeError(outcome.error)
        return outcome.data


def _download_url(election_name: str) -> str:
    encoded_name = urllib.parse.quote(election_name)
    return f"{_FLATEAU_BASE}/api/downloads?electionName={encoded_name}&category=results&format=json"


def _authority_from_election_name(election_name: str) -> str:
    before_dash = election_name.split(" - ", 1)[0]
    return _normalize_token(before_dash or election_name)


def _enrich_row(row: dict[str, Any], election_name: str) -> dict[str, Any]:
    enriched = dict(row)
    authority = _authority_from_election_name(election_name)
    enriched["_flateau_election_name"] = election_name
    enriched["_flateau_authority"] = authority
    enriched["contest_code"] = _contest_code_for_row(enriched)
    party = enriched.get("party") or enriched.get("candidateParty")
    enriched["party_code"] = _normalize_party_code(party)
    return enriched


def _parse_ny_results(data: list[dict[str, Any]]) -> list[ResultRow]:
    rows: list[ResultRow] = []
    for row in data:
        candidate_name = row.get("candidateName")

        # Check if it is a write-in or blank/void
        is_write_in = False
        option_label = None

        # Flateau sometimes has propositionBudgetName / shortDescription for measures
        prop_name = row.get("propositionBudgetName") or row.get("shortDescription")

        if prop_name:
            option_label = prop_name
            candidate_name = None
        elif candidate_name:
            name_upper = candidate_name.upper()
            if "WRITE-IN" in name_upper or "WRITE IN" in name_upper:
                is_write_in = True
                option_label = "Write-In"
                candidate_name = None
            elif name_upper in ("BLANK", "VOID", "SCATTERING", "SCATTERED", "UNRECORDED"):
                option_label = candidate_name
                candidate_name = None

        # If it's none of the above and candidateName is absent, skip it
        if not candidate_name and not option_label:
            continue

        vote_count = 0
        vote_total_val = row.get("voteTotal")
        if vote_total_val is not None:
            try:
                vote_count = int(float(str(vote_total_val).replace(",", "").strip()))
            except (ValueError, TypeError):
                vote_count = 0

        # Outcome
        outcome_val = row.get("outcome")
        is_winner = None
        if outcome_val:
            is_winner = outcome_val.upper() in ("WIN", "PASS")

        # Jurisdiction / precinct mapping
        authority = row.get("_flateau_authority") or ""
        jurisdiction = row.get("contestJurisdiction") or ""
        precinct = row.get("precinct")
        if precinct:
            jurisdiction_fragment = f"{jurisdiction} - {precinct}".strip(" - ")
        else:
            jurisdiction_fragment = jurisdiction
        if authority:
            jurisdiction_fragment = f"{authority} - {jurisdiction_fragment}".strip(" - ")

        rows.append(
            ResultRow(
                candidate_name=candidate_name,
                option_label=option_label,
                vote_count=vote_count,
                vote_pct=None,
                is_winner=is_winner,
                result_type="official",
                office_title=row.get("office"),
                is_write_in_aggregate=is_write_in,
                jurisdiction_fragment=jurisdiction_fragment,
                raw=row,
            )
        )
    return rows
