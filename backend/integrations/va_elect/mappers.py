"""
Mappers for Enhanced Voting / Virginia ELECT data → CivicMirror model fields.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from elections.models import Candidate, Election, Race

# ---------------------------------------------------------------------------
# Election-level helpers
# ---------------------------------------------------------------------------

_FEDERAL_OFFICE_KEYWORDS = {
    "u.s. house", "u.s. senate", "house of representatives",
    "united states", "president", "vice president",
}


def normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _get_text(names: list, lang: str = "en") -> str:
    for n in names:
        if n.get("languageId") == lang:
            return (n.get("text") or "").strip()
    return ((names[0].get("text") or "").strip()) if names else ""


def is_primary_slug(slug: str) -> bool:
    return "primary" in slug.lower()


def infer_election_type(slug: str, enr_metadata: dict | None = None) -> str:
    """
    Determine election type from slug — isPrimary in the API is always false.

    Slug patterns:
      primary   → "2025-June-Republican-Primary", "2024_June_Democratic_Primary"
      special   → "2025-September-9-Special"
      general   → "2025-November-General", "2023-Nov-Gen"
    """
    slug_lower = slug.lower()
    if "primary" in slug_lower:
        return "primary"
    if "special" in slug_lower:
        return "special"
    return "general"


def infer_election_status(election_date: date) -> str:
    from django.utils import timezone as tz
    today = tz.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def parse_election_date(meta: dict) -> date | None:
    raw = meta.get("electionDate")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


def map_election(slug: str, meta: dict) -> dict:
    """
    Map Enhanced Voting election metadata → Election model field values.

    slug:  e.g. "2025-November-General"
    meta:  response from GET /api/elections/Virginia/{slug}
    """
    election_date = parse_election_date(meta)
    election_type = infer_election_type(slug)

    # Build a human-readable name from the slug when the API doesn't provide one.
    name = meta.get("electionName") or slug.replace("-", " ").replace("_", " ").title()

    return {
        "source_id": f"va_elect_{slug}",
        "name": name,
        "election_date": election_date,
        "election_type": election_type,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "VA",
        "status": infer_election_status(election_date) if election_date else Election.Status.UPCOMING,
        "source_metadata": {"enr_slug": slug},
    }


# ---------------------------------------------------------------------------
# Race-level helpers
# ---------------------------------------------------------------------------

_FEDERAL_RACE_RE = re.compile(
    r"(u\.s\.|united states|house of representatives|senate|president)",
    re.IGNORECASE,
)


def _is_federal(office_title: str) -> bool:
    return bool(_FEDERAL_RACE_RE.search(office_title))


def _extract_district_label(office_title: str) -> str:
    """
    Extract a district label from office_title for canonical key purposes.

    "Member, House of Delegates (1st District)" → "1st district"
    "Governor"                                   → "statewide"
    "Member, House of Representatives (4th District)" → "4th district"
    """
    m = re.search(r"\(([^)]+)\)", office_title)
    if m:
        return normalize(m.group(1))
    return "statewide"


def build_canonical_key(
    election_source_id: str,
    office_title: str,
    district_label: str,
    contest_type: str,
    party: str = "",
) -> str:
    """
    Canonical key pattern:
      va_elect:{election_source_id}:{office}:{district}:{party}

    For ballot measures, party is omitted (always "nonpartisan").
    """
    parts = [
        "va_elect",
        election_source_id,
        normalize(office_title),
        normalize(district_label) or "statewide",
        normalize(party) or "nonpartisan",
    ]
    return ":".join(parts)


def map_race(election_obj: Election, ballot_item: dict) -> dict:
    """
    Map a single ballotItem from /data → Race model field values.

    Does NOT include 'canonical_key' — caller must pop it from the returned dict
    and pass it as a separate argument to Race(), following the SC VREMS pattern.
    """
    contest_type = ballot_item.get("contestType", "Candidate")
    office_title = _get_text(ballot_item.get("name") or [])
    ballot_item_id = ballot_item.get("id", "")

    district_label = _extract_district_label(office_title)

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

    # Jurisdiction label: use district label for district races, state name for statewide
    jurisdiction = district_label.title() if district_label != "statewide" else "Virginia"

    geography_scope = "statewide" if district_label == "statewide" else "district"
    if _is_federal(office_title):
        geography_scope = "federal"

    referendum_text = ""
    if contest_type == "BallotMeasure":
        referenda = ballot_item.get("referendum") or []
        for ref in referenda:
            if ref.get("languageId") == "en":
                referendum_text = (ref.get("text") or "")[:2000]
                break

    canonical_key = build_canonical_key(
        election_obj.source_id or election_obj.canonical_key or "",
        office_title,
        district_label,
        contest_type,
    )

    return {
        "canonical_key": canonical_key,
        "race_type": race_type,
        "office_title": office_title,
        "normalized_office_title": normalize(office_title),
        "jurisdiction": jurisdiction,
        "geography_scope": geography_scope,
        "certification_status": certification_status,
        "source": Race.Source.VA_ELECT,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.YES_NO if race_type == Race.RaceType.MEASURE else Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "source_metadata": {
            "enr_ballot_item_id": ballot_item_id,
            "enr_slug": (election_obj.source_metadata or {}).get("enr_slug", ""),
            "contest_type": contest_type,
            "reporting_units": ballot_item.get("reportingUnits"),
            "referendum_text": referendum_text or None,
        },
    }


# ---------------------------------------------------------------------------
# Candidate-level helpers
# ---------------------------------------------------------------------------

def map_candidate(ballot_option: dict) -> dict:
    """Map a ballotOptions[] entry to Candidate model field values."""
    party_data = ballot_option.get("party") or {}
    party_abbr_raw = party_data.get("abbreviation", "")
    party_abbr = party_abbr_raw if isinstance(party_abbr_raw, str) else ""
    _party_name_raw = party_data.get("name", "")
    if isinstance(_party_name_raw, list):
        party_name = _get_text(_party_name_raw)
    elif isinstance(_party_name_raw, str):
        party_name = _party_name_raw
    else:
        party_name = ""

    return {
        "party": party_name or party_abbr,
        "incumbent": False,
        "candidate_status": Candidate.CandidateStatus.RUNNING,
        "source_metadata": {
            "enr_native_id": ballot_option.get("nativeId"),
            "party_abbreviation": party_abbr,
            "is_write_in": bool(ballot_option.get("isWriteIn", False)),
        },
    }


def map_measure_option(ballot_option: dict) -> dict:
    """Map a ballotOptions[] entry for a BallotMeasure to MeasureOption field values."""
    return {
        "option_label": _get_text(ballot_option.get("name") or []) or ballot_option.get("nativeId", ""),
        "source_metadata": {
            "enr_native_id": ballot_option.get("nativeId"),
        },
    }
