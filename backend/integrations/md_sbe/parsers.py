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
    """Parse one MD SBE per-county results CSV into row dicts.

    Handles both published shapes — the general election's
    {cycle}{yy}_{county}CountyResults.csv and the primary's per-party
    {cycle}{yy}_{county}{Party}Results.csv — which share the same leading
    columns. The primary files omit "Write-In?" and the "* Against" columns
    entirely (verified live 2026-08-04 on GP26_01DemocraticResults.csv), so
    every column is read by header name with a safe default.

    "Office District" MUST be captured: it is the only thing distinguishing
    e.g. House of Delegates district 01A from 01B, and without it every
    district's votes for an office collapse into one bogus statewide row that
    can never match a district-qualified Race. MD renders it zero-padded
    ("01", "01A", "06") while the candidate CSV spells it out ("Legislative
    District 1A") — see mappers.normalize_district_key for the bridge.

    Each row already represents a county-level total (no precinct summing
    needed) — see docs/state-research/MD/MD-Election_Research.md's
    "CountyResults schema" section.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []
    for raw_csv_row in reader:
        # MD pads the last column of some files with a trailing space, so the
        # header parses as "Total Votes " / "Total Votes Against " (verified
        # live 2026-08-04 on GP26_01DemocraticResults.csv). Strip header names
        # before lookup, or every vote total silently reads as 0.
        raw_row = {
            (key or "").strip(): value
            for key, value in raw_csv_row.items()
            if key is not None
        }
        office_name = _clean(raw_row.get("Office Name"))
        candidate_name = _clean(raw_row.get("Candidate Name"))
        if not office_name or not candidate_name:
            continue
        rows.append({
            "office_name": office_name,
            "district": _clean(raw_row.get("Office District")),
            "candidate_name": candidate_name,
            "party": _clean(raw_row.get("Party")),
            "is_winner": _clean(raw_row.get("Winner")).upper() == "Y",
            "is_write_in": _clean(raw_row.get("Write-In?")).upper() == "Y",
            "total_votes": _parse_int(raw_row.get("Total Votes")),
        })
    return rows
