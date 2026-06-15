"""
California SOS HTTP client.

Two base URLs:
  - api.sos.ca.gov  — Election Night Reporting REST API v2 (results JSON)
  - media.sos.ca.gov — Endpoint catalog CSV files (json-endpoints.csv, api-endpoints.csv)

No authentication required. JSON returned by default from the REST API.
Append ?f=csv for CSV output (not used; JSON preferred).

Note: If GCP Cloud Run IPs are blocked by Akamai/CDN, route through the
Cloudflare proxy by setting use_proxy=True or adding the domain to
CLARITY_PROXY_HOSTS. Test reachability first before enabling the proxy.
"""
import hashlib
import logging

import requests

from .exceptions import CaSosError, CaSosRetryableError

logger = logging.getLogger(__name__)

API_BASE = "https://api.sos.ca.gov"
MEDIA_BASE = "https://media.sos.ca.gov/media"

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CivicMirror/1.0; "
        "+https://civicmirror.app)"
    ),
    "Accept": "application/json, text/csv, text/plain, */*",
}


class CaSosClient:
    def __init__(self, timeout: int = 30, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _get(self, url: str) -> requests.Response:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise CaSosRetryableError(f"CA SOS GET failed: {exc}") from exc
                logger.warning("ca_sos.client.retry attempt=%d url=%s err=%s", attempt, url, exc)
                continue

            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise CaSosRetryableError(
                        f"CA SOS returned {resp.status_code} for {url}"
                    )
                logger.warning(
                    "ca_sos.client.retry attempt=%d url=%s status=%d",
                    attempt, url, resp.status_code,
                )
                continue

            if resp.status_code == 404:
                logger.info("ca_sos.client.not_found url=%s", url)
                return resp

            resp.raise_for_status()
            return resp

        raise CaSosRetryableError("CA SOS GET retries exhausted")

    def fetch_contest(self, endpoint_path: str) -> list[dict]:
        """
        Fetch results for a single contest.

        endpoint_path is the path after the base URL, e.g. "/returns/governor"
        or "/returns/ballot-measures".

        Returns the parsed JSON list, or an empty list if the endpoint
        returns 404 (contest not available for this election).
        """
        url = f"{API_BASE}{endpoint_path}"
        resp = self._get(url)

        if resp.status_code == 404:
            logger.info("ca_sos.client.contest_not_found endpoint=%s", endpoint_path)
            return []

        try:
            data = resp.json()
        except ValueError as exc:
            raise CaSosError(
                f"CA SOS returned non-JSON for {url}: {exc}"
            ) from exc

        if not isinstance(data, list):
            # Some endpoints return a dict; wrap for uniform handling
            data = [data]

        logger.info(
            "ca_sos.client.contest_fetched endpoint=%s contests=%d",
            endpoint_path, len(data),
        )
        return data

    def fetch_status(self) -> dict:
        """Fetch county reporting status from /returns/status."""
        url = f"{API_BASE}/returns/status"
        resp = self._get(url)
        try:
            return resp.json()
        except ValueError as exc:
            raise CaSosError(f"CA SOS /returns/status returned non-JSON: {exc}") from exc

    def fetch_endpoint_catalog_csv(self, filename: str = "api-endpoints.csv") -> bytes:
        """
        Download the endpoint catalog CSV from media.sos.ca.gov.

        filename is typically "json-endpoints.csv" or "api-endpoints.csv".
        Returns raw CSV bytes.
        """
        url = f"{MEDIA_BASE}/{filename}"
        resp = self._get(url)
        if resp.status_code == 404:
            raise CaSosError(f"Endpoint catalog not found at {url}")
        logger.info(
            "ca_sos.client.catalog_fetched filename=%s bytes=%d",
            filename, len(resp.content),
        )
        return resp.content

    def get_endpoint_catalog_fingerprint(self, filename: str = "api-endpoints.csv") -> str | None:
        """
        Return an MD5 hash of the endpoint catalog CSV for change detection.
        Returns None if the file is unavailable.
        """
        try:
            content = self.fetch_endpoint_catalog_csv(filename)
        except CaSosRetryableError:
            logger.warning("ca_sos.client.catalog_unavailable filename=%s", filename)
            return None
        return hashlib.md5(content).hexdigest()
