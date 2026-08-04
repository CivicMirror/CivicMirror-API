"""
Stage 1 mappers for the MD SBE integration.

Source: consolidated {PREFIX}{yy}_statewide_candidatelist.csv, confirmed
2026-08-04 to carry every in-scope office in one file (585 rows for the
2026 primary cycle) — see docs/state-research/MD/MD-Election_Research.md
Rank 2 and the plan's "Live-Verified Source Facts" section.

Full Core scope for this wave (per ADR-005/COVERAGE-CLARIFICATION, same
convention as NC/KY/VT): federal + state legislative + state executive
offices only. Judicial (Judge of the Circuit Court, appellate retention)
and all county/local/municipal offices are out of scope.
"""
from __future__ import annotations

import csv
import io

IN_SCOPE_OFFICES: frozenset[str] = frozenset({
    "Governor / Lt. Governor",
    "Attorney General",
    "Comptroller",
    "U.S. Senator",
    "Representative in Congress",
    "State Senator",
    "House of Delegates",
})


def is_in_scope_office(office_name: str) -> bool:
    return (office_name or "").strip() in IN_SCOPE_OFFICES


def parse_statewide_candidate_csv(csv_text: str) -> list[dict]:
    """Parse the consolidated statewide candidate-list CSV into row dicts.

    Maps by header name (csv.DictReader), never by column position — MD's
    schema has drifted between cycles before.
    """
    # Strip UTF-8 BOM if present (MD's exports include it)
    if csv_text.startswith('﻿'):
        csv_text = csv_text[1:]
    reader = csv.DictReader(io.StringIO(csv_text))
    return [dict(row) for row in reader]


def group_candidate_rows(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Group candidate rows by (Office Name, district). One group = one race."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        key = (
            (row.get("Office Name") or "").strip(),
            (row.get("Contest Run By District Name and Number") or "").strip(),
        )
        groups.setdefault(key, []).append(row)
    return groups


def map_race_identity(office_name: str, district: str) -> tuple[dict, dict]:
    """
    Return (identity, fields) for aggregation.ingest.ingest_race, from one
    (office_name, district) group of statewide candidate-list rows.
    """
    from elections.models import Race

    office_name = (office_name or "").strip()
    district = (district or "").strip()
    is_statewide = district == "State Of Maryland" or district == ""
    office_title = office_name if is_statewide else f"{office_name} - {district}"
    variant = f"md:{office_name}:{district}"

    identity = {
        "office_title": office_title,
        "ocd_division_id": "",
        "race_type": Race.RaceType.CANDIDATE,
        "contest_variant": variant,
    }
    fields = {
        "office_title": office_title,
        "jurisdiction": "Maryland",
        "geography_scope": "statewide" if is_statewide else "district",
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "source": Race.Source.MD_SBE,
        "source_metadata": {
            "provider": "md_sbe",
            "office_name": office_name,
            "district": district,
            "contest_variant": variant,
        },
    }
    return identity, fields


def candidate_display_name(row: dict) -> str:
    """
    Build the ballot display name. Governor/Lt. Governor rows combine the
    primary candidate and their running mate into one "A / B" line — there
    is no ticket/running_mate field on the Candidate model, so this is the
    single Candidate row's name for that race. Both individual names are
    preserved separately in map_candidate's source_metadata for provenance.
    """
    last = (row.get("Candidate Ballot Last Name and Suffix") or "").strip()
    first = (row.get("Candidate First Name and Middle Name") or "").strip()
    primary_name = f"{first} {last}".strip()

    has_related = (row.get("Has Related Candidate") or "").strip().lower() == "yes"
    if not has_related:
        return primary_name

    related_last = (row.get("Related Candidate Last Name and Suffix") or "").strip()
    related_first = (row.get("Related Candidate First Name and Middle Name") or "").strip()
    related_name = f"{related_first} {related_last}".strip()
    if not related_name:
        return primary_name
    return f"{primary_name} / {related_name}"


def map_candidate(row: dict) -> dict:
    """Map a statewide candidate-list CSV row to Candidate model fields."""
    from elections.models import Candidate

    status_raw = (row.get("Candidate Status") or "").strip()
    status_map = {
        "active": Candidate.CandidateStatus.RUNNING,
        "withdrawn": Candidate.CandidateStatus.WITHDRAWN,
        "disqualified": Candidate.CandidateStatus.DISQUALIFIED,
    }
    candidate_status = status_map.get(status_raw.lower(), Candidate.CandidateStatus.RUNNING)

    return {
        "candidate_status": candidate_status,
        "source_metadata": {
            "provider": "md_sbe",
            "md_status": status_raw,
            "filing": (row.get("Filing Type and Date") or "").strip(),
            "related_candidate_last_name": (row.get("Related Candidate Last Name and Suffix") or "").strip(),
            "related_candidate_first_name": (row.get("Related Candidate First Name and Middle Name") or "").strip(),
        },
    }
