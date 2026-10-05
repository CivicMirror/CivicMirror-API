from cm2_ma.constants import SOLVER_WAIT_SECONDS
from cm2_ma.sources.solver import MaSolverBytesSource


class FakeSolverClient:
    def __init__(self, text: str):
        self.text = text
        self.calls = []

    def fetch_through_cf(self, solve_url, payload_url, payload_referer=None):
        self.calls.append((solve_url, payload_url, payload_referer))
        return self.text


def test_acquire_solves_and_fetches_same_url_and_encodes_to_bytes():
    client = FakeSolverClient("<html>hello</html>")
    source = MaSolverBytesSource(client=client)
    source.url = "https://www.sec.state.ma.us/example.htm"

    result = source.acquire()

    assert result == b"<html>hello</html>"
    assert client.calls == [
        ("https://www.sec.state.ma.us/example.htm", "https://www.sec.state.ma.us/example.htm", None)
    ]


def test_default_client_uses_configured_wait_seconds(monkeypatch):
    captured = {}

    class RecordingCfSolverClient:
        def __init__(self, wait_seconds):
            captured["wait_seconds"] = wait_seconds

    monkeypatch.setattr("cm2_ma.sources.solver.CfSolverClient", RecordingCfSolverClient)

    MaSolverBytesSource()

    assert captured["wait_seconds"] == SOLVER_WAIT_SECONDS
