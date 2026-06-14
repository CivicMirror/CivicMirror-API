"""
Mappers for VoteWA public API data → CivicMirror model fields.
"""
from __future__ import annotations

from datetime import date, datetime

from elections.models import Candidate, Election, Race


def _get_text(names: list, lang: str = "en") -> str:
    """Extract display text from a VoteWA multilingual name list."""
    for n in names:
        if n.get("languageId") == lang:
            return (n.get("text") or "").strip()
    return ((names[0].get("text") or "").strip()) if names else ""


def normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def parse_election_date(meta: dict) -> date | None:
    raw = meta.get("electionDate")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


def parse_election_date_from_slug(slug: str) -> date | None:
    """Parse a yyyymmdd slug into a date."""
    try:
        return datetime.strptime(slug, "%Y%m%d").date()
    except (ValueError, TypeError):
        return None


def infer_election_type(election_date: date) -> str:
    if election_date.month == 11:
        return Election.ElectionType.GENERAL
    if election_date.month in {8, 9}:
        return Election.ElectionType.PRIMARY
    return Election.ElectionType.SPECIAL


def infer_election_status(election_date: date) -> str:
    from django.utils import timezone as tz
    today = tz.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def map_election(slug: str, meta: dict) -> dict:
    """
    Map VoteWA election metadata → Election model field values.

    slug:  yyyymmdd route key, e.g. "20260428"
    meta:  response from GET /api/elections/washington/{slug}
    """
    election_date = parse_election_date(meta) or parse_election_date_from_slug(slug)
    election_type = infer_election_type(election_date) if election_date else Election.ElectionType.OTHER

    date_label = election_date.strftime("%Y %B %-d") if election_date else slug
    name = meta.get("electionName") or f"Washington {date_label} Election"

    return {
        "source_id": f"wa_votewa:{slug}",
        "name": name,
        "election_date": election_date,
        "election_type": election_type,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "WA",
        "status": infer_election_status(election_date) if election_date else Election.Status.UPCOMING,
        "source_metadata": {
            "enr_slug": slug,
            "votewa_jurisdiction_slug": "washington",
            "is_official_results": meta.get("isOfficialResults", False),
        },
    }


def map_race(
    election_obj,
    ballot_item: dict,
    jurisdiction_slug: str = "washington",
) -> dict:
    """
    Map a VoteWA ballotItems[] entry → Race model field values.

    jurisdiction_slug: "washington" for state-level items;
                       "{county}-county-wa" for county-local items.
    """
    contest_type = ballot_item.get("contestType", "Candidate")
    office_title = _get_text(ballot_item.get("name") or [])
    ballot_item_id = ballot_item.get("id", "")
    parent_ballot_item_id = ballot_item.get("parentId") or ballot_item.get("parentBallotItemId")

    race_type = (
        Race.RaceType.MEASURE
        if contest_type == "BallotMeasure"
        else Race.RaceType.CANDIDATE
    )

    certification_status = (
        Race.CertificationStatus.UPCOMING
        if election_obj.status in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_PENDING
    )

    is_county = jurisdiction_slug != "washington"
    if is_county:
        jurisdiction = jurisdiction_slug.replace("-wa", "").replace("-", " ").title()
        geography_scope = "county"
    else:
        jurisdiction = "Washington"
        geography_scope = "statewide"

    enr_slug = (election_obj.source_metadata or {}).get("enr_slug", "")

    return {
        "race_type": race_type,
        "office_title": office_title,
        "normalized_office_title": normalize(office_title),
        "jurisdiction": jurisdiction,
        "geography_scope": geography_scope,
        "certification_status": certification_status,
        "source": Race.Source.WA_VOTEWA,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": (
            Race.VoteMethod.YES_NO
            if race_type == Race.RaceType.MEASURE
            else Race.VoteMethod.SINGLE_CHOICE
        ),
        "max_selections": 1,
        "ocd_division_id": "",
        "source_metadata": {
            "votewa_ballot_item_id": ballot_item_id,
            "votewa_parent_ballot_item_id": parent_ballot_item_id,
            "votewa_jurisdiction_slug": jurisdiction_slug,
            "enr_slug": enr_slug,
            "contest_type": contest_type,
        },
    }


def map_candidate(ballot_option: dict) -> dict:
    """Map a VoteWA ballotOptions[] entry → Candidate model field values."""
    party_data = ballot_option.get("party") or {}
    party_abbr = party_data.get("abbreviation", "")
    party_name_raw = party_data.get("name", "")
    if isinstance(party_name_raw, list):
        party_name = _get_text(party_name_raw)
    else:
        party_name = party_name_raw if isinstance(party_name_raw, str) else ""

    return {
        "party": party_name or party_abbr,
        "incumbent": False,
        "candidate_status": Candidate.CandidateStatus.RUNNING,
        "source_metadata": {
            "votewa_native_id": ballot_option.get("nativeId"),
            "party_abbreviation": party_abbr,
            "is_write_in": bool(ballot_option.get("isWriteIn", False)),
        },
    }


def map_measure_option(ballot_option: dict) -> dict:
    """Map a VoteWA ballotOptions[] entry for a BallotMeasure → MeasureOption field values."""
    return {
        "option_label": (
            _get_text(ballot_option.get("name") or []) or ballot_option.get("nativeId", "")
        ),
        "source_metadata": {
            "votewa_native_id": ballot_option.get("nativeId"),
        },
    }
