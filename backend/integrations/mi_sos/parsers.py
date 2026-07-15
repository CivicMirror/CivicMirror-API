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


def parse_boe_candidate_listing(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    table_rows = []
    for tr in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
        if cells:
            table_rows.append(cells)

    current_office = ""
    candidates: list[dict[str, str]] = []
    for cells in table_rows:
        non_empty = [cell for cell in cells if cell]
        joined = " ".join(non_empty)
        if len(non_empty) == 1 and "candidate" not in joined.lower():
            current_office = non_empty[0]
            continue
        if "Candidate Name" in joined and "Filed On" in joined:
            continue
        if not current_office or len(cells) < 7:
            continue

        status = cells[3].strip() if len(cells) > 3 else ""
        if status not in _STATUS_CODES:
            continue
        candidate_name = cells[4].strip() if len(cells) > 4 else ""
        if not candidate_name:
            continue
        candidates.append({
            "office_title": current_office,
            "party": cells[0].strip(),
            "incumbent": cells[1].strip(),
            "filing_method": cells[2].strip(),
            "status": status,
            "candidate_name": candidate_name,
            "candidate_address": cells[5].strip() if len(cells) > 5 else "",
            "filed_on": cells[6].strip() if len(cells) > 6 else "",
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
