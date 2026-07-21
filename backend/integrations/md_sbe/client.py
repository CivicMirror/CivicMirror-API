from __future__ import annotations

import requests

from .exceptions import MdSbeRetryableError

_BASE_URL = "https://elections.maryland.gov"
_PAGE_NOT_FOUND_MARKER = "Page Not Found"


class MdSbeClient:
    """Fetches Maryland SBE's certified per-county results CSVs.

    MD SBE returns HTTP 200 with a "Page Not Found" HTML body (~14,424 bytes)
    for missing pages instead of a real 404 — every fetch here checks the
    response body for that marker rather than trusting the status code.
    """

    COUNTY_CODES: tuple[str, ...] = tuple(f"{i:02d}" for i in range(1, 25))

    def __init__(self):
        self.session = requests.Session()
        self.timeout = 15

    @staticmethod
    def build_url(year: int, cycle_prefix: str, county_code: str) -> str:
        return (
            f"{_BASE_URL}/elections/archive/{year}/election_data/"
            f"{cycle_prefix}{year % 100:02d}_{county_code}CountyResults.csv"
        )

    def fetch_county_results(self, year: int, cycle_prefix: str, county_code: str) -> str:
        url = self.build_url(year=year, cycle_prefix=cycle_prefix, county_code=county_code)
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise MdSbeRetryableError(f"MD SBE GET failed: {exc}") from exc

        # utf-8-sig strips a leading BOM if present, and is a no-op otherwise —
        # some MD SBE CSVs (candidate lists) are BOM-prefixed, county results
        # currently are not, so decode defensively either way.
        text = response.content.decode("utf-8-sig", errors="replace")

        if response.status_code != 200 or _PAGE_NOT_FOUND_MARKER in text:
            raise MdSbeRetryableError(
                f"MD SBE soft-404 or error for county={county_code} url={url}"
            )

        return text
