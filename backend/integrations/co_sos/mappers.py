"""
Mappers for Colorado SOS data → CivicMirror model fields.
"""
import calendar
from datetime import date, timedelta

from elections.models import Candidate, Election, Race

_FEDERAL_KEYWORDS = frozenset({
    "us senate", "u.s. senate", "us house", "u.s. house",
    "united states", "congress", "senate", "house of representatives",
})

_STATEWIDE_KEYWORDS = frozenset({
    "us senate", "u.s. senate", "governor", "secretary of state",
    "state treasurer", "attorney general",
    "state board of education", "university of colorado board of regents",
    "colorado state university system board of governors",
})


def normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


# ---------------------------------------------------------------------------
# Election date computation (statutory)
# ---------------------------------------------------------------------------

def _last_tuesday_of_june(year: int) -> date:
    """Colorado primary: last Tuesday in June of even-numbered years."""
    last_day = date(year, 6, 30)
    # weekday(): Monday=0 … Sunday=6; Tuesday=1
    days_back = (last_day.weekday() - calendar.TUESDAY) % 7
    return last_day - timedelta(days=days_back)


def _first_tuesday_after_first_monday_of_november(year: int) -> date:
    """General election: first Tuesday after the first Monday in November."""
    first = date(year, 11, 1)
    # Advance to the first Monday
    days_to_monday = (calendar.MONDAY - first.weekday()) % 7
    first_monday = first + timedelta(days=days_to_monday)
    return first_monday + timedelta(days=1)


def co_election_date(year: int, election_type: str) -> date:
    if election_type == "primary":
        return _last_tuesday_of_june(year)
    if election_type == "general":
        return _first_tuesday_after_first_monday_of_november(year)
    raise ValueError(f"Unknown election_type: {election_type!r}")


# ---------------------------------------------------------------------------
# Election mappers
# ---------------------------------------------------------------------------

def infer_election_status(election_date: date) -> str:
    from django.utils import timezone as tz
    today = tz.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def build_election_source_id(year: int, election_type: str) -> str:
    """e.g. 'co_sos_2026_primary'"""
    return f"co_sos_{year}_{election_type}"


def map_election(year: int, election_type: str) -> dict:
    """Return Election model field values for the given CO election."""
    election_date = co_election_date(year, election_type)
    type_label = election_type.title()

    return {
        "source_id": build_election_source_id(year, election_type),
        "name": f"{year} Colorado {type_label} Election",
        "election_date": election_date,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "CO",
        "status": infer_election_status(election_date),
    }


# ---------------------------------------------------------------------------
# Race / Candidate mappers
# ---------------------------------------------------------------------------

def infer_geography_scope(office: str, district: str) -> str:
    office_lower = normalize(office)
    if any(kw in office_lower for kw in _STATEWIDE_KEYWORDS):
        return "statewide"
    if district and normalize(district) not in {"statewide", ""}:
        return "district"
    return "statewide"


def infer_jurisdiction_for_race(office: str, district: str) -> str:
    if district and normalize(district) not in {"statewide", ""}:
        return district
    return "Colorado"


def build_race_canonical_key(
    election_source_id: str,
    office: str,
    district: str,
    party_group: str,
) -> str:
    parts = [
        "co_sos",
        election_source_id,
        normalize(office),
        normalize(district) or "statewide",
        normalize(party_group) or "nonpartisan",
    ]
    return ":".join(parts)


def build_race_groups(candidates: list[dict], is_primary: bool) -> list[dict]:
    """
    Group candidate rows into race dicts.

    For primary elections: partition by (office, district, party) so that
    Republican and Democratic primaries are tracked as separate races.
    For general elections: partition by (office, district).
    """
    groups: dict[tuple, dict] = {}

    for c in candidates:
        office = c["office"].strip()
        district = c["district"].strip()
        party = c["party"].strip() if is_primary else ""
        key = (office, district, party)

        if key not in groups:
            groups[key] = {
                "office": office,
                "district": district,
                "party_group": party,
                "candidates": [],
            }
        groups[key]["candidates"].append(c)

    return list(groups.values())


def map_race(election_obj: Election, race_group: dict) -> dict:
    """Map a race group to Race model field values."""
    office = race_group["office"]
    district = race_group["district"]
    party_group = race_group["party_group"]

    office_lower = normalize(office)
    is_federal = any(kw in office_lower for kw in _FEDERAL_KEYWORDS)

    certification_status = (
        Race.CertificationStatus.UPCOMING
        if election_obj.status in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_PENDING
    )

    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office,
        "jurisdiction": infer_jurisdiction_for_race(office, district),
        "geography_scope": infer_geography_scope(office, district),
        "certification_status": certification_status,
        "source": Race.Source.CO_SOS,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "normalized_office_title": normalize(office),
        "canonical_key": build_race_canonical_key(
            election_obj.source_id, office, district, party_group
        ),
        "source_metadata": {
            "co_sos_election_id": election_obj.source_id,
            "district": district,
            "party_group": party_group,
            "is_federal": is_federal,
        },
    }


def map_candidate(candidate_row: dict) -> dict:
    """
    Map a parsed candidate row to Candidate model field values.

    Status precedence: WITHDRAWN > WRITE_IN > RUNNING.
    """
    if candidate_row.get("is_withdrawn"):
        status = Candidate.CandidateStatus.WITHDRAWN
    elif candidate_row.get("is_write_in"):
        status = Candidate.CandidateStatus.WRITE_IN
    else:
        status = Candidate.CandidateStatus.RUNNING

    return {
        "party": candidate_row.get("party", ""),
        "incumbent": False,
        "candidate_status": status,
        "source_metadata": {
            "co_sos_office": candidate_row.get("office", ""),
            "co_sos_district": candidate_row.get("district", ""),
            "is_write_in": candidate_row.get("is_write_in", False),
        },
    }
