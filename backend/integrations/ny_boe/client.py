from __future__ import annotations

import datetime
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

_NY_BOE_BASE = "https://elections.ny.gov"
_TIMEOUT_MS = 30000
# elections.ny.gov 403s plain `requests` (basic bot/UA fingerprinting, not a
# Cloudflare Managed Challenge) but serves a real stealth-Chromium session
# immediately — same pattern already proven for flateau.elections.ny.gov in
# results/adapters/ny.py, no need for the heavier core/cf_solver.py service.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class CertificationDocument:
    document_type: str
    title: str
    election_date: datetime.date
    election_type: str
    landing_url: str
    pdf_url: str


@contextmanager
def _browser_page(*, accept_downloads: bool = False):
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            context = browser.new_context(user_agent=_USER_AGENT, accept_downloads=accept_downloads)
            yield context.new_page()
        finally:
            browser.close()


class NyBoeClient:
    landing_url = _NY_BOE_BASE

    def get_current_certification_documents(self) -> list[dict]:
        with _browser_page() as page:
            response = page.goto(self.landing_url, timeout=_TIMEOUT_MS)
            if response is None or not response.ok:
                status = response.status if response else "no response"
                raise RuntimeError(f"NY BOE landing page fetch failed: {status}")
            html = page.content()

        soup = BeautifulSoup(html, "html.parser")
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
        # elections.ny.gov's WAF treats an in-page fetch (page.request.get, no
        # Sec-Fetch-Mode: navigate / Referer) as a bot signal and 403s it, even
        # though a real top-level navigation to the same URL is let through as
        # a normal PDF download. Navigating to a PDF URL makes Chromium start a
        # download rather than render a page, so Playwright's goto() always
        # raises "Download is starting" here — that's expected, not a failure;
        # the actual bytes come from the intercepted Download object.
        with _browser_page(accept_downloads=True) as page:
            with page.expect_download(timeout=_TIMEOUT_MS) as download_info:
                try:
                    page.goto(url, timeout=_TIMEOUT_MS)
                except Exception:
                    pass
            download_path = download_info.value.path()
            if download_path is None:
                raise RuntimeError(f"NY BOE PDF download failed for {url}")
            content = download_path.read_bytes()
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
