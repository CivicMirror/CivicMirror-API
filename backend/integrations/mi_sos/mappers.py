from __future__ import annotations

import re

from elections.models import Candidate

_PARTY_MAP = {
    "democratic": "DEM",
    "democrat": "DEM",
    "republican": "REP",
    "libertarian": "LIB",
    "green": "GRN",
    "working class": "WCP",
    "natural law": "NLP",
    "us taxpayers": "UST",
    "u.s. taxpayers": "UST",
    "nonpartisan": "NPA",
    "non-partisan": "NPA",
}


def party_abbrev(raw_party: str) -> str:
    normalized = (raw_party or "").strip().lower()
    return _PARTY_MAP.get(normalized, normalized.upper()[:3])


def candidate_status(raw_status: str) -> str:
    status = (raw_status or "").strip().upper()
    if status == "WITHD":
        return Candidate.CandidateStatus.WITHDRAWN
    if status == "DISQ":
        return Candidate.CandidateStatus.DISQUALIFIED
    return Candidate.CandidateStatus.RUNNING


def normalize_office_title(raw_office: str) -> str:
    office = " ".join((raw_office or "").split())
    upper = office.upper()

    prefix_district = re.search(r"^(\d+)(?:ST|ND|RD|TH)?\s+DISTRICT", upper)
    suffix_district = re.search(r"(\d+)(?:ST|ND|RD|TH)?\s+DISTRICT", upper)
    district_match = prefix_district or suffix_district
    district = district_match.group(1) if district_match else ""

    if "GOVERNOR" in upper and "LIEUTENANT" not in upper:
        return "Governor"
    if "LIEUTENANT GOVERNOR" in upper:
        return "Lieutenant Governor"
    if "UNITED STATES SENATOR" in upper or "U.S. SENATOR" in upper:
        return "U.S. Senate"
    if "UNITED STATES REPRESENTATIVE" in upper or "U.S. REPRESENTATIVE" in upper:
        return f"U.S. House - District {district}" if district else "U.S. House"
    if "STATE SENATOR" in upper:
        return f"State Senate - District {district}" if district else "State Senate"
    if "STATE REPRESENTATIVE" in upper:
        return f"State House - District {district}" if district else "State House"
    return office


def result_office_title(raw_contest: str) -> str:
    return normalize_office_title(raw_contest)


def is_write_in(candidate_name: str) -> bool:
    return "WRITE" in (candidate_name or "").upper()
