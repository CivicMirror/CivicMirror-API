"""
CSV aggregation for the Illinois results adapter.

IL SBE's per-office CSV is precinct-level: one row per
(jurisdiction, precinct, candidate). This sums VoteCount by CandidateName
within one office/contest, excluding non-candidate bookkeeping rows
(Under Votes, Over Votes, Blank Ballots) and normalizing write-in
capitalization variants (WRITE-IN / Write-In / Write-in) into a single
aggregate row.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict

from .base import ResultRow

_NON_CANDIDATE_ROWS = frozenset({"under votes", "over votes", "blank ballots"})


def _clean_text(value: str) -> str:
    """Remove NUL/control bytes that PostgreSQL cannot store, then trim."""
    return "".join(ch for ch in value if ch >= " " or ch == "\t").strip()


def _is_write_in(candidate_name: str) -> bool:
    return candidate_name.strip().lower().replace(" ", "") in {"write-in", "writein"}


def aggregate_csv_rows(csv_text: str, office_name: str) -> list[ResultRow]:
    """Aggregate one office's precinct-level CSV into per-candidate ResultRows."""
    reader = csv.DictReader(io.StringIO(csv_text))

    totals: dict[str, int] = defaultdict(int)
    write_in_total = 0
    saw_write_in = False
    party_by_candidate: dict[str, str] = {}

    for row in reader:
        raw_name = _clean_text(row.get("CandidateName") or "")
        if not raw_name or raw_name.lower() in _NON_CANDIDATE_ROWS:
            continue

        try:
            vote_count = int((row.get("VoteCount") or "0").strip())
        except ValueError:
            vote_count = 0

        if _is_write_in(raw_name):
            saw_write_in = True
            write_in_total += vote_count
            continue

        totals[raw_name] += vote_count
        party_by_candidate.setdefault(raw_name, _clean_text(row.get("PartyName") or ""))

    rows = [
        ResultRow(
            candidate_name=name,
            option_label=None,
            vote_count=count,
            vote_pct=None,
            is_winner=None,
            result_type="official",
            office_title=office_name,
            is_write_in_aggregate=False,
            raw={"party": party_by_candidate.get(name, "")},
        )
        for name, count in totals.items()
    ]

    if saw_write_in:
        rows.append(
            ResultRow(
                candidate_name="Write-In",
                option_label=None,
                vote_count=write_in_total,
                vote_pct=None,
                is_winner=None,
                result_type="official",
                office_title=office_name,
                is_write_in_aggregate=True,
                raw={},
            )
        )

    return rows
