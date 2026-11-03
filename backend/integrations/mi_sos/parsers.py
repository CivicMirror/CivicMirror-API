from __future__ import annotations

import csv
import io
import re
from typing import Any

from bs4 import BeautifulSoup

_DATE_RE = re.compile(r"(?P<date>\d{1,2}/\d{1,2}/\d{4})")
_STATUS_CODES = {"", "DISQ", "WITHD"}
_PARTY_LABELS = {"DEMOCRATIC", "REPUBLICAN", "LIBERTARIAN", "GREEN", "NONPARTISAN", "NON-PARTISAN"}


def parse_mvic_elections(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    select = soup.find("select", id=lambda value: value and "ElectionDateId" in value)
    if select is None:
        select = soup.find("select", attrs={"name": lambda value: value and "ElectionDateId" in value})
    if select is None:
        return []

    elections: list[dict[str, str]] = []
    for option in select.find_all("option"):
        election_id = (option.get("value") or "").strip()
        label = option.get_text(" ", strip=True)
        if not election_id or not label:
            continue
        match = _DATE_RE.search(label)
        date_text = match.group("date") if match else ""
        name = label.replace(date_text, "").strip(" -") if date_text else label
        elections.append({
            "election_id": election_id,
            "date": date_text,
            "name": name,
            "type": name,
        })
    return elections


# Header label -> output field. The BOE report's column order differs between the
# primary and general listings (the general one has a combined "Party / Incumbent"
# column and no address), so columns are located by header text rather than by a
# fixed index. Hardcoded indices silently dropped every partisan row of the Nov 3,
# 2026 general listing: index 3 held "Democratic Party", which failed the status
# check, so only non-partisan (judicial) offices survived.
_HEADER_FIELDS = {
    "status": "status",
    "party": "party",
    "incumbent": "incumbent",
    "party / incumbent": "party_or_incumbent",
    "party/incumbent": "party_or_incumbent",
    "candidate name": "candidate_name",
    "candidate address": "candidate_address",
    "filed on": "filed_on",
    "filing method": "filing_method",
}
_INCUMBENT_LABEL = "INCUMBENT"


def _squash(value: str) -> str:
    """Collapse whitespace, including the non-breaking spaces the BOE emits in tickets."""
    return " ".join((value or "").split())


def _direct_cells(tr) -> list[str]:
    """
    Cell text for this row only, never from a table nested inside it.

    The live report nests the whole listing inside a one-cell layout table, so a
    recursive search returns every cell in the document (~10,000) for the outer
    row, which defeats every row-shape heuristic below.
    """
    return [_squash(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"], recursive=False)]


def _is_header(cells: list[str]) -> bool:
    lowered = {cell.lower() for cell in cells}
    return "candidate name" in lowered and "filed on" in lowered


def _report_rows(soup) -> list[list[str]]:
    """Rows of the innermost table that carries the report header, else every row."""
    for table in reversed(soup.find_all("table")):
        rows = [cells for cells in (_direct_cells(tr) for tr in table.find_all("tr")) if cells]
        if any(_is_header(cells) for cells in rows):
            return rows
    return [cells for cells in (_direct_cells(tr) for tr in soup.find_all("tr")) if cells]


def parse_boe_candidate_listing(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")

    current_office = ""
    columns: dict[int, str] = {}
    candidates: list[dict[str, str]] = []
    for cells in _report_rows(soup):
        non_empty = [cell for cell in cells if cell]
        joined = " ".join(non_empty)
        if _is_header(cells):
            columns = {
                index: _HEADER_FIELDS[cell.lower()]
                for index, cell in enumerate(cells)
                if cell.lower() in _HEADER_FIELDS
            }
            continue
        if len(non_empty) == 1 and "candidate" not in joined.lower():
            current_office = non_empty[0]
            continue
        if not current_office or not columns:
            continue

        row = {field: cells[index] for index, field in columns.items() if index < len(cells)}
        if row.get("status", "") not in _STATUS_CODES:
            continue
        candidate_name = row.get("candidate_name", "")
        if not candidate_name:
            continue

        # One column may carry either a party name or the literal "INCUMBENT":
        # non-partisan offices have no party, partisan ones no incumbent marker.
        party = row.get("party", "")
        incumbent = row.get("incumbent", "")
        combined = row.get("party_or_incumbent", "")
        if combined:
            if combined.upper() == _INCUMBENT_LABEL:
                incumbent = combined
            else:
                party = combined

        candidates.append({
            "office_title": current_office,
            "party": party,
            "incumbent": incumbent,
            "filing_method": row.get("filing_method", ""),
            "status": row.get("status", ""),
            "candidate_name": candidate_name,
            "candidate_address": row.get("candidate_address", ""),
            "filed_on": row.get("filed_on", ""),
        })
    return candidates


def parse_mvic_result_file(text: str) -> list[dict[str, Any]]:
    if not (text or "").strip():
        return []

    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,|")
    except csv.Error:
        dialect = csv.excel_tab

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = []
    for record in reader:
        normalized = {
            str(k or "").strip().lower().replace(" ", "_"): (v or "").strip()
            for k, v in record.items()
        }
        contest = normalized.get("contest") or normalized.get("office") or normalized.get("race") or ""
        candidate = normalized.get("candidate") or normalized.get("candidate_name") or ""
        votes = normalized.get("votes") or normalized.get("vote_total") or normalized.get("total_votes") or ""
        if not contest or not candidate or votes == "":
            continue
        rows.append({
            "contest": contest,
            "party": normalized.get("party", ""),
            "candidate_name": candidate,
            "votes": votes.replace(",", ""),
            "vote_pct": (normalized.get("pct") or normalized.get("percent") or normalized.get("vote_pct") or "")
            .replace("%", ""),
            "county": normalized.get("county", ""),
            "raw": normalized,
        })
    return rows


def parse_mvic_county_results_html(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows = []
    current_contest = ""
    current_party = ""

    for line in lines:
        upper = line.upper()
        if " POSITION" in upper or " TERM " in upper:
            current_contest = line
            current_party = ""
            continue
        if upper in _PARTY_LABELS:
            current_party = line
            continue
        match = re.match(r"^(?P<name>.+?)\s{2,}(?P<votes>[\d,]+)\s{2,}(?P<pct>[\d.]+)%?$", line)
        if current_contest and match:
            rows.append({
                "contest": current_contest,
                "party": current_party,
                "candidate_name": match.group("name").strip(),
                "votes": match.group("votes").replace(",", ""),
                "vote_pct": match.group("pct"),
                "county": "",
                "raw": {"source": "mvic_html", "line": line},
            })
    return rows
