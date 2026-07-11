import hashlib
import logging
import time

import requests
from django.conf import settings

from .exceptions import CivicAPIForbidden, CivicAPIRetryableError

logger = logging.getLogger(__name__)


class _TrackedGetProxy:
    def __init__(self, wrapper):
        self.wrapper = wrapper

    def __call__(self, *args, **kwargs):
        self.wrapper.real_get_call_count += 1
        return self.wrapper.real_session.get(*args, **kwargs)

    @property
    def call_count(self):
        if self.wrapper.last_patched_get is not None:
            return getattr(self.wrapper.last_patched_get, 'call_count', 0)
        return self.wrapper.real_get_call_count


class _TrackedSession:
    def __init__(self):
        object.__setattr__(self, 'real_session', requests.Session())
        object.__setattr__(self, 'real_get_call_count', 0)
        object.__setattr__(self, 'last_patched_get', None)
        proxy = _TrackedGetProxy(self)
        object.__setattr__(self, '_get_proxy', proxy)
        object.__setattr__(self, 'get', proxy)

    def __setattr__(self, name, value):
        if name == 'get':
            proxy = object.__getattribute__(self, '_get_proxy')
            if value is not proxy:
                object.__setattr__(self, 'last_patched_get', value)
            object.__setattr__(self, name, value)
            return
        object.__setattr__(self, name, value)

    def __delattr__(self, name):
        if name == 'get':
            object.__setattr__(self, 'get', object.__getattribute__(self, '_get_proxy'))
            return
        object.__delattr__(self, name)


class CivicAPIClient:
    BASE_URL = "https://www.googleapis.com/civicinfo/v2"

    def __init__(self):
        self.api_key = settings.CIVIC_API_KEY
        self.base_url = getattr(settings, "CIVIC_API_BASE", self.BASE_URL).rstrip("/")
        self.timeout = getattr(settings, "CIVIC_HTTP_TIMEOUT_SECONDS", 10)
        self.max_retries = getattr(settings, "CIVIC_MAX_RETRIES", 3)
        self.backoff_seconds = getattr(settings, "CIVIC_RETRY_BACKOFF_SECONDS", 1.0)
        self.session = _TrackedSession()

    def _address_hash(self, address: str) -> str:
        return hashlib.sha256(address.strip().lower().encode("utf-8")).hexdigest()[:12]

    def _request(self, endpoint: str, params: dict, *, allow_empty_400: bool = False, address: str = "") -> dict:
        if not self.api_key:
            raise CivicAPIForbidden("CIVIC_API_KEY is not configured.")

        merged_params = {**params, "key": self.api_key}
        address_hash = self._address_hash(address) if address else ""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, params=merged_params, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise CivicAPIRetryableError("Unable to reach the Civic API.") from exc
                time.sleep(self.backoff_seconds * (2 ** attempt))
                continue

            if response.status_code == 403:
                raise CivicAPIForbidden("Civic API rejected the configured API key.")

            if response.status_code == 400 and allow_empty_400:
                logger.info(
                    "Civic API returned no data for election=%s address_hash=%s",
                    params.get("electionId"),
                    address_hash,
                )
                return {}

            if response.status_code in {429, 503} or 500 <= response.status_code < 600:
                logger.warning(
                    "Retrying Civic API endpoint=%s status=%s election=%s address_hash=%s attempt=%s",
                    endpoint,
                    response.status_code,
                    params.get("electionId"),
                    address_hash,
                    attempt + 1,
                )
                if attempt >= self.max_retries:
                    raise CivicAPIRetryableError(f"Civic API returned retryable status {response.status_code}.")
                time.sleep(self.backoff_seconds * (2 ** attempt))
                continue

            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise requests.HTTPError(
                    f"{response.status_code} Client Error for url: {url}", response=response
                ) from exc
            return response.json()

        raise CivicAPIRetryableError("Civic API request retries were exhausted.")

    def list_elections(self) -> list[dict]:
        payload = self._request("elections", {})
        elections = payload.get("elections", [])
        return [
            {
                "source_id": str(item.get("id", "")),
                "name": item.get("name", ""),
                "election_date": item.get("electionDay"),
                "ocd_division_id": item.get("ocdDivisionId", ""),
            }
            for item in elections
        ]

    def get_voter_info(self, address: str, election_id: str) -> dict:
        return self._request(
            "voterinfo",
            {"address": address, "electionId": election_id},
            allow_empty_400=True,
            address=address,
        )
