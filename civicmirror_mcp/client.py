from __future__ import annotations

import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin

import requests


class CivicMirrorAPIError(RuntimeError):
    """Raised when CivicMirror API data cannot satisfy an MCP query."""


class CivicMirrorAPIClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        session: requests.Session | None = None,
        timeout: int | float | None = None,
    ):
        self.base_url = (base_url or os.getenv("CIVICMIRROR_API_BASE_URL") or "http://127.0.0.1:8000/api/v1").rstrip("/")
        self.api_key = api_key or os.getenv("CIVICMIRROR_MCP_API_KEY") or os.getenv("CIVICMIRROR_API_KEY")
        self.session = session or requests.Session()
        self.timeout = timeout or float(os.getenv("CIVICMIRROR_MCP_TIMEOUT", "30"))

    def request(self, path_or_url: str, params: dict[str, Any] | None = None) -> Any:
        url = self._url(path_or_url)
        headers = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key

        try:
            response = self.session.get(url, headers=headers, params=params or {}, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CivicMirrorAPIError(f"CivicMirror API request failed: {exc}") from exc

        try:
            return response.json()
        except ValueError as exc:
            raise CivicMirrorAPIError(f"CivicMirror API returned non-JSON response from {url}") from exc

    def list_paginated(self, path: str, params: dict[str, Any] | None = None, max_pages: int = 10) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: str | None = path
        next_params = dict(params or {})
        pages_seen = 0

        while next_url:
            pages_seen += 1
            if pages_seen > max_pages:
                raise CivicMirrorAPIError(f"Pagination exceeded max_pages={max_pages} for {path}")

            payload = self.request(next_url, next_params)
            next_params = {}

            if isinstance(payload, dict) and isinstance(payload.get("results"), list):
                items.extend(payload["results"])
                next_url = payload.get("next")
                continue

            if isinstance(payload, list):
                items.extend(payload)
                break

            raise CivicMirrorAPIError(f"Unexpected paginated response shape from {path}")

        return items

    def get_results(self, ocd_id: str, election_date: str, contest: str | None = None) -> dict[str, Any]:
        races = self._find_races(ocd_id=ocd_id, election_date=election_date, contest=contest)
        return {
            "ocd_id": ocd_id,
            "election_date": election_date,
            "contest": contest,
            "race_count": len(races),
            "races": [self._race_with_results(race) for race in races],
        }

    def list_adapters(self, state: str | None = None) -> dict[str, Any]:
        payload = self.request("/coverage/sync-status/")
        state_code = state.upper() if state else None

        adapter_states = payload.get("adapter_states", [])
        by_state = payload.get("by_state", {})
        coverage_tiers = payload.get("coverage_tiers", {})

        if state_code:
            adapter_states = [candidate for candidate in adapter_states if candidate.upper() == state_code]
            by_state = {state_code: by_state.get(state_code, {})}
            coverage_tiers = {state_code: coverage_tiers[state_code]} if state_code in coverage_tiers else {}

        return {
            "as_of": payload.get("as_of"),
            "adapter_states": adapter_states,
            "by_state": by_state,
            "coverage_tiers": coverage_tiers,
        }

    def compare_sources(
        self,
        ocd_id: str,
        contest: str,
        election_date: str | None = None,
    ) -> dict[str, Any]:
        races = self._find_races(ocd_id=ocd_id, election_date=election_date, contest=contest)
        race_payloads = [self._race_with_results(race) for race in races]
        by_source = {self._source_name(payload["race"]): payload for payload in race_payloads}
        comparisons = self._compare_source_results(by_source)

        return {
            "ocd_id": ocd_id,
            "contest": contest,
            "election_date": election_date,
            "source_count": len(by_source),
            "sources": by_source,
            "comparisons": comparisons,
        }

    def _find_races(
        self,
        ocd_id: str,
        election_date: str | None = None,
        contest: str | None = None,
    ) -> list[dict[str, Any]]:
        state = self._state_from_ocd_id(ocd_id)
        params: dict[str, Any] = {"state": state, "page_size": 100}
        if election_date:
            params["election_date__gte"] = election_date
            params["election_date__lte"] = election_date
        if contest:
            params["search"] = contest

        races = self.list_paginated("/races/", params=params)
        contest_query = contest.lower() if contest else None
        return [
            race for race in races
            if race.get("ocd_division_id") == ocd_id
            and (
                contest_query is None
                or contest_query in str(race.get("office_title", "")).lower()
                or contest_query in str(race.get("jurisdiction", "")).lower()
            )
        ]

    def _race_with_results(self, race: dict[str, Any]) -> dict[str, Any]:
        race_id = race.get("id")
        if race_id is None:
            raise CivicMirrorAPIError("Race payload is missing id")

        detail = {**race, **self.request(f"/races/{race_id}/")}
        results = self.request(f"/races/{race_id}/results/")
        return {
            "race": detail,
            "results": results,
        }

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        return urljoin(f"{self.base_url}/", path_or_url.lstrip("/"))

    @staticmethod
    def _state_from_ocd_id(ocd_id: str) -> str:
        match = re.search(r"(?:^|/)state:([a-z]{2})(?:/|$)", ocd_id, re.IGNORECASE)
        if not match:
            raise CivicMirrorAPIError(f"OCD ID does not include a state segment: {ocd_id}")
        return match.group(1).upper()

    @staticmethod
    def _source_name(race: dict[str, Any]) -> str:
        return str(race.get("source") or "unknown")

    @classmethod
    def _compare_source_results(cls, sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        if len(sources) < 2:
            return []

        source_names = list(sources)
        baseline_name = source_names[0]
        baseline_rows = cls._results_by_name(sources[baseline_name])
        comparisons: list[dict[str, Any]] = []

        for source_name in source_names[1:]:
            source_rows = cls._results_by_name(sources[source_name])
            for label in sorted(set(baseline_rows) | set(source_rows)):
                baseline = baseline_rows.get(label, {})
                candidate = source_rows.get(label, {})
                comparisons.append({
                    "candidate_or_option": label,
                    "baseline_source": baseline_name,
                    "comparison_source": source_name,
                    "baseline_vote_count": baseline.get("vote_count"),
                    "comparison_vote_count": candidate.get("vote_count"),
                    "vote_count_delta": cls._delta(candidate.get("vote_count"), baseline.get("vote_count")),
                    "baseline_vote_pct": baseline.get("vote_pct"),
                    "comparison_vote_pct": candidate.get("vote_pct"),
                    "vote_pct_delta": cls._delta(candidate.get("vote_pct"), baseline.get("vote_pct")),
                })

        return comparisons

    @classmethod
    def _results_by_name(cls, race_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        race = race_payload.get("race", {})
        candidate_names = {candidate.get("id"): candidate.get("name") for candidate in race.get("candidates", [])}
        option_names = {
            option.get("id"): option.get("option_label")
            for option in race.get("measure_options", [])
        }

        rows = {}
        for row in race_payload.get("results", []):
            label = (
                candidate_names.get(row.get("candidate"))
                or option_names.get(row.get("measure_option"))
                or row.get("jurisdiction_fragment")
                or f"result:{row.get('id', 'unknown')}"
            )
            rows[str(label)] = row
        return rows

    @staticmethod
    def _delta(left: Any, right: Any) -> int | float | None:
        if left is None or right is None:
            return None
        try:
            result = Decimal(str(left)) - Decimal(str(right))
        except (InvalidOperation, ValueError):
            return None
        if result == result.to_integral_value():
            return int(result)
        return float(result)
