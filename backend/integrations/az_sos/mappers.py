"""
Static data and normalization helpers for the AZ SOS integration.

AZ_ELECTIONS:
    Hard-coded election records. Source: AZ HB2022, signed 2026-02-06.
    The primary was moved from "first Tuesday in August" to
    "second-to-last Tuesday in July". Do not derive from a formula.

normalize_contest_name:
    Canonical race name shared by Stage 1 (CandidateList) and Stage 2
    (Results XML). Both callers MUST use this function so the join works.

    Real source strings confirmed from 2024 Primary XML and live CandidateList:

    XML:  'U.S. Representative in Congress - District No. 1 (DEM)'
    List: 'U.S. House of Rep. - District 1'
    → canonical: 'U.S. House - District 1'

    XML:  'State Senator - District No.  1 (DEM)'   ← double space
    List: 'State Senator - District 1'
    → canonical: 'State Senator - District 1'

    Party suffixes found in XML: (DEM), (REP), (GRN), (LIB), (NOL), (NPA), (IND)
"""
from __future__ import annotations

import re
from datetime import date

# ---------------------------------------------------------------------------
# Election records
# ---------------------------------------------------------------------------

AZ_ELECTIONS: list[dict] = [
    {
        "name": "2026 Arizona Primary Election",
        "election_type": "primary",
        "election_date": date(2026, 7, 21),
        "source_id": "az_sos_2026_primary",
    },
    {
        "name": "2026 Arizona General Election",
        "election_type": "general",
        "election_date": date(2026, 11, 3),
        "source_id": "az_sos_2026_general",
    },
]

# ---------------------------------------------------------------------------
# Party abbreviation
# ---------------------------------------------------------------------------

_PARTY_MAP: dict[str, str] = {
    "democratic": "DEM",
    "republican": "REP",
    "libertarian": "LIB",
    "green": "GRN",
    "no labels": "NOL",     # AZ XML uses (NOL) not (NL)
    "non-partisan": "NPA",  # AZ XML uses (NPA) not (NP)
    "nonpartisan": "NPA",
    "independent": "IND",
    "american independent": "AIP",
}


def party_abbrev(party_name: str) -> str:
    return _PARTY_MAP.get(party_name.lower().strip(), party_name.upper()[:4])


# ---------------------------------------------------------------------------
# Contest name normalization
# ---------------------------------------------------------------------------

# Explicit allowlist of known AZ party suffixes — avoids matching Roman numerals,
# state abbreviations, or other 2–4 uppercase parentheticals.
_PARTY_SUFFIX_RE = re.compile(
    r"\s*\((DEM|REP|GRN|LIB|IND|NP|NL|NOL|NPA|AIP|OTH|NON)\)\s*$"
)

# "District No.  1" or "District No. 12" (single or double space before number)
# Handles the double space present in every AZ XML state legislative contest name.
_DISTRICT_NO_RE = re.compile(r"\bDistrict\s+No\.?\s+(\d+)\b")

# Both "U.S. Representative in Congress" (XML) and "U.S. House of Rep." (CandidateList)
# normalize to "U.S. House". The optional " - " after is consumed to avoid double dash.
_US_HOUSE_RE = re.compile(
    r"U\.S\.\s+(?:Representative\s+in\s+Congress|House\s+of\s+Rep\.)\s*-?\s*",
    re.IGNORECASE,
)


def normalize_contest_name(raw: str) -> str:
    """
    Return a canonical race name usable as a join key between Stage 1 races
    and Stage 2 XML results. Must be called on strings from both sources.

    Transformations (in order):
    1. Strip trailing party suffix from the explicit allowlist.
    2. Normalize "District No. X" / "District No.  X" → "District X".
    3. Normalize US House variants → "U.S. House - District X".
    4. Collapse internal whitespace.
    """
    name = _PARTY_SUFFIX_RE.sub("", raw).strip()
    name = _DISTRICT_NO_RE.sub(lambda m: f"District {m.group(1)}", name)
    name = _US_HOUSE_RE.sub("U.S. House - ", name)
    name = " ".join(name.split())
    return name


# ---------------------------------------------------------------------------
# Geography scope
# ---------------------------------------------------------------------------

def geography_scope(branch: str) -> str:
    """Map a CandidateList branch name to a Race.geography_scope value."""
    if "FEDERAL" in branch:
        return "congressional_district"
    if "CITY" in branch:
        return "city"
    if "COUNTY" in branch:
        return "county"
    if "EXECUTIVE" in branch:
        return "statewide"
    # STATE - LEGISLATIVE
    return "state_legislative_district"


# ---------------------------------------------------------------------------
# Candidate name normalization
# ---------------------------------------------------------------------------

_WRITE_IN_LABEL = "(Write-In)"
_GENERIC_WRITE_IN = "write-in"


def normalize_candidate_name(xml_name: str) -> tuple[str | None, bool]:
    """
    Convert an XML choiceName to (First Last form, is_write_in).

    XML stores names as "Last, First" (e.g. "Gallego, Ruben").
    Stage 1 stores names as "First Last" (e.g. "Ruben Gallego").
    The task runner matches ResultRow.candidate_name against Candidate.name
    by string equality, so this inversion is required for results to attach.

    Returns:
        (None, True)          — generic write-in aggregate ("Write-In")
                                result attaches at race level, not a candidate
        ("First Last", True)  — named write-in ("Flores, Alex (Write-In)")
        ("First Last", False) — regular candidate ("Gallego, Ruben")

    Name reversal is best-effort: multi-word first names, suffixes, and
    nicknames may cause mismatches. The task runner logs unmatched candidates
    as PARTIAL_RESULTS — they do not silently disappear.
    """
    is_write_in = _WRITE_IN_LABEL in xml_name
    name = xml_name.replace(_WRITE_IN_LABEL, "").strip()

    if name.lower() == _GENERIC_WRITE_IN:
        return None, True

    if "," in name:
        last, _, first = name.partition(",")
        name = f"{first.strip()} {last.strip()}".strip()

    return name or None, is_write_in
