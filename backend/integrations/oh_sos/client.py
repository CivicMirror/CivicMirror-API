"""
Ohio SOS CFDISCLOSURE HTTP client.

Downloads the ACT_CAN_LIST.CSV (active candidate list) from Ohio's Campaign
Finance Disclosure Oracle APEX system at www6.ohiosos.gov.

Access pattern (two-step):
  1. GET the CFDISCLOSURE:73 page — this sets the ORA_WWV_APP_119 APEX session
     cookie AND triggers the Cloudflare Managed Challenge. The CF solver service
     handles both via nodriver, returning cf_clearance + ORA_WWV_APP_119.
  2. GET CFDISCLOSURE:72 with P72_GETID=120 using both cookies — downloads the
     765-row CSV without triggering a second CF challenge.

The CF solver result is cached in Redis for 25 minutes, so repeated daily runs
cost only one Chrome session per day.
"""
import logging

import requests

from core.cf_solver import CfSolverClient, CfSolverError

from .exceptions import OhSosError, OhSosRetryableError

logger = logging.getLogger(__name__)

_APEX_SESSION_URL = (
    "https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73:::NO::P73_TYPE:CAN:"
)
_CSV_DOWNLOAD_URL = (
    "https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:72:::NO::P72_GETID:120"
)

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class OhSosClient:
    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self._cf = CfSolverClient()

    def fetch_active_candidates_csv(self) -> str:
        """
        Obtain CF bypass cookies via the solver service, then download and return
        the ACT_CAN_LIST.CSV text. Raises OhSosError on failure.
        """
        try:
            cookie_header, user_agent = self._cf.cookie_header(_APEX_SESSION_URL)
        except CfSolverError as exc:
            raise OhSosError(
                f"CF solver failed for www6.ohiosos.gov — cannot fetch candidates: {exc}"
            ) from exc

        headers = {
            "Cookie": cookie_header,
            "User-Agent": user_agent,
            "Referer": _APEX_SESSION_URL,
        }

        try:
            resp = requests.get(_CSV_DOWNLOAD_URL, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise OhSosRetryableError(f"Ohio SOS CSV download failed: {exc}") from exc

        if resp.status_code in _RETRYABLE_STATUSES:
            raise OhSosRetryableError(
                f"Ohio SOS CSV returned {resp.status_code} — likely stale CF cookies or transient error"
            )

        if resp.status_code != 200:
            raise OhSosError(
                f"Ohio SOS CSV returned unexpected status {resp.status_code}"
            )

        content_disposition = resp.headers.get("content-disposition", "").lower()
        content_type = resp.headers.get("content-type", "").lower()
        if "csv" not in content_disposition and "csv" not in content_type and "octet" not in content_type:
            raise OhSosError(
                f"Ohio SOS response is not a CSV — got Content-Type={resp.headers.get('content-type')!r}. "
                "CF cookies may have expired."
            )

        logger.info(
            "oh_sos.client.csv_downloaded bytes=%d rows_approx=%d",
            len(resp.content),
            resp.text.count("\n"),
        )
        return resp.text
