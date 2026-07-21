"""
Aggregation for the Maryland SBE results adapter.

MD SBE's {cycle}{yy}_{county}CountyResults.csv files are already
county-aggregated (no precinct-level summing needed) — this module sums
each candidate's Total Votes across all 24 counties' files to get the
statewide total per (office, candidate).

Write-in rows are a special case: MD's source CSVs list several distinct
write-in candidate names per office (e.g. "Patrick J. Burke", "Other
Write-Ins", ...). Per the aggregate-results contract used across other
state adapters (see il_aggregate.py), all rows flagged Write-In? are
summed into a single combined row per office, keyed only by office_name,
emitted as one ResultRow with candidate_name="Write-In" and
is_write_in_aggregate=True — never one row per write-in candidate name,
since downstream candidate matching treats all is_write_in_aggregate rows
as candidate=None and would otherwise collide on the same DB key.
"""
from __future__ import annotations

from collections import defaultdict

from .base import ResultRow


def aggregate_county_rows(all_rows: list[dict], office_allowlist: frozenset[str]) -> list[ResultRow]:
    totals: dict[tuple[str, str], int] = defaultdict(int)
    winner_seen: dict[tuple[str, str], bool] = defaultdict(bool)
    party_by_key: dict[tuple[str, str], str] = {}

    write_in_totals: dict[str, int] = defaultdict(int)
    write_in_seen: dict[str, bool] = defaultdict(bool)

    for row in all_rows:
        office_name = row["office_name"]
        if office_name not in office_allowlist:
            continue

        if row["is_write_in"]:
            write_in_totals[office_name] += row["total_votes"]
            write_in_seen[office_name] = True
            continue

        key = (office_name, row["candidate_name"])
        totals[key] += row["total_votes"]
        winner_seen[key] = winner_seen[key] or row["is_winner"]
        party_by_key.setdefault(key, row["party"])

    rows = [
        ResultRow(
            candidate_name=candidate_name,
            option_label=None,
            vote_count=vote_count,
            vote_pct=None,
            is_winner=winner_seen[(office_name, candidate_name)],
            result_type="official",
            office_title=office_name,
            is_write_in_aggregate=False,
            raw={"party": party_by_key.get((office_name, candidate_name), "")},
        )
        for (office_name, candidate_name), vote_count in totals.items()
    ]

    rows.extend(
        ResultRow(
            candidate_name="Write-In",
            option_label=None,
            vote_count=vote_count,
            vote_pct=None,
            is_winner=None,
            result_type="official",
            office_title=office_name,
            is_write_in_aggregate=True,
            raw={},
        )
        for office_name, vote_count in write_in_totals.items()
        if write_in_seen[office_name]
    )

    return rows
