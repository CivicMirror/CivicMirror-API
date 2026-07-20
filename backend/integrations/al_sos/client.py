from __future__ import annotations

import base64
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from bs4 import BeautifulSoup

from .exceptions import AlSosError, AlSosRetryableError

_BASE_URL = "https://www2.alabamavotes.gov/electionNight/statewideResultsByContest.aspx"
_FCPA_BASE_URL = "https://fcpa.alabamavotes.gov/page.request.do"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
_REQUIRED_FIELDS = ("__VIEWSTATE", "__EVENTVALIDATION", "__VIEWSTATEGENERATOR")


def enr_url_for_ecode(ecode: str) -> str:
    return f"{_BASE_URL}?ecode={ecode.strip()}"


def extract_webforms_fields(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html or "", "html.parser")
    fields: dict[str, str] = {}
    for name in _REQUIRED_FIELDS:
        node = soup.find("input", id=name)
        value = (node.get("value") if node else None) or ""
        if not value:
            raise AlSosError(f"Alabama ENR page missing {name}")
        fields[name] = value
    return fields


def ecode_from_results_url(url: str) -> str:
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("ecode") or []
    return values[0].strip() if values else ""


class AlSosClient:
    def __init__(self, session=None, timeout: int = 30, export_timeout: int = 60):
        self.session = session or requests.Session()
        self.session.headers.update(_HEADERS)
        self.timeout = timeout
        self.export_timeout = export_timeout

    def fetch_enr_export(self, ecode: str) -> bytes:
        if not ecode or not ecode.strip():
            raise AlSosError("Alabama ENR ecode is required")
        return self.fetch_enr_export_from_url(enr_url_for_ecode(ecode))

    def fetch_enr_export_from_url(self, url: str) -> bytes:
        try:
            get_response = self.session.get(url, timeout=self.timeout)
            get_response.raise_for_status()
            fields = extract_webforms_fields(get_response.text)
            post_response = self.session.post(
                url,
                data={
                    "__EVENTTARGET": "hlnkExportData",
                    "__EVENTARGUMENT": "",
                    **fields,
                },
                timeout=self.export_timeout,
            )
            post_response.raise_for_status()
        except requests.RequestException as exc:
            raise AlSosRetryableError(f"Alabama ENR export request failed: {exc}") from exc

        content_type = post_response.headers.get("Content-Type", "")
        disposition = post_response.headers.get("Content-Disposition", "")
        if "spreadsheetml" not in content_type and "sosEnrExport.xlsx" not in disposition:
            raise AlSosError("Alabama ENR export did not return an Excel workbook")
        return post_response.content

    def fetch_election_year_page(self, year: int) -> str:
        url = f"https://www.sos.alabama.gov/alabama-votes/voter/election-information/{year}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AlSosRetryableError(f"Alabama election-information page request failed: {exc}") from exc
        return response.text

    def fetch_fcpa_race_search(self, election_id: str, office_id: int, page_number: int, page_size: int = 100) -> str:
        params = {
            "page": "com.acf.common.page.politicalracesearchresults",
            "pageNumber": page_number,
            "pageSize": page_size,
            "sortDirection": "ASC",
            "sortBy": "candidate",
            "election": election_id,
            "office": office_id,
            "jurisdiction": "null",
            "party": "null",
            "place": "null",
            "district": "null",
            "city": "null",
            "year": "null",
        }
        url = f"{_FCPA_BASE_URL}?{urlencode(params)}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AlSosRetryableError(f"Alabama FCPA race search request failed: {exc}") from exc
        return response.text

    def fetch_fcpa_committee_detail(self, committee_id: int) -> str:
        encoded_type = base64.b64encode(b"pcc").decode()
        encoded_id = base64.b64encode(str(committee_id).encode()).decode()
        params = {
            "page": "page.acfPublicCommitteeDetails",
            "type": encoded_type,
            "id": encoded_id,
        }
        url = f"{_FCPA_BASE_URL}?{urlencode(params)}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AlSosRetryableError(f"Alabama FCPA committee detail request failed: {exc}") from exc
        return response.text
