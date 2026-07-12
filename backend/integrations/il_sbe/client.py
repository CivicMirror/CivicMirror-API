"""
Illinois State Board of Elections (SBE) HTTP client.

Source: https://www.elections.il.gov/electionoperations/
No authentication required. The search page uses ASP.NET WebForms
auto-postback: selecting a different election in the `Elections` dropdown
fires a same-page postback that swaps in a new encrypted `ID` token for
that election. `OfficeType` category tokens are stable across elections
(confirmed live 2026-07-11 — see docs/superpowers/specs/2026-07-11-il-adapter-design.md).
"""
from __future__ import annotations

import logging

import requests

from .exceptions import IlSbeRetryableError
from .parsers import parse_postback_fields

logger = logging.getLogger(__name__)

BASE_URL = "https://www.elections.il.gov/electionoperations"
SEARCH_PAGE_URL = f"{BASE_URL}/votetotalsearch.aspx"
RESULTS_PAGE_URL = f"{BASE_URL}/ElectionVoteTotals.aspx"

# Stable category tokens (decoded), confirmed identical across elections.
OFFICE_TYPE_FEDERAL_STATEWIDE = "LpWf6lpbWOfBN3kEuxRi3A=="
OFFICE_TYPE_SENATE = "XmLrbPr2rU0jTLF//JHNA=="
# "House" is a flyout submenu on the site; hypDistrictAll returns all 118
# State House districts in one request (confirmed live 2026-07-11).
OFFICE_TYPE_HOUSE_ALL = "TPsWaFcg2f+ZHFrYI+6FR0aY47e3tS2y"
# Reserved for the deferred Judicial-races build (see
# docs/state-research/IL/IL-Election_Research.md) — not wired into any
# category loop yet. Confirmed correct live 2026-07-11.
OFFICE_TYPE_JUDICIAL = "OIPn0DmJsHWCRPQwcCA4+K+zeOSGzX4E"

_DDL_ELECTIONS_FIELD = "ctl00$ContentPlaceHolder1$ddlElections"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_RETRYABLE_STATUSES = {403, 429, 500, 502, 503, 504}


class IllinoisSbeClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        call = self._session.get if method == "GET" else self._session.post
        for attempt in range(self.max_retries + 1):
            try:
                resp = call(url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise IlSbeRetryableError(f"IL SBE {method} failed: {exc}") from exc
                logger.warning(
                    "il_sbe.client.retry method=%s attempt=%d url=%s err=%s",
                    method, attempt, url, exc,
                )
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise IlSbeRetryableError(f"IL SBE returned {resp.status_code} for {url}")
                logger.warning(
                    "il_sbe.client.retry method=%s attempt=%d url=%s status=%d",
                    method, attempt, url, resp.status_code,
                )
                continue
            resp.raise_for_status()
            return resp
        raise IlSbeRetryableError("IL SBE request retries exhausted")

    def fetch_search_page(self) -> str:
        """GET the default search page (most recent election preselected)."""
        return self._request("GET", SEARCH_PAGE_URL).text

    def fetch_election_page(self, election_value: str) -> str:
        """
        Replay the ddlElections auto-postback to load the page for a specific
        election (identified by its dropdown `value`, e.g. "66").
        """
        base_html = self.fetch_search_page()
        fields = parse_postback_fields(base_html)
        data = {
            "__EVENTTARGET": _DDL_ELECTIONS_FIELD,
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": fields["__VIEWSTATE"],
            "__VIEWSTATEGENERATOR": fields["__VIEWSTATEGENERATOR"],
            "__EVENTVALIDATION": fields["__EVENTVALIDATION"],
            _DDL_ELECTIONS_FIELD: election_value,
        }
        resp = self._request(
            "POST", SEARCH_PAGE_URL, data=data, headers={"Referer": SEARCH_PAGE_URL}
        )
        return resp.text

    def fetch_category_page(self, election_id_token: str, office_type_token: str) -> str:
        """GET a results category page (Federal/Statewide, Senate) for one election."""
        resp = self._request(
            "GET",
            RESULTS_PAGE_URL,
            params={"ID": election_id_token, "OfficeType": office_type_token},
        )
        return resp.text

    def fetch_office_csv(self, csv_url: str) -> str:
        """GET a per-office precinct-level results CSV. Public, no auth required."""
        return self._request("GET", csv_url).text
