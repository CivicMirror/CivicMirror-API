"""
Parsers for Minnesota Secretary of State election-results file formats.

Confirmed live 2026-07-13 against the Nov 5, 2024 general election
(ersElectionId=170) — see
docs/superpowers/specs/2026-07-13-mn-adapter-design.md.
"""
from __future__ import annotations

from bs4 import BeautifulSoup


def parse_file_index(html: str) -> list[dict]:
    """
    Parse the "Downloadable Text Files" index page into {label, url} pairs.

    Confirmed structure: <a class="downloadlink" href="...">Label Text</a>.
    Includes every listed file, in scope or not — callers filter via
    mappers.is_in_scope_file.
    """
    soup = BeautifulSoup(html, "html.parser")
    files = []
    for link in soup.select("a.downloadlink"):
        url = link.get("href", "").strip()
        label = link.get_text(strip=True)
        if url and label:
            files.append({"label": label, "url": url})
    return files


_RESULT_FIELDS = (
    "state", "county_id", "precinct_name", "office_id", "office_name",
    "district", "candidate_order_code", "candidate_name", "suffix",
    "incumbent_code", "party", "precincts_reporting", "total_precincts",
    "candidate_votes", "candidate_pct", "total_office_votes",
)

_CANDIDATE_FIELDS = (
    "candidate_id", "candidate_name", "office_id", "office_title",
    "county_id", "order_code", "party",
)


def _parse_semicolon_rows(text: str, field_names: tuple[str, ...]) -> list[dict]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(";")
        if len(parts) != len(field_names):
            continue
        rows.append(dict(zip(field_names, parts)))
    return rows


def parse_result_file(text: str) -> list[dict]:
    """
    Parse a MN SOS results file (16-field positional, semicolon-delimited).
    Confirmed live: these files are already aggregated to the file's stated
    granularity (statewide or by-district) — no precinct-summing needed.
    """
    return _parse_semicolon_rows(text, _RESULT_FIELDS)


def parse_candidate_table(text: str) -> list[dict]:
    """Parse cand.txt (7-field positional, semicolon-delimited)."""
    return _parse_semicolon_rows(text, _CANDIDATE_FIELDS)
