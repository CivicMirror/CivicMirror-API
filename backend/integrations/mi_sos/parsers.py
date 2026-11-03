from __future__ import annotations

import csv
import io
import re
from typing import Any

from bs4 import BeautifulSoup

_DATE_RE = re.compile(r"(?P<date>\d{1,2}/\d{1,2}/\d{4})")
_STATUS_CODES = {"", "DISQ", "WITHD"}


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


# MVIC's bulk result file ("<year><TYPE>_MI_CENR_BY_COUNTY.txt") is tab-delimited, but
# it is not a bare CSV: line 1 is a preamble ("TOTAL VOTER TURNOUT: 97,057,730"), line 2
# the header, and the last line a trailer ("RECORDS: 6108\tRESULTS: OFFICIAL"). Feeding
# the whole file to csv.DictReader takes the preamble as the header and yields nothing
# usable, and every column name differs from the ones the previous implementation looked
# for — it searched for "contest"/"candidate"/"votes" against OfficeDescription,
# CandidateLastName and CandidateVotes. Verified 2026-11-02 against the real
# 2024 general (6,109 lines) and 2026 primary (2,538 lines) files.
_TSV_HEADER_MARKER = "OfficeDescription"
_TSV_TRAILER_PREFIX = "RECORDS:"
_RESULTS_STATUS_RE = re.compile(r"RESULTS:\s*(?P<status>[A-Za-z]+)")
_COL_OFFICE = "OfficeDescription"
_COL_COUNTY = "CountyName"
_COL_PARTY = "PartyDescription"
_COL_LAST = "CandidateLastName"
_COL_FIRST = "CandidateFirstName"
_COL_MIDDLE = "CandidateMiddleName"
_COL_VOTES = "CandidateVotes"
_COL_WRITE_IN = "WriteIn(W)/Uncommitted(Z)"
# The header says W/Z; the files actually carry "Y". Party is also set to WRITE-IN on
# those rows, so either signal identifies them.
_WRITE_IN_FLAG = "Y"
_WRITE_IN_PARTY = "WRITE-IN"


def _result_file_body(text: str) -> list[str]:
    """The header line and data lines, with the preamble and trailer removed."""
    lines = (text or "").splitlines()
    header_index = next(
        (i for i, line in enumerate(lines) if _TSV_HEADER_MARKER in line),
        None,
    )
    if header_index is None:
        return []
    body = [
        line for line in lines[header_index:]
        if line.strip() and not line.startswith(_TSV_TRAILER_PREFIX)
    ]
    return body


def parse_mvic_result_status(text: str) -> str:
    """
    "official" or "unofficial", from the file's own trailer.

    MVIC states this explicitly ("RESULTS: OFFICIAL"), which most sources never do —
    results.tasks only certifies a race when every row is official, so reading it here
    keeps election-night returns out of results_certified. Unknown or missing is
    treated as unofficial.
    """
    for line in reversed((text or "").splitlines()):
        if line.startswith(_TSV_TRAILER_PREFIX):
            match = _RESULTS_STATUS_RE.search(line)
            if match and match.group("status").upper() == "OFFICIAL":
                return "official"
            return "unofficial"
    return "unofficial"


def _mvic_candidate_name(record: dict) -> str:
    """"Last, First Middle" — the shape the BOE candidate listing also uses."""
    last = _squash(record.get(_COL_LAST) or "")
    given = _squash(" ".join(
        part for part in (record.get(_COL_FIRST) or "", record.get(_COL_MIDDLE) or "") if part
    ))
    if last and given:
        return f"{last}, {given}"
    return last or given


