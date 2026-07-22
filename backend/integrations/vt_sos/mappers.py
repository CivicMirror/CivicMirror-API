"""
Mappers for Vermont SOS static-JSON election data -> CivicMirror model fields.

See docs/state-research/VT/VT-Creation-Pipeline-Review.md for the full field
reference this is built from.
"""
from __future__ import annotations

import datetime

from elections.models import Candidate, Election, Race

# Vermont election-type codes -> CivicMirror Election.ElectionType.
_ELECTION_TYPE_MAP = {
    "P": "primary",
    "PP": "primary",
    "G": "general",
    "L": "municipal",
    "LS": "special",
}

# Categories fetched for Phase 1 (statewide only; town/local deferred).
CORE_CATEGORIES = ("federal", "stateWide", "senate", "house", "county")

# Aggregate write-in placeholder — never created as a Candidate row.
_OTHER_WRITE_IN_CID = 0


def map_election_type(raw_type_code: str) -> str:
    return _ELECTION_TYPE_MAP.get((raw_type_code or "").upper(), "other")


def parse_election_date(raw_date: str) -> datetime.date | None:
    """Vermont dates are ISO datetimes, e.g. '2026-08-11T00:00:00'."""
    if not raw_date:
        return None
    try:
        return datetime.date.fromisoformat(raw_date[:10])
    except ValueError:
        return None


def infer_election_status(election_date: datetime.date, is_official: bool) -> str:
    if is_official:
        return Election.Status.RESULTS_CERTIFIED
    today = datetime.date.today()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def map_election_identity(election_index_row: dict) -> tuple[dict, dict]:
    """
    Return (identity, fields) for aggregation.ingest.ingest_election, from
    one row of elections/elections.json.
    """
    election_guid = election_index_row["electionGuid"]
    election_date = parse_election_date(election_index_row.get("electionDate"))
    election_type = map_election_type(election_index_row.get("electionTypeCode"))
    is_official = bool(election_index_row.get("isOfficial", False))

    identity = {
        "state": "VT",
        "election_type": election_type,
        "election_date": election_date,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
    }
    fields = {
        "name": (election_index_row.get("electionName") or "").strip(),
        "status": infer_election_status(election_date, is_official) if election_date else Election.Status.UPCOMING,
        "results_url": f"https://static.electionresults.vermont.gov/elections/{election_guid}.json",
        "source_metadata": {
            "election_guid": election_guid,
            "election_type_code": election_index_row.get("electionTypeCode", ""),
            "election_category_code": election_index_row.get("electionCategoryCode", ""),
            "is_statewide": bool(election_index_row.get("isStateWideElection", False)),
            "is_general": bool(election_index_row.get("isGeneralElection", False)),
            "is_sync": bool(election_index_row.get("isSync", False)),
            "is_official": is_official,
            "provider": "Vermont SOS election results static feed",
        },
    }
    return identity, fields


def build_election_source_id(election_guid: str) -> str:
    return f"vt_sos_{election_guid}"


def contest_variant_key(category: str, party_code: str, office_id, district_code: str = "") -> str:
    """
    vt:{category}:{party-code-or-all}:{office-id}:{district-code-or-statewide}

    This is the source-supplied disambiguator threaded through
    aggregation.identity.race_canonical_key's optional contest_variant
    parameter (see aggregation/identity.py) — without it, Vermont's
    per-party primary ballots for the same office (same oid) would
    collapse into a single Race.
    """
    party = (party_code or "all").strip() or "all"
    district = (district_code or "statewide").strip() or "statewide"
    return f"vt:{category}:{party}:{office_id}:{district}"


def map_race_identity(
    category: str,
    contest: dict,
    party_code: str,
    district_code: str = "",
    district_name: str = "",
) -> tuple[dict, dict]:
    """
    Return (identity, fields) for aggregation.ingest.ingest_race, from one
    contest object in a category's party wrapper (contest["o"][i]).
    """
    office_id = contest.get("oid")
    office_title = (contest.get("on") or "").strip()
    vote_for = contest.get("vf") or 1

    variant = contest_variant_key(category, party_code, office_id, district_code)

    identity = {
        "office_title": office_title,
        "ocd_division_id": "",
        "race_type": Race.RaceType.CANDIDATE,
        "contest_variant": variant,
    }
    fields = {
        "office_title": office_title,
        "jurisdiction": "Vermont",
        "geography_scope": "district" if district_code else "statewide",
        "vote_method": Race.VoteMethod.MULTI_SEAT if vote_for > 1 else Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": max(1, vote_for),
        "ballot_type": party_code or "",
        "source": Race.Source.VT_SOS,
        "location_name": district_name or "",
        "source_metadata": {
            "provider": "vt_sos",
            "category": category,
            "party_code": party_code or "",
            "office_id": office_id,
            "office_type_code": contest.get("otc", ""),
            "district_code": district_code or "",
            "district_name": district_name or "",
            "vote_for": vote_for,
            "contest_variant": variant,
            # results/tasks.py::_race_source_identity() matches ResultRow.raw
            # against these two keys to route result rows to the correct
            # Race; contest_code = the same variant used for the canonical
            # key, so it's already unique per (category, party, office,
            # district) — see results/adapters/vt.py.
            "contest_code": variant,
        },
    }
    return identity, fields


def iter_named_candidates(contest: dict):
    """
    Collect the union of a contest's cs[].rc and cs[].wc rows, deduplicated
    by candidate source ID, skipping the OTHER WRITE-IN aggregate (cid=0).
    Per contest, not per reporting-unit row — candidate identity is the same
    across every town/district cs row, so the first occurrence is enough.
    """
    seen: dict[int, dict] = {}
    for cs_row in contest.get("cs") or []:
        for cand in list(cs_row.get("rc") or []) + list(cs_row.get("wc") or []):
            cid = cand.get("cid")
            if cid is None or cid == _OTHER_WRITE_IN_CID:
                continue
            if cid not in seen:
                seen[cid] = cand
    return list(seen.values())


def map_candidate(raw_candidate: dict) -> dict:
    """Map a source candidate row (rc[]/wc[] entry) to Candidate model fields."""
    is_write_in = bool(raw_candidate.get("isWriteIn", False))
    return {
        "candidate_status": (
            Candidate.CandidateStatus.WRITE_IN if is_write_in else Candidate.CandidateStatus.RUNNING
        ),
        "source_metadata": {
            "provider": "vt_sos",
            "candidate_id": raw_candidate.get("cid"),
            "party_color": raw_candidate.get("pco", ""),
            "is_write_in": is_write_in,
        },
    }
