"""
Aggregation for the Maryland SBE results adapter.

MD SBE's {cycle}{yy}_{county}CountyResults.csv files are already
county-aggregated (no precinct-level summing needed) — this module sums
each candidate's Total Votes across all 24 counties' files to get the
statewide total per (office, candidate).
"""
from __future__ import annotations

from collections import defaultdict

from .base import ResultRow


def aggregate_county_rows(all_rows: list[dict], office_allowlist: frozenset[str]) -> list[ResultRow]:
    totals: dict[tuple[str, str], int] = defaultdict(int)
    winner_seen: dict[tuple[str, str], bool] = defaultdict(bool)
    write_in_seen: dict[tuple[str, str], bool] = defaultdict(bool)
    party_by_key: dict[tuple[str, str], str] = {}

    for row in all_rows:
        office_name = row["office_name"]
        if office_name not in office_allowlist:
            continue
        key = (office_name, row["candidate_name"])
        totals[key] += row["total_votes"]
        winner_seen[key] = winner_seen[key] or row["is_winner"]
        write_in_seen[key] = write_in_seen[key] or row["is_write_in"]
        party_by_key.setdefault(key, row["party"])

    return [
        ResultRow(
            candidate_name=candidate_name,
            option_label=None,
            vote_count=vote_count,
            vote_pct=None,
            is_winner=winner_seen[(office_name, candidate_name)],
            result_type="official",
            office_title=office_name,
            is_write_in_aggregate=write_in_seen[(office_name, candidate_name)],
            raw={"party": party_by_key.get((office_name, candidate_name), "")},
        )
        for (office_name, candidate_name), vote_count in totals.items()
    ]
