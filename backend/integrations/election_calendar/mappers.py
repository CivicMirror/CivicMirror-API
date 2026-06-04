"""
2026 U.S. election calendar — static data.

Sources:
  - NCSL 2026 State Primary Election Dates
    https://www.ncsl.org/elections-and-campaigns/2026-state-primary-election-dates
  - FVAP Primary Elections Calendar (official US government)
    https://www.fvap.gov/uploads/FVAP/VAO/PrimaryElectionsCalendar.pdf
  - Ballotpedia 2026 Elections Calendar

All 50 states: one primary date + one general date (November 3, 2026).
Runoffs are excluded — they are conditional on primary outcomes and their
presence as UPCOMING records would create phantom elections.

Special cases documented:
  - Louisiana: uses a jungle primary (top-two) for congressional races;
    May 16 is the qualifying/non-partisan primary. The November 3 general
    is the effective deciding election for most LA federal contests.
  - States with odd-year cycles (NJ, VA for state offices) still have
    federal congressional primaries in 2026 on the dates listed.
  - Nebraska: nonpartisan unicameral; primary elects top two to November.
  - DC is excluded (not a state; no Senate; nonvoting House delegate only).
"""
from __future__ import annotations

from datetime import date
from typing import NamedTuple


class ElectionSpec(NamedTuple):
    state: str
    election_type: str   # matches Election.ElectionType choices
    election_date: date
    name: str


_GENERAL = date(2026, 11, 3)

# Primary dates by state (NCSL / FVAP, verified June 2026)
_PRIMARY_DATES: dict[str, date] = {
    "AL": date(2026, 5, 19),
    "AK": date(2026, 8, 18),
    "AZ": date(2026, 7, 21),
    "AR": date(2026, 3, 3),
    "CA": date(2026, 6, 2),
    "CO": date(2026, 6, 30),
    "CT": date(2026, 8, 11),
    "DE": date(2026, 9, 15),
    "FL": date(2026, 8, 18),
    "GA": date(2026, 5, 19),
    "HI": date(2026, 8, 8),
    "ID": date(2026, 5, 19),
    "IL": date(2026, 3, 17),
    "IN": date(2026, 5, 5),
    "IA": date(2026, 6, 2),
    "KS": date(2026, 8, 4),
    "KY": date(2026, 5, 19),
    "LA": date(2026, 5, 16),
    "ME": date(2026, 6, 9),
    "MD": date(2026, 6, 23),
    "MA": date(2026, 9, 1),
    "MI": date(2026, 8, 4),
    "MN": date(2026, 8, 11),
    "MS": date(2026, 3, 10),
    "MO": date(2026, 8, 4),
    "MT": date(2026, 6, 2),
    "NE": date(2026, 5, 12),
    "NV": date(2026, 6, 9),
    "NH": date(2026, 9, 8),
    "NJ": date(2026, 6, 2),
    "NM": date(2026, 6, 2),
    "NY": date(2026, 6, 23),
    "NC": date(2026, 3, 3),
    "ND": date(2026, 6, 9),
    "OH": date(2026, 5, 5),
    "OK": date(2026, 6, 16),
    "OR": date(2026, 5, 19),
    "PA": date(2026, 5, 19),
    "RI": date(2026, 9, 9),
    "SC": date(2026, 6, 9),
    "SD": date(2026, 6, 2),
    "TN": date(2026, 8, 6),
    "TX": date(2026, 3, 3),
    "UT": date(2026, 6, 23),
    "VT": date(2026, 8, 11),
    "VA": date(2026, 8, 4),
    "WA": date(2026, 8, 4),
    "WV": date(2026, 5, 12),
    "WI": date(2026, 8, 11),
    "WY": date(2026, 8, 18),
}

_STATE_NAMES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}


def build_2026_election_specs() -> list[ElectionSpec]:
    """Return all 2026 ElectionSpec records (primary + general for each state)."""
    specs: list[ElectionSpec] = []
    for state, primary_date in _PRIMARY_DATES.items():
        name = _STATE_NAMES[state]
        specs.append(ElectionSpec(
            state=state,
            election_type="primary",
            election_date=primary_date,
            name=f"2026 {name} Primary Election",
        ))
        specs.append(ElectionSpec(
            state=state,
            election_type="general",
            election_date=_GENERAL,
            name=f"2026 {name} General Election",
        ))
    return specs
