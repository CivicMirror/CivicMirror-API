"""
Mappers for SC VREMS data → CivicMirror model fields.
"""
from datetime import date, datetime, timezone

from elections.models import Candidate, Election, Race

# ----------------------------------------------------------------------------
# Election-level helpers
# ----------------------------------------------------------------------------

_FEDERAL_KEYWORDS = {"u.s.", "congress", "us house", "u.s. house", "u.s. senate", "us senate"}


def is_referendum(election: dict) -> bool:
    """True when filingPeriodBeginDate is null — VREMS marks referendums this way."""
    return election.get("filingPeriodBeginDate") is None


def is_filing_open(election: dict) -> bool:
    """True when the filing period has started AND the election has not yet passed."""
    begin = election.get("filingPeriodBeginDate")
    if begin is None:
        return True  # referendum — will return 0 rows from CandidateSearch naturally

    # Skip elections whose date has already passed — no point re-syncing daily.
    election_date_str = election.get("electionDate")
    if election_date_str:
        try:
            elec_date = date.fromisoformat(str(election_date_str)[:10])
            if elec_date < date.today():
                return False
        except (ValueError, TypeError):
            pass

    try:
        filing_dt = datetime.fromisoformat(begin).replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= filing_dt
    except (ValueError, TypeError):
        return True  # assume open if unparseable


def is_primary_election(election_name: str) -> bool:
    return "primary" in election_name.lower()


def map_jurisdiction_level(election_type: str, election_name: str) -> str:
    name_lower = election_name.lower()
    if any(kw in name_lower for kw in _FEDERAL_KEYWORDS):
        return Election.JurisdictionLevel.NATIONAL
    if election_type == "Local":
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


def map_election(vrems_election: dict) -> dict:
    """Map a VREMS election dict to Election model field values."""
    election_date_raw = vrems_election["electionDate"]
    if isinstance(election_date_raw, str):
        election_date = date.fromisoformat(election_date_raw[:10])
    else:
        election_date = election_date_raw

    election_type = vrems_election.get("electionType", "General")
    election_name = vrems_election.get("electionName", "")

    return {
        "source_id": f"vrems_sc_{vrems_election['electionId']}",
        "name": vrems_election.get("displayName") or election_name,
        "election_date": election_date,
        "jurisdiction_level": map_jurisdiction_level(election_type, election_name),
        "state": "SC",
        "status": infer_election_status(election_date),
    }


# ----------------------------------------------------------------------------
# Race-level helpers
# ----------------------------------------------------------------------------

def normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def build_race_groups(election: dict, candidates: list[dict]) -> list[dict]:
    """
    Group candidate rows into race records.

    For primary elections: partition by (office, filing_location, associated_counties, party)
    so Republican and Democratic primaries are tracked as separate races.

    For general/special elections: partition by (office, filing_location, associated_counties)
    so all parties competing for the same seat are in one race.
    """
    primary = is_primary_election(election.get("electionName", ""))
    groups: dict[tuple, dict] = {}

    for c in candidates:
        office = c["office"].strip()
        filing_loc = c["filing_location"].strip()
        counties = c["associated_counties"].strip()
        party = c["party"].strip() if primary else ""
        key = (office, filing_loc, counties, party)

        if key not in groups:
            groups[key] = {
                "office": office,
                "filing_location": filing_loc,
                "associated_counties": counties,
                "party_group": party,
                "candidates": [],
            }
        groups[key]["candidates"].append(c)

    return list(groups.values())


def build_canonical_key(election_source_id: str, office: str, filing_location: str,
                        associated_counties: str, party_group: str) -> str:
    parts = [
        "sc_vrems",
        election_source_id,
        normalize(office),
        normalize(filing_location),
        normalize(associated_counties) or "statewide",
        normalize(party_group) or "nonpartisan",
    ]
    return ":".join(parts)


def map_race(election_obj: Election, race_group: dict) -> dict:
    """Map a race group to Race model field values."""
    office = race_group["office"]
    filing_location = race_group["filing_location"]
    counties = race_group["associated_counties"]
    party_group = race_group["party_group"]

    jurisdiction = counties if counties else filing_location if filing_location else "South Carolina"

    geography_scope = "statewide" if not counties and (not filing_location or filing_location.lower() == "state") else "local"

    certification_status = (
        Race.CertificationStatus.UPCOMING
        if election_obj.status in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_PENDING
    )

    return {
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office,
        "jurisdiction": jurisdiction,
        "geography_scope": geography_scope,
        "certification_status": certification_status,
        "source": Race.Source.SC_VREMS,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "normalized_office_title": normalize(office),
        "canonical_key": build_canonical_key(
            election_obj.source_id, office, filing_location, counties, party_group
        ),
        "source_metadata": {
            "vrems_election_id": election_obj.source_id,
            "filing_location": filing_location,
            "associated_counties": counties,
            "party_group": party_group,
        },
    }


# ----------------------------------------------------------------------------
# Candidate-level helpers
# ----------------------------------------------------------------------------

_WITHDRAWN_STATUSES = {"withdrew before primary"}
_DISQUALIFIED_STATUSES = {
    "decertified before primary",
    "disqualified before primary",
    "not certified for primary",
}


def map_candidate_status(vrems_status: str) -> str:
    normalized = vrems_status.strip().lower()
    if normalized in _WITHDRAWN_STATUSES:
        return Candidate.CandidateStatus.WITHDRAWN
    if normalized in _DISQUALIFIED_STATUSES:
        return Candidate.CandidateStatus.DISQUALIFIED
    # Active, Elected, Defeated In Primary, Defeated in Election all map to RUNNING;
    # raw outcome is preserved in source_metadata.
    return Candidate.CandidateStatus.RUNNING


def map_candidate(vrems_candidate: dict) -> dict:
    """Map a VREMS candidate row to Candidate model field values."""
    return {
        "party": vrems_candidate.get("party", ""),
        "incumbent": False,
        "candidate_status": map_candidate_status(vrems_candidate.get("status", "")),
        "source_metadata": {
            "vrems_candidate_id": vrems_candidate.get("candidate_id"),
            "vrems_detail_id": vrems_candidate.get("candidate_detail_id"),
            "vrems_status": vrems_candidate.get("status", ""),
            "running_mate": vrems_candidate.get("running_mate", ""),
        },
    }
