"""
Statutory Minnesota statewide election dates.

Federal/state offices are elected in even years: the state primary is the
second Tuesday of August (Minn. Stat. 204D.03) and the state general is the
Tuesday after the first Monday of November. These are computed, not scraped,
so auto-onboarding (discover_mn_elections) can know which date paths to probe
without touching the Radware-protected portal.

Odd-year November elections are municipal/school only (out of the current
Federal+State scope) and are not produced here.
"""
from __future__ import annotations

import datetime

_TUESDAY = 1  # Monday=0 .. Sunday=6
_MONDAY = 0


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime.date:
    first = datetime.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + datetime.timedelta(days=offset + 7 * (n - 1))


def state_primary_date(year: int) -> datetime.date:
    """Second Tuesday of August."""
    return _nth_weekday(year, 8, _TUESDAY, 2)


def state_general_date(year: int) -> datetime.date:
    """Tuesday after the first Monday of November."""
    first_monday = _nth_weekday(year, 11, _MONDAY, 1)
    return first_monday + datetime.timedelta(days=1)


def statutory_statewide_elections(
    reference_date: datetime.date, years_back: int = 2, years_ahead: int = 2,
) -> list[tuple[datetime.date, str, str]]:
    """
    (date, election_type, name) for the statewide primary + general of every
    even year in the window [year-years_back, year+years_ahead].
    """
    elections = []
    for year in range(reference_date.year - years_back, reference_date.year + years_ahead + 1):
        if year % 2 != 0:
            continue
        elections.append((state_primary_date(year), "primary", f"{year} Minnesota Primary"))
        elections.append(
            (state_general_date(year), "general", f"{year} Minnesota General Election")
        )
    return elections
