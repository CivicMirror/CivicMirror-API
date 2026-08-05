from __future__ import annotations

import requests

from .exceptions import UtElectionsRetryableError


class UtElectionsClient:
    """Fetches Utah's Candidate Filing Excel workbook.

    Returns raw bytes — the file is a binary .xlsx, parsed separately by
    mappers.parse_candidate_filing_workbook via openpyxl.
    """

    def __init__(self):
        self.session = requests.Session()
        self.timeout = 20

    def fetch_candidate_filing_workbook(self, url: str) -> bytes:
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise UtElectionsRetryableError(f"UT candidate filing GET failed: {exc}") from exc

        if response.status_code != 200:
            raise UtElectionsRetryableError(
                f"UT candidate filing fetch failed status={response.status_code} url={url}"
            )

        # The workbook URL is a hand-maintained WordPress upload path (see
        # calendar.py) that can move or disappear. A moved/missing WP file
        # typically responds HTTP 200 with an HTML error page, not a real
        # 404, so a status-code check alone isn't enough — verify the body
        # actually looks like a zip/xlsx (magic bytes "PK\x03\x04") before
        # treating this as a successful fetch.
        if not response.content.startswith(b"PK\x03\x04"):
            raise UtElectionsRetryableError(
                f"UT candidate filing fetch returned unexpected content (not xlsx) url={url}"
            )

        return response.content
