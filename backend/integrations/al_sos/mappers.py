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

import re

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


def normalize_certification_office(office: str) -> str:
    """Map the office labels printed in SOS certification tables to race titles."""
    value = " ".join((office or "").replace("\u00a0", " ").split()).strip(" ,")
    value = value.replace("§", "5")
    value = re.sub(r"\s*,\s*", ", ", value)
    patterns = (
        (r"^(?:U\.\s*S\.|U\.S\.|United States)\s+Senate$", "U.S. Senate"),
        (r"^United States Senator$", "U.S. Senate"),
        (r"^U\.S\. Senator$", "U.S. Senate"),
        (r"^U\.\s*S\.\s+Congress\s+Congressional\s+District\s+(\d+)$", r"U.S. House - District \1"),
        (r"^U\.S\.\s+Congress\s+Congressional\s+District\s+(\d+)$", r"U.S. House - District \1"),
        (
            r"^United States Representative,?\s+(\d+)(?:ST|ND|RD|TH)?\s+Congressional District$",
            r"U.S. House - District \1",
        ),
        (r"^United States Representative Congressional District\s+(\d+)$", r"U.S. House - District \1"),
        (r"^Governor$", "Governor"),
        (r"^(?:Lt\.?|Lieutenant)\s+Governor$", "Lieutenant Governor"),
        (r"^Attorney General$", "Attorney General"),
        (r"^Secretary of State$", "Secretary of State"),
        (r"^(?:State )?Treasurer$", "State Treasurer"),
        (r"^(?:State )?Auditor$", "State Auditor"),
        (r"^Commissioner of Agriculture and Industries$", "Commissioner of Agriculture & Industries"),
        (r"^Commissioner of Agriculture & Industries$", "Commissioner of Agriculture & Industries"),
        (r"^Public Service Commission Place (\d+)$", r"Public Service Commissioner - Place \1"),
        (r"^Public Service Commission,?\s+Place (\d+)$", r"Public Service Commissioner - Place \1"),
        (r"^Public Service Commissioner Place (\d+)$", r"Public Service Commissioner - Place \1"),
        (
            r"^(?:Alabama )?State Board of Education,?\s*District (\d+)$",
            r"State Board of Education - District \1",
        ),
        (r"^State Board of Education Member District (\d+)$", r"State Board of Education - District \1"),
        (r"^(?:Alabama )?State Senate,?\s*District (\d+)$", r"State Senate - District \1"),
        (r"^State Senator,?\s+District (\d+)$", r"State Senate - District \1"),
        (
            r"^(?:Alabama )?State House of Representatives,?\s*District (\d+)$",
            r"State House - District \1",
        ),
        (r"^State Representative,?\s+District (\d+)$", r"State House - District \1"),
        (r"^State Representative District (\d+)$", r"State House - District \1"),
        (r"^Associate Justice of the Alabama Supreme Court,? Place (\d+)$", r"Alabama Supreme Court - Place \1"),
        (r"^Alabama Court of Civil Appeals Place (\d+)$", r"Alabama Court of Civil Appeals - Place \1"),
        (r"^Alabama Court of Criminal Appeals Place (\d+)$", r"Alabama Court of Criminal Appeals - Place \1"),
        (r"^Circuit Judge Circuit (\d+),? Place (\d+)$", r"Circuit Judge - Circuit \1, Place \2"),
        (
            r"^Circuit Court Judge,?\s+(\d+)(?:ST|ND|RD|TH)? Judicial Circuit,?\s+Place (\d+)$",
            r"Circuit Judge - Circuit \1, Place \2",
        ),
        (r"^District Judge ([A-Za-z ]+),? Place (\d+)$", r"District Judge - \1 County, Place \2"),
        (
            r"^District Court Judge,?\s+([A-Za-z ]+?) County,?\s+Place(?: No\.)? (\d+)$",
            r"District Judge - \1 County, Place \2",
        ),
    )
    for pattern, replacement in patterns:
        if re.fullmatch(pattern, value, flags=re.IGNORECASE):
            return re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    return value


def is_core_certification_office(office_title: str) -> bool:
    """Limit statewide certifications to federal/state seats and state courts."""
    if office_title in {
        "U.S. Senate",
        "Governor",
        "Lieutenant Governor",
        "Attorney General",
        "Secretary of State",
        "State Treasurer",
        "State Auditor",
        "Commissioner of Agriculture & Industries",
    }:
        return True
    return office_title.startswith((
        "U.S. House - District ",
        "State Senate - District ",
        "State House - District ",
        "State Board of Education - District ",
        "Public Service Commissioner - Place ",
        "Alabama Supreme Court - Place ",
        "Alabama Court of Civil Appeals - Place ",
        "Alabama Court of Criminal Appeals - Place ",
        "Circuit Judge - Circuit ",
        "District Judge - ",
    ))


def certification_party(label: str) -> str:
    """Return the party code named by a candidate-certification link label."""
    lowered = (label or "").lower()
    for name, code in (("democratic", "DEM"), ("republican", "REP"), ("independent", "IND")):
        if name in lowered:
            return code
    return ""


def certification_geography_scope(office_title: str) -> str:
    """Infer the narrowest scope supported by the office title."""
    lowered = (office_title or "").lower()
    if any(marker in lowered for marker in (
        "state senate - district",
        "state house - district",
        "state board of education - district",
    )):
        return "state_legislative_district"
    if "circuit judge - circuit" in lowered or "district judge - " in lowered:
        return "judicial_district"
    if " - district " in lowered:
        return "district"
    return "statewide"


def select_candidate_certification_links(document_links: list[dict]) -> list[dict]:
    """Select the last linked candidate-certification version for each party.

    The SOS year page lists original and amended/state certifications in
    publication order. Later eligible links supersede earlier links for that
    party; results, ballot measures, and sample ballots are excluded.
    """
    selected: dict[str, dict] = {}
    for link in document_links:
        label = " ".join(str(link.get("label", "")).split())
        lowered = label.lower()
        if "candidate" not in lowered or "certif" not in lowered or "result" in lowered:
            continue
        party = certification_party(label)
        if not party:
            continue
        selected[party] = {**link, "party": party}
    return list(selected.values())


def normalize_office_title(office: str, district: str, place: str = "") -> str:
    """
    E.g. ("State Senator", "27") -> "State Senate - District 27", matching
    the cross-state convention used by integrations.pa_sos and
    integrations.mi_sos.

    State Board of Education (office id 39) has 8 elected districts and
    Public Service Commissioner (office ids 31/32) is elected statewide by
    "Place" -- both need their district/place folded into the title, or
    every district/place collapses into a single race via ingest_race's
    canonical key (office_title + ocd_division_id + race_type).
    """
    office = (office or "").strip()
    district = (district or "").strip()
    place = (place or "").strip()
    title = _OFFICE_TITLE_OVERRIDES.get(office, office)

    if title == "State Senator":
        return f"State Senate - District {district}" if district else "State Senate"
    if title == "State Representative":
        return f"State House - District {district}" if district else "State House"
    if title == "State Board of Education":
        return f"State Board of Education - District {district}" if district else "State Board of Education"
    if title == "Public Service Commissioner":
        return f"Public Service Commissioner - Place {place}" if place else "Public Service Commissioner"
    return title


def geography_scope(office_title: str) -> str:
    """
    Districted state-legislative-style offices normalize their title to
    "... - District {N}" (State Senate, State House, State Board of
    Education); anything else -- including Public Service Commissioner,
    which is elected statewide at-large by "Place" rather than by a
    sub-state jurisdiction -- is statewide.
    """
    if " - district" in office_title.lower():
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
