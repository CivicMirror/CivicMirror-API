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
