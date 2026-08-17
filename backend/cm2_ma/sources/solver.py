from core.cf_solver import CfSolverClient

from cm2_ma.constants import SOLVER_WAIT_SECONDS, SOURCE_SYSTEM


class MaSolverBytesSource:
    """
    Base class for cm2_ma sources that must go through the shared cf-solver
    microservice because sec.state.ma.us is Incapsula-blocked. Mirrors
    cm2_nc.sources.http.NcPublicBytesSource's role (plain-HTTP fetch), but
    solves the challenge and fetches the payload in-browser via
    CfSolverClient.fetch_through_cf() instead of a direct requests.get().
    """

    source_system = SOURCE_SYSTEM
    url = ""

    def __init__(self, *, client=None):
        self._client = client or CfSolverClient(wait_seconds=SOLVER_WAIT_SECONDS)

    def acquire(self) -> bytes:
        text = self._client.fetch_through_cf(solve_url=self.url, payload_url=self.url)
        return text.encode("utf-8")
