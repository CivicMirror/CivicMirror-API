"""
Scope classification for Minnesota SOS downloadable files.

Federal + State offices only this build (county/municipal/school/hospital,
ballot questions, and district court deferred — see
docs/superpowers/specs/2026-07-13-mn-adapter-design.md).
"""
from __future__ import annotations

import re

from elections.models import Election, Race

IN_SCOPE_LABELS = frozenset({
    "U.S. President Statewide",
    "U.S. Senator Statewide",
    "U.S. Representative by District",
    "State Senator by District",
    "State Representative by District",
    "Supreme Court and Courts of Appeals Races",
})

# No Governor/state executive file exists in the Nov 2024 general (off-year
# for MN's governor); match by pattern for future gubernatorial cycles.
_GOVERNOR_PATTERN = re.compile(r"^Governor.*\bStatewide\b", re.IGNORECASE)

_WRITE_IN_ORDER_CODE = "9901"


def is_in_scope_file(label: str) -> bool:
    if label in IN_SCOPE_LABELS:
        return True
    return bool(_GOVERNOR_PATTERN.match(label.strip()))


def is_write_in(candidate_order_code: str) -> bool:
    return candidate_order_code == _WRITE_IN_ORDER_CODE


def format_office_title(office_name: str, district: str) -> str:
    office_name = (office_name or "").strip()
    district = (district or "").strip()
    if not office_name:
        return district
    if not district:
        return office_name
    if district in office_name or "district" in office_name.lower():
        return office_name
    return f"{office_name} District {district}"


def map_election(election) -> dict:
    """Map a registered MnElection descriptor to Election model field values."""
    metadata = {"mn_date_path": election.date_path}
    if election.ers_election_id is not None:
        metadata["mn_ers_election_id"] = election.ers_election_id
    return {
        "source_id": election.source_id,
        "name": election.name,
        "election_date": election.election_date,
        "election_type": election.election_type,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "MN",
        "status": election.status,
        "source_metadata": metadata,
    }


def map_race(office_id: str, office_title: str) -> dict:
    """Map an in-scope MN office to Race model field values."""
    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office_title,
        "jurisdiction": "Minnesota",
        "geography_scope": "district" if "District" in office_title else "statewide",
        "certification_status": Race.CertificationStatus.RESULTS_CERTIFIED,
        "source": "mn_sos",
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "normalized_office_title": " ".join(office_title.lower().split()),
        "source_metadata": {"mn_office_id": office_id},
    }


def map_candidate(candidate_row: dict) -> dict:
    """Map a parsed cand.txt row to Candidate model field values."""
    return {
        "party": candidate_row.get("party", ""),
        "incumbent": False,
        "source_metadata": {
            "mn_candidate_id": candidate_row.get("candidate_id", ""),
            "mn_office_id": candidate_row.get("office_id", ""),
        },
    }
