"""
VREMS API client for vrems.scvotes.sc.gov/Candidate

Auth: ASP.NET Core antiforgery cookie — issued automatically on the first GET.
No credentials, API key, or login required.
"""
import logging
import re

import requests
from bs4 import BeautifulSoup

from .exceptions import SCVremsError, SCVremsRetryableError

logger = logging.getLogger(__name__)

BASE_URL = "https://vrems.scvotes.sc.gov"
ELECTION_TYPES = ["General", "Local", "Special"]

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class VremsClient:
    def __init__(self, timeout: int = 20, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session: requests.Session | None = None

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def get_session(self) -> requests.Session:
        """Establish or return existing session with antiforgery cookie."""
        if self._session is not None:
            return self._session
        session = requests.Session()
        session.headers.update({"User-Agent": "CivicMirror-SC-VREMS/1.0"})
        resp = session.get(f"{BASE_URL}/Candidate/SelectElection", timeout=self.timeout)
        resp.raise_for_status()
        self._session = session
        return session

    def _get(self, url: str, params: dict | None = None) -> requests.Response:
        session = self.get_session()
        headers = {"X-Requested-With": "XMLHttpRequest"}
        for attempt in range(self.max_retries + 1):
            try:
                resp = session.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise SCVremsRetryableError(f"VREMS GET failed: {exc}") from exc
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise SCVremsRetryableError(f"VREMS returned {resp.status_code}")
                continue
            resp.raise_for_status()
            return resp
        raise SCVremsRetryableError("VREMS GET retries exhausted")

    def _post(self, url: str, data: dict) -> requests.Response:
        session = self.get_session()
        headers = {"X-Requested-With": "XMLHttpRequest"}
        for attempt in range(self.max_retries + 1):
            try:
                resp = session.post(url, data=data, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise SCVremsRetryableError(f"VREMS POST failed: {exc}") from exc
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise SCVremsRetryableError(f"VREMS returned {resp.status_code}")
                continue
            resp.raise_for_status()
            return resp
        raise SCVremsRetryableError("VREMS POST retries exhausted")

    # ------------------------------------------------------------------
    # Discovery endpoints
    # ------------------------------------------------------------------

    def get_years(self, election_type: str) -> list[int]:
        """Return available years (descending) for the given election type."""
        resp = self._get(
            f"{BASE_URL}/Candidate/GetYearsByElectionType",
            params={"electionType": election_type},
        )
        try:
            return [item["electionYear"] for item in resp.json()]
        except (ValueError, KeyError) as exc:
            raise SCVremsError(f"Unexpected GetYearsByElectionType response: {exc}") from exc

    def get_elections(self, election_type: str, year: int) -> list[dict]:
        """
        Return all elections for a type + year.

        Each dict contains:
          electionId, electionName, displayName, electionDate,
          filingPeriodBeginDate, electionType (injected)
        """
        resp = self._get(
            f"{BASE_URL}/Candidate/GetElections",
            params={"electionType": election_type, "year": year},
        )
        try:
            elections = resp.json()
        except ValueError as exc:
            raise SCVremsError(f"Unexpected GetElections response: {exc}") from exc
        for e in elections:
            e["electionType"] = election_type
        return elections

    def get_all_elections(
        self,
        election_types: list[str] | None = None,
        years: list[int] | None = None,
    ) -> list[dict]:
        """
        Sweep all election types, deduplicating by electionId.
        Filter by years if provided.
        """
        if election_types is None:
            election_types = ELECTION_TYPES
        seen: set[str] = set()
        results = []
        for etype in election_types:
            available = self.get_years(etype)
            targets = [y for y in available if years is None or y in years]
            for year in targets:
                for election in self.get_elections(etype, year):
                    eid = str(election["electionId"])
                    if eid not in seen:
                        seen.add(eid)
                        results.append(election)
        return results

    # ------------------------------------------------------------------
    # Candidate data
    # ------------------------------------------------------------------

    def get_candidates(self, election_id: str | int) -> list[dict]:
        """
        POST to CandidateSearch and return parsed candidate rows.
        Returns empty list for referendums or elections with unopened filing.
        """
        resp = self._post(
            f"{BASE_URL}/Candidate/CandidateSearch/",
            data={
                "ElectionId": str(election_id),
                "ExportFileName": f"Candidates_{election_id}",
                "SelectedOffice": "-1",
                "SelectedCandidateStatus": "All",
                "CandidateFirstName": "",
                "CandidateLastName": "",
                "SelectedPoliticalParty": "All",
                "SelectedFilingLocation": "All",
            },
        )
        return _parse_candidate_table(resp.text)


# ------------------------------------------------------------------
# HTML table parser
# ------------------------------------------------------------------

_DETAIL_CID_RE = re.compile(r"candidateId=(\d+)")
_DETAIL_EID_RE = re.compile(r"electionId=(\d+)")


def _parse_candidate_table(html: str) -> list[dict]:
    """
    Parse <table id="gridCandidateSearch"> from the CandidateSearch HTML response.

    Confirmed column order:
      0: Office
      1: Associated Counties
      2: Name on Ballot  (contains <a href="CandidateDetail/?candidateId=...&electionId=...">)
      3: Running Mate
      4: Party
      5: Location of Filing
      6: Candidate Status
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", {"id": "gridCandidateSearch"})
    if not table:
        return []
    tbody = table.find("tbody")
    if not tbody:
        return []

    candidates = []
    for row in tbody.find_all("tr"):
        candidate_id = row.get("data-key")
        cells = row.find_all("td")
        if len(cells) < 7:
            continue

        name_link = cells[2].find("a")
        name = name_link.get_text(strip=True) if name_link else cells[2].get_text(strip=True)

        detail_cid = detail_eid = None
        if name_link and name_link.get("href"):
            m = _DETAIL_CID_RE.search(name_link["href"])
            if m:
                detail_cid = m.group(1)
            m2 = _DETAIL_EID_RE.search(name_link["href"])
            if m2:
                detail_eid = m2.group(1)

        candidates.append({
            "candidate_id": candidate_id,
            "candidate_detail_id": detail_cid or candidate_id,
            # Note: detail_election_id links to the General election even in Primary searches
            "candidate_detail_election_id": detail_eid,
            "office": cells[0].get_text(strip=True),
            "associated_counties": cells[1].get_text(strip=True),
            "name_on_ballot": name,
            "running_mate": cells[3].get_text(strip=True),
            "party": cells[4].get_text(strip=True),
            "filing_location": cells[5].get_text(strip=True),
            "status": cells[6].get_text(strip=True),
        })

    return candidates
