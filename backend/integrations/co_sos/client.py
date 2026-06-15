"""
Colorado Secretary of State HTTP client.

Fetches the official primary election candidate list HTML page
from the Colorado SOS website. No authentication required.

The candidate list is an HTML table at a stable URL. Withdrawn candidates
are marked with inline CSS `text-decoration: line-through` on table cells.

Change detection uses an MD5 hash of the response body (the site does not
reliably return ETag headers).
"""
import hashlib
import logging

import requests

from .exceptions import CoSosError, CoSosRetryableError

logger = logging.getLogger(__name__)

# Only primary is fully supported. The general petition page has a different
# schema and is not a complete general-election candidate list (deferred).
CANDIDATE_PAGE_URLS: dict[str, str] = {
    "primary": (
        "https://www.coloradosos.gov/pubs/elections/vote/primaryCandidates.html"
    ),
}

_RETRYABLE_STATUSES = {403, 429, 500, 502, 503, 504}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CivicMirror/1.0; "
        "+https://civicmirror.app)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Referer": "https://www.coloradosos.gov/",
}


class ColoradoSosClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _get(self, url: str) -> requests.Response:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise CoSosRetryableError(f"CO SOS GET failed: {exc}") from exc
                logger.warning("co_sos.client.retry attempt=%d url=%s err=%s", attempt, url, exc)
                continue

            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise CoSosRetryableError(
                        f"CO SOS returned {resp.status_code} for {url}"
                    )
                logger.warning(
                    "co_sos.client.retry attempt=%d url=%s status=%d",
                    attempt, url, resp.status_code,
                )
                continue

            resp.raise_for_status()
            return resp

        raise CoSosRetryableError("CO SOS GET retries exhausted")

    def get_candidate_page_fingerprint(self, election_type: str) -> str | None:
        """
        Return an MD5 content hash of the candidate list page, or None if unavailable.

        The hash is used for change detection — only re-parse when the page changes.
        election_type must be 'primary'.
        """
        url = CANDIDATE_PAGE_URLS.get(election_type)
        if not url:
            raise CoSosError(f"Unknown election_type: {election_type!r}")

        try:
            resp = self._get(url)
        except CoSosRetryableError:
            logger.warning("co_sos.client.page_unavailable election_type=%s", election_type)
            return None

        fingerprint = hashlib.md5(resp.content).hexdigest()
        logger.info(
            "co_sos.client.fingerprint election_type=%s fingerprint=%s bytes=%d",
            election_type, fingerprint, len(resp.content),
        )
        return fingerprint

    def fetch_candidate_html(self, election_type: str) -> str:
        """Fetch and return the candidate list page HTML."""
        url = CANDIDATE_PAGE_URLS.get(election_type)
        if not url:
            raise CoSosError(f"Unknown election_type: {election_type!r}")
        resp = self._get(url)
        logger.info(
            "co_sos.client.html_fetched election_type=%s bytes=%d",
            election_type, len(resp.content),
        )
        return resp.text
