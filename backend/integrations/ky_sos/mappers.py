"""
Mappers for Kentucky SOS Candidate Filings data -> CivicMirror model fields.
"""
from __future__ import annotations

import calendar
import datetime

from elections.models import Election, Race

IN_SCOPE_OFFICE_IDS = frozenset({3, 4, 11, 12})

# office_id -> expected office label text (sanity/lookup only; office_title
# itself always comes from the parsed row text, not this table).
OFFICE_LABELS = {
    3: "US Senator",
    4: "US Representative",
    11: "State Senator",
    12: "State Representative",
}

_STATEWIDE_OFFICES = frozenset({"US Senator"})


def ky_general_election_date(year: int) -> datetime.date:
    """First Tuesday after first Monday in November (Ky. Const. §148, KRS 118.025(4))."""
    first = datetime.date(year, 11, 1)
    days_to_monday = (calendar.MONDAY - first.weekday()) % 7
    first_monday = first + datetime.timedelta(days=days_to_monday)
    return first_monday + datetime.timedelta(days=1)


def infer_election_status(election_date: datetime.date) -> str:
    from django.utils import timezone
    today = timezone.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def map_election(election_label: str) -> dict:
    """
    Map the Candidate Filings election dropdown label (e.g. "2026 General
    Election") to Election model field values. Only "General Election" labels
    are supported — this adapter doesn't sweep primary-cycle filings.
    """
    year = int(election_label.split()[0])
    election_date = ky_general_election_date(year)
    return {
        "source_id": f"ky_sos_{year}_general",
        "name": f"{year} Kentucky General Election",
        "election_date": election_date,
        "election_type": "general",
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "KY",
        "status": infer_election_status(election_date),
    }


def map_race(office_name: str, district: str) -> dict:
    is_statewide = office_name in _STATEWIDE_OFFICES
    office_title = office_name if is_statewide else f"{office_name} District {district}"
    jurisdiction = "Kentucky" if is_statewide else f"Kentucky District {district}"

    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office_title,
        "jurisdiction": jurisdiction,
        "geography_scope": "statewide" if is_statewide else "district",
        "certification_status": Race.CertificationStatus.UPCOMING,
        "source": Race.Source.KY_SOS,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "normalized_office_title": " ".join(office_title.lower().split()),
        "source_metadata": {"ky_sos_office": office_name, "ky_sos_district": district},
    }


def map_candidate(row: dict, candidate_status: str) -> tuple[str, str, dict]:
    fields = {
        "candidate_status": candidate_status,
        "source_metadata": {
            "ky_sos_date_filed": row.get("date_filed", ""),
            "ky_sos_office": row.get("office", ""),
            "ky_sos_district": row.get("district", ""),
        },
    }
    return row["name"], row.get("party", ""), fields
