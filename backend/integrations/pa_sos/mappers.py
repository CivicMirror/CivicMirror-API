"""
Static mapping and normalization helpers for the PA Voter Services Candidate Database.
"""
from __future__ import annotations

import re
from datetime import date

# ---------------------------------------------------------------------------
# Election Specs
# ---------------------------------------------------------------------------

PA_ELECTIONS = [
    {
        "name": "2026 Pennsylvania Primary Election",
        "election_type": "primary",
        "election_date": date(2026, 5, 19),
        "source_id": "pa_sos_2026_primary",
        "db_dropdown_value": 153,
    },
    {
        "name": "2026 Pennsylvania General Election",
        "election_type": "general",
        "election_date": date(2026, 11, 3),
        "source_id": "pa_sos_2026_general",
        "db_dropdown_value": 160,
    },
]

# ---------------------------------------------------------------------------
# Party Normalization
# ---------------------------------------------------------------------------

_PARTY_MAP: dict[str, str] = {
    "democratic": "DEM",
    "republican": "REP",
    "green": "GRN",
    "libertarian": "LIB",
    "non-partisan": "NPA",
    "nonpartisan": "NPA",
    "independent": "IND",
}


def party_abbrev(party_name: str) -> str:
    """Normalize full party name to standard 3-letter abbreviation."""
    return _PARTY_MAP.get(party_name.lower().strip(), party_name.upper()[:3])


# ---------------------------------------------------------------------------
# Race / Office Normalization
# ---------------------------------------------------------------------------

def normalize_contest_name(office: str, district: str) -> str:
    """
    Return a canonical race name shared by Stage 1 and Stage 2 results.
    E.g.:
      "REPRESENTATIVE IN THE GENERAL ASSEMBLY", "55th Legislative District" -> "State House - District 55"
      "GOVERNOR ", "Statewide" -> "Governor"
    """
    off = office.strip().upper()
    dist = district.strip()

    # Extract district number
    dist_num = ""
    m = re.search(r"(\d+)", dist)
    if m:
        dist_num = m.group(1)

    if "LIEUTENANT GOVERNOR" in off:
        return "Lieutenant Governor"
    if "GOVERNOR" in off:
        return "Governor"
    elif "REPRESENTATIVE IN CONGRESS" in off:
        return f"U.S. House - District {dist_num}" if dist_num else "U.S. House"
    elif "REPRESENTATIVE IN THE GENERAL ASSEMBLY" in off:
        return f"State House - District {dist_num}" if dist_num else "State House"
    elif "SENATOR IN THE GENERAL ASSEMBLY" in off:
        return f"State Senate - District {dist_num}" if dist_num else "State Senate"

    # Fallback
    if dist and dist.lower() != "statewide":
        return f"{office.strip()} - {dist}"
    return office.strip()


# ---------------------------------------------------------------------------
# Geography / Scope Mapping
# ---------------------------------------------------------------------------

def geography_scope(office_title: str) -> str:
    """Map normalized office title to geography_scope value."""
    title = office_title.lower()
    if "state house" in title or "state senate" in title:
        return "state_legislative_district"
    if "u.s. house" in title or "representative in congress" in title:
        return "congressional_district"
    return "statewide"
