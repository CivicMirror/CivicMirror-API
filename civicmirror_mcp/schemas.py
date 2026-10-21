"""
Typed tool contracts for the read-only CivicMirror MCP server (issue #196).

Every field that CivicMirror can report is modelled explicitly, and anything the
API did not supply stays ``None``. The server never substitutes a placeholder for
missing election metadata: a caller must be able to tell "no value was reported"
from "the reported value is X".

Field groups the Phase-1 contract must preserve:

* result status      -- ``race_status``, ``certification_status``, ``result_type``, ``is_winner``
* source authority   -- ``source``, ``sources``, ``source_url``, ``field_provenance``
* freshness          -- ``last_synced_at``, ``certified_at``, ``as_of``
* partial reporting  -- ``jurisdiction_fragment`` (blank = contest total), ``race_status``
* source conflict    -- ``SourceComparison`` rows
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

UNREPORTED = None
"""Sentinel meaning "the API did not report this". Spelled out so call sites read clearly."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _opt_str(value: Any) -> str | None:
    """Normalize an optional API string, keeping '' distinct from a missing value."""
    if value is None:
        return UNREPORTED
    return str(value)


class ResultRow(_Model):
    """One official result row: a candidate, a measure option, or a sub-jurisdiction split."""

    id: int | None = Field(default=None, description="CivicMirror OfficialResult id, when reported.")
    race: int | None = Field(default=None, description="CivicMirror Race id this row belongs to.")
    candidate: int | None = Field(default=None, description="Candidate id; null for measures and write-in aggregates.")
    candidate_name: str | None = Field(default=None, description="Candidate name as reported; null when not a candidate row.")
    candidate_party: str | None = Field(default=None, description="Candidate party; null when unknown or not a candidate row.")
    measure_option: int | None = Field(default=None, description="MeasureOption id; null for candidate rows.")
    option_label: str | None = Field(default=None, description="Ballot-measure option label (e.g. Yes/No); null for candidate rows.")
    label: str | None = Field(
        default=None,
        description=(
            "Comparison label for this row (candidate name, measure option, or sub-jurisdiction). "
            "Null when the API reported no name for any of them -- the row is then not comparable "
            "across sources and is excluded from `comparisons`."
        ),
    )
    vote_count: int | None = Field(default=None, description="Votes reported; null when the source published none.")
    vote_pct: float | str | None = Field(default=None, description="Vote percentage as reported by the API (may be a decimal string).")
    result_type: str | None = Field(default=None, description="Result status as reported, e.g. unofficial / official / certified.")
    is_winner: bool | None = Field(
        default=None,
        description="True/False when determined; null when undetermined (ties, measures, races with no total row).",
    )
    round_number: int | None = Field(default=None, description="RCV round, when the source reports rounds.")
    jurisdiction_fragment: str | None = Field(
        default=None,
        description="Sub-jurisdiction this row covers (county/town/precinct). Empty string = the contest total; null = not reported.",
    )
    is_write_in_aggregate: bool | None = Field(default=None, description="True when the row aggregates write-ins.")
    certified_at: str | None = Field(default=None, description="Certification timestamp for this row; null when uncertified or unreported.")
    source_url: str | None = Field(default=None, description="URL of the source document/feed this row came from.")

    @classmethod
    def from_api(cls, payload: dict[str, Any], label: str | None = None) -> ResultRow:
        return cls(
            id=payload.get("id"),
            race=payload.get("race"),
            candidate=payload.get("candidate"),
            candidate_name=_opt_str(payload.get("candidate_name")),
            candidate_party=_opt_str(payload.get("candidate_party")),
            measure_option=payload.get("measure_option"),
            option_label=_opt_str(payload.get("option_label")),
            label=label,
            vote_count=payload.get("vote_count"),
            vote_pct=payload.get("vote_pct"),
            result_type=_opt_str(payload.get("result_type")),
            is_winner=payload.get("is_winner"),
            round_number=payload.get("round_number"),
            jurisdiction_fragment=_opt_str(payload.get("jurisdiction_fragment")),
            is_write_in_aggregate=payload.get("is_write_in_aggregate"),
            certified_at=_opt_str(payload.get("certified_at")),
            source_url=_opt_str(payload.get("source_url")),
        )


class Candidate(_Model):
    id: int | None = None
    name: str | None = None
    party: str | None = None
    incumbent: bool | None = None
    candidate_status: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Candidate:
        return cls(
            id=payload.get("id"),
            name=_opt_str(payload.get("name")),
            party=_opt_str(payload.get("party")),
            incumbent=payload.get("incumbent"),
            candidate_status=_opt_str(payload.get("candidate_status")),
        )


class MeasureOption(_Model):
    id: int | None = None
    option_label: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> MeasureOption:
        return cls(id=payload.get("id"), option_label=_opt_str(payload.get("option_label")))


