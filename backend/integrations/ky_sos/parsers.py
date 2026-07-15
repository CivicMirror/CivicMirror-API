"""
HTML parsers for the Kentucky SOS Candidate Filings application
(web.sos.ky.gov/CandidateFilings/).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

_OFFICE_LINK_RE = re.compile(r"^Default\.aspx\?id=(\d+)$")
_COUNT_RE = re.compile(r"\((\d+)\)\s*$")


def parse_current_election(html: str) -> dict:
    """Extract {value, label} for the currently-selected election dropdown option."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find(id="ctl00_MainContent_ddlElection")
    if not select:
        return {}
    option = select.find("option", selected=True) or select.find("option")
    if not option:
        return {}
    return {"value": option.get("value", ""), "label": option.get_text(strip=True)}


def parse_office_directory(html: str) -> list[dict]:
    """Extract {office_id, label, count} for every office group in the directory."""
    soup = BeautifulSoup(html, "html.parser")
    offices = []
    for a in soup.find_all("a", href=_OFFICE_LINK_RE):
        match = _OFFICE_LINK_RE.match(a["href"])
        office_id = int(match.group(1))
        text = a.get_text(strip=True)
        count_match = _COUNT_RE.search(text)
        count = int(count_match.group(1)) if count_match else 0
        label = _COUNT_RE.sub("", text).strip()
        offices.append({"office_id": office_id, "label": label, "count": count})
    return offices


def parse_candidate_rows(html: str) -> list[dict]:
    """
    Extract candidate rows from an office-group results table (active office
    pages have 6 columns ending in Date Filed; the withdrawn group has 5
    columns with no Date Filed).
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for body in soup.select("div.cf-office-body"):
        table = body.find("table")
        if not table:
            continue
        trs = table.find_all("tr")[1:]  # skip header row
        for tr in trs:
            cells = tr.find_all("td")
            if len(cells) < 5:
                continue
            name_link = cells[0].find("a")
            name = name_link.get_text(strip=True) if name_link else cells[0].get_text(strip=True)
            office = cells[2].get_text(strip=True)
            district_link = cells[3].find("a")
            district = district_link.get_text(strip=True) if district_link else ""
            party = cells[4].get_text(strip=True)
            date_filed = cells[5].get_text(strip=True) if len(cells) >= 6 else ""
            rows.append({
                "name": name,
                "office": office,
                "district": district,
                "party": party,
                "date_filed": date_filed,
            })
    return rows
