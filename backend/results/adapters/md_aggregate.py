"""
Aggregation for the Maryland SBE results adapter.

MD SBE's per-county result CSVs are already county-aggregated (no
precinct-level summing needed) — this module sums each candidate's Total
Votes across all 24 counties' files to get the statewide total per
(office, district, party, candidate).

District is part of the key, not decoration: "House of Delegates" appears in
every county's file once per legislative district, so keying on office alone
sums 141 delegates' votes into one bogus statewide "House of Delegates" row
that can never match Stage 1's district-qualified races. Same for State
Senator and U.S. Congress.

Party is part of the key because MD publishes PRIMARY results as one file per
ballot party (GP26_01DemocraticResults.csv, GP26_01RepublicanResults.csv) and
Stage 1 correspondingly creates one Race per party per primary contest. The
row's own "Party" column carries the code, so this works unchanged for the
general election too (where the Race is party-agnostic and simply ignores
party_code when matching).

Race matching: every emitted ResultRow carries
`raw["contest_code"]` (and `raw["party_code"]` where known), which
results/tasks.py::_race_source_identity compares against the matching keys in
Race.source_metadata written by integrations.md_sbe.mappers.map_race_identity.
That identity path is exact and takes precedence over office_title string
matching — but office_title is still emitted in Stage 1's exact format
(see mappers.race_office_title) so the fallback path and race bootstrapping
also line up.

Write-in rows are a special case: MD's general-election CSVs list several
distinct write-in candidate names per office (e.g. "Patrick J. Burke",
"Other Write-Ins", ...). Per the aggregate-results contract used across
other state adapters (see il_aggregate.py), all rows flagged Write-In? are
summed into a single combined row per contest, emitted as one ResultRow with
candidate_name="Write-In" and is_write_in_aggregate=True — never one row per
write-in candidate name, since downstream candidate matching treats all
is_write_in_aggregate rows as candidate=None and would otherwise collide on
the same DB key. (MD's primary per-party files carry no "Write-In?" column
at all, verified live 2026-08-04.)
"""
from __future__ import annotations

from collections import defaultdict

from integrations.md_sbe.mappers import (
    normalize_district_key,
    normalize_party_key,
    race_contest_code,
    race_office_title,
)

from .base import ResultRow

# The results CSVs use a different Office Name than the candidate CSV for
# exactly ONE in-scope office (verified live 2026-08-04 against both
# PG24_01CountyResults.csv and GP26_01DemocraticResults.csv — every other
# in-scope office name matches byte-for-byte). Alias on the results side only,
# so IN_SCOPE_OFFICES stays the single source of truth for Stage 1.
_OFFICE_NAME_ALIASES: dict[str, str] = {
    "U.S. Congress": "Representative in Congress",
}


def canonical_office_name(office_name: str) -> str:
    name = (office_name or "").strip()
    return _OFFICE_NAME_ALIASES.get(name, name)


def aggregate_county_rows(all_rows: list[dict], office_allowlist: frozenset[str]) -> list[ResultRow]:
    # key = (canonical office, district key, party code, candidate name)
    totals: dict[tuple[str, str, str, str], int] = defaultdict(int)
    winner_seen: dict[tuple[str, str, str, str], bool] = defaultdict(bool)
    party_by_key: dict[tuple[str, str, str, str], str] = {}

    # Write-ins collapse to one row per (office, district) — a write-in has no
    # meaningful party, so it must not be split by one.
    write_in_totals: dict[tuple[str, str], int] = defaultdict(int)

    for row in all_rows:
        office_name = canonical_office_name(row["office_name"])
        if office_name not in office_allowlist:
            continue
        district_key = normalize_district_key(row.get("district", ""))

        if row["is_write_in"]:
            write_in_totals[(office_name, district_key)] += row["total_votes"]
            continue

        party_code = normalize_party_key(row.get("party", ""))
        key = (office_name, district_key, party_code, row["candidate_name"])
        totals[key] += row["total_votes"]
        winner_seen[key] = winner_seen[key] or row["is_winner"]
        party_by_key.setdefault(key, row.get("party", ""))

    rows = [
        ResultRow(
            candidate_name=candidate_name,
            option_label=None,
            vote_count=vote_count,
            vote_pct=None,
            is_winner=winner_seen[(office_name, district_key, party_code, candidate_name)],
            result_type="official",
            office_title=race_office_title(office_name, district_key),
            is_write_in_aggregate=False,
            raw={
                "party": party_by_key.get(
                    (office_name, district_key, party_code, candidate_name), "",
                ),
                "contest_code": race_contest_code(office_name, district_key),
                **({"party_code": party_code} if party_code else {}),
            },
        )
        for (office_name, district_key, party_code, candidate_name), vote_count in totals.items()
    ]

    rows.extend(
        ResultRow(
            candidate_name="Write-In",
            option_label=None,
            vote_count=vote_count,
            vote_pct=None,
            is_winner=None,
            result_type="official",
            office_title=race_office_title(office_name, district_key),
            is_write_in_aggregate=True,
            raw={"contest_code": race_contest_code(office_name, district_key)},
        )
        for (office_name, district_key), vote_count in write_in_totals.items()
    )

    return rows
