"""
HTML parsers for azcleanelections.gov endpoints.

Only FEDERAL and STATE branches are included; county/city excluded since
their race names are non-unique and absent from the AZSOS results XML.
"""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

_INCLUDED_BRANCH_PREFIXES = ("FEDERAL", "STATE")
_WRITE_IN_SUFFIX = " (Write-In)"
_VIEWCAND_RE = re.compile(r"ViewCand\((\d+)\)")


@dataclass
class CandidateListEntry:
    branch: str
    race_name: str
    candidate_id: int
    name: str
    party: str
    is_write_in: bool


@dataclass
class CandidateDetailData:
    name: str = ""
    photo_url: str = ""
    office: str = ""
    party: str = ""
    funding_type: str = ""
    website_url: str = ""
    donation_url: str = ""
    facebook: str = ""
    twitter: str = ""
    youtube: str = ""
    instagram: str = ""
    bio: str = ""
    campaign_statement: str = ""


def parse_candidate_list(html_bytes: bytes) -> list[CandidateListEntry]:
    soup = BeautifulSoup(html_bytes, "lxml")
    entries: list[CandidateListEntry] = []

    for branch_section in soup.find_all("section", id=re.compile(r"^secBL\d+$")):
        branch_h3 = branch_section.find("h3", class_="branch")
        branch = branch_h3.get_text(strip=True) if branch_h3 else ""

        if not any(branch.startswith(p) for p in _INCLUDED_BRANCH_PREFIXES):
            continue

        for race_section in branch_section.find_all("section", recursive=False):
            race_h3 = race_section.find("h3")
            race_name = race_h3.get_text(strip=True) if race_h3 else ""

            for li in race_section.find_all("li"):
                viewmore = li.find("img", class_="viewmore")
                if not viewmore:
                    continue
                m = _VIEWCAND_RE.search(viewmore.get("onclick", ""))
                if not m:
                    continue
                candidate_id = int(m.group(1))

                b_tag = li.find("b")
                raw_name = html_lib.unescape(b_tag.get_text(strip=True) if b_tag else "")
                is_write_in = raw_name.endswith(_WRITE_IN_SUFFIX)
                name = raw_name[: -len(_WRITE_IN_SUFFIX)].strip() if is_write_in else raw_name

                party_span = li.find("span", class_="party")
                party = party_span.get_text(strip=True) if party_span else ""

                entries.append(CandidateListEntry(
                    branch=branch,
                    race_name=race_name,
                    candidate_id=candidate_id,
                    name=name,
                    party=party,
                    is_write_in=is_write_in,
                ))

    return entries


def parse_candidate_detail(html_bytes: bytes) -> CandidateDetailData:
    soup = BeautifulSoup(html_bytes, "lxml")
    article = soup.find("article", class_="person")
    if not article:
        return CandidateDetailData()

    h4 = article.find("h4")
    name = h4.get_text(strip=True) if h4 else ""

    figure = article.find("figure")
    fig_img = figure.find("img") if figure else None
    photo_url = fig_img.get("src", "") if fig_img else ""

    office = party = funding_type = ""
    first_p = article.find("p")
    if first_p and not first_p.get("class"):
        lines = [t.strip() for t in first_p.get_text("\n").split("\n") if t.strip()]
        if len(lines) > 0:
            office = lines[0]
        if len(lines) > 1:
            party = lines[1]
        if len(lines) > 2:
            funding_type = lines[2]

    website_url = donation_url = ""
    for p in article.find_all("p"):
        text = p.get_text(strip=True)
        a = p.find("a")
        if text.startswith("Website") and a:
            website_url = a.get("href", "")
        elif text.startswith("Donations") and a:
            donation_url = a.get("href", "")

    facebook = twitter = youtube = instagram = ""
    social_p = article.find("p", class_="social")
    if social_p:
        for a_tag in social_p.find_all("a"):
            icon = a_tag.find("i")
            if not icon:
                continue
            classes = " ".join(icon.get("class", []))
            href = a_tag.get("href", "")
            if "fa-facebook" in classes:
                facebook = href
            elif "fa-x-twitter" in classes:
                twitter = href
            elif "fa-youtube" in classes:
                youtube = href
            elif "fa-instagram" in classes:
                instagram = href

    bio = campaign_statement = ""
    for p in article.find_all("p"):
        if p is first_p:
            continue
        if p.get("class"):
            continue
        text_stripped = p.get_text(strip=True)
        if not text_stripped or text_stripped.startswith("Website") or text_stripped.startswith("Donations"):
            continue
        b_tag = p.find("b")
        if b_tag and b_tag.get_text(strip=True) == "Statement":
            lines = p.get_text(separator="\n").split("\n", 1)
            campaign_statement = lines[1].strip() if len(lines) > 1 else ""
        elif not bio and not b_tag:
            bio = text_stripped

    return CandidateDetailData(
        name=name, photo_url=photo_url, office=office, party=party,
        funding_type=funding_type, website_url=website_url, donation_url=donation_url,
        facebook=facebook, twitter=twitter, youtube=youtube, instagram=instagram,
        bio=bio, campaign_statement=campaign_statement,
    )
