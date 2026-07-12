"""
Mappers for Illinois SBE data -> CivicMirror model fields.

Election dates: IL SBE's election dropdown only gives label text (e.g.
"2026 GENERAL PRIMARY"), not a machine-readable date. General Elections and
Consolidated Elections follow fixed statutory formulas and are computed
exactly. General Primary dates have shifted by statute in recent cycles
(e.g. moved to June in 2022 for redistricting reasons) — this maps them to
the typical third-Tuesday-in-March date and flags the result as
`election_date_approximate` in source_metadata so it can be corrected if
wrong. Special elections have no fixed schedule and are not mapped at all
(returns None; sync_il_elections skips them).
"""
from __future__ import annotations

import calendar
import datetime
import re

from elections.models import Election, Race

_FEDERAL_STATE_PATTERNS = (
    re.compile(r"^UNITED STATES SENATOR$"),
    re.compile(r"^PRESIDENT AND VICE PRESIDENT$"),
    re.compile(r"^\d+(ST|ND|RD|TH) CONGRESS$"),
    re.compile(r"^\d+(ST|ND|RD|TH) SENATE$"),
    re.compile(r"^\d+(ST|ND|RD|TH) REPRESENTATIVE$"),
)

_STATEWIDE_ROW_OFFICES = frozenset({
    "GOVERNOR AND LIEUTENANT GOVERNOR",
    "ATTORNEY GENERAL",
    "SECRETARY OF STATE",
    "COMPTROLLER",
    "TREASURER",
})

_DISTRICT_OFFICE_PATTERNS = (
    re.compile(r"^\d+(ST|ND|RD|TH) CONGRESS$"),
    re.compile(r"^\d+(ST|ND|RD|TH) SENATE$"),
    re.compile(r"^\d+(ST|ND|RD|TH) REPRESENTATIVE$"),
)


def is_federal_or_state_office(office_name: str) -> bool:
    name = office_name.strip().upper()
    if name in _STATEWIDE_ROW_OFFICES:
        return True
    return any(p.match(name) for p in _FEDERAL_STATE_PATTERNS)


def _is_district_office(office_name: str) -> bool:
    name = office_name.strip().upper()
    return any(p.match(name) for p in _DISTRICT_OFFICE_PATTERNS)


def _first_tuesday_after_first_monday(year: int, month: int) -> datetime.date:
    first = datetime.date(year, month, 1)
    days_to_monday = (calendar.MONDAY - first.weekday()) % 7
    first_monday = first + datetime.timedelta(days=days_to_monday)
    return first_monday + datetime.timedelta(days=1)


def _third_tuesday_of_march(year: int) -> datetime.date:
    first = datetime.date(year, 3, 1)
    days_to_tuesday = (calendar.TUESDAY - first.weekday()) % 7
    first_tuesday = first + datetime.timedelta(days=days_to_tuesday)
    return first_tuesday + datetime.timedelta(days=14)


def _first_tuesday_of_april(year: int) -> datetime.date:
    first = datetime.date(year, 4, 1)
    days_to_tuesday = (calendar.TUESDAY - first.weekday()) % 7
    return first + datetime.timedelta(days=days_to_tuesday)


def infer_election_type_and_date(label: str) -> tuple[str, datetime.date] | None:
    """
    Parse an IL SBE election dropdown label into (election_type, election_date).
    Returns None for labels whose date can't be reliably computed (specials).
    """
    match = re.match(r"^(\d{4})\s+(.*)$", label.strip())
    if not match:
        return None
    year = int(match.group(1))
    kind = match.group(2).strip().upper()

    if kind == "GENERAL ELECTION":
        return "general", _first_tuesday_after_first_monday(year, 11)
    if kind == "GENERAL PRIMARY":
        return "primary", _third_tuesday_of_march(year)
    if kind == "CONSOLIDATED ELECTION":
        return "municipal", _first_tuesday_of_april(year)
    return None


def map_election(value: str, label: str) -> dict | None:
    """Return Election model field values for one IL SBE dropdown entry, or None if undatable."""
    inferred = infer_election_type_and_date(label)
    if inferred is None:
        return None
    election_type, election_date = inferred

    today = datetime.date.today()
    if election_date > today:
        status = Election.Status.UPCOMING
    elif election_date == today:
        status = Election.Status.ACTIVE
    else:
        status = Election.Status.RESULTS_PENDING

    return {
        "source_id": f"il_sbe_{value}",
        "name": f"{label.split()[0]} Illinois {label.split(maxsplit=1)[1].title()}",
        "election_date": election_date,
        "election_type": election_type,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "IL",
        "status": status,
        "source_metadata": {
            "il_sbe_election_value": value,
            "election_date_approximate": election_type == "primary",
        },
    }


def map_race(election_obj, office_name: str) -> dict:
    """Map an IL SBE office name to Race model field values."""
    office_name = office_name.strip()
    is_district = _is_district_office(office_name)

    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office_name,
        "jurisdiction": office_name if is_district else "Illinois",
        "geography_scope": "district" if is_district else "statewide",
        "certification_status": Race.CertificationStatus.UPCOMING,
        "source": Race.Source.IL_SBE,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "normalized_office_title": " ".join(office_name.lower().split()),
        "source_metadata": {
            "il_sbe_election_source_id": getattr(election_obj, "source_id", ""),
        },
    }
