"""
Maintained table of Utah's statutory primary/general election dates and the
Candidate Filing Excel workbook URL for each cycle.

Neither field is computable: the primary date is set by the legislature per
cycle (2026: June 23, per docs/state-research/UT/UT-Election_Research.md),
and the workbook URL's path segment is a WordPress upload date, not a fixed
pattern — confirmed live 2026-08-05 at
https://vote.utah.gov/wp-content/uploads/2026/06/Candidate-Filing-2026.xlsx.
This table must be updated by hand each cycle from
https://vote.utah.gov/2026-candidate-filings/ (or the equivalent year's page).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class UtElectionCycle:
    year: int
    primary_date: datetime.date
    general_date: datetime.date
    candidate_filing_url: str


UT_ELECTION_CYCLES: dict[int, UtElectionCycle] = {
    2026: UtElectionCycle(
        year=2026,
        primary_date=datetime.date(2026, 6, 23),
        general_date=datetime.date(2026, 11, 3),
        candidate_filing_url=(
            "https://vote.utah.gov/wp-content/uploads/2026/06/Candidate-Filing-2026.xlsx"
        ),
    ),
}


def get_active_cycle(today: datetime.date) -> UtElectionCycle | None:
    """Return the cycle whose general election hasn't yet passed, or None."""
    candidates = sorted(
        (c for c in UT_ELECTION_CYCLES.values() if c.general_date >= today),
        key=lambda c: c.general_date,
    )
    return candidates[0] if candidates else None
