import requests

from cm2_ma.constants import SOURCE_SYSTEM, SOURCE_TIMEOUT_SECONDS


class MaPublicBytesSource:
    """
    Base class for cm2_ma sources that are plain, unauthenticated HTTP —
    unlike sec.state.ma.us (see sources/solver.py), OCPF's bulk data files
    (ocpf2.blob.core.windows.net) are not behind any bot protection, so a
    direct requests.get() works. Mirrors cm2_nc.sources.http.NcPublicBytesSource.
    """

    source_system = SOURCE_SYSTEM
    url = ""

    def __init__(self, *, session=None):
        self._session = session or requests.Session()

    def acquire(self) -> bytes:
        response = self._session.get(self.url, timeout=SOURCE_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.content
