"""
Mappers for Alabama FCPA Political Race Search data -> CivicMirror model
fields.

The FCPA office dropdown (fcpa.alabamavotes.gov/page.request.do?page=
page.acfPublicPoliticalRaceSearch) lists 45 offices including county and
municipal seats (Sheriff, Tax Assessor, Circuit Clerk, ...). CORE_OFFICE_IDS
restricts Stage 1 ingestion to statewide and state-legislative offices,
matching the "federal and state elections" Core coverage target in
docs/state-research/AL/AL-Election_Research.md. IDs confirmed against the
live dropdown captured in
docs/state-research/AL/fcpa.alabamavotes.gov_Archive [26-07-20 12-42-17].har.
"""
from __future__ import annotations

OFFICE_LABELS: dict[int, str] = {
    23: "Governor",
    26: "Lt. Governor",
    3: "Attorney General",
    36: "Secretary of State",
    38: "State Auditor",
    42: "State Treasurer",
    10: "Commissioner of Agriculture & Industries",
    39: "State Board of Education",
    32: "President of the Public Service Commission",
    31: "Public Service Commissioner",
    41: "State Senator",
    40: "State Representative",
}

CORE_OFFICE_IDS = frozenset(OFFICE_LABELS)

assert CORE_OFFICE_IDS == set(OFFICE_LABELS), "CORE_OFFICE_IDS and OFFICE_LABELS keys must match"

_OFFICE_TITLE_OVERRIDES = {
    "Lt. Governor": "Lieutenant Governor",
}

_PARTY_MAP = {
    "democratic": "DEM",
    "republican": "REP",
    "independent": "IND",
    "libertarian": "LIB",
    "green": "GRN",
}


def normalize_office_title(office: str, district: str) -> str:
    """
    E.g. ("State Senator", "27") -> "State Senate - District 27", matching
    the cross-state convention used by integrations.pa_sos and
    integrations.mi_sos.
    """
    office = (office or "").strip()
    district = (district or "").strip()
    title = _OFFICE_TITLE_OVERRIDES.get(office, office)

    if title == "State Senator":
        return f"State Senate - District {district}" if district else "State Senate"
    if title == "State Representative":
        return f"State House - District {district}" if district else "State House"
    return title


def geography_scope(office_title: str) -> str:
    title = office_title.lower()
    if "state senate" in title or "state house" in title:
        return "state_legislative_district"
    return "statewide"


def party_abbrev(party_name: str) -> str:
    return _PARTY_MAP.get((party_name or "").lower().strip(), (party_name or "").upper()[:3])


def build_candidate_name(detail: dict) -> str:
    """Build a display name from committeeDetailsObj's structured name fields."""
    parts = [
        detail.get("candidateFirstName", "").strip(),
        detail.get("candidateMiddleName", "").strip(),
        detail.get("candidateLastName", "").strip(),
    ]
    name = " ".join(part for part in parts if part)
    suffix = detail.get("suffix", "").strip()
    return f"{name} {suffix}".strip() if suffix else name
