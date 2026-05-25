"""
Virginia ELECT / Enhanced Voting API client.

Provides access to:
  - Election slug discovery (scraping elections.virginia.gov)
  - Enhanced Voting ENR metadata and full data endpoints
  - ENR CSV download URL construction from publicReportCategories
  - SBE candidate list HTML scraping

ENR base URL:  https://enr.elections.virginia.gov/results/public/api
CDN base URL:  https://enr.elections.virginia.gov/cdn/results/{election_uuid}/{blob_name}

No authentication is required for any endpoint.
"""
from __future__ import annotations

import logging
import re
import urllib.parse

import requests
from bs4 import BeautifulSoup

from .exceptions import VaElectError, VaElectRetryableError

logger = logging.getLogger(__name__)

_ENR_API_BASE = "https://enr.elections.virginia.gov/results/public/api"
_ENR_CDN_BASE = "https://enr.elections.virginia.gov/cdn/results"
_SLUG_DISCOVERY_URL = "https://www.elections.virginia.gov/resultsreports/election-results/"
_CANDIDATE_LIST_BASE = "https://www.elections.virginia.gov/casting-a-ballot/candidate-list"
_SBE_CSV_BASE = "https://apps.elections.virginia.gov/SBE_CSV/ELECTIONS"

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Matches ENR href patterns like:
#   /results/public/Virginia/2025-November-General
#   /results/public/Virginia/2024NovemberGeneral
#   /results/public/Virginia/2024_June_Democratic_Primary
_ENR_HREF_RE = re.compile(
    r"/results/public/[Vv]irginia/([A-Za-z0-9_\-]+/?)",
    re.IGNORECASE,
)


class VaElectClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "CivicMirror-VA-ELECT/1.0"})

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, url: str, params: dict | None = None, timeout: int | None = None) -> requests.Response:
        effective_timeout = timeout or self.timeout
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=effective_timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise VaElectRetryableError(f"GET {url} failed: {exc}") from exc
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise VaElectRetryableError(f"GET {url} returned {resp.status_code}")
                continue
            resp.raise_for_status()
            return resp
        raise VaElectRetryableError(f"GET {url} retries exhausted")

    # ------------------------------------------------------------------
    # Slug discovery
    # ------------------------------------------------------------------

    def get_election_slugs(self) -> list[str]:
        """
        Scrape elections.virginia.gov to discover all available ENR slugs.

        Returns slugs exactly as they appear in the href (e.g. "2025-November-General",
        "2024NovemberGeneral", "2025-April-8-Town-of-Marion-Special_").
        Trailing slashes and leading path segments are stripped.
        """
        try:
            resp = self._get(_SLUG_DISCOVERY_URL)
        except VaElectRetryableError:
            logger.warning("va_elect.client.slug_discovery_failed url=%s", _SLUG_DISCOVERY_URL)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        slugs: list[str] = []
        seen: set[str] = set()

        for tag in soup.find_all("a", href=True):
            m = _ENR_HREF_RE.search(tag["href"])
            if m:
                # Strip trailing slash; preserve trailing underscore (edge case: Marion special)
                raw_slug = m.group(1).rstrip("/")
                if raw_slug not in seen:
                    seen.add(raw_slug)
                    slugs.append(raw_slug)

        logger.info("va_elect.client.slugs_discovered count=%d", len(slugs))
        return slugs

    # ------------------------------------------------------------------
    # Enhanced Voting API
    # ------------------------------------------------------------------

    def get_election_metadata(self, slug: str) -> dict:
        """
        GET /api/elections/Virginia/{slug}

        Lightweight call (~5–10 KB). Contains:
          asOf, isOfficialResults, electionDate, isProduction, publicReportCategories, ...
        """
        url = f"{_ENR_API_BASE}/elections/Virginia/{slug}"
        try:
            resp = self._get(url, timeout=15)
        except VaElectRetryableError as exc:
            raise VaElectRetryableError(f"Metadata fetch failed for slug={slug}: {exc}") from exc
        try:
            return resp.json()
        except ValueError as exc:
            raise VaElectError(f"Invalid JSON from {url}: {exc}") from exc

    def get_election_data(self, slug: str) -> dict:
        """
        GET /api/elections/Virginia/{slug}/data

        Full contest data (1–3 MB). Contains:
          jurisdiction.bannerUrl (→ election_uuid),
          publicReportCategories[].reports[].blobName,
          ballotItems[] (flat — ALL races and ballot measures statewide)
        """
        url = f"{_ENR_API_BASE}/elections/Virginia/{slug}/data"
        try:
            resp = self._get(url, timeout=60)
        except VaElectRetryableError as exc:
            raise VaElectRetryableError(f"Data fetch failed for slug={slug}: {exc}") from exc
        try:
            return resp.json()
        except ValueError as exc:
            raise VaElectError(f"Invalid JSON from {url}: {exc}") from exc

    # ------------------------------------------------------------------
    # CSV download URL construction
    # ------------------------------------------------------------------

    @staticmethod
    def get_election_uuid(data: dict) -> str | None:
        """
        Extract the election UUID from the jurisdiction.bannerUrl field.

        bannerUrl format: "{uuid}/BannerImage_{image_uuid}.png"
        Returns the UUID prefix, or None if not present.
        """
        banner = (data.get("jurisdiction") or {}).get("bannerUrl", "")
        if "/" in banner:
            return banner.split("/")[0]
        return None

    @staticmethod
    def get_report_urls(data: dict) -> list[dict]:
        """
        Build CDN download URLs for all available CSV reports.

        Returns a list of dicts:
          [{"report_name": "Election Results", "url": "https://...", "blob_name": "..."}, ...]

        Source: data["publicReportCategories"][n]["reports"][m]["blobName"]
        CDN pattern: {_ENR_CDN_BASE}/{election_uuid}/{blob_name}
        """
        election_uuid = VaElectClient.get_election_uuid(data)
        if not election_uuid:
            logger.warning("va_elect.client.no_election_uuid in data response")
            return []

        reports: list[dict] = []
        for category in data.get("publicReportCategories") or []:
            for report in category.get("reports") or []:
                blob_name = report.get("blobName", "")
                if not blob_name:
                    continue
                encoded = urllib.parse.quote(blob_name, safe="._-")
                reports.append({
                    "report_name": report.get("reportName", ""),
                    "blob_name": blob_name,
                    "url": f"{_ENR_CDN_BASE}/{election_uuid}/{encoded}",
                })

        return reports

    # ------------------------------------------------------------------
    # SBE candidate list
    # ------------------------------------------------------------------

    def get_candidate_list(self, election_label_slug: str) -> list[dict]:
        """
        Scrape the SBE candidate list HTML table for a given election.

        URL: https://www.elections.virginia.gov/casting-a-ballot/candidate-list/{slug}/

        Available fields: name, party, office, district, incumbent, email, phone,
        website, address.  The "all office" slug variant (e.g.
        "november-4-2025-gen-elect-all-office") is strongly preferred as it
        returns all candidates without JS rendering requirements.
        """
        url = f"{_CANDIDATE_LIST_BASE}/{election_label_slug}/"
        try:
            resp = self._get(url)
        except VaElectRetryableError as exc:
            logger.warning("va_elect.client.candidate_list_failed url=%s: %s", url, exc)
            return []

        return _parse_candidate_list_html(resp.text, source_url=url)

    # ------------------------------------------------------------------
    # SBE CSV (historical — 2005 to 2023)
    # ------------------------------------------------------------------

    def get_sbe_csv_url(self, year: int, election_name: str, report_type: str = "ELECTIONRESULTS") -> str:
        """
        Construct SBE CSV download URL for historical elections (2005–2023).

        report_type options: ELECTIONRESULTS, ELECTIONWINNERS, ELECTIONCHANGES
        """
        encoded_name = urllib.parse.quote(election_name, safe="")
        return f"{_SBE_CSV_BASE}/{report_type}/{year}/{encoded_name}.csv"


