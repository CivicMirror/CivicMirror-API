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

NOTE on office_allowlist matching: `office_allowlist` (passed in by
results/adapters/md.py as integrations.md_sbe.mappers.IN_SCOPE_OFFICES) is
matched against each row's `office_name` by exact string equality. That set
was built from the candidate-list CSV's "Office Name" column; whether the
per-county RESULTS CSV uses the identical strings for every office
(especially "House of Delegates" — the results file may instead break this
out per-district, e.g. "Delegate District 1A") has not been verified, since
no 2026 results CSV exists yet. If a live results CSV is later found to use
different Office Name strings than the candidate CSV for the same office,
add a small alias map here (e.g. `_OFFICE_NAME_ALIASES: dict[str, str]`
translating a results-CSV office_name to the canonical IN_SCOPE_OFFICES
value before the allowlist check) rather than changing IN_SCOPE_OFFICES
itself. Do not invent that alias map speculatively without evidence from a
real results CSV.
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
