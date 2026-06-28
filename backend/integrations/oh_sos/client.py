"""
Ohio SOS CFDISCLOSURE HTTP client.

Downloads the ACT_CAN_LIST.CSV (active candidate list) from Ohio's Campaign
Finance Disclosure Oracle APEX system at www6.ohiosos.gov.

Access pattern (two-step, both performed inside the CF solver's browser session):
  1. CF solver navigates to CFDISCLOSURE:73 — this sets both the ORA_WWV_APP_119
     APEX session cookie AND passes Cloudflare Bot Management. Because these
     cookies are HttpOnly they cannot be extracted from the browser; instead the
     solver performs the next step from within the same browser session.
  2. CF solver fetches CFDISCLOSURE:72 with P72_GETID=120 via an in-browser
     JavaScript fetch(), which automatically includes all cookies (HttpOnly and
     non-HttpOnly) from the browser's live cookie jar. The CSV text is returned
     directly without ever extracting individual cookies.

The CF solver result (the CSV text) is cached in Redis for 25 minutes.
"""
import logging

from core.cf_solver import CfSolverClient, CfSolverError

from .exceptions import OhSosError, OhSosRetryableError

logger = logging.getLogger(__name__)

_APEX_SESSION_URL = (
    "https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73:::NO::P73_TYPE:CAN:"
)
_CSV_DOWNLOAD_URL = (
    "https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:72:::NO::P72_GETID:120"
)


class OhSosClient:
    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self._cf = CfSolverClient()

    def fetch_active_candidates_csv(self) -> str:
        """
        Obtain the ACT_CAN_LIST.CSV text by solving the CF challenge and fetching
        the CSV from within the browser session. Raises OhSosError on failure.
        """
        try:
            csv_text = self._cf.fetch_through_cf(
                solve_url=_APEX_SESSION_URL,
                payload_url=_CSV_DOWNLOAD_URL,
                payload_referer=_APEX_SESSION_URL,
            )
        except CfSolverError as exc:
            raise OhSosError(
                f"CF solver failed for www6.ohiosos.gov — cannot fetch candidates: {exc}"
            ) from exc

        # APEX exports use \r (CR-only) or \r\n as line endings; count either.
        row_count = max(csv_text.count("\n"), csv_text.count("\r"))
        if not csv_text or row_count < 10:
            raise OhSosError(
                f"Ohio SOS CSV appears invalid — got {len(csv_text)} chars / "
                f"{row_count} rows. CF session may have expired."
            )

        if "just a moment" in csv_text.lower() or "<!doctype html" in csv_text.lower():
            raise OhSosRetryableError(
                "Ohio SOS returned HTML instead of CSV — CF cookies may have expired."
            )

        logger.info(
            "oh_sos.client.csv_downloaded bytes=%d rows_approx=%d",
            len(csv_text),
            row_count,
        )
        return csv_text
