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
from typing import Any

from django.core.cache import cache
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from elections.models import Election

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_FLATEAU_BASE = "https://flateau.elections.ny.gov"
_TIMEOUT_MS = 60000  # 60 seconds


@register
class NewYorkAdapter(StateResultsAdapter):
    state = "NY"

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

        election_name = (election.source_metadata or {}).get("election_name")
        if not election_name:
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

        # Download endpoint
        encoded_name = urllib.parse.quote(election_name)
        api_url = f"{_FLATEAU_BASE}/api/downloads?electionName={encoded_name}&category=results&format=json"

        # Fetch using Playwright stealth
        try:
            logger.info("ny_sos.adapter.fetching election_id=%d using Playwright", election_id)
            data = self._fetch_via_playwright_stealth(api_url)
        except Exception as exc:
            logger.error("ny_sos.adapter.fetch_failed: %s", exc)
            return AdapterResult(
                rows=[],
                source_url=api_url,
                mapping_confidence="none",
                notes=f"Playwright fetch failed: {exc}",
            )

        if not isinstance(data, list):
            logger.error("ny_sos.adapter.unexpected_data_type type=%s", type(data))
            return AdapterResult(
                rows=[],
                source_url=api_url,
                mapping_confidence="none",
                notes=f"Expected list of results, got {type(data)}",
            )

        # Parse results
        rows = _parse_ny_results(data)

        # Fingerprint the JSON payload for version cache
        payload_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        new_hash = hashlib.sha256(payload_bytes).hexdigest()
        cache_key = self.version_cache_key(election_id)
        cached_hash = cache.get(cache_key)

        if cached_hash == new_hash:
            logger.debug("ny_sos.adapter.unchanged election_id=%d", election_id)
            return AdapterResult(
                rows=[],
                source_url=api_url,
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
            source_url=api_url,
            mapping_confidence="full",
            source_version=new_hash,
        )

    def _fetch_via_playwright_stealth(self, url: str) -> Any:
        with Stealth().use_sync(sync_playwright()) as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ]
            )
            # Use a realistic User Agent
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            # Navigate to the home page first to pass CF challenge and get cookies
            logger.debug("Navigating to Flateau home page")
            page.goto(_FLATEAU_BASE, timeout=_TIMEOUT_MS)
            page.wait_for_load_state("networkidle", timeout=_TIMEOUT_MS)

            # Evaluate API fetch within the page context to inherit cookies/clearance
            logger.debug("Evaluating fetch for API URL: %s", url)
            result = page.evaluate(
                """async (apiUrl) => {
                    const response = await fetch(apiUrl);
                    if (!response.ok) {
                        throw new Error(`API fetch failed with status ${response.status}`);
                    }
                    return await response.json();
                }""",
                url
            )
            browser.close()
            return result


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
        jurisdiction = row.get("contestJurisdiction") or ""
        precinct = row.get("precinct")
        if precinct:
            jurisdiction_fragment = f"{jurisdiction} - {precinct}".strip(" - ")
        else:
            jurisdiction_fragment = jurisdiction

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
