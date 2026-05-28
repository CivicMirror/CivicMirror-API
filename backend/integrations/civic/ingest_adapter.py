"""Bridge Civic payloads into the aggregation ingest service."""
from datetime import date

from aggregation import ingest
from elections.models import Election
from .mappers import (
    map_contest_to_race_defaults, map_candidate_defaults,
    parse_jurisdiction_level, parse_state_from_ocd, infer_election_status,
)


def infer_election_type(name: str) -> str:
    lowered = (name or "").lower()
    if "primary" in lowered:
        return Election.ElectionType.PRIMARY
    if "general" in lowered:
        return Election.ElectionType.GENERAL
    if "special" in lowered:
        return Election.ElectionType.SPECIAL
    if "municipal" in lowered:
        return Election.ElectionType.MUNICIPAL
    return Election.ElectionType.OTHER


def ingest_civic_election(payload: dict):
    election_date = payload["election_date"]
    if isinstance(election_date, str):
        election_date = date.fromisoformat(election_date)
    ocd = payload.get("ocd_division_id", "")
    identity = {
        "state": parse_state_from_ocd(ocd),
        "election_type": infer_election_type(payload["name"]),
        "election_date": election_date,
        "jurisdiction_level": parse_jurisdiction_level(ocd),
    }
    fields = {"name": payload["name"], "status": infer_election_status(election_date)}
    return ingest.ingest_election(
        source="civic_api", source_id=str(payload["source_id"]),
        identity=identity, fields=fields,
    )