# ---------------------------------------------------------------------------
# HTML parsers
# ---------------------------------------------------------------------------

def _parse_candidate_list_html(html: str, source_url: str = "") -> list[dict]:
    """
    Parse the SBE candidate list page.

    The page contains a data table with columns that vary slightly by election
    year.  We extract whatever contact fields are present and return them as
    a list of dicts with normalized keys.
    """
    soup = BeautifulSoup(html, "lxml")

    # SBE pages use a variety of table IDs/classes; fall back to first data table.
    table = (
        soup.find("table", {"id": re.compile(r"candidate", re.I)})
        or soup.find("table", class_=re.compile(r"candidate", re.I))
        or soup.find("table")
    )
    if not table:
        logger.debug("va_elect.client.no_candidate_table url=%s", source_url)
        return []

    # Build header map from <th> elements
    headers: list[str] = []
    thead = table.find("thead") or table
    for th in thead.find_all("th"):
        headers.append(th.get_text(strip=True).lower().replace(" ", "_"))

    candidates: list[dict] = []
    tbody = table.find("tbody") or table
    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        raw: dict = {}
        for i, cell in enumerate(cells):
            key = headers[i] if i < len(headers) else f"col_{i}"
            # Prefer link href for website fields
            link = cell.find("a")
            if link and link.get("href", "").startswith("http"):
                raw[key] = link["href"].strip()
            else:
                raw[key] = cell.get_text(strip=True)

        candidates.append(_normalize_candidate_row(raw))

    return candidates


_FIELD_ALIASES = {
    # name variants
    "candidate_name": "name",
    "name_on_ballot": "name",
    "ballot_name": "name",
    # party variants
    "political_party": "party",
    "party_affiliation": "party",
    # office variants
    "office_sought": "office",
    "office_title": "office",
    # district variants
    "district_name": "district",
    # email variants
    "campaign_email": "email",
    "email_address": "email",
    # phone variants
    "campaign_phone": "phone",
    "phone_number": "phone",
    # website variants
    "campaign_website": "website",
    "campaign_url": "website",
    # address variants
    "campaign_address": "address",
    "mailing_address": "address",
    # incumbent variants
    "is_incumbent": "incumbent",
    "incumbent_flag": "incumbent",
}


def _normalize_candidate_row(raw: dict) -> dict:
    normalized: dict = {}
    for k, v in raw.items():
        canonical = _FIELD_ALIASES.get(k, k)
        normalized[canonical] = v
    # Normalize incumbent to bool
    if "incumbent" in normalized:
        val = str(normalized["incumbent"]).strip().lower()
        normalized["incumbent"] = val in {"yes", "true", "1", "y", "x"}
    return normalized
