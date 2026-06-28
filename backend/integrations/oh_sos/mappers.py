"""
Mappers for Ohio SOS CFDISCLOSURE data → CivicMirror model fields.
"""
from datetime import date, timedelta

from elections.models import Candidate, Election, Race


def _first_tuesday_after_first_monday(year: int, month: int) -> date:
    """Standard US election day formula."""
    first = date(year, month, 1)
    days_to_monday = (0 - first.weekday()) % 7  # Monday = 0
    first_monday = first + timedelta(days=days_to_monday)
    return first_monday + timedelta(days=1)


def oh_general_election_date(year: int) -> date:
    return _first_tuesday_after_first_monday(year, 11)


def infer_election_status(election_date: date) -> str:
    from django.utils import timezone as tz
    today = tz.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def map_election(year: int) -> dict:
    election_date = oh_general_election_date(year)
    return {
        "source_id": f"oh_sos_{year}_general",
        "name": f"{year} Ohio General Election",
        "election_date": election_date,
        "election_type": "general",
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "OH",
        "status": infer_election_status(election_date),
    }


# ---------------------------------------------------------------------------
# Office → race title + OCD division ID
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    return " ".join(s.strip().lower().split())


_STATEWIDE_OFFICES: dict[str, tuple[str, str]] = {
    "GOVERNOR":           ("Governor", "ocd-division/country:us/state:oh"),
    "ATTORNEY GENERAL":   ("Attorney General", "ocd-division/country:us/state:oh"),
    "SECRETARY OF STATE": ("Secretary of State", "ocd-division/country:us/state:oh"),
    "TREASURER":          ("Treasurer of State", "ocd-division/country:us/state:oh"),
    "AUDITOR":            ("Auditor of State", "ocd-division/country:us/state:oh"),
    "SUPREME COURT JUSTICE":       ("Ohio Supreme Court Justice", "ocd-division/country:us/state:oh"),
    "SUPREME COURT CHIEF JUSTICE": ("Ohio Supreme Court Chief Justice", "ocd-division/country:us/state:oh"),
    "STATE BOARD OF EDUCATION":    ("State Board of Education", "ocd-division/country:us/state:oh"),
}

_DISTRICT_OFFICES: dict[str, tuple[str, str]] = {
    "HOUSE":                ("Ohio House of Representatives, District {d}", "ocd-division/country:us/state:oh/sldl:{d}"),
    "SENATE":               ("Ohio State Senate, District {d}", "ocd-division/country:us/state:oh/sldu:{d}"),
    "COURT OF APPEALS JUDGE": ("Ohio Court of Appeals Judge, District {d}", "ocd-division/country:us/state:oh"),
}


def resolve_office(office: str, district: str) -> tuple[str, str]:
    """
    Return (office_title, ocd_division_id) for a CFDISCLOSURE office code.

    For district offices (HOUSE, SENATE, COURT OF APPEALS JUDGE), the district
    number is substituted into the title and OCD ID template.
    """
    if office in _STATEWIDE_OFFICES:
        return _STATEWIDE_OFFICES[office]

    if office in _DISTRICT_OFFICES:
        title_tmpl, ocd_tmpl = _DISTRICT_OFFICES[office]
        d = district or "0"
        return title_tmpl.format(d=d), ocd_tmpl.format(d=d)

    # Unknown office type — pass through as-is, statewide scope
    title = office.title()
    return title, "ocd-division/country:us/state:oh"


def build_race_groups(candidates: list[dict]) -> list[dict]:
    """
    Group parsed candidates by (office, district).

    Ohio general election races are non-partisan at the race level — party
    affiliation is stored per-candidate. A single race covers both Republican
    and Democratic nominees.
    """
    groups: dict[tuple, dict] = {}
    for c in candidates:
        key = (c["office"], c["district"])
        if key not in groups:
            office_title, ocd_id = resolve_office(c["office"], c["district"])
            groups[key] = {
                "office_code":  c["office"],
                "district":     c["district"],
                "office_title": office_title,
                "ocd_id":       ocd_id,
                "candidates":   [],
            }
        groups[key]["candidates"].append(c)
    return list(groups.values())


def map_race(election_obj: Election, group: dict) -> dict:
    office_title = group["office_title"]
    office_code  = group["office_code"]
    district     = group["district"]

    is_statewide = office_code in _STATEWIDE_OFFICES
    geography_scope = "statewide" if is_statewide else "district"

    certification_status = (
        Race.CertificationStatus.UPCOMING
        if election_obj.status in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_PENDING
    )

    election_ref = election_obj.source_id or ""

    return {
        "race_type":            Race.RaceType.CANDIDATE,
        "office_title":         office_title,
        "jurisdiction":         f"Ohio District {district}" if district else "Ohio",
        "geography_scope":      geography_scope,
        "certification_status": certification_status,
        "source":               Race.Source.OH_SOS,
        "race_status":          Race.RaceStatus.ACTIVE,
        "vote_method":          Race.VoteMethod.SINGLE_CHOICE,
        "max_selections":       1,
        "ocd_division_id":      group["ocd_id"],
        "normalized_office_title": _normalize(office_title),
        "canonical_key": ":".join([
            "oh_sos", election_ref,
            _normalize(office_code),
            district or "statewide",
        ]),
        "source_metadata": {
            "oh_sos_office_code": office_code,
            "district": district,
        },
    }


def map_candidate(candidate_row: dict) -> dict:
    return {
        "party":            candidate_row.get("party", ""),
        "incumbent":        False,
        "candidate_status": Candidate.CandidateStatus.RUNNING,
        "source_metadata": {
            "oh_sos_master_key":    candidate_row.get("master_key", ""),
            "oh_sos_committee":     candidate_row.get("committee_name", ""),
            "oh_sos_office_code":   candidate_row.get("office", ""),
            "oh_sos_district":      candidate_row.get("district", ""),
        },
    }
