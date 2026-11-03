from __future__ import annotations

import requests

from core.cf_solver import CfSolverClient, CfSolverError

from .exceptions import MiSosRetryableError

_MVIC_BASE = "https://mvic.sos.state.mi.us"
_BOE_REPORT_URL = "https://mi-boe.entellitrak.com/etk-mi-boe-prod/page.request.do"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


class MiSosClient:
    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def fetch_votehistory_page(self) -> str:
        """
        The MVIC vote-history page, whose dropdown carries each election's MVIC id.

        Goes through the CF solver: every mvic.sos.state.mi.us path answers a plain
        request with a 403 Cloudflare challenge, verified 2026-11-02 against
        /, /votehistory/, GetElectionResultFile and GetCountyVoteRecords.
        """
        page_url = f"{_MVIC_BASE}/votehistory/"
        try:
            return CfSolverClient().fetch_through_cf(page_url, page_url, payload_referer=page_url)
        except CfSolverError as exc:
            raise MiSosRetryableError(f"MVIC votehistory CF fetch failed: {exc}") from exc

    def fetch_candidate_listing(self, election_type: str, election_year: int) -> str:
        try:
            resp = self.session.get(
                _BOE_REPORT_URL,
                params={
                    "page": "page.miboePublicReport",
                    "electionType": election_type,
                    "electionYear": election_year,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            raise MiSosRetryableError(f"BOE candidate listing fetch failed: {exc}") from exc

    def fetch_result_file(self, election_id: int) -> str:
        payload_url = f"{_MVIC_BASE}/VoteHistory/GetElectionResultFile?electionId={election_id}"
        try:
            return CfSolverClient().fetch_through_cf(
                f"{_MVIC_BASE}/votehistory/",
                payload_url,
                payload_referer=f"{_MVIC_BASE}/votehistory/",
            )
        except CfSolverError as exc:
            raise MiSosRetryableError(f"MVIC result file CF fetch failed: {exc}") from exc

    def fetch_county_vote_records(self, election_id: int) -> str:
        """
        The vote-records page for one election — the results adapter's fallback.

        Also solver-routed. This was a plain GET, which answers 403 like every other
        mvic.sos.state.mi.us path (verified 2026-11-02), so the fallback could never
        have received anything in production: results.adapters.mi only wraps the bulk
        fetch in its try/except, and a raise here propagates out of fetch_results.
        """
        page_url = f"{_MVIC_BASE}/votehistory/"
        payload_url = f"{_MVIC_BASE}/VoteHistory/GetCountyVoteRecords?electionId={election_id}"
        try:
            return CfSolverClient().fetch_through_cf(page_url, payload_url, payload_referer=page_url)
        except CfSolverError as exc:
            raise MiSosRetryableError(f"MVIC county vote records CF fetch failed: {exc}") from exc