class Race(_Model):
    """A contest as CivicMirror holds it, from one source."""

    id: int | None = Field(default=None, description="CivicMirror Race id.")
    election: int | None = Field(default=None, description="CivicMirror Election id.")
    election_date: str | None = Field(default=None, description="Election date echoed from the query; null when not filtered by date.")
    race_type: str | None = None
    office_title: str | None = None
    normalized_office_title: str | None = None
    jurisdiction: str | None = None
    geography_scope: str | None = None
    ocd_division_id: str | None = None
    party: str | None = None
    normalized_party: str | None = None
    vote_method: str | None = None
    max_selections: int | None = None
    ballot_type: str | None = None

    # Status.
    race_status: str | None = Field(default=None, description="Reporting status of the contest (also the partial-reporting signal).")
    certification_status: str | None = Field(default=None, description="Certification status as reported, e.g. unofficial / certified.")

    # Source authority and freshness.
    source: str | None = Field(default=None, description="Primary source identifier; null when the API reported none.")
    sources: list[str] | None = Field(default=None, description="All sources that contributed to this record, when reported.")
    last_synced_at: str | None = Field(default=None, description="When CivicMirror last retrieved this record.")
    field_provenance: dict[str, Any] | None = Field(default=None, description="Per-field source attribution, when reported.")
    match_confidence: float | str | None = Field(default=None, description="Cross-source match confidence, when reported.")
    results_url: str | None = Field(default=None, description="API path to this race's official results.")

    candidates: list[Candidate] = Field(default_factory=list)
    measure_options: list[MeasureOption] = Field(default_factory=list)
    winners: list[dict[str, Any]] | None = Field(
        default=None,
        description="Candidates marked winner in the official results. Empty list = none determined; null = not reported.",
    )

    @classmethod
    def from_api(cls, payload: dict[str, Any], election_date: str | None = None) -> Race:
        sources = payload.get("sources")
        return cls(
            id=payload.get("id"),
            election=payload.get("election"),
            election_date=_opt_str(payload.get("election_date")) or election_date,
            race_type=_opt_str(payload.get("race_type")),
            office_title=_opt_str(payload.get("office_title")),
            normalized_office_title=_opt_str(payload.get("normalized_office_title")),
            jurisdiction=_opt_str(payload.get("jurisdiction")),
            geography_scope=_opt_str(payload.get("geography_scope")),
            ocd_division_id=_opt_str(payload.get("ocd_division_id")),
            party=_opt_str(payload.get("party")),
            normalized_party=_opt_str(payload.get("normalized_party")),
            vote_method=_opt_str(payload.get("vote_method")),
            max_selections=payload.get("max_selections"),
            ballot_type=_opt_str(payload.get("ballot_type")),
            race_status=_opt_str(payload.get("race_status")),
            certification_status=_opt_str(payload.get("certification_status")),
            source=_opt_str(payload.get("source")),
            sources=[str(item) for item in sources] if isinstance(sources, list) else UNREPORTED,
            last_synced_at=_opt_str(payload.get("last_synced_at")),
            field_provenance=payload.get("field_provenance"),
            match_confidence=payload.get("match_confidence"),
            results_url=_opt_str(payload.get("results_url")),
            candidates=[Candidate.from_api(item) for item in payload.get("candidates") or []],
            measure_options=[MeasureOption.from_api(item) for item in payload.get("measure_options") or []],
            winners=payload.get("winners"),
        )


class RaceResults(_Model):
    """A race plus the official result rows CivicMirror holds for it."""

    race: Race
    results: list[ResultRow] = Field(default_factory=list)
    result_count: int = 0
    contest_total_rows: int = Field(
        default=0,
        description="Rows reporting the contest total (blank jurisdiction_fragment).",
    )
    sub_jurisdiction_rows: int = Field(
        default=0,
        description="Rows reporting a sub-jurisdiction split (non-blank jurisdiction_fragment).",
    )


class GetResultsOutput(_Model):
    """Output of ``get_results``."""

    ocd_id: str
    election_date: str
    contest: str | None = None
    race_count: int = 0
    races: list[RaceResults] = Field(default_factory=list)
    notes: list[str] = Field(
        default_factory=list,
        description="Explicit caveats about what this answer does and does not cover.",
    )


class ListAdaptersOutput(_Model):
    """Output of ``list_adapters``."""

    as_of: str | None = Field(default=None, description="Freshness of the sync-status snapshot; null when not reported.")
    state: str | None = Field(default=None, description="State filter applied, uppercased; null when unfiltered.")
    adapter_states: list[str] = Field(default_factory=list)
    by_state: dict[str, Any] = Field(default_factory=dict, description="Per-state adapter run status as reported by the API.")
    coverage_tiers: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class SourceComparison(_Model):
    """One candidate/option compared between two sources -- the source-conflict signal."""

    label: str = Field(description="Candidate, measure option, or sub-jurisdiction being compared.")
    baseline_source: str
    comparison_source: str
    baseline_present: bool = Field(description="False when the baseline source reported no row for this label.")
    comparison_present: bool = Field(description="False when the comparison source reported no row for this label.")
    baseline_vote_count: int | None = None
    comparison_vote_count: int | None = None
    vote_count_delta: int | float | None = Field(
        default=None, description="comparison - baseline; null when either side reported no count."
    )
    baseline_vote_pct: float | str | None = None
    comparison_vote_pct: float | str | None = None
    vote_pct_delta: int | float | None = Field(
        default=None, description="comparison - baseline; null when either side reported no percentage."
    )
    baseline_result_type: str | None = None
    comparison_result_type: str | None = None
    baseline_certified_at: str | None = None
    comparison_certified_at: str | None = None
    conflict: bool = Field(
        description="True when both sources reported a count and the counts differ."
    )


class CompareSourcesOutput(_Model):
    """Output of ``compare_sources``."""

    ocd_id: str
    contest: str
    election_date: str | None = None
    source_count: int = 0
    sources: dict[str, RaceResults] = Field(
        default_factory=dict,
        description="Race + results keyed by source identifier. The key 'source:unreported' is used only "
                    "when the API itself reported no source for a record.",
    )
    unreported_source_count: int = Field(
        default=0, description="Records whose source the API did not report."
    )
    comparisons: list[SourceComparison] = Field(default_factory=list)
    conflict_count: int = Field(default=0, description="Comparisons where both sources reported differing counts.")
    notes: list[str] = Field(default_factory=list)
