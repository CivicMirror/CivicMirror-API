# backend/integrations/fl_ew/mappers.py
"""
Mappers for FL Election Watch tab-delimited data → CivicMirror model fields.
"""
from __future__ import annotations

from datetime import date

from django.utils import timezone

from elections.models import Candidate, Election, Race

from .parsers import ElectionRow


def normalize(text: str | None) -> str:
    return " ".join((text or "").strip().lower().split())


def build_candidate_name(row: ElectionRow) -> str:
    parts = [row.can_name_first, row.can_name_middle, row.can_name_last]
    return " ".join(p for p in parts if p).strip()


def infer_election_type(election_date: date) -> str:
    if election_date.month == 11:
        return Election.ElectionType.GENERAL
    if election_date.month in {8, 9}:
        return Election.ElectionType.PRIMARY
    return Election.ElectionType.SPECIAL


def infer_election_status(election_date: date) -> str:
    today = timezone.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def map_election(slug: str, election_date: date) -> dict:
    """Map a date slug → Election model field values."""
    election_type = infer_election_type(election_date)
    date_label = election_date.strftime("%B %-d, %Y")
    type_label = election_type.replace("_", " ").title()
    name = f"Florida {date_label} {type_label}"

    return {
        "source_id": f"fl_ew:{slug}",
        "name": name,
        "election_date": election_date,
        "election_type": election_type,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "FL",
        "status": infer_election_status(election_date),
        "source_metadata": {
            "fl_ew_slug": slug,
        },
    }


def build_race_groups(rows: list[ElectionRow], is_primary: bool) -> list[dict]:
    """
    Group ElectionRow list into race dicts.

    For primary elections: partition by (race_name, juris1_num, juris2_num, party_code)
    so that REP and DEM primaries for the same office are tracked as separate races.

    For general/special elections: partition by (race_name, juris1_num, juris2_num)
    so all candidates across parties share one race.
    """
    groups: dict[tuple, dict] = {}

    for row in rows:
        if is_primary:
            key = (row.race_name, row.juris1_num, row.juris2_num, row.party_code)
            party_code = row.party_code
            party_name = row.party_name
        else:
            key = (row.race_name, row.juris1_num, row.juris2_num)
            party_code = ""
            party_name = ""

        if key not in groups:
            groups[key] = {
                "race_name": row.race_name,
                "race_code": row.race_code,
                "juris1_num": row.juris1_num,
                "juris2_num": row.juris2_num,
                "party_code": party_code,
                "party_name": party_name,
                "rows": [],
            }
        groups[key]["rows"].append(row)

    return list(groups.values())


def map_race(election_obj: Election, group: dict) -> dict:
    """Map a race group dict → Race model field values."""
    office_title = group["race_name"]
    certification_status = (
        Race.CertificationStatus.UPCOMING
        if election_obj.status in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_PENDING
    )

    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office_title,
        "normalized_office_title": normalize(office_title),
        "jurisdiction": "Florida",
        "geography_scope": "statewide" if not group["juris1_num"] or group["juris1_num"] == "000" else "district",
        "certification_status": certification_status,
        "source": Race.Source.FL_EW,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "source_metadata": {
            "fl_ew_race_code": group["race_code"],
            "fl_ew_juris1_num": group["juris1_num"],
            "fl_ew_juris2_num": group["juris2_num"],
            "fl_ew_party_code": group["party_code"],
            "fl_ew_party_name": group["party_name"],
        },
    }


def map_candidate(row: ElectionRow) -> tuple[str, str, dict]:
    """
    Map an ElectionRow → (name, party, fields) for ingest_candidate.

    Returns a 3-tuple so the caller can unpack directly into the ingest call.
    """
    name = build_candidate_name(row)
    party = row.party_name or row.party_code
    fields = {
        "incumbent": False,
        "candidate_status": Candidate.CandidateStatus.RUNNING,
        "source_metadata": {
            "fl_ew_party_code": row.party_code,
        },
    }
    return name, party, fields
