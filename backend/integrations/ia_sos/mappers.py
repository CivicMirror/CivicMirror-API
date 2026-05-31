"""
Mappers for Iowa SOS data → CivicMirror model fields.
"""
from datetime import date

from elections.models import Candidate, Election, Race

# Federal office keywords for jurisdiction_level detection
_FEDERAL_KEYWORDS = frozenset({
    "u.s.", "u.s. senator", "u.s. representative", "united states",
    "congress", "senate", "representative in congress",
})

# Iowa offices that span the whole state
_STATEWIDE_KEYWORDS = frozenset({
    "governor", "lt. governor", "lieutenant governor",
    "secretary of state", "auditor of state", "treasurer of state",
    "secretary of agriculture", "attorney general",
    "u.s. senator",
})


def normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


# ---------------------------------------------------------------------------
# Election mappers
# ---------------------------------------------------------------------------

def map_jurisdiction_level(election_type: str) -> str:
    if election_type == "municipal":
        return Election.JurisdictionLevel.LOCAL
    return Election.JurisdictionLevel.STATE


def infer_election_status(election_date: date) -> str:
    from django.utils import timezone as tz
    today = tz.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def build_election_source_id(year: int, election_type: str) -> str:
    """e.g. 'ia_sos_2026_primary', 'ia_sos_2025_municipal'"""
    return f"ia_sos_{year}_{election_type}"


def map_election(parsed: dict) -> dict:
    """Map a parsed calendar row to Election model field values."""
    from datetime import date as d
    election_date_raw = parsed["election_date"]
    election_date = (
        d.fromisoformat(election_date_raw)
        if isinstance(election_date_raw, str)
        else election_date_raw
    )

    year = parsed["election_year"]
    election_type = parsed["election_type"]

    return {
        "source_id": build_election_source_id(year, election_type),
        "name": parsed["name"],
        "election_date": election_date,
        "election_type": election_type,
        "jurisdiction_level": map_jurisdiction_level(election_type),
        "state": "IA",
        "status": infer_election_status(election_date),
    }


# ---------------------------------------------------------------------------
# Race / Candidate mappers
# ---------------------------------------------------------------------------

def is_primary_election(election_name: str) -> bool:
    return "primary" in election_name.lower()


def infer_geography_scope(office: str, district: str) -> str:
    office_lower = normalize(office)
    if any(kw in office_lower for kw in _STATEWIDE_KEYWORDS):
        return "statewide"
    if district:
        return "district"
    return "local"


def infer_jurisdiction_for_race(office: str, district: str) -> str:
    if district:
        return district
    office_lower = normalize(office)
    if any(kw in office_lower for kw in _STATEWIDE_KEYWORDS):
        return "Iowa"
    return "Iowa"


def build_race_canonical_key(
    election_source_id: str,
    office: str,
    district: str,
    party_group: str,
) -> str:
    parts = [
        "ia_sos",
        election_source_id,
        normalize(office),
        normalize(district) or "statewide",
        normalize(party_group) or "nonpartisan",
    ]
    return ":".join(parts)


def build_race_groups(election_name: str, candidates: list[dict]) -> list[dict]:
    """
    Group candidate rows into race dicts.

    For primary elections: partition by (office, district, party) so that
    R and D primaries are tracked as separate races.
    For general/other elections: partition by (office, district).
    """
    primary = is_primary_election(election_name)
    groups: dict[tuple, dict] = {}

    for c in candidates:
        office = c["office"].strip()
        district = c["district"].strip()
        party = c["party"].strip() if primary else ""
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

    election_ref = election_obj.source_id or election_obj.canonical_key or ""

    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office,
        "jurisdiction": infer_jurisdiction_for_race(office, district),
        "geography_scope": infer_geography_scope(office, district),
        "certification_status": certification_status,
        "source": Race.Source.IA_SOS,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "normalized_office_title": normalize(office),
        "canonical_key": build_race_canonical_key(
            election_ref, office, district, party_group
        ),
        "source_metadata": {
            "ia_sos_election_id": election_ref,
            "district": district,
            "party_group": party_group,
            "is_federal": is_federal,
        },
    }


def map_candidate(candidate_row: dict) -> dict:
    """Map a parsed candidate row to Candidate model field values."""
    return {
        "party": candidate_row.get("party", ""),
        "incumbent": False,
        "candidate_status": Candidate.CandidateStatus.RUNNING,
        "source_metadata": {
            "ia_sos_office": candidate_row.get("office", ""),
            "ia_sos_district": candidate_row.get("district", ""),
        },
    }
