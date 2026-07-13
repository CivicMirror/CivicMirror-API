from __future__ import annotations

import datetime
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import unescape
from urllib.parse import urljoin

import requests

from .exceptions import OrSosError

logger = logging.getLogger(__name__)

_BASE_URL = "https://sos.oregon.gov"
_ORESTAR_BASE_URL = "https://secure.sos.state.or.us/orestar"
_LISTS_URL = f"{_BASE_URL}/elections/_vti_bin/Lists.asmx"
_VIEWS_URL = f"{_BASE_URL}/elections/_vti_bin/Views.asmx"
CURRENT_ELECTION_URL = f"{_BASE_URL}/elections/Pages/current-election.aspx"
ELECTION_DATES_URL = f"{_BASE_URL}/elections/Pages/election-dates.aspx"
CF_SEARCH_PAGE_URL = f"{_ORESTAR_BASE_URL}/CFSearchPage.do"
LOCAL_MEASURE_SEARCH_PAGE_URL = f"{_ORESTAR_BASE_URL}/gotoLocalMeasSearch.do"
OPEN_OFFICES_GENERAL_URL = f"{_BASE_URL}/elections/Documents/open-offices-general-election.pdf"
BALLOT_COUNT_HISTORY_URL = "https://data.oregon.gov/resource/rxzj-n3di.json"
_HISTORY_LIST = "History"
_KNOWN_PUBLIC_VIEW_GUID = "{B5E14970-1EE5-4BCB-8D5E-D2089E612F1C}"
_SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
_SP_NS = "http://schemas.microsoft.com/sharepoint/soap/"
_RS_NS = "urn:schemas-microsoft-com:rowset"
_Z_NS = "#RowsetSchema"


@dataclass(frozen=True)
class OrHistoryRow:
    election_date: datetime.date | None
    election_type: str
    results_html: str
    source_version: str


class OrSosClient:
    def __init__(self, timeout: int = 45):
        self.timeout = timeout
        self.session = requests.Session()
        self._orestar_csrf_token = ""

    def get_history_rows(self) -> list[OrHistoryRow]:
        view_guid = self._discover_public_history_view() or _KNOWN_PUBLIC_VIEW_GUID
        envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="{_SOAP_NS}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <GetListItems xmlns="{_SP_NS}">
      <listName>{_HISTORY_LIST}</listName>
      <viewName>{view_guid}</viewName>
      <queryOptions>
        <QueryOptions>
          <IncludeAttachmentUrls>TRUE</IncludeAttachmentUrls>
        </QueryOptions>
      </queryOptions>
    </GetListItems>
  </soap:Body>
