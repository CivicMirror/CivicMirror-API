"""
Mappers for Massachusetts SOS data → CivicMirror model fields.

All functions are pure (no DB access) and receive plain Python dicts/primitives.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from elections.models import Candidate, Election, Race

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FEDERAL_OFFICE_KEYWORDS = {
    "u.s. house", "u.s. senate", "president",
    "house of representatives", "united states senate",
}

_STATE_OFFICE_KEYWORDS = {
    "governor", "state senate", "state representative",
    "lieutenant governor", "attorney general", "secretary of state",
    "treasurer", "auditor", "governor's council", "district attorney",
    "sheriff", "register of deeds", "county commissioner",
}

_STAGE_TO_TYPE = {
    "general": "general",
    "primaries": "primary",
    "democratic": "primary",
    "republican": "primary",
    "green-rainbow": "primary",
    "libertarian": "primary",
    "working families": "primary",
    "united independent": "primary",
    "american": "primary",
    "independent voters": "primary",
}

# Per-party stage slugs -> the canonical party label, in the same vocabulary
# electionstats already uses in general-election CSV party rows ("Democratic",
# "Republican", "Unenrolled", ...). Deliberately excludes "general"/"primaries"
# — those aren't a party, so party lookup for those stages returns "".
_STAGE_TO_PARTY_LABEL = {
    "democratic": "Democratic",
    "republican": "Republican",
    "green-rainbow": "Green-Rainbow",
    "libertarian": "Libertarian",
    "working families": "Working Families",
    "united independent": "United Independent",
    "american": "American",
    "independent voters": "Independent Voters",
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def infer_election_type(stage: str) -> str:
    """
    Map electionstats stage string to Election.ElectionType.

    "General" → "general"
    "Democratic" / "Republican" / etc. → "primary"
    Contains "Special" → "special"
    "Primaries" → "primary"
    """
    if not stage:
        return "general"
    lower = stage.lower()
    if "special" in lower:
        return "special"
    return _STAGE_TO_TYPE.get(lower, "general")


def party_label_from_stage(stage: str) -> str:
    """
    Map a per-party stage slug ("Democratic", "Republican", ...) to its
    canonical party label. Returns "" for non-party stages (General,
    Primaries) — there's no party to derive there.
    """
    return _STAGE_TO_PARTY_LABEL.get((stage or "").strip().lower(), "")


def contest_variant_key(office: str, district: str, stage: str) -> str:
    """
    Disambiguator threaded into aggregation.identity.race_canonical_key's
    optional contest_variant parameter.

    Without it, a partisan primary's Democratic and Republican contests for
    the same office/date collapse into a single Race (same election_type,
    date, office, and OCD) — see issue #105. Returns "" for non-party stages
    (General, generic Primaries) so those races are unaffected — this mirrors
    the vt_sos/nc_sbe/ny_boe contest_variant pattern.
    """
    party = party_label_from_stage(stage)
    if not party:
        return ""
    return f"ma:{normalize(office)}:{normalize(district) or 'statewide'}:{party.lower()}"


def infer_jurisdiction_level(office: str) -> str:
    """
    Infer Election.JurisdictionLevel from office string.

    Returns "national" for federal offices, "state" for state-level, "local" otherwise.
    """
    lower = normalize(office)
    for kw in _FEDERAL_OFFICE_KEYWORDS:
        if kw in lower:
            return Election.JurisdictionLevel.NATIONAL
    for kw in _STATE_OFFICE_KEYWORDS:
        if kw in lower:
            return Election.JurisdictionLevel.STATE
    return Election.JurisdictionLevel.LOCAL


def infer_geography_scope(office: str, district: str = "") -> str:
    """
    Infer Race.geography_scope from office/district strings.

    "statewide" if no district; "federal" for federal races; "district" otherwise.
    """
    lower = normalize(office)
    for kw in _FEDERAL_OFFICE_KEYWORDS:
        if kw in lower:
            return "federal"
    if not district or normalize(district) in {"statewide", ""}:
        return "statewide"
    return "district"


def infer_election_status(election_date: date | None) -> str:
    from django.utils import timezone as tz
    if not election_date:
        return Election.Status.UPCOMING
    today = tz.localdate()
    if election_date > today:
        return Election.Status.UPCOMING
    if election_date == today:
        return Election.Status.ACTIVE
    return Election.Status.RESULTS_PENDING


def parse_ocpf_date(date_str: str) -> date | None:
    """
    Parse an OCPF date string like "11/5/2024" → date(2024, 11, 5).

    Returns None on failure.
    """
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
    except (ValueError, TypeError):
        return None


def build_canonical_key(election_source_id: str, office: str, district: str) -> str:
    """
    Build canonical key for a MA SOS race.

    Format: ma_sos:{election_source_id}:{normalized_office}:{normalized_district}

    Example: ma_sos:ma_sos_165323:u.s. house:1st congressional
    """
    return f"ma_sos:{election_source_id}:{normalize(office)}:{normalize(district) or 'statewide'}"


# ---------------------------------------------------------------------------
# Election mapper
# ---------------------------------------------------------------------------

def map_election(election_row: dict, schedule: dict) -> dict:
    """
    Map an electionstats election row + OCPF schedule → Election model field values.

    election_row keys: election_id, office, district, stage, year
    schedule keys: primaryElectionDate, generalElectionDate (from OCPF /filingSchedules/{year})

    Returns a dict ready for Election(**...) — does NOT include source_id (caller pops it).
    """
    election_id = election_row["election_id"]
    office = election_row.get("office", "")
    district = election_row.get("district", "")
    stage = election_row.get("stage", "General")
    year = election_row.get("year", 0)

    election_type = infer_election_type(stage)

    # Resolve election date from OCPF schedule
    if election_type == "primary":
        raw_date = schedule.get("primaryElectionDate", "")
    else:
        raw_date = schedule.get("generalElectionDate", "")
    election_date = parse_ocpf_date(raw_date)

    # Build a human-readable name
    parts = [str(year), "MA", office]
    if district:
        parts.append(district)
    if stage.lower() not in {"general", "primaries"}:
        parts.append(stage)
    name = " ".join(p for p in parts if p)

    jurisdiction_level = infer_jurisdiction_level(office)
    status = infer_election_status(election_date)

    return {
        "source_id": f"ma_sos_{election_id}",
        "name": name,
        "election_date": election_date,
        "election_type": election_type,
        "jurisdiction_level": jurisdiction_level,
        "state": "MA",
        "status": status,
        "source_metadata": {
            "electionstats_id": election_id,
            "stage": stage,
        },
    }


# ---------------------------------------------------------------------------
# Race mapper
# ---------------------------------------------------------------------------

def map_race(election_obj: Election, election_row: dict) -> dict:
    """
    Map an electionstats election row → Race model field values.

    Returns a dict that includes "canonical_key" — caller must pop() it and pass
    it separately (bulk_create unique_fields=["canonical_key"] pattern).
    """
    office = election_row.get("office", "")
    district = election_row.get("district", "")
    election_id = election_row["election_id"]

    geography_scope = infer_geography_scope(office, district)

    jurisdiction = district if district else "Statewide"

    cert_status = (
        Race.CertificationStatus.UPCOMING
        if election_obj.status in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_CERTIFIED
    )

    canonical_key = build_canonical_key(election_obj.source_id, office, district)
    stage = election_row.get("stage", "")
    variant = contest_variant_key(office, district, stage)

    return {
        "canonical_key": canonical_key,
        "contest_variant": variant,
        "race_type": Race.RaceType.CANDIDATE,
        "office_title": office,
        "normalized_office_title": normalize(office),
        "jurisdiction": jurisdiction,
        "geography_scope": geography_scope,
        "certification_status": cert_status,
        "source": Race.Source.MA_SOS,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "ocd_division_id": "",
        "source_metadata": {
            "electionstats_id": election_id,
            "party": party_label_from_stage(stage),
            # Consumed by results.tasks._race_source_identity /
            # _row_source_identity to route each party's CSV results to the
            # right Race when a primary is split across multiple Races that
            # share one canonical Election (see contest_variant_key).
            # _process_race_results requires every key present on the race's
            # identity to also match on a result row — so both keys must be
            # set here, and results/adapters/ma.py must tag both onto every
            # row it produces, or a race with a non-empty party_code will
            # never match any row (see results/adapters/ma.py's fetch_results
            # docstring for the incident this caused).
            "contest_code": str(election_id),
            "party_code": party_label_from_stage(stage),
        },
    }


# ---------------------------------------------------------------------------
# Candidate mapper
# ---------------------------------------------------------------------------

def map_candidate(candidate_row: dict, stage: str = "") -> dict:
    """
    Map a parsed CSV candidate row → Candidate model field values.

    candidate_row keys: name, party, col_index

    Primary CSVs (one party per election_id, see contest_variant_key) don't
    carry a party row, so `party` falls back to the election's stage — e.g.
    an election discovered under stage="Republican" implies every candidate
    on its CSV is Republican. General-election CSVs already have `party`
    populated per-column and take precedence.
    """
    party = candidate_row.get("party", "") or party_label_from_stage(stage)
    return {
        "party": party,
        "incumbent": False,
        "candidate_status": Candidate.CandidateStatus.RUNNING,
        "source_metadata": {
            "csv_column_index": candidate_row.get("col_index"),
        },
    }


# ---------------------------------------------------------------------------
# Ballot question mapper
# ---------------------------------------------------------------------------

def map_ballot_question(metadata: dict, election_obj: Election) -> dict:
    """
    Map a parsed BQ metadata dict → Race model field values.

    metadata keys: bq_id, question_number, question, question_alias, summary,
                   is_initiative_petition, is_referendum, is_local, is_county
    """
    bq_id = metadata["bq_id"]
    question_number = metadata.get("question_number", "")
    question_alias = metadata.get("question_alias", "")
    summary = (metadata.get("summary") or "")[:2000]
    question_text = metadata.get("question", "")
    is_local = metadata.get("is_local", False)
    is_county = metadata.get("is_county", False)

    office_title = f"Ballot Question {question_number}" if question_number else "Ballot Question"
    geography_scope = "district" if (is_local or is_county) else "statewide"
    jurisdiction = "Statewide" if not (is_local or is_county) else "Local"

    cert_status = (
        Race.CertificationStatus.UPCOMING
        if election_obj.status in {Election.Status.UPCOMING, Election.Status.ACTIVE}
        else Race.CertificationStatus.RESULTS_CERTIFIED
    )

    return {
        "canonical_key": f"ma_sos:bq_{bq_id}",
        "race_type": Race.RaceType.MEASURE,
        "office_title": office_title,
        "normalized_office_title": normalize(office_title),
        "jurisdiction": jurisdiction,
        "geography_scope": geography_scope,
        "certification_status": cert_status,
        "source": Race.Source.MA_SOS,
        "race_status": Race.RaceStatus.ACTIVE,
        "vote_method": Race.VoteMethod.YES_NO,
        "max_selections": 1,
        "ocd_division_id": "",
        "source_metadata": {
            "electionstats_bq_id": bq_id,
            "question_number": question_number,
            "question_alias": question_alias,
            "summary": summary,
            "is_initiative_petition": metadata.get("is_initiative_petition", False),
            "is_referendum": metadata.get("is_referendum", False),
            "is_local": is_local,
            "full_question_text": question_text,
        },
    }


# ---------------------------------------------------------------------------
# OCPF candidate enrichment mapper
# ---------------------------------------------------------------------------

_OCPF_OFFICE_TO_CHAMBER = {"house": "lower", "senate": "upper"}


def map_ocpf_filer(depository_row: dict, detail: dict) -> dict:
    """
    Map an OCPF legislative-depository row + /filer/{cpfId} detail →
    CandidateMatcher enrichment payload.

    depository_row: from MaSosClient.get_legislative_depository(year) — has
        cpfId, filerName, YTD $ totals.
    detail: from MaSosClient.get_filer_detail(cpfId) — has the candidate's
        legal name, address, office sought (with office type), party, ballot
        tags, and photo. May be {} if the detail fetch failed; depository_row
        alone is still enough to attempt a name/office match, just without
        the office-type chamber signal or address/tags/photo.

    Matching itself needs no new logic in CandidateMatcher — office_sought's
    "House"/"Senate" maps onto the same chamber-branch cross-race matching
    already used for other state-legislature sources (see
    _match_cross_race_from_payload / _match_last_name_cross_race_from_payload).
    """
    from django.utils import timezone as tz

    office_sought = detail.get("officeSought") or {}
    office_description = (office_sought.get("officeDescription") or "").strip().lower()
    chamber = _OCPF_OFFICE_TO_CHAMBER.get(office_description, "")
    district = (office_sought.get("districtDescription") or depository_row.get("officeSought") or "").strip()

    candidate_info = detail.get("candidate") or {}
    full_name = (detail.get("fullName") or "").strip()
    if not full_name:
        # depository_row.filerName is "Last, First" — reverse it for a usable name.
        reversed_name = (depository_row.get("filerName") or "").strip()
        if "," in reversed_name:
            last, _, first = reversed_name.partition(",")
            full_name = f"{first.strip()} {last.strip()}".strip()
        else:
            full_name = reversed_name

    cpf_id = str(detail.get("cpfId") or depository_row.get("cpfId") or "")

    tags = detail.get("tags") or []
    on_ballot = any(t.get("tagTypeDescription") == "On Ballot" for t in tags)
    is_winner = any(t.get("tagTypeDescription") == "Winner" for t in tags)

    return {
        "ocpf_filer_id": cpf_id,
        "name": full_name,
        "family_name": (detail.get("candidateLastName") or "").strip(),
        "state": "MA",
        "chamber": chamber,
        "district": district,
        "party": (detail.get("partyAffiliation") or depository_row.get("partyAffiliation") or "").strip(),
        "contact_office": (candidate_info.get("fullAddress") or "").strip(),
        "image_url": (detail.get("filerPhotoUrl") or "").strip(),
        "source_metadata": {
            "ocpf": {
                "cpf_id": cpf_id,
                "committee_name": detail.get("committeeName") or "",
                "on_ballot": on_ballot,
                "is_winner": is_winner,
                "tags": tags,
                "receipts_ytd": depository_row.get("receiptsYtdNumeric"),
                "expenditures_ytd": depository_row.get("expendituresYtdNumeric"),
                "cash_on_hand": depository_row.get("currentCashOnHandNumeric"),
                "last_synced": tz.now().isoformat(),
            }
        },
    }
