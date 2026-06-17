"""
Mappers for TX GoElect ENR API data → CivicMirror model fields.
"""
from __future__ import annotations

from datetime import date, datetime

from elections.models import Election, Race

_TYPE_MAP = {
    "P":  Election.ElectionType.PRIMARY,
    "RU": Election.ElectionType.PRIMARY_RUNOFF,
    "GE": Election.ElectionType.GENERAL,
    "S":  Election.ElectionType.SPECIAL,
    "SR": Election.ElectionType.SPECIAL,
    "GR": Election.ElectionType.GENERAL_RUNOFF,
}

_TARGET_GENERAL_DATE = date(2026, 11, 3)


def parse_election_date(elec_date_str: str) -> date | None:
    """Parse GoElect MMDDYYYY string → date."""
    try:
        return datetime.strptime(elec_date_str, "%m%d%Y").date()
    except (ValueError, TypeError):
        return None


def infer_election_type(type_code: str) -> str:
    return _TYPE_MAP.get(type_code, Election.ElectionType.OTHER)


def classify_election(election_id: int, type_code: str, home: dict) -> dict:
    """
    Build normalized metadata tags for every discovered election.
    is_target_general_2026=True only for GE on 2026-11-03.
    """
    elec_date = parse_election_date(home.get("ElecDate", ""))
    source_date = elec_date.isoformat() if elec_date else ""

    is_target = (type_code == "GE" and elec_date == _TARGET_GENERAL_DATE)

    return {
        "tx_election_id": election_id,
        "election_type_code": type_code,
        "election_scope": "statewide",   # GoElect only surfaces statewide; update if district scope detected
        "source_date": source_date,
        "is_target_general_2026": is_target,
    }


def map_election(
    election_id: int,
    type_code: str,
    home: dict,
    election_name: str,
) -> dict:
    elec_date = parse_election_date(home.get("ElecDate", ""))
    election_type = infer_election_type(type_code)
    classification = classify_election(election_id, type_code, home)

    status = Election.Status.UPCOMING
    if elec_date:
        from django.utils import timezone as tz
        today = tz.localdate()
        if elec_date < today:
            status = Election.Status.RESULTS_PENDING
        elif elec_date == today:
            status = Election.Status.ACTIVE

    return {
        "source_id": f"tx_goelect:{election_id}",
        "name": election_name or f"Texas Election {election_id}",
        "election_date": elec_date,
        "election_type": election_type,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "TX",
        "status": status,
        "source_metadata": classification,
    }


def map_race(
    election_obj,
    office: dict,
    office_type_name: str,
    election_id: int,
) -> dict:
    office_id = office["ID"]
    office_name = office.get("ON", "")
    district_num = office.get("SSO", 0) or 0

    race_type = (
        Race.RaceType.MEASURE
        if "PROPOSITION" in office_type_name.upper() or "PROPOSITION" in office_name.upper()
        else Race.RaceType.CANDIDATE
    )

    geography_scope = "district" if district_num else "statewide"

    cert_status = (
        Race.CertificationStatus.UPCOMING
        if getattr(election_obj, "status", "") in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_PENDING
    )

    return {
        "source_id": f"tx_goelect:{election_id}:office:{office_id}",
        "office_title": office_name,
        "normalized_office_title": office_name.strip().lower(),
        "race_type": race_type,
        "geography_scope": geography_scope,
        "jurisdiction": f"District {district_num}" if district_num else "Texas",
        "certification_status": cert_status,
        "source": Race.Source.TX_GOELECT,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": (
            Race.VoteMethod.YES_NO
            if race_type == Race.RaceType.MEASURE
            else Race.VoteMethod.SINGLE_CHOICE
        ),
        "max_selections": 1,
        "ocd_division_id": "",
        "source_metadata": {
            "tx_election_id": election_id,
            "tx_office_id": office_id,
            "office_type": office_type_name,
            "district_number": district_num,
        },
    }


def map_candidate(election_id: int, office_id: int, ballot_option: dict) -> dict:
    candidate_id = ballot_option.get("ID") or ballot_option.get("id")
    name = ballot_option.get("BN") or ballot_option.get("N") or ""
    party = ballot_option.get("P", "")

    return {
        "name": name,
        "party": party,
        "source_id": f"tx_goelect:{election_id}:office:{office_id}:candidate:{candidate_id}",
        "source_metadata": {
            "tx_candidate_id": candidate_id,
            "party_abbreviation": party,
        },
    }


def map_county_fragment(county_entry: dict) -> str:
    """Lowercase county name slug, e.g. 'harris' from {"CN": "HARRIS", "MID": 48201}."""
    return (county_entry.get("CN") or "").lower()
