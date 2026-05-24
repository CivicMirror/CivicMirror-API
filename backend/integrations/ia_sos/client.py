"""
Iowa Secretary of State HTTP client.

Fetches the 3-year election calendar PDF and candidate list PDFs
from the Iowa SOS website. No authentication required.

Known access note: Iowa SOS may return 403 from automated clients without
proper User-Agent headers. All requests include a descriptive User-Agent and
Referer header to mimic a browser fetch. 403 is treated as retryable to
handle transient Akamai rate-limiting.
"""
import logging
import re

import requests
from bs4 import BeautifulSoup

from .exceptions import IowaSosError, IowaSosRetryableError

logger = logging.getLogger(__name__)

CALENDAR_PDF_URL = "https://sos.iowa.gov/elections/pdf/cal3yr.pdf"

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

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CivicMirror/1.0; "
        "+https://civicmirror.welshrd.com)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/pdf",
}


class IowaSosClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _get(self, url: str, stream: bool = False) -> requests.Response:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout, stream=stream)
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
                logger.warning(
                    "ia_sos.client.retry attempt=%d url=%s status=%d",
                    attempt, url, resp.status_code,
                )
                continue

            resp.raise_for_status()
            return resp

        raise IowaSosRetryableError("Iowa SOS GET retries exhausted")

    # ------------------------------------------------------------------
    # Calendar PDF
    # ------------------------------------------------------------------

    def fetch_calendar_pdf(self) -> bytes:
        """Download the 3-year election calendar PDF."""
        resp = self._get(CALENDAR_PDF_URL)
        logger.info("ia_sos.client.calendar_pdf bytes=%d", len(resp.content))
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

        # Look for any link to a candidate list PDF
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            if re.search(r"candidate[^/]*\.pdf", href, re.IGNORECASE):
                full_url = href if href.startswith("http") else f"https://sos.iowa.gov{href}"
                logger.info(
                    "ia_sos.client.candidate_pdf_found election_type=%s url=%s",
                    election_type, full_url,
                )
                # HEAD request to get ETag/Last-Modified without downloading
                try:
                    head = self._session.head(full_url, timeout=self.timeout)
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
