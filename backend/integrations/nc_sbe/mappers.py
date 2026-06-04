"""
Static helpers and normalization for the NC SBE integration.

Election type heuristic:
    November     → general
    March / May  → primary
    everything else → special

This covers:
    - General elections (November)
    - State primaries (historically March, occasionally May for runoffs)
    - Municipal/special elections (varied dates)

Contest type codes from the TSV:
    S — Statewide (state legislative, federal, judicial)
    C — County/City (county commissioner, mayor, school board, etc.)

Write-in detection: "Write-In" anywhere in the Choice string (case-insensitive).
"""
from __future__ import annotations

import datetime


def election_type_from_date(d: datetime.date) -> str:
    if d.month == 11:
        return "general"
    if d.month in (3, 5):
        return "primary"
    return "special"


def election_name(d: datetime.date) -> str:
    etype = election_type_from_date(d)
    label = {
        "general": "General Election",
        "primary": "Primary Election",
        "special": "Special Election",
    }[etype]
    return f"{d.year} North Carolina {label} ({d.strftime('%B %-d')})"


def geography_scope(contest_type_code: str) -> str:
    """Map NC contest type code to canonical geography_scope string."""
    return "statewide" if contest_type_code.upper() == "S" else "local"


def is_write_in(choice: str) -> bool:
    return "write-in" in choice.lower()
