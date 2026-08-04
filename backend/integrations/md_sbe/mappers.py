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
