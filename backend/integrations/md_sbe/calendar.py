"""
Maintained table of Maryland's statutory primary/general election dates.

MD's primary date is set by statute but has been moved by the legislature
across recent cycles (2022: July 19, 2024: May 14, 2026: June 23) — there is
no computable formula. This table must be updated by hand each cycle from
the official calendar PDF (Rank 6 in docs/state-research/MD/MD-Election_Research.md):
https://elections.maryland.gov/elections/{year}/{year}_Election_Calendar.pdf

cycle_prefix mirrors the prefix MD SBE embeds in its candidate-list and
results-CSV filenames (e.g. "GP" = Gubernatorial cycle, "PG" = Presidential
cycle — confirmed against the live 2026_GP_statewide_candidatelist.csv and
the existing results/adapters/md.py which already uses "PG" for 2024).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class MdElectionCycle:
    year: int
    primary_date: datetime.date
    general_date: datetime.date
    cycle_prefix: str


MD_ELECTION_CYCLES: dict[int, MdElectionCycle] = {
    2026: MdElectionCycle(
        year=2026,
        primary_date=datetime.date(2026, 6, 23),
        general_date=datetime.date(2026, 11, 3),
        cycle_prefix="GP",
    ),
}


def get_active_cycle(today: datetime.date) -> MdElectionCycle | None:
    """Return the cycle whose general election hasn't yet passed, or None."""
    candidates = sorted(
        (c for c in MD_ELECTION_CYCLES.values() if c.general_date >= today),
        key=lambda c: c.general_date,
    )
    return candidates[0] if candidates else None
