"""
Stage 1 mappers for the UT elections integration.

Source: the Candidate Filing Excel workbook (single sheet, hand-formatted
into sections — see docs/state-research/UT/UT-Election_Research.md and the
plan's "Live-Verified Source Facts" section). Each section is: a title row
(single non-empty cell in column A), a blank row, a
"Candidate | Office | Party | Status" sub-header row, then data rows, then a
blank row before the next section.

Full Core scope for this wave (per ADR-005/COVERAGE-CLARIFICATION, same
convention as MD/NC/VT): federal + state legislative + state executive
offices only. State School Board and State Judicial (judicial retention
questions — not office/district/party/candidate-shaped) are out of scope.
"""
from __future__ import annotations

import io

import openpyxl

IN_SCOPE_SECTIONS: frozenset[str] = frozenset({
    "Federal Offices",
    "State Offices",
    "State Senate",
    "State House",
})


def is_in_scope_section(section: str) -> bool:
    return (section or "").strip() in IN_SCOPE_SECTIONS


def parse_candidate_filing_workbook(content: bytes) -> list[dict]:
    """
    Parse the sectioned Candidate Filing workbook into row dicts, already
    filtered to in-scope sections (is_in_scope_section). Section headers and
    sub-header rows are consumed as parser state, not emitted as data.
    """
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    ws = wb.active

    section: str | None = None
    rows: list[dict] = []

    for raw_row in ws.iter_rows(values_only=True):
        cells = list(raw_row[:4]) + [None] * max(0, 4 - len(raw_row))
        a, b, c, d = cells[:4]
        a = a.strip() if isinstance(a, str) else a

        if a and not b and not c and not d:
            # Section-title row, e.g. "Federal Offices". The very first
            # non-empty-A-only row is the workbook's own top banner
            # ("Federal Offices | State Offices | ..."), which never matches
            # a real section title and is harmlessly overwritten by the next
            # real section row before any data row is seen.
            section = a
            continue

        if a == "Candidate" and b == "Office":
            continue  # sub-header row within an office section
        if a == "Judicial Retention" and b == "Status":
            continue  # sub-header row within the judicial section (out of scope anyway)

        if not a or section is None:
            continue  # blank row

        if not is_in_scope_section(section):
            continue

        rows.append({
            "section": section,
            "name": a,
            "office": (b or "").strip() if isinstance(b, str) else (b or ""),
            "party": (c or "").strip() if isinstance(c, str) else (c or ""),
            "status": (d or "").strip() if isinstance(d, str) else (d or ""),
        })

    return rows


def titlecase_name(raw: str) -> str:
    """
    Best-effort display-name casing for the source's ALL-CAPS candidate
    names. Python's str.title() handles ordinary names and apostrophe names
    ("O'Dell") correctly but does not special-case Mc/Mac surnames
    ("MCADAMS" -> "Mcadams", not "McAdams") — accepted as a known
    display-quality limitation; no name dictionary is available to fix it.
    """
    return (raw or "").strip().title()


# Statuses observed live 2026-08-05 (post-primary): "Election Candidate",
# "Out in Convention", "Out in Primary", "Withdrew", "Disqualified".
# "Primary" and "Filed" are documented in the research doc as earlier-stage
# statuses (pre-primary) not observed in this snapshot; mapped here from the
# state's own documented status vocabulary. "Out in Convention"/"Out in
# Primary" mean the candidate lost a party process and never reached any
# public ballot — modeled as WITHDRAWN (closest fit in the 4-value
# CandidateStatus enum; there is no distinct "eliminated" status).
_CANDIDATE_STATUS_MAP: dict[str, str] = {
    "election candidate": "running",
    "primary": "running",
    "withdrew": "withdrawn",
    "out in convention": "withdrawn",
    "out in primary": "withdrawn",
    "disqualified": "disqualified",
}
# "Filed" is the earliest pre-viability stage (declared but not yet advanced
# past any qualification step) — skip these rows entirely rather than
# creating a Candidate record for someone who never reached a ballot.
_SKIP_STATUSES: frozenset[str] = frozenset({"filed"})


def candidate_status_for(status_raw: str) -> str | None:
    """
    Map a raw filing status to a Candidate.CandidateStatus value.
    Returns None to signal the row should be skipped entirely (Filed only).
    Unknown/future statuses default to "running" (least-destructive default,
    same convention used by every other state adapter's status mapping).
    """
    key = (status_raw or "").strip().lower()
    if key in _SKIP_STATUSES:
        return None
    return _CANDIDATE_STATUS_MAP.get(key, "running")


def map_race_identity(office: str) -> tuple[dict, dict]:
    """
    Return (identity, fields) for aggregation.ingest.ingest_race, from one
    Office cell value. Utah's workbook already stores the full contest name
    (office + district, when applicable) in a single cell — no split is
    needed, unlike Maryland's separate office/district columns.
    """
    from elections.models import Race

    office_title = (office or "").strip()
    is_district = "district" in office_title.lower()
    variant = f"ut:{office_title}"

    identity = {
        "office_title": office_title,
        "ocd_division_id": "",
        "race_type": Race.RaceType.CANDIDATE,
        "contest_variant": variant,
    }
    fields = {
        "office_title": office_title,
        "jurisdiction": "Utah",
        "geography_scope": "district" if is_district else "statewide",
        "vote_method": Race.VoteMethod.SINGLE_CHOICE,
        "max_selections": 1,
        "source": Race.Source.UT_ELECTIONS,
        "source_metadata": {
            "provider": "ut_elections",
            "office": office_title,
            "contest_variant": variant,
        },
    }
    return identity, fields


def map_candidate(row: dict) -> dict | None:
    """
    Map a parsed candidate-filing row to Candidate model fields, or None if
    the row's status means "never reached a ballot" (see candidate_status_for).
    """
    status_raw = (row.get("status") or "").strip()
    candidate_status = candidate_status_for(status_raw)
    if candidate_status is None:
        return None

    return {
        "candidate_status": candidate_status,
        "source_metadata": {
            "provider": "ut_elections",
            "ut_status": status_raw,
        },
    }
