"""
Parsers for New Jersey's election-night-results county table.

NJ has no state-level results aggregator — each of 21 counties publishes
results independently. This page (nj.gov/state/elections/election-night-
results.shtml) lists each county's results URL. Most, but not all, counties
run some flavor of Clarity Elections (ENR Web 4.x) — this module identifies
which.

Confirmed live 2026-07-12: 16 of 21 counties are Clarity-pattern, spread
across three hostnames due to different hosting arrangements:
  - results.enr.clarityelections.com (majority)
  - admin.enr.clarityelections.com (Hudson only, alternate subdomain)
  - www.livevoterturnout.com (Salem only, legacy Clarity branding —
    confirmed same underlying platform via matching asset filenames to
    other states' known Clarity deployments)
The remaining 5 counties (Bergen, Camden, Sussex, Warren, Hunterdon) each
run their own independent site with no common mechanism — out of scope.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

CLARITY_HOSTS: frozenset[str] = frozenset({
    "results.enr.clarityelections.com",
    "admin.enr.clarityelections.com",
    "www.livevoterturnout.com",
})

_COUNTY_ROW_RE = re.compile(r'^([A-Za-z. ]+) County')


def parse_county_urls(html: str) -> list[dict]:
    """Extract {county, url} for all 21 counties from the results page table."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for td in soup.find_all("td"):
        text = td.get_text(" ", strip=True)
        match = _COUNTY_ROW_RE.match(text)
        if not match:
            continue
        link = td.find("a", class_="elect_results")
        out.append({
            "county": match.group(1).strip(),
            "url": link["href"] if link else None,
        })
    return out


def classify_clarity_counties(county_urls: list[dict]) -> list[dict]:
    """
    Filter to counties on Clarity-pattern infrastructure and extract each
    county's numeric election ID from its URL path. A Clarity county with
    no ID posted yet for the current cycle returns election_id=None (still
    included — the caller decides whether to skip it).
    """
    in_scope = []
    for entry in county_urls:
        url = entry["url"]
        if not url:
            continue
        host = urlparse(url).hostname
        if host not in CLARITY_HOSTS:
            continue
        id_match = re.search(r'/(\d+)(?:/|$)', urlparse(url).path)
        in_scope.append({
            "county": entry["county"],
            "url": url,
            "election_id": id_match.group(1) if id_match else None,
        })
    return in_scope
