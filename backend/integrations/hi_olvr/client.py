from __future__ import annotations

import logging
import re
from html import unescape

import requests

from .exceptions import HawaiiOlvrError, HawaiiOlvrRetryableError
from .parsers import parse_candidate_report_link

logger = logging.getLogger(__name__)

_LANDING_URL = "https://elections.hawaii.gov/candidates/candidate-reports/"
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
_INPUT_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
_CSV_BUTTON_RE = re.compile(
    r'<input[^>]+name="(?P<name>[^"]+)"[^>]+class="[^"]*rgExpCSV[^"]*"',
    re.IGNORECASE,
)
_SUBMIT_TYPES = {"submit", "image"}
_SELECT_RE = re.compile(r"<select\b[^>]*>.*?</select>", re.IGNORECASE | re.DOTALL)
_SELECTED_OPTION_RE = re.compile(
    r'<option\b[^>]*\bselected\b[^>]*value="(?P<value>[^"]*)"', re.IGNORECASE,
)
_FIRST_OPTION_RE = re.compile(r'<option\b[^>]*value="(?P<value>[^"]*)"', re.IGNORECASE)
# The cycle selector. The portal also keeps the active election in a cookie, so
# omitting this field lets a stale session decide which year gets exported.
_ELECTION_SELECT_NAME = "ctl00$cphFooter$ddlElection"


class HawaiiOlvrClient:
    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(_BROWSER_HEADERS)

    def fetch_landing_page(self) -> str:
        try:
            response = self._session.get(_LANDING_URL, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise HawaiiOlvrRetryableError(f"failed to fetch Hawaii candidate landing page: {exc}") from exc
        return response.text

    def resolve_candidate_report(self) -> tuple[str, str, str]:
        landing_html = self.fetch_landing_page()
        report_url, elid = parse_candidate_report_link(landing_html)
        return landing_html, report_url, elid

    def fetch_candidate_report_html(self, report_url: str) -> str:
        try:
            response = self._session.get(report_url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise HawaiiOlvrRetryableError(f"failed to fetch Hawaii candidate report page: {exc}") from exc
        return response.text

    def fetch_candidate_report_csv(self, report_url: str, *, expected_elid: str = "") -> bytes:
        page_html = self.fetch_candidate_report_html(report_url)
        payload = _collect_form_inputs(page_html)
        button_name = _find_csv_button_name(page_html)
        payload[button_name] = ""

        # The portal pins the active cycle to a session cookie, so a stale
        # session can serve a different year than the URL asked for. Confirm
        # the page's own dropdown agrees before trusting the export.
        if expected_elid:
            served_elid = payload.get(_ELECTION_SELECT_NAME, "")
            if served_elid and served_elid != expected_elid:
                raise HawaiiOlvrError(
                    f"Hawaii candidate report served election {served_elid}, expected {expected_elid}"
                )

        try:
            response = self._session.post(report_url, data=payload, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise HawaiiOlvrRetryableError(f"failed to export Hawaii candidate CSV: {exc}") from exc

        content_type = (response.headers.get("content-type") or "").lower()
        if "text/csv" not in content_type:
            raise HawaiiOlvrError(f"expected CSV export, got {content_type or 'unknown content type'}")
        return response.content


def _collect_form_inputs(html: str) -> dict[str, str]:
    # Submit/image inputs are excluded: a real browser only ever includes the
    # one button that was actually clicked in the submitted form data. This
    # page has several (Export to PDF, Clear Filter, pagination), and
    # submitting them all confuses ASP.NET's postback control resolution -
    # it picks a different control (e.g. "Next Page") instead of firing the
    # CSV export handler, so the response is a re-rendered grid page, not CSV.
    payload: dict[str, str] = {}
    for match in _INPUT_RE.finditer(html or ""):
        tag = match.group(0)
        type_match = re.search(r'type="([^"]+)"', tag, re.IGNORECASE)
        if type_match and type_match.group(1).lower() in _SUBMIT_TYPES:
            continue
        name_match = re.search(r'name="([^"]+)"', tag, re.IGNORECASE)
        if not name_match:
            continue
        name = name_match.group(1)
        if not name:
            continue
        value_match = re.search(r'value="([^"]*)"', tag, re.IGNORECASE)
        payload[name] = unescape(value_match.group(1) if value_match else "")

    # <select> fields are part of the form too. The election-cycle dropdown in
    # particular must be posted back, or the server falls back to the cookie's
    # election and can export a different year than the one requested.
    for match in _SELECT_RE.finditer(html or ""):
        block = match.group(0)
        name_match = re.search(r'name="([^"]+)"', block, re.IGNORECASE)
        if not name_match or not name_match.group(1):
            continue
        option = _SELECTED_OPTION_RE.search(block) or _FIRST_OPTION_RE.search(block)
        if option:
            payload[name_match.group(1)] = unescape(option.group("value"))

    return payload


def _find_csv_button_name(html: str) -> str:
    match = _CSV_BUTTON_RE.search(html or "")
    if not match:
        raise HawaiiOlvrError("CSV export button not found on Hawaii candidate report page")
    return match.group("name")