</soap:Envelope>"""
        resp = requests.post(
            _LISTS_URL,
            data=envelope.encode("utf-8"),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": f"{_SP_NS}GetListItems",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return parse_history_response(resp.text)

    def download_document(self, url: str) -> tuple[bytes, str]:
        resp = requests.get(
            url,
            timeout=self.timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"},
        )
        resp.raise_for_status()
        content_type = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" in content_type:
            attachment_url = resolve_records_attachment_url(resp.text, resp.url)
            if attachment_url and attachment_url != resp.url:
                attachment_resp = requests.get(
                    attachment_url,
                    timeout=self.timeout,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"},
                )
                attachment_resp.raise_for_status()
                return attachment_resp.content, attachment_resp.url
        return resp.content, resp.url

    def fetch_open_offices_pdf(self, url: str = OPEN_OFFICES_GENERAL_URL) -> tuple[bytes, str]:
        return self.download_document(url)

    def fetch_page_text(self, url: str) -> tuple[str, str]:
        resp = requests.get(
            url,
            timeout=self.timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"},
        )
        resp.raise_for_status()
        return resp.text, resp.url

    def fetch_ballot_count_history(self, limit: int = 5000) -> tuple[list[dict], str]:
        resp = requests.get(
            BALLOT_COUNT_HISTORY_URL,
            params={"$limit": limit, "$order": "date DESC"},
            timeout=self.timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"},
        )
        resp.raise_for_status()
        return resp.json(), resp.url

    def search_candidate_filings(self, election_year: int, election_id: str, page_index: int = 0) -> tuple[str, str]:
        token = self._get_orestar_csrf_token(CF_SEARCH_PAGE_URL)
        data = {
            "cfSearchButtonName": "next" if page_index else "",
            "cfName": "",
            "cfyearActive": str(election_year),
            "cfElection": election_id,
            "cfOffice": " ",
            "cfPartyAffiliation": "",
            "cfFilingType": "",
            "cfFilingFromDate": "",
            "cfFilingToDate": "",
            "cfWithDrawFromDate": "",
            "cfWithDrawToDate": "",
        }
        if page_index:
            data.update({
                "mode": "create",
                "cfSearchCriteria": "",
                "cfSearchPageIdx": str(page_index),
                "srtOrder": "asc",
                "by": "BALLOT_NAME",
            })
        if token:
            data["OWASP_CSRFTOKEN"] = token

        resp = self.session.post(
            f"{_ORESTAR_BASE_URL}/cfFilings.do",
            data=data,
            timeout=self.timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"},
        )
        resp.raise_for_status()
        return resp.text, resp.url

    def search_local_measures(self, election_year: int, election_id: str, page_index: int = 0) -> tuple[str, str]:
        token = self._get_orestar_csrf_token(LOCAL_MEASURE_SEARCH_PAGE_URL)
        data = {
            "measSearchYear": "2018",
            "searchButtonName": "next" if page_index else "",
            "electionYear": str(election_year),
            "election": election_id,
            "county": "",
            "measureNumber": " ",
            "ballotTitle": "",
            "search": "Submit",
        }
        if page_index:
            data.update({
                "mode": "create",
                "measSearchCriteria": "",
                "measSearchPageIdx": str(page_index),
                "srtOrder": "asc",
                "by": "MEASURE",
            })
        if token:
            data["OWASP_CSRFTOKEN"] = token

        resp = self.session.post(
            f"{_ORESTAR_BASE_URL}/LocalMeasures.do",
            data=data,
            timeout=self.timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"},
        )
        resp.raise_for_status()
        return resp.text, resp.url

    def _get_orestar_csrf_token(self, start_url: str) -> str:
        if self._orestar_csrf_token:
            return self._orestar_csrf_token
        try:
            self.session.get(
                start_url,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"},
            ).raise_for_status()
            self.session.get(
                f"{_ORESTAR_BASE_URL}/JavaScriptServlet",
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)"},
            ).raise_for_status()
            resp = self.session.post(
                f"{_ORESTAR_BASE_URL}/JavaScriptServlet",
                timeout=self.timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.app)",
                    "FETCH-CSRF-TOKEN": "1",
                },
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("or_sos.orestar_csrf_failed: %s", exc)
            return ""
        match = re.search(r"OWASP_CSRFTOKEN:([^\s<]+)", resp.text or "")
        self._orestar_csrf_token = match.group(1).strip() if match else ""
        return self._orestar_csrf_token

    def _discover_public_history_view(self) -> str:
        envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="{_SOAP_NS}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <GetViewCollection xmlns="{_SP_NS}">
      <listName>{_HISTORY_LIST}</listName>
    </GetViewCollection>
  </soap:Body>
</soap:Envelope>"""
        try:
            resp = requests.post(
                _VIEWS_URL,
                data=envelope.encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": f"{_SP_NS}GetViewCollection",
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("or_sos.view_discovery_failed: %s", exc)
            return ""

        return parse_public_view_guid(resp.text)


def parse_public_view_guid(xml_text: str) -> str:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise OrSosError(f"Invalid Oregon SharePoint view XML: {exc}") from exc

    for view in root.findall(".//{*}View"):
        display_name = (view.attrib.get("DisplayName") or view.attrib.get("Name") or "").strip().lower()
        if display_name == "public":
            return view.attrib.get("Name") or ""
    return ""


def parse_history_response(xml_text: str) -> list[OrHistoryRow]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise OrSosError(f"Invalid Oregon SharePoint history XML: {exc}") from exc

    rows: list[OrHistoryRow] = []
    for row in root.findall(f".//{{{_Z_NS}}}row"):
        date_text = row.attrib.get("ows_Election_x0020_Date") or ""
        election_type = _clean_sharepoint_value(row.attrib.get("ows_Election_x0020_Type") or "")
        results_html = _clean_sharepoint_value(row.attrib.get("ows_Results") or "")
        modified = row.attrib.get("ows_Modified") or ""
        source_version = modified or f"{date_text}|{election_type}|{results_html}"
        rows.append(
            OrHistoryRow(
                election_date=_parse_sharepoint_date(date_text),
                election_type=election_type,
                results_html=results_html,
                source_version=source_version,
            )
        )
    return rows


def find_result_links(results_html: str) -> list[str]:
    html = unescape(results_html or "")
    links = re.findall(r"href=[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE)
    return [urljoin(_BASE_URL, link.strip()) for link in links if link.strip()]


def resolve_records_attachment_url(html: str, base_url: str) -> str:
    links = re.findall(r"(?:href|src)=[\"']([^\"']+)[\"']", html or "", flags=re.IGNORECASE)
    absolute_links = [urljoin(base_url, unescape(link.strip())) for link in links if link.strip()]
    for suffix in (".zip", ".csv", ".tsv", ".txt", ".xlsx", ".xls", ".pdf"):
        for link in absolute_links:
            if link.lower().split("?", 1)[0].endswith(suffix):
                return link
    download_keywords = ("download", "document", "attachment", "file", "stream", "content")
    for link in absolute_links:
        lowered = link.lower()
        if any(keyword in lowered for keyword in download_keywords):
            return link
    return ""


def select_history_row(rows: list[OrHistoryRow], election_date: datetime.date, election_type: str = "") -> OrHistoryRow | None:
    candidates = [row for row in rows if row.election_date == election_date]
    if not candidates:
        return None
    normalized_type = election_type.strip().lower()
    if normalized_type:
        for row in candidates:
            if normalized_type in row.election_type.lower() or row.election_type.lower() in normalized_type:
                return row
    return candidates[0]


def _clean_sharepoint_value(value: str) -> str:
    if ";#" in value:
        return value.split(";#", 1)[1].strip()
    return value.strip()


def _parse_sharepoint_date(value: str) -> datetime.date | None:
    value = _clean_sharepoint_value(value)
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(value[:19], fmt).date()
        except ValueError:
            continue
    return None
