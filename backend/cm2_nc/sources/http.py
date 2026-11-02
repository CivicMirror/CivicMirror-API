import requests

from cm2_nc.constants import SOURCE_SYSTEM, SOURCE_TIMEOUT_SECONDS


class NcPublicBytesSource:
    source_system = SOURCE_SYSTEM
    url = ""

    def __init__(self, *, session=None):
        self._session = session or requests.Session()

    def acquire(self) -> bytes:
        response = self._session.get(self.url, timeout=SOURCE_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.content
