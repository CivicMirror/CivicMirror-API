"""
Minnesota Secretary of State HTTP client.

electionresults.sos.mn.gov (the human-facing site) sits behind Radware
bot-detection on some pages (confirmed live 2026-07-13: the MediaFileLayout
doc page 302s behind a JS challenge), but the file-index page
(Select/MediaFiles/Index) and every actual .txt data file — served from the
separate electionresultsfiles.sos.mn.gov host — return 200 cleanly with a
plain browser User-Agent. No further bypass is required for this adapter.
"""
from __future__ import annotations

import logging

import requests

from .exceptions import MnSosRetryableError

logger = logging.getLogger(__name__)

_FILE_INDEX_URL = "https://electionresults.sos.mn.gov/Select/MediaFiles/Index"
_FILE_HOST = "https://electionresultsfiles.sos.mn.gov"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_RETRYABLE_STATUSES = {403, 429, 500, 502, 503, 504}

# Radware sometimes answers the file-index page with an HTTP 200 CAPTCHA
# challenge instead of the real index (confirmed live 2026-07-16: ~15 KB body,
# title "Radware Captcha Page", zero download links). We key on the title only:
# the *legitimate* index page also contains "validate.perfdrive.com" (in its
# stormcaster telemetry config), so that string cannot distinguish the two.
_CAPTCHA_MARKER = "radware captcha"


def _looks_like_captcha(html: str) -> bool:
    return _CAPTCHA_MARKER in html.lower()


class MnSosClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _get(self, url: str, **kwargs) -> requests.Response:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise MnSosRetryableError(f"MN SOS GET failed: {exc}") from exc
                logger.warning("mn_sos.client.retry attempt=%d url=%s err=%s", attempt, url, exc)
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise MnSosRetryableError(f"MN SOS returned {resp.status_code} for {url}")
                logger.warning(
                    "mn_sos.client.retry attempt=%d url=%s status=%d",
                    attempt, url, resp.status_code,
                )
                continue
            resp.raise_for_status()
            return resp
        raise MnSosRetryableError("MN SOS request retries exhausted")

    def fetch_file_index(self, ers_election_id: int) -> str:
        """
        GET the "Downloadable Text Files" index page for one election.

        Raises MnSosRetryableError when Radware returns its CAPTCHA challenge
        (which comes back as HTTP 200, so a status check alone would let the
        challenge HTML through to the parser as a false empty result).
        """
        html = self._get(_FILE_INDEX_URL, params={"ersElectionId": ers_election_id}).text
        if _looks_like_captcha(html):
            raise MnSosRetryableError(
                f"MN SOS served a Radware CAPTCHA for file index ersElectionId={ers_election_id}"
            )
        return html

    def fetch_file(self, url: str) -> str:
        """GET a result file or cand.txt directly by its full URL."""
        return self._get(url).text

    def fetch_candidate_table(self, date_path: str) -> str:
        """GET cand.txt for one election's result directory."""
        return self._get(f"{_FILE_HOST}/{date_path}/cand.txt").text