def parse_mvic_result_file(text: str) -> list[dict[str, Any]]:
    """
    Per-county rows plus a contest-total row per candidate.

    The file reports only county splits. results.winners derives winners from
    contest-total rows (jurisdiction_fragment == "") and deliberately refuses to sum
    sub-jurisdiction rows itself, because fragments can overlap in general. Michigan's
    83 counties partition the state exactly, so summing them here is safe and is the
    only way these results yield a winner.
    """
    body = _result_file_body(text)
    if not body:
        return []

    reader = csv.DictReader(io.StringIO("\n".join(body)), delimiter="\t")
    county_rows: list[dict[str, Any]] = []
    totals: dict[tuple, dict[str, Any]] = {}

    for record in reader:
        contest = _squash(record.get(_COL_OFFICE) or "")
        candidate_name = _mvic_candidate_name(record)
        votes_raw = (record.get(_COL_VOTES) or "").strip().replace(",", "")
        if not contest or not candidate_name or not votes_raw:
            continue
        try:
            votes = int(votes_raw)
        except ValueError:
            continue

        party = _squash(record.get(_COL_PARTY) or "")
        county = _squash(record.get(_COL_COUNTY) or "")
        write_in = (
            (record.get(_COL_WRITE_IN) or "").strip().upper() == _WRITE_IN_FLAG
            or party.upper() == _WRITE_IN_PARTY
        )

        shared = {
            "contest": contest,
            "party": party,
            "candidate_name": candidate_name,
            "vote_pct": "",  # the file carries no percentages
            "write_in": write_in,
        }
        county_rows.append({
            **shared,
            "votes": str(votes),
            "county": county,
            "raw": {"source": "mvic_result_file", "county": county, **shared},
        })

        key = (contest, candidate_name, party)
        entry = totals.setdefault(key, {**shared, "votes": 0, "county": ""})
        entry["votes"] += votes

    total_rows = [
        {
            **entry,
            "votes": str(entry["votes"]),
            "raw": {
                "source": "mvic_result_file",
                "aggregated_from": "county",
                **{k: v for k, v in entry.items() if k != "votes"},
            },
        }
        for entry in totals.values()
    ]
    return total_rows + county_rows


# MVIC renders results as a Bootstrap grid inside the "Election Results" tab, not a
# table: each contest is a <div class="row"> with no column children, and each result
# a sibling row of col-md-* cells. The previous implementation flattened the document
# with get_text("\n") and required name, votes and percent on ONE line separated by
# two or more spaces, which is how the hand-written 705 fixture was shaped but not how
# MVIC renders anything — it returned zero rows from the real document (verified
# 2026-11-02 against electionId=706, 867 KB of official Aug 4, 2026 primary results).
_RESULTS_PANE_ID = "tab-target-voteResults"
# Party and contest subtotal rows ("Party Votes:", "Total Votes:") carry the same shape
# as a result row and are marked only by this class on the label cell.
_SUBTOTAL_CLASS = "bold"
_MIN_RESULT_CELLS = 4


def parse_mvic_county_results_html(html: str) -> list[dict[str, Any]]:
    """Per-candidate contest totals from MVIC's vote-records page."""
    soup = BeautifulSoup(html or "", "html.parser")
    pane = soup.find("div", id=_RESULTS_PANE_ID)
    if pane is None:
        return []

    rows: list[dict[str, Any]] = []
    current_contest = ""
    for row in pane.find_all("div", class_="row"):
        cells = row.find_all("div", recursive=False)

        if not cells:
            # A row with no columns is the contest banner.
            title = _squash(row.get_text(" ", strip=True))
            if title:
                current_contest = title
            continue

        if not current_contest or len(cells) < _MIN_RESULT_CELLS:
            continue
        if _SUBTOTAL_CLASS in (cells[1].get("class") or []):
            continue

        party = _squash(cells[0].get_text(" ", strip=True))
        candidate_name = _squash(cells[1].get_text(" ", strip=True))
        votes = _squash(cells[2].get_text(" ", strip=True)).replace(",", "")
        vote_pct = _squash(cells[3].get_text(" ", strip=True)).replace("%", "")
        if not candidate_name or not votes:
            continue

        rows.append({
            "contest": current_contest,
            "party": party,
            "candidate_name": candidate_name,
            "votes": votes,
            "vote_pct": vote_pct,
            # This endpoint reports statewide contest totals, not per-county splits, so
            # the rows are contest totals (results.tasks keys those on an empty fragment).
            "county": "",
            "raw": {
                "source": "mvic_county_records",
                "contest": current_contest,
                "party": party,
                "candidate_name": candidate_name,
                "votes": votes,
                "vote_pct": vote_pct,
            },
        })
    return rows
