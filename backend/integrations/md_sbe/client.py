from __future__ import annotations

import requests

from .exceptions import MdSbeRetryableError

_BASE_URL = "https://elections.maryland.gov"
_PAGE_NOT_FOUND_MARKER = "Page Not Found"


def _election_data_dir(year: int, archived: bool) -> str:
    """Directory holding a cycle's result CSVs.

    Verified live 2026-08-04: the CURRENT cycle publishes under
    /elections/{year}/election_data/ and only moves to
    /elections/archive/{year}/election_data/ once the cycle is over —
    /elections/archive/2026/... soft-404s today while /elections/2026/...
    serves the real files, and the reverse holds for 2024.
    """
    if archived:
        return f"/elections/archive/{year}/election_data/"
    return f"/elections/{year}/election_data/"


class MdSbeClient:
    """Fetches Maryland SBE's certified per-county results CSVs.

    MD SBE returns HTTP 200 with a "Page Not Found" HTML body (~14,424 bytes)
    for missing pages instead of a real 404 — every fetch here checks the
    response body for that marker rather than trusting the status code.

    Two result-file shapes exist, and which one is published depends on the
    election PHASE (verified live 2026-08-04 against
    /elections/2026/election_data/index.html and
    /elections/archive/2024/election_data/):

        general — {prefix}{yy}_{county}CountyResults.csv  (all parties, one file)
        primary — {prefix}{yy}_{county}{Party}Results.csv (one file per ballot
                  party, e.g. GP26_01DemocraticResults.csv,
                  GP26_01RepublicanResults.csv, GP26_01Non-PartisanResults.csv)

    Asking for the wrong shape soft-404s — GP26_01CountyResults.csv does not
    exist during the primary phase.
    """

    COUNTY_CODES: tuple[str, ...] = tuple(f"{i:02d}" for i in range(1, 25))

    #: Ballot-party file labels published for a primary, spelled exactly as
    #: they appear in the filename. Third parties (Green, Working Class, ...)
    #: nominate by convention/petition in MD and have no primary ballot, so
    #: they get no results file. "Non-Partisan" files exist but carry only
    #: out-of-scope offices (Board of Education, judicial), so they are not
    #: fetched.
    PRIMARY_PARTY_FILE_LABELS: tuple[str, ...] = ("Democratic", "Republican")

    def __init__(self):
        self.session = requests.Session()
        self.timeout = 15

    @staticmethod
    def build_url(
        year: int, cycle_prefix: str, county_code: str, archived: bool = True,
    ) -> str:
        """General-election per-county results URL (all parties in one file)."""
        return (
            f"{_BASE_URL}{_election_data_dir(year, archived)}"
            f"{cycle_prefix}{year % 100:02d}_{county_code}CountyResults.csv"
        )

    @staticmethod
    def build_party_results_url(
        year: int, cycle_prefix: str, county_code: str, party: str, archived: bool = True,
    ) -> str:
        """Primary-election per-county, per-ballot-party results URL."""
        return (
            f"{_BASE_URL}{_election_data_dir(year, archived)}"
            f"{cycle_prefix}{year % 100:02d}_{county_code}{party}Results.csv"
        )

    @staticmethod
    def build_candidate_csv_url(year: int, cycle_prefix: str, phase: str) -> str:
        path = "primary_candidates" if phase == "primary" else "general_candidates"
        return (
            f"{_BASE_URL}/elections/{year}/{path}/"
            f"{year}_{cycle_prefix}_statewide_candidatelist.csv"
        )

    def _get(self, url: str, context: str) -> str:
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise MdSbeRetryableError(f"MD SBE GET failed: {exc}") from exc

        # utf-8-sig strips a leading BOM if present, and is a no-op otherwise —
        # some MD SBE CSVs (candidate lists, primary per-party results) are
        # BOM-prefixed, general county results currently are not, so decode
        # defensively either way.
        text = response.content.decode("utf-8-sig", errors="replace")

        if response.status_code != 200 or _PAGE_NOT_FOUND_MARKER in text:
            raise MdSbeRetryableError(f"MD SBE soft-404 or error for {context} url={url}")

        return text

    def fetch_county_results(
        self, year: int, cycle_prefix: str, county_code: str, archived: bool = True,
    ) -> str:
        url = self.build_url(
            year=year, cycle_prefix=cycle_prefix, county_code=county_code, archived=archived,
        )
        return self._get(url, f"county={county_code}")

    def fetch_county_party_results(
        self,
        year: int,
        cycle_prefix: str,
        county_code: str,
        party: str,
        archived: bool = True,
    ) -> str:
        url = self.build_party_results_url(
            year=year, cycle_prefix=cycle_prefix, county_code=county_code,
            party=party, archived=archived,
        )
        return self._get(url, f"county={county_code} party={party}")

    def fetch_statewide_candidate_csv(self, year: int, cycle_prefix: str, phase: str) -> str:
        url = self.build_candidate_csv_url(year=year, cycle_prefix=cycle_prefix, phase=phase)
        return self._get(url, f"phase={phase}")
