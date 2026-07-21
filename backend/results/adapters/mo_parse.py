"""
Parser for Missouri SOS's "Grand Totals" certified-results PDF text.

MO has no results API and is not on Clarity — results are published as a
text-based PDF (confirmed not a scanned image; pdfplumber extracts real
text). The report is a flat, repeated-block structure per contest:

    {Office} ({N} of {M} Precincts Reported)
    {Candidate Name} {Party} {Votes} {Pct}%
    ...
    Total Votes {N}

Unlike MD, MO's Grand Totals report lists each write-in filer individually
by name with their own vote count — there is no single collapsed
"Write-In" aggregate row, so no write-in-specific aggregation is needed
here (each row already has result_type="official", is_write_in_aggregate
always False).

Judicial-retention and ballot-measure contests share a different row shape
("{Candidate/Measure} Yes Votes {N} {Pct}%" / "No {Votes} {N} {Pct}%") and
are NOT handled by this parser — they are filtered out entirely by the
office_allowlist, since this build only recognizes statewide candidate
contest office names.
"""
from __future__ import annotations

import re

from .base import ResultRow

_HEADER_RE = re.compile(r'^(?P<office>.+?)\s+\((?P<reported>\d+) of (?P<total>\d+) Precincts Reported\)$')
_CANDIDATE_RE = re.compile(r'^(?P<name>.+?)\s+(?P<party>[A-Za-z][A-Za-z\-]*)\s+(?P<votes>[\d,]+)\s+(?P<pct>[\d.]+)%$')
_TOTAL_RE = re.compile(r'^Total Votes [\d,]+$')


def parse_grand_totals_text(text: str, office_allowlist: frozenset[str]) -> list[ResultRow]:
    rows: list[ResultRow] = []
    current_office: str | None = None
    in_scope = False

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        header_match = _HEADER_RE.match(line)
        if header_match:
            current_office = header_match.group("office")
            in_scope = current_office in office_allowlist
            continue

        if not in_scope:
            continue

        if _TOTAL_RE.match(line):
            continue

        candidate_match = _CANDIDATE_RE.match(line)
        if not candidate_match:
            continue

        vote_count = int(candidate_match.group("votes").replace(",", ""))
        rows.append(
            ResultRow(
                candidate_name=candidate_match.group("name"),
                option_label=None,
                vote_count=vote_count,
                vote_pct=float(candidate_match.group("pct")),
                is_winner=None,
                result_type="official",
                office_title=current_office,
                is_write_in_aggregate=False,
                raw={"party": candidate_match.group("party")},
            )
        )

    return rows
