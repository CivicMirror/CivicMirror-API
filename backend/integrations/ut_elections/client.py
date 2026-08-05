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

        return response.content
