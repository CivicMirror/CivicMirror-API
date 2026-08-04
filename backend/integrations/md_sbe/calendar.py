"""
Maintained table of Maryland's statutory primary/general election dates.

MD's primary date is set by statute but has been moved by the legislature
across recent cycles (2022: July 19, 2024: May 14, 2026: June 23) — there is
no computable formula. This table must be updated by hand each cycle from
the official calendar PDF (Rank 6 in docs/state-research/MD/MD-Election_Research.md):
https://elections.maryland.gov/elections/{year}/{year}_Election_Calendar.pdf

Filename prefixes
-----------------
MD SBE embeds a TWO-letter prefix in its candidate-list and results-CSV
filenames: ``[cycle letter][phase letter]``.

    cycle letter — "G" gubernatorial cycle (2022, 2026, ...),
                   "P" presidential cycle (2020, 2024, ...)
    phase letter — "P" primary, "G" general

So the 2026 gubernatorial cycle is ``GP`` for the primary and ``GG`` for the
general; the 2024 presidential cycle was ``PP`` / ``PG``. A single prefix per
cycle is therefore wrong — using the primary prefix for a general-election
URL soft-404s (verified live 2026-08-04: ``.../2026/general_candidates/
2026_GP_statewide_candidatelist.csv`` returns the "Page Not Found" HTML body,
while ``2026_GG_statewide_candidatelist.csv`` returns the real CSV).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass

PRIMARY = "primary"
GENERAL = "general"


@dataclass(frozen=True)
class MdElectionCycle:
    year: int
    primary_date: datetime.date
    general_date: datetime.date
    #: "G" (gubernatorial) or "P" (presidential) — the CYCLE half of MD's
    #: two-letter filename prefix. The PHASE half is appended per-request by
    #: prefix_for_phase(); never store a whole prefix here.
    cycle_letter: str

    @property
    def primary_cycle_prefix(self) -> str:
        return f"{self.cycle_letter}P"

    @property
    def general_cycle_prefix(self) -> str:
        return f"{self.cycle_letter}G"

    def prefix_for_phase(self, phase: str) -> str:
        """Return the filename prefix for 'primary' or 'general'."""
        return self.primary_cycle_prefix if phase == PRIMARY else self.general_cycle_prefix

    def phase_for_date(self, today: datetime.date) -> str:
        """Which phase MD is publishing data for as of `today`."""
        return PRIMARY if today <= self.primary_date else GENERAL


MD_ELECTION_CYCLES: dict[int, MdElectionCycle] = {
    2026: MdElectionCycle(
        year=2026,
        primary_date=datetime.date(2026, 6, 23),
        general_date=datetime.date(2026, 11, 3),
        cycle_letter="G",
    ),
}


def get_active_cycle(today: datetime.date) -> MdElectionCycle | None:
    """Return the cycle whose general election hasn't yet passed, or None."""
    candidates = sorted(
        (c for c in MD_ELECTION_CYCLES.values() if c.general_date >= today),
        key=lambda c: c.general_date,
    )
    return candidates[0] if candidates else None
