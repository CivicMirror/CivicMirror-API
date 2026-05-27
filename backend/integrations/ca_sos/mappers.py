"""
Mappers for California SOS data → CivicMirror model fields.
"""
import calendar
import re
from datetime import date, timedelta

from elections.models import Election, Race

_FEDERAL_KEYWORDS = frozenset({
    "us senate", "u.s. senate", "us house", "u.s. house",
    "united states", "congress", "senate", "house of representatives",
    "president", "presidential",
})

_STATEWIDE_KEYWORDS = frozenset({
    "governor", "lieutenant governor", "attorney general", "secretary of state",
    "state treasurer", "state controller", "superintendent of public instruction",
    "insurance commissioner", "us senate", "u.s. senate",
    "ballot measure", "proposition", "statewide",
})


def normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


# ---------------------------------------------------------------------------
# Election date computation (California statutory)
# ---------------------------------------------------------------------------

def ca_primary_date(year: int) -> date:
    """
    California primary: first Tuesday after the first Monday in March.
    (Consolidated Statewide Primary — even-numbered years)
    """
    first = date(year, 3, 1)
    days_to_monday = (calendar.MONDAY - first.weekday()) % 7
    first_monday = first + timedelta(days=days_to_monday)
    return first_monday + timedelta(days=1)


def ca_general_date(year: int) -> date:
    """California general: first Tuesday after the first Monday in November."""
    first = date(year, 11, 1)
    days_to_monday = (calendar.MONDAY - first.weekday()) % 7
    first_monday = first + timedelta(days=days_to_monday)
    return first_monday + timedelta(days=1)


def ca_election_date(year: int, election_type: str) -> date:
    if election_type == "primary":
        return ca_primary_date(year)
    if election_type == "general":
        return ca_general_date(year)
    raise ValueError(f"Unknown election_type: {election_type!r}")


def infer_election_status(election_date: date) -> str:
    from django.utils import timezone as tz
    today = tz.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def build_election_source_id(year: int, election_type: str) -> str:
    return f"ca_sos_{year}_{election_type}"


def map_election(year: int, election_type: str) -> dict:
    """Return Election model field values for the given CA election."""
    election_date = ca_election_date(year, election_type)
    type_label = election_type.title()
    return {
        "source_id": build_election_source_id(year, election_type),
        "name": f"{year} California {type_label} Election",
        "election_date": election_date,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "CA",
        "status": infer_election_status(election_date),
    }


# ---------------------------------------------------------------------------
# Race / Candidate mappers
# ---------------------------------------------------------------------------

def infer_geography_scope(contest_name: str) -> str:
    normalized = normalize(contest_name)
    if any(kw in normalized for kw in _STATEWIDE_KEYWORDS):
        return "statewide"
    if re.search(r"\bdistrict\b|\bcd-?\d|\bsd-?\d|\bad-?\d", normalized):
        return "district"
    return "statewide"


def infer_race_type(contest_type: str) -> str:
    if contest_type == "measure":
        return Race.RaceType.MEASURE
    return Race.RaceType.CANDIDATE


def build_race_canonical_key(
    election_source_id: str,
    contest_name: str,
    endpoint_path: str,
) -> str:
    parts = [
        "ca_sos",
        election_source_id,
        normalize(contest_name) or normalize(endpoint_path),
    ]
    return ":".join(parts)


def map_race(election_obj: Election, catalog_entry: dict) -> dict:
    """
    Map a catalog entry to Race model field values.

    catalog_entry has keys: name, path, type, race_id
    """
    contest_name = catalog_entry["name"]
    endpoint_path = catalog_entry["path"]
    contest_type = catalog_entry["type"]

    contest_lower = normalize(contest_name)
    is_federal = any(kw in contest_lower for kw in _FEDERAL_KEYWORDS)
    race_type = infer_race_type(contest_type)
    geography_scope = infer_geography_scope(contest_name)

    certification_status = (
        Race.CertificationStatus.UPCOMING
        if election_obj.status in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_PENDING
    )

    return {
        "race_type": race_type,
        "office_title": contest_name,
        "jurisdiction": "California",
        "geography_scope": geography_scope,
        "certification_status": certification_status,
        "source": Race.Source.CA_SOS,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "normalized_office_title": normalize(contest_name),
        "canonical_key": build_race_canonical_key(
            election_obj.source_id, contest_name, endpoint_path
        ),
        "source_metadata": {
            "ca_endpoint": endpoint_path,
            "ca_race_id": catalog_entry.get("race_id", ""),
            "is_federal": is_federal,
            "contest_type": contest_type,
        },
    }


def map_candidate(raw_candidate: dict) -> dict:
    """
    Map a CA SOS results JSON candidate entry to Candidate model field values.

    raw_candidate fields (from /returns/{contest} JSON):
      Name, Party, Votes, Percent, incumbent (bool, optional)
    """
    from elections.models import Candidate

    is_incumbent = bool(raw_candidate.get("incumbent", False))
    name = (raw_candidate.get("Name") or "").strip()

    return {
        "party": (raw_candidate.get("Party") or "").strip(),
        "incumbent": is_incumbent,
        "candidate_status": Candidate.CandidateStatus.RUNNING,
        "source_metadata": {
            "ca_votes": raw_candidate.get("Votes", ""),
            "ca_percent": raw_candidate.get("Percent", ""),
        },
    }
