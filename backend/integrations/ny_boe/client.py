from __future__ import annotations

import datetime
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

_NY_BOE_BASE = "https://elections.ny.gov"


@dataclass
class CertificationDocument:
    document_type: str
    title: str
    election_date: datetime.date
    election_type: str
    landing_url: str
    pdf_url: str


class NyBoeClient:
    landing_url = _NY_BOE_BASE

    def get_current_certification_documents(self) -> list[dict]:
        response = requests.get(self.landing_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        docs = []
        for link in soup.find_all("a"):
            title = " ".join(link.get_text(" ").split())
            href = link.get("href") or ""
            if not href.lower().endswith(".pdf"):
                continue
            lowered = title.lower()
            if "certification" not in lowered or "primary" not in lowered:
                continue
            if "offices to be filled" in lowered:
                continue
            docs.append(
                {
                    "document_type": "primary_candidate_certification",
                    "title": title,
                    "election_date": _date_from_title(title),
                    "election_type": "primary",
                    "landing_url": self.landing_url,
                    "pdf_url": urljoin(self.landing_url, href),
                }
            )
        return [doc for doc in docs if doc["election_date"] is not None]

    def fetch_certification_pdf(self, url: str) -> bytes:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        content = response.content
        if not content.startswith(b"%PDF"):
            raise ValueError("NY BOE certification response was not a PDF")
        return content


def _date_from_title(title: str):
    import re

    match = re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})", title or "")
    if not match:
        return None
    try:
        return datetime.datetime.strptime(match.group(0), "%B %d, %Y").date()
    except ValueError:
        return None
