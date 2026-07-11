"""
HTML/postback parsers for the Illinois State Board of Elections (SBE) site.

The search page (votetotalsearch.aspx) is classic ASP.NET WebForms: selecting
a different election in the `Elections` dropdown fires a same-page auto-postback
via __doPostBack, swapping in a new encrypted `ID` token used by the results
category pages. The `OfficeType` category tokens are stable across elections
(see client.py for the constants).
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

_POSTBACK_FIELDS = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")

_CSV_BASE_URL = "https://www.elections.il.gov"


def parse_postback_fields(html: str) -> dict[str, str]:
    """Extract the ASP.NET WebForms hidden postback fields required to replay a postback."""
    soup = BeautifulSoup(html, "html.parser")
    fields: dict[str, str] = {}
    for field_id in _POSTBACK_FIELDS:
        tag = soup.find(id=field_id)
        fields[field_id] = tag.get("value", "") if tag else ""
    return fields


def parse_election_options(html: str) -> list[dict]:
    """Extract {value, label} pairs from the `Elections` dropdown."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find(id="ContentPlaceHolder1_ddlElections")
    if not select:
        return []
    options = []
    for opt in select.find_all("option"):
        value = opt.get("value", "").strip()
        label = opt.get_text(strip=True)
        if value and label:
            options.append({"value": value, "label": label})
    return options


def parse_election_id_token(html: str) -> str | None:
    """
    Decode the per-election `ID` token from the "Federal / Statewide" category link.
    Returns None if the link isn't present (e.g. election has no results page yet).
    """
    soup = BeautifulSoup(html, "html.parser")
    link = soup.find("a", string="Federal / Statewide")
    if not link or not link.get("href"):
        return None
    query = urlparse(link["href"]).query
    params = parse_qs(query)
    values = params.get("ID")
    if not values:
        return None
    return unquote(values[0])


def parse_category_offices(html: str) -> list[dict]:
    """
    Extract {office_name, csv_url} for every office on a results category page
    (Federal/Statewide, Senate, ...).
    """
    soup = BeautifulSoup(html, "html.parser")
    offices = []
    for block in soup.select("div.gridview-title-bar"):
        header = block.select_one("[id*=gridHeader]")
        link = block.select_one("a.gridview-download")
        if not header or not link or not link.get("href"):
            continue
        office_name = header.get_text(strip=True)
        raw_href = link["href"].replace("\\", "/")
        csv_url = f"{_CSV_BASE_URL}/{raw_href.lstrip('/')}"
        offices.append({"office_name": office_name, "csv_url": csv_url})
    return offices
