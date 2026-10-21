from __future__ import annotations

import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin

import requests

from .schemas import (
    UNREPORTED,
    CompareSourcesOutput,
    GetResultsOutput,
    ListAdaptersOutput,
    Race,
    RaceResults,
    ResultRow,
    SourceComparison,
)

UNREPORTED_SOURCE_KEY = "source:unreported"
"""Key used when the API itself reported no source for a record (never a guessed name)."""


class CivicMirrorAPIError(RuntimeError):
    """Raised when CivicMirror API data cannot satisfy an MCP query."""


class CivicMirrorAPIClient:
    """
    Read-only HTTP client for the CivicMirror DRF API.

    Every request is an HTTP ``GET``; this class exposes no write path (see
    ``mcp_server/tests/test_readonly_regression.py``). It adapts API payloads into
    the typed contracts in ``civicmirror_mcp.schemas`` and never substitutes a
    placeholder for metadata the API did not report.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        session: requests.Session | None = None,
        timeout: int | float | None = None,
    ):
        self.base_url = (base_url or os.getenv("CIVICMIRROR_API_BASE_URL") or "http://127.0.0.1:8000/api/v1").rstrip("/")
        self.api_key = api_key or os.getenv("CIVICMIRROR_MCP_API_KEY")
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

    # -- Tools ---------------------------------------------------------------

    def get_results(self, ocd_id: str, election_date: str, contest: str | None = None) -> GetResultsOutput:
        races = self._find_races(ocd_id=ocd_id, election_date=election_date, contest=contest)
        race_results = [self._race_with_results(race, election_date=election_date) for race in races]

        notes: list[str] = []
        if not race_results:
            notes.append(
                f"No CivicMirror race matched ocd_id={ocd_id!r} on {election_date}"
                + (f" for contest {contest!r}." if contest else ".")
                + " This means CivicMirror holds no such record, not that no election occurred."
            )
        notes.extend(self._coverage_notes(race_results))

        return GetResultsOutput(
            ocd_id=ocd_id,
            election_date=election_date,
            contest=contest,
            race_count=len(race_results),
            races=race_results,
            notes=notes,
        )

    def list_adapters(self, state: str | None = None) -> ListAdaptersOutput:
        payload = self.request("/coverage/sync-status/")
        if not isinstance(payload, dict):
            raise CivicMirrorAPIError("Unexpected /coverage/sync-status/ response shape")

        state_code = state.upper() if state else None

        adapter_states = payload.get("adapter_states") or []
        by_state = payload.get("by_state") or {}
        coverage_tiers = payload.get("coverage_tiers") or {}

        notes: list[str] = []
        if state_code:
            adapter_states = [candidate for candidate in adapter_states if str(candidate).upper() == state_code]
            by_state = {state_code: by_state.get(state_code, {})}
            coverage_tiers = {state_code: coverage_tiers[state_code]} if state_code in coverage_tiers else {}
            if not adapter_states:
                notes.append(f"No results adapter is registered for {state_code}.")

        if payload.get("as_of") is None:
            notes.append("The API did not report an as_of timestamp, so this snapshot's freshness is unknown.")

        return ListAdaptersOutput(
            as_of=payload.get("as_of"),
            state=state_code,
            adapter_states=[str(item) for item in adapter_states],
            by_state=by_state,
            coverage_tiers=coverage_tiers,
            notes=notes,
        )

    def compare_sources(
        self,
        ocd_id: str,
        contest: str,
        election_date: str | None = None,
    ) -> CompareSourcesOutput:
        races = self._find_races(ocd_id=ocd_id, election_date=election_date, contest=contest)
        race_results = [self._race_with_results(race, election_date=election_date) for race in races]

        by_source: dict[str, RaceResults] = {}
        unreported = 0
        for payload in race_results:
            source = payload.race.source
            key = source if source is not None else UNREPORTED_SOURCE_KEY
            if source is None:
                unreported += 1

            existing = by_source.get(key)
            if existing is not None:
                # Two distinct contests from one source would be compared against each other's
                # candidates, manufacturing phantom agreement or conflict. Refuse instead.
                raise CivicMirrorAPIError(
                    f"contest={contest!r} in {ocd_id} matched more than one race from source {key!r}: "
                    f"{existing.race.office_title!r} (race {existing.race.id}) and "
                    f"{payload.race.office_title!r} (race {payload.race.id}). "
                    "Narrow `contest` to a single office, or pass `election_date`, so the comparison "
                    "is between sources for one contest."
                )
            by_source[key] = payload

        comparisons = self._compare_source_results(by_source)

        notes: list[str] = []
        if len(by_source) < 2:
            notes.append(
                f"Only {len(by_source)} source record(s) found for contest {contest!r} in {ocd_id}; "
                "cross-source comparison needs at least two."
            )
        if unreported:
            notes.append(
                f"{unreported} record(s) had no source reported by the API and are keyed as "
                f"{UNREPORTED_SOURCE_KEY!r} rather than given a guessed source name."
            )
        notes.extend(self._uncomparable_notes(by_source))
        notes.extend(self._coverage_notes(list(by_source.values())))

        return CompareSourcesOutput(
            ocd_id=ocd_id,
            contest=contest,
            election_date=election_date,
            source_count=len(by_source),
            sources=by_source,
            unreported_source_count=unreported,
            comparisons=comparisons,
            conflict_count=sum(1 for row in comparisons if row.conflict),
            notes=notes,
        )

    # -- Internals -----------------------------------------------------------

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

    def _race_with_results(self, race: dict[str, Any], election_date: str | None = None) -> RaceResults:
        race_id = race.get("id")
        if race_id is None:
            raise CivicMirrorAPIError("Race payload is missing id")

        detail = {**race, **self.request(f"/races/{race_id}/")}
        raw_results = self.request(f"/races/{race_id}/results/")
        if not isinstance(raw_results, list):
            raise CivicMirrorAPIError(f"Unexpected /races/{race_id}/results/ response shape")

        race_model = Race.from_api(detail, election_date=election_date)
        rows = [ResultRow.from_api(row, label=self._row_label(row)) for row in raw_results]

        return RaceResults(
            race=race_model,
            results=rows,
            result_count=len(rows),
            contest_total_rows=sum(1 for row in rows if row.jurisdiction_fragment in ("", None)),
            sub_jurisdiction_rows=sum(1 for row in rows if row.jurisdiction_fragment not in ("", None)),
        )

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
    def _row_label(row: dict[str, Any]) -> str | None:
        """
        Label a result row for cross-source comparison, or ``None`` when the API named nothing.

        A synthetic label (e.g. a row id) would not match across sources, so an unnamed row is
        reported as unlabelled instead of being given an invented identity.
        """
        for key in ("candidate_name", "option_label", "jurisdiction_fragment"):
            value = row.get(key)
            if value not in (None, ""):
                return str(value)
        return UNREPORTED

    @classmethod
    def _compare_source_results(cls, sources: dict[str, RaceResults]) -> list[SourceComparison]:
        if len(sources) < 2:
            return []

        source_names = sorted(sources)  # deterministic baseline regardless of API ordering
        baseline_name = source_names[0]
        baseline_rows = cls._results_by_label(sources[baseline_name])
        comparisons: list[SourceComparison] = []

        for source_name in source_names[1:]:
            source_rows = cls._results_by_label(sources[source_name])
            for label in sorted(set(baseline_rows) | set(source_rows)):
                baseline = baseline_rows.get(label)
                candidate = source_rows.get(label)
                baseline_count = baseline.vote_count if baseline else None
                candidate_count = candidate.vote_count if candidate else None
                comparisons.append(SourceComparison(
                    label=label,
                    baseline_source=baseline_name,
                    comparison_source=source_name,
                    baseline_present=baseline is not None,
                    comparison_present=candidate is not None,
                    baseline_vote_count=baseline_count,
                    comparison_vote_count=candidate_count,
                    vote_count_delta=cls._delta(candidate_count, baseline_count),
                    baseline_vote_pct=baseline.vote_pct if baseline else None,
                    comparison_vote_pct=candidate.vote_pct if candidate else None,
                    vote_pct_delta=cls._delta(
                        candidate.vote_pct if candidate else None,
                        baseline.vote_pct if baseline else None,
                    ),
                    baseline_result_type=baseline.result_type if baseline else None,
                    comparison_result_type=candidate.result_type if candidate else None,
                    baseline_certified_at=baseline.certified_at if baseline else None,
                    comparison_certified_at=candidate.certified_at if candidate else None,
                    conflict=(
                        baseline_count is not None
                        and candidate_count is not None
                        and baseline_count != candidate_count
                    ),
                ))

        return comparisons

    @staticmethod
    def _results_by_label(race_results: RaceResults) -> dict[str, ResultRow]:
        return {row.label: row for row in race_results.results if row.label is not None}

    @staticmethod
    def _uncomparable_notes(sources: dict[str, RaceResults]) -> list[str]:
        notes = []
        for key, payload in sources.items():
            unlabelled = sum(1 for row in payload.results if row.label is None)
            if unlabelled:
                notes.append(
                    f"Source {key!r}: {unlabelled} result row(s) carried no candidate, option, or "
                    "sub-jurisdiction name and were excluded from comparisons."
                )
        return notes

    @staticmethod
    def _coverage_notes(race_results: list[RaceResults]) -> list[str]:
        notes = []
        for payload in race_results:
            race = payload.race
            label = race.office_title or f"race {race.id}"
            if race.source is None:
                notes.append(f"{label}: the API reported no source for this record.")
            if race.last_synced_at is None:
                notes.append(f"{label}: the API reported no last_synced_at, so record freshness is unknown.")
            if race.certification_status is None:
                notes.append(f"{label}: the API reported no certification_status.")
            if payload.result_count == 0:
                notes.append(f"{label}: CivicMirror holds no official result rows for this race yet.")
            elif payload.contest_total_rows == 0:
                notes.append(
                    f"{label}: all {payload.result_count} result row(s) are sub-jurisdiction splits; "
                    "no contest-total row is present, so totals are partial."
                )
        return notes

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
