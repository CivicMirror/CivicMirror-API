from __future__ import annotations

import re
from datetime import date

from django.utils import timezone

from elections.models import Candidate, Election, Race

STATE = "GA"
SOURCE = "ga_sos"
JURISDICTION = "Georgia"

_FEDERAL_RE = re.compile(r"\b(u\.?s\.?|united states|president)\b", re.IGNORECASE)
_DISTRICT_RE = re.compile(r"\bDistrict\s+([A-Za-z0-9-]+)\b", re.IGNORECASE)
_PARTY_SUFFIX = {
    "DEM": "dem",
    "D": "dem",
    "REP": "rep",
    "R": "rep",
}


def _get_text(names, lang: str = "en") -> str:
    if isinstance(names, str):
        return names.strip()
    if not isinstance(names, list):
        return ""
    for item in names:
        if item.get("languageId") == lang:
            return (item.get("text") or "").strip()
    return ((names[0].get("text") or "").strip()) if names else ""


def normalize(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", (text or "").lower())
    return " ".join(cleaned.split())


def normalize_office_title(title: str, party_name: str = "") -> str:
    normalized_party = _PARTY_SUFFIX.get((party_name or "").strip().upper())
    source_title = (title or "").strip()
    if normalized_party:
        suffix = f" - {normalized_party}"
        if source_title.lower().endswith(suffix):
            source_title = source_title[: -len(suffix)]
    return normalize(source_title)


def parse_election_date(row: dict) -> date | None:
    raw = row.get("electionDate")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def infer_election_type(public_election_id: str, name: str) -> str:
    haystack = f"{public_election_id} {name}".lower()
    if "primary" in haystack and "runoff" in haystack:
        return Election.ElectionType.PRIMARY_RUNOFF
    if "general" in haystack and "runoff" in haystack:
        return Election.ElectionType.GENERAL_RUNOFF
    if "primary" in haystack:
        return Election.ElectionType.PRIMARY
    if "special" in haystack:
        return Election.ElectionType.SPECIAL
    if "general" in haystack:
        return Election.ElectionType.GENERAL
    return Election.ElectionType.OTHER


def infer_election_status(election_date: date | None) -> str:
    if election_date is None:
        return Election.Status.UPCOMING
    today = timezone.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def map_election(row: dict) -> dict:
    public_id = (row.get("publicElectionId") or "").strip()
    election_date = parse_election_date(row)
    name = _get_text(row.get("name") or []) or public_id
    return {
        "source_id": f"{SOURCE}:{public_id}",
        "name": name,
        "election_date": election_date,
        "election_type": infer_election_type(public_id, name),
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": STATE,
        "status": infer_election_status(election_date),
        "source_metadata": {
            "provider": "enhanced_voting",
            "jurisdiction_slug": JURISDICTION,
            "enr_slug": public_id,
            "ga_public_election_id": public_id,
        },
    }


def _district_label(office_title: str) -> str:
    english_title = (office_title or "").split("/", 1)[0]
    match = _DISTRICT_RE.search(english_title)
    if not match:
        return ""
    return f"District {match.group(1)}"


def _is_federal(office_title: str) -> bool:
    return bool(_FEDERAL_RE.search(office_title or ""))


def _vote_for_count(ballot_item: dict) -> int:
    vote_for = ballot_item.get("voteFor")
    if isinstance(vote_for, int):
        return max(vote_for, 1)
    text = _get_text(vote_for or [])
    match = re.search(r"(\d+)", text)
    if match:
        return max(int(match.group(1)), 1)
    return 1


def map_race(election_obj, ballot_item: dict) -> dict:
    contest_type = ballot_item.get("contestType", "Candidate")
    office_title = _get_text(ballot_item.get("name") or [])
    party_name = (ballot_item.get("partyName") or "").strip()
    district = _district_label(office_title)

    race_type = Race.RaceType.MEASURE if contest_type == "BallotMeasure" else Race.RaceType.CANDIDATE
    certification_status = (
        Race.CertificationStatus.UPCOMING
        if election_obj.status in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_PENDING
    )

    if _is_federal(office_title):
        jurisdiction = JURISDICTION
        geography_scope = "federal"
    elif district:
        jurisdiction = district
        geography_scope = "district"
    else:
        jurisdiction = JURISDICTION
        geography_scope = "statewide"

    reporting_status = ballot_item.get("reportingStatus") or {}
    source_meta = {
        "ga_ballot_item_id": ballot_item.get("id", ""),
        "enr_slug": (election_obj.source_metadata or {}).get("enr_slug", ""),
        "ga_public_election_id": (election_obj.source_metadata or {}).get("ga_public_election_id", ""),
        "contest_type": contest_type,
        "party_name": party_name,
        "reporting_units": reporting_status.get("reportingUnits"),
        "total_units": reporting_status.get("totalUnits"),
        "source_office_title": office_title,
    }

    return {
        "race_type": race_type,
        "office_title": office_title,
        "normalized_office_title": normalize_office_title(office_title, party_name),
        "jurisdiction": jurisdiction,
        "geography_scope": geography_scope,
        "certification_status": certification_status,
        "source": Race.Source.GA_SOS,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.YES_NO if race_type == Race.RaceType.MEASURE else Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": _vote_for_count(ballot_item),
        "ocd_division_id": "",
        "source_metadata": source_meta,
    }


def _party_name(ballot_option: dict) -> str:
    party_data = ballot_option.get("party") or {}
    party_name_raw = party_data.get("name", "")
    party_name = _get_text(party_name_raw) if isinstance(party_name_raw, list) else party_name_raw
    party_abbr = party_data.get("abbreviation") or ballot_option.get("politicalParty", "")
    return (party_name or party_abbr or "").strip()


def map_candidate(ballot_option: dict) -> dict:
    party = _party_name(ballot_option)
    native_id = ballot_option.get("nativeId") or ballot_option.get("id")
    return {
        "party": party,
        "incumbent": False,
        "candidate_status": Candidate.CandidateStatus.RUNNING,
        "source_metadata": {
            "ga_native_id": native_id,
            "ga_option_id": ballot_option.get("id"),
            "party_abbreviation": party,
            "is_write_in": bool(ballot_option.get("isWriteIn", False) or ballot_option.get("isQualifiedWriteIn", False)),
        },
    }


def map_measure_option(ballot_option: dict) -> dict:
    return {
        "option_label": _get_text(ballot_option.get("name") or []) or str(ballot_option.get("nativeId") or ""),
        "source_metadata": {
            "ga_native_id": ballot_option.get("nativeId") or ballot_option.get("id"),
        },
    }
