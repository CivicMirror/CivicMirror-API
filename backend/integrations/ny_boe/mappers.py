from __future__ import annotations

from typing import Any

from elections.models import Candidate, Election, Race

_PARTY_ALIASES = {
    "DEMOCRATIC": "DEM",
    "DEMOCRAT": "DEM",
    "DEM": "DEM",
    "REPUBLICAN": "REP",
    "REP": "REP",
    "CONSERVATIVE": "CON",
    "CON": "CON",
    "WORKING FAMILIES": "WFP",
    "WORKING FAMILIES PARTY": "WFP",
}


def _compact(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def normalize_ny_office(value: str) -> str:
    return _compact(value)


def normalize_ny_district(value: str) -> str:
    return _compact(value)


def normalize_ny_party(value: str) -> str:
    raw = " ".join(str(value or "").strip().split()).upper()
    return _PARTY_ALIASES.get(raw, raw)


def build_ny_source_identity(contest: dict) -> dict[str, str | int]:
    office = normalize_ny_office(contest.get("office", ""))
    district = normalize_ny_district(contest.get("district", ""))
    district2 = normalize_ny_district(contest.get("district2", ""))
    party = normalize_ny_party(contest.get("party", ""))
    return {
        "ny_identity_version": 1,
        "contest_code": f"{office}|{district}|{district2}",
        "party_code": party,
        "ny_office": office,
        "ny_district": district,
        "ny_district2": district2,
        "ny_party": party,
    }


def build_canonical_key(contest: dict) -> str:
    identity = build_ny_source_identity(contest)
    return f"ny:{identity['contest_code']}:{identity['party_code']}"


def _vote_for(value: Any) -> int:
    try:
        return max(1, int(str(value or "1").strip()))
    except ValueError:
        return 1


def _geography_scope(contest: dict) -> str:
    district = str(contest.get("district") or contest.get("district2") or "").strip()
    return "district" if district else "statewide"


def map_contest_to_race(contest: dict, election: Election, existing_metadata: dict | None = None) -> tuple[dict, dict]:
    source_identity = build_ny_source_identity(contest)
    office_title = (contest.get("office") or "").strip()
    party = source_identity["party_code"]
    vote_for = _vote_for(contest.get("vote_for"))
    metadata = {
        **(existing_metadata or {}),
        "provider": "ny_boe",
        "source_key": contest.get("key", ""),
        "counties": contest.get("counties", ""),
        "vote_for": vote_for,
        **source_identity,
    }
    contest_variant = f"ny:{source_identity['contest_code']}:{party}"
    identity = {
        "office_title": office_title,
        "ocd_division_id": "",
        "race_type": Race.RaceType.CANDIDATE,
        "contest_variant": contest_variant,
    }
    fields = {
        "office_title": office_title,
        "jurisdiction": "New York",
        "geography_scope": _geography_scope(contest),
        "vote_method": Race.VoteMethod.MULTI_SEAT if vote_for > 1 else Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": vote_for,
        "ballot_type": (contest.get("party") or "").strip(),
        "source": Race.Source.NY_BOE,
        "source_metadata": metadata,
    }
    return identity, fields


def map_candidate(candidate_row: dict, existing_metadata: dict | None = None) -> dict:
    metadata = {
        **(existing_metadata or {}),
        "provider": "ny_boe",
        "ballot_order": (candidate_row.get("ballot_order") or "").strip(),
    }
    if candidate_row.get("running_mate"):
        metadata["running_mate"] = candidate_row["running_mate"]
    return {
        "candidate_status": Candidate.CandidateStatus.RUNNING,
        "source_metadata": metadata,
    }
