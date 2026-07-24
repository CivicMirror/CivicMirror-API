"""
Iowa Secretary of State HTTP client.

Fetches the 3-year election calendar PDF and candidate list PDFs
from the Iowa SOS website. No authentication required.

Known access note: Iowa SOS is protected by Akamai Bot Manager. GCP Cloud
Run IPs are flagged at Layer 1 (IP reputation) before headers are even
evaluated. All requests are routed through the CivicMirror Cloudflare proxy
worker (CIVICMIRROR_PROXY_URL setting) whose edge IPs pass Akamai's IP check.
In local dev (CIVICMIRROR_PROXY_URL empty), the client falls back to direct
requests with full browser-like headers to pass Akamai's Layer 4 check.
"""
import logging
import random
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from core.http import ProxyAuthError, UpstreamBlockedError, proxy_request

from .exceptions import IowaSosError, IowaSosRetryableError

logger = logging.getLogger(__name__)

CALENDAR_PAGE_URL = "https://sos.iowa.gov/three-year-election-calendar"
RESULTS_PORTAL_URL = "https://electionresults.iowa.gov/IA/"

_RESULTS_PATH_RE = re.compile(r"(/IA/\d+/)(?:web\.[^/]+/)?", re.IGNORECASE)

_CALENDAR_PDF_RE = re.compile(
    r'href=["\']([^"\']*\.pdf)["\']',
    re.IGNORECASE,
)

# Pages that link to versioned candidate list PDFs.
# Keyed by election_type ('primary' / 'general').
CANDIDATE_PAGE_URLS = {
    "primary": "https://sos.iowa.gov/primary-election",
    "general": "https://sos.iowa.gov/general-election",
}

_CANDIDATE_PDF_RE = re.compile(
    r'href=["\']([^"\']*(?:Candidate[^"\']*\.pdf|candidate[^"\']*\.pdf))["\']',
    re.IGNORECASE,
)

_RETRYABLE_STATUSES = {403, 429, 500, 502, 503, 504}

# Full browser-like header set required to pass Akamai Bot Manager's
# Layer 4 header-shape inspection. Missing headers (especially Referer,
# Accept-Language, and Sec-Fetch-*) are strong bot signals.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://sos.iowa.gov/elections-voting",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# Backoff base in seconds for retryable responses; jitter added per attempt.
_RETRY_BACKOFF_BASE = 2


class IowaSosClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries

    def _get(self, url: str) -> requests.Response:
        for attempt in range(self.max_retries + 1):
            try:
                resp = proxy_request(
                    "GET", url,
                    headers=_HEADERS,
                    use_proxy=True,
                    timeout=self.timeout,
                )
            except ProxyAuthError as exc:
                raise IowaSosError(
                    "Iowa SOS proxy returned 401 — check CIVICMIRROR_PROXY_SECRET configuration"
                ) from exc
            except UpstreamBlockedError as exc:
                # Non-retryable — direct 403 means GCP IP blocked; proxy must be configured.
                raise IowaSosError(
                    f"Iowa SOS host is blocking GCP IPs — ensure CIVICMIRROR_PROXY_URL is set: {exc}"
                ) from exc
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise IowaSosRetryableError(f"Iowa SOS GET failed: {exc}") from exc
                logger.warning("ia_sos.client.retry attempt=%d url=%s err=%s", attempt, url, exc)
                continue

            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise IowaSosRetryableError(
                        f"Iowa SOS returned {resp.status_code} for {url}"
                    )
                wait = (_RETRY_BACKOFF_BASE ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "ia_sos.client.retry attempt=%d url=%s status=%d wait=%.1fs",
                    attempt, url, resp.status_code, wait,
                )
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp

        raise IowaSosRetryableError("Iowa SOS GET retries exhausted")

    def get_results_url(self, election_year: int, election_type: str) -> str | None:
        """Return the Clarity base results URL for an IA election when discoverable."""
        expected_year = str(election_year)
        expected_type = election_type.lower()

        try:
            resp = self._get(urljoin(RESULTS_PORTAL_URL, "elections.json"))
            elections = resp.json()
        except (IowaSosError, requests.RequestException) as exc:
            logger.warning("ia_sos.client.results_json_unavailable err=%s", exc)
            elections = []
        except (TypeError, ValueError) as exc:
            logger.info("ia_sos.client.results_json_invalid err=%s", exc)
            elections = []

        if isinstance(elections, list):
            for election in elections:
                if not isinstance(election, dict):
                    continue
                label = str(election.get("ElectionName") or "").lower()
                election_id = str(election.get("EID") or "").strip()
                if expected_year in label and expected_type in label and election_id.isdigit():
                    return urljoin(RESULTS_PORTAL_URL, f"{election_id}/")

        resp = self._get(RESULTS_PORTAL_URL)
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup.find_all("a", href=True):
            label = tag.get_text(" ", strip=True).lower()
            href = tag["href"]
            combined = f"{label} {href}".lower()
            if expected_year not in combined or expected_type not in combined:
                continue
            match = _RESULTS_PATH_RE.search(href)
            if not match:
                continue
            return urljoin(RESULTS_PORTAL_URL, match.group(1)).rstrip("/") + "/"

        return None

    # ------------------------------------------------------------------
    # Calendar PDF
    # ------------------------------------------------------------------

    def _discover_calendar_pdf_url(self) -> str:
        """
        Scrape the Iowa SOS three-year-election-calendar landing page for the
        current PDF link. Iowa re-uploads this PDF under a new dated path
        (/sites/default/files/YYYY-MM/...) each time the calendar is revised,
        so the URL cannot be hardcoded — same reasoning as candidate PDF
        discovery below.
        """
        resp = self._get(CALENDAR_PAGE_URL)
        match = _CALENDAR_PDF_RE.search(resp.text)
        if not match:
            raise IowaSosError(
                f"No PDF link found on Iowa SOS calendar page: {CALENDAR_PAGE_URL}"
            )
        href = match.group(1)
        return href if href.startswith("http") else f"https://sos.iowa.gov{href}"

    def fetch_calendar_pdf(self) -> bytes:
        """Download the 3-year election calendar PDF."""
        pdf_url = self._discover_calendar_pdf_url()
        resp = self._get(pdf_url)
        logger.info("ia_sos.client.calendar_pdf url=%s bytes=%d", pdf_url, len(resp.content))
        return resp.content

    # ------------------------------------------------------------------
    # Candidate list PDF discovery
    # ------------------------------------------------------------------

    def get_candidate_pdf_info(self, election_type: str) -> dict | None:
        """
        Scrape the Iowa SOS election page for the current candidate list PDF.

        Returns a dict with 'url', 'etag', 'last_modified' or None if not found.
        election_type must be 'primary' or 'general'.
        """
        page_url = CANDIDATE_PAGE_URLS.get(election_type)
        if not page_url:
            raise IowaSosError(f"Unknown election_type: {election_type!r}")

        try:
            resp = self._get(page_url)
        except IowaSosRetryableError:
            logger.warning("ia_sos.client.page_unavailable election_type=%s", election_type)
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Iowa SOS (Drupal 10, SSR) stores the candidate list under the
        # article body. Match by link text ("candidate list") since the href
        # path uses a dated upload pattern (/sites/default/files/YYYY-MM/...)
        # that does not contain the word "candidate" in the URL itself.
        body = soup.select_one("article[data-history-node-id] .field--name-body")
        search_scope = body if body else soup

        for tag in search_scope.find_all("a", href=True):
            href = tag["href"]
            if not href.lower().endswith(".pdf"):
                continue
            link_text = tag.get_text(strip=True).lower()
            # Match "candidate list" link text OR href containing "candidate"
            if "candidate list" in link_text or re.search(r"candidate", href, re.IGNORECASE):
                full_url = href if href.startswith("http") else f"https://sos.iowa.gov{href}"
                logger.info(
                    "ia_sos.client.candidate_pdf_found election_type=%s url=%s",
                    election_type, full_url,
                )
                # HEAD request through proxy to get ETag/Last-Modified without
                # downloading the full PDF. Previously this bypassed the proxy;
                # now routed through CF Worker to avoid Akamai GCP IP block.
                try:
                    head = proxy_request(
                        "HEAD", full_url,
                        headers=_HEADERS,
                        use_proxy=True,
                        timeout=self.timeout,
                    )
                    etag = head.headers.get("ETag", "")
                    last_modified = head.headers.get("Last-Modified", "")
                except requests.RequestException:
                    etag = last_modified = ""

                return {
                    "url": full_url,
                    "etag": etag,
                    "last_modified": last_modified,
                }

        logger.info(
            "ia_sos.client.no_candidate_pdf election_type=%s page=%s",
            election_type, page_url,
        )
        return None

    def fetch_pdf(self, url: str) -> bytes:
        """Download a PDF by URL."""
        resp = self._get(url)
        logger.info("ia_sos.client.pdf_downloaded url=%s bytes=%d", url, len(resp.content))
        return resp.content
