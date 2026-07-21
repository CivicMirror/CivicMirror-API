from __future__ import annotations

import csv
import io


def _clean(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch >= " " or ch == "\t").strip()


def _parse_int(value: str | None) -> int:
    cleaned = _clean(value).replace(",", "")
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        return 0


def parse_county_results_csv(csv_text: str) -> list[dict]:
    """Parse one MD SBE {cycle}{yy}_{county}CountyResults.csv into row dicts.

    Each row already represents a county-level total (no precinct summing
    needed) — see docs/state-research/MD/MD-Election_Research.md's
    "CountyResults schema" section.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []
    for raw_row in reader:
        office_name = _clean(raw_row.get("Office Name"))
        candidate_name = _clean(raw_row.get("Candidate Name"))
        if not office_name or not candidate_name:
            continue
        rows.append({
            "office_name": office_name,
            "candidate_name": candidate_name,
            "party": _clean(raw_row.get("Party")),
            "is_winner": _clean(raw_row.get("Winner")).upper() == "Y",
            "is_write_in": _clean(raw_row.get("Write-In?")).upper() == "Y",
            "total_votes": _parse_int(raw_row.get("Total Votes")),
        })
    return rows
