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

    def fetch_candidate_report_csv(self, report_url: str) -> bytes:
        page_html = self.fetch_candidate_report_html(report_url)
        payload = _collect_form_inputs(page_html)
        button_name = _find_csv_button_name(page_html)
        payload[button_name] = ""

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
    payload: dict[str, str] = {}
    for match in _INPUT_RE.finditer(html or ""):
        tag = match.group(0)
        name_match = re.search(r'name="([^"]+)"', tag, re.IGNORECASE)
        if not name_match:
            continue
        name = name_match.group(1)
        if not name:
            continue
        value_match = re.search(r'value="([^"]*)"', tag, re.IGNORECASE)
        payload[name] = unescape(value_match.group(1) if value_match else "")
    return payload


def _find_csv_button_name(html: str) -> str:
    match = _CSV_BUTTON_RE.search(html or "")
    if not match:
        raise HawaiiOlvrError("CSV export button not found on Hawaii candidate report page")
    return match.group("name")
