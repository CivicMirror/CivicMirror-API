"""
ENR client for www.enr-scvotes.org.

Provides election discovery via elections.json and URL resolution for each EID.
The site requires a browser User-Agent — requests with the default python-requests
UA receive HTTP 403 from CloudFront. _CLARITY_HEADERS from clarity.py provides
the correct UA and is reused here to keep the two modules in sync.

URL resolution: each EID navigates via a server-side redirect to a fully resolved
path containing the /web.XXXXXX/ deployment segment. This segment is required to
construct the current_ver.txt and summary.json paths used by ClarityAdapter.
"""
import logging
import time

import requests

from .exceptions import SCEnrError, SCEnrRetryableError

logger = logging.getLogger(__name__)

ENR_BASE = "https://www.enr-scvotes.org"
ENR_ELECTIONS_URL = f"{ENR_BASE}/SC/elections.json"

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Reuse the same browser UA already present in clarity.py.
# If this UA ever needs updating, update it in clarity.py; the string below
# should always match _CLARITY_HEADERS["User-Agent"] in results/adapters/clarity.py.
_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _BROWSER_UA}


class ENRClient:
    def __init__(self, timeout: int = 15, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries

    def _get(self, url: str, **kwargs) -> requests.Response:
        """GET with retries on transient errors."""
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.get(
                    url,
                    headers=_HEADERS,
                    timeout=self.timeout,
                    **kwargs,
                )
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise SCEnrRetryableError(f"ENR GET failed: {exc}") from exc
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise SCEnrRetryableError(f"ENR returned {resp.status_code} for {url}")
                continue
            resp.raise_for_status()
            return resp
        raise SCEnrRetryableError(f"ENR GET retries exhausted for {url}")

    def get_elections(self) -> list[dict]:
        """
        Fetch the elections.json discovery feed.

        Returns a list of election dicts when elections are active, or [] during
        the off-season. Each dict contains:
          ElectionName  str
          Date          str  "MM/DD/YYYY HH:MM:SS"
          State         str  always "SC"
          County        str | null   null = state-level entry
          EID           int

        A cache-buster param is included per the observed Angular app pattern.
        """
        try:
            resp = self._get(
                ENR_ELECTIONS_URL,
                params={"v": int(time.time() * 1000)},
            )
        except SCEnrRetryableError:
            raise
        except Exception as exc:
            raise SCEnrError(f"ENR elections.json fetch failed: {exc}") from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise SCEnrError(f"ENR elections.json returned non-JSON: {exc}") from exc

        if not isinstance(data, list):
            raise SCEnrError(f"ENR elections.json returned unexpected shape: {type(data)}")

        return data

    def resolve_url(self, eid: int, county: str | None = None) -> str:
        """
        Follow the server-side redirect from /{EID}/ to /{EID}/web.XXXXXX/.

        The web.XXXXXX segment is required to construct data API paths
        (e.g. /web.XXXXXX/current_ver.txt). It is NOT present in elections.json
        and must be obtained by following the redirect.

        Only call this when enr_resolved_url is empty or stale (404 on current_ver.txt).
        """
        if county:
            path = f"{ENR_BASE}/SC/{county.replace(' ', '_')}/{eid}/"
        else:
            path = f"{ENR_BASE}/SC/{eid}/"

        try:
            resp = self._get(path, allow_redirects=True)
        except SCEnrRetryableError:
            raise
        except Exception as exc:
            raise SCEnrError(f"ENR URL resolution failed for EID={eid}: {exc}") from exc

        resolved = resp.url
        # Ensure trailing slash for consistent path construction downstream.
        if not resolved.endswith("/"):
            resolved += "/"

        logger.debug("sc_enr.resolve_url eid=%d county=%s resolved=%s", eid, county, resolved)
        return resolved
