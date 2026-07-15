"""
Mappers for Tennessee SOS calendar and qualified-candidate workbook data ->
CivicMirror model fields.
"""
from __future__ import annotations

from elections.models import Candidate, Election, Race

from .parsers import TnCandidateRecord, TnElectionRow

_FEDERAL_OFFICE_MARKERS = ("united states", "u.s.", "us senate", "us house")
_STATEWIDE_OFFICES = ("governor",)
# Party executive-committee seats appear in the SOS candidate lists but are
# party offices, not public federal/state offices — out of scope like KY's
# judicial/county groups.
_OUT_OF_SCOPE_OFFICE_MARKERS = ("state executive committee",)


def is_in_scope_office(office: str) -> bool:
    normalized = office.lower()
    return not any(marker in normalized for marker in _OUT_OF_SCOPE_OFFICE_MARKERS)


def infer_election_status(election_date) -> str:
    from django.utils import timezone

    today = timezone.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def infer_election_type(name: str) -> str:
    normalized = name.lower()
    if "primary" in normalized:
        return Election.ElectionType.PRIMARY
    if "general" in normalized:
        return Election.ElectionType.GENERAL
    if "special" in normalized:
        return Election.ElectionType.SPECIAL
    if "municipal" in normalized:
        return Election.ElectionType.MUNICIPAL
    return Election.ElectionType.OTHER


def map_election(row: TnElectionRow) -> dict:
    scope = "statewide" if row.is_statewide else _slug(row.county or row.jurisdiction)
    return {
        "source_id": f"tn_sos:{row.election_date.isoformat()}:{scope}",
        "name": row.name,
        "election_date": row.election_date,
        "election_type": infer_election_type(row.name),
        "jurisdiction_level": (
            Election.JurisdictionLevel.STATE if row.is_statewide else Election.JurisdictionLevel.LOCAL
        ),
        "state": "TN",
        "status": infer_election_status(row.election_date),
        "source_metadata": {"tn_source_url": row.source_url},
    }


def normalized_office_title(office: str, district: str) -> str:
    title = office
    if district:
        district_text = district if "district" in district.lower() else f"District {district}"
        title = f"{office} {district_text}"
    return " ".join(title.lower().split())


def _geography_scope(office: str, district: str) -> str:
    normalized = office.lower()
    if any(marker in normalized for marker in _FEDERAL_OFFICE_MARKERS):
        return "federal"
    if district:
        return "district"
    if any(marker in normalized for marker in _STATEWIDE_OFFICES):
        return "statewide"
    return "statewide"


def map_race(election_obj, record: TnCandidateRecord) -> dict:
    district = record.district.strip()
    district_text = ""
    office_title = record.office
    if district:
        district_text = district if "district" in district.lower() else f"District {district}"
        office_title = f"{record.office} {district_text}"

    certification = (
        Race.CertificationStatus.RESULTS_PENDING
        if election_obj.status == Election.Status.RESULTS_PENDING
        else Race.CertificationStatus.UPCOMING
    )
    scope = _geography_scope(record.office, district)
    jurisdiction = f"Tennessee {district_text}".strip() if scope == "district" else "Tennessee"

    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office_title,
        "jurisdiction": jurisdiction or "Tennessee",
        "geography_scope": scope,
        "certification_status": certification,
        "source": Race.Source.TN_SOS,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "normalized_office_title": normalized_office_title(record.office, district),
        "source_metadata": {
            "tn_sos_office": record.office,
            "tn_sos_district": district,
            "tn_source_url": record.source_url,
        },
    }


def map_candidate(record: TnCandidateRecord) -> dict:
    return {
        "name": record.candidate_name,
        "party": record.party,
        "candidate_status": Candidate.CandidateStatus.RUNNING,
        "source_metadata": {
            "tn_source_url": record.source_url,
            "tn_source_row": record.source_row,
            "tn_workbook_status": record.status,
        },
    }


def _slug(value: str) -> str:
    return "-".join(value.lower().split()) or "local"
