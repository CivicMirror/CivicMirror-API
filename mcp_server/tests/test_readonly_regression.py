"""
Regression guards for the Phase-1 boundary (issue #196).

These tests fail if a later change quietly widens the MCP surface: a fourth tool,
a write request, a remote transport, or direct reading of Civic-Data files.
"""

from __future__ import annotations

import inspect
import io
import tokenize
from pathlib import Path

import pytest

from civicmirror_mcp import client as client_module
from civicmirror_mcp.client import CivicMirrorAPIClient, CivicMirrorAPIError

PACKAGE_DIR = Path(client_module.__file__).parent
PHASE_1_TOOLS = {"get_results", "list_adapters", "compare_sources"}
WRITE_METHODS = ("post", "put", "patch", "delete", "head", "options")


class GetOnlySession:
    """Session that records GETs and raises if any write verb is attempted."""

    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(url)
        raise AssertionError("stop here: the request path was reached")

    def __getattr__(self, name):
        if name in WRITE_METHODS or name == "request":
            raise AssertionError(f"client attempted a non-GET request via session.{name}")
        raise AttributeError(name)


def test_client_only_ever_calls_session_get():
    client = CivicMirrorAPIClient(base_url="https://api.example.test/api/v1", session=GetOnlySession())

    with pytest.raises(AssertionError, match="stop here"):
        client.request("/races/")


def test_client_source_contains_no_write_verbs():
    source = (PACKAGE_DIR / "client.py").read_text()
    for verb in WRITE_METHODS:
        assert f"session.{verb}(" not in source, f"client.py calls session.{verb}()"
    assert "requests.post" not in source
    assert "requests.put" not in source
    assert "requests.delete" not in source


def test_server_exposes_only_the_phase_1_tools():
    from civicmirror_mcp import server as server_module

    tools = {name for name, obj in vars(server_module).items()
             if callable(obj) and getattr(obj, "__module__", None) == server_module.__name__}
    assert tools == PHASE_1_TOOLS


@pytest.mark.anyio
async def test_no_write_or_extraction_tool_is_registered():
    from civicmirror_mcp import server as server_module

    names = {tool.name for tool in await server_module.mcp.list_tools()}
    assert names == PHASE_1_TOOLS
    for forbidden in ("propose_results", "fetch_page", "extract_pdf_text", "lookup_ocd_id"):
        assert forbidden not in names


def test_server_runs_stdio_only():
    from civicmirror_mcp import server as server_module

    source = (PACKAGE_DIR / "server.py").read_text()
    assert "mcp.run()" in source, "the entrypoint must use the default stdio transport"
    for remote in ("sse", "streamable_http", "transport=", "host=", "port="):
        assert remote not in source, f"server.py references remote transport setting {remote!r}"
    assert inspect.signature(server_module.mcp.run).parameters  # sanity: run() accepts args we deliberately omit


def test_package_does_not_read_local_files_or_civic_data_paths():
    """Phase 1 reads the API over HTTP only -- no repository files, no Civic-Data parsing."""
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        code = _code_without_strings_and_comments(path.read_text())
        for forbidden in ("open(", "Path(", "yaml", "subprocess", "glob(", "Civic-Data", "Civic_Data"):
            assert forbidden not in code, f"{path.name} references {forbidden!r} outside a docstring"


def _code_without_strings_and_comments(source: str) -> str:
    """Return ``source`` with string literals and comments blanked out, so docstrings do not trip guards."""
    out = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.STRING, tokenize.COMMENT):
            continue
        out.append(token.string)
    return " ".join(out)


def test_api_errors_do_not_leak_the_api_key():
    client = CivicMirrorAPIClient(
        base_url="https://api.example.test/api/v1",
        api_key="super-secret-key",
        session=_FailingSession(),
    )

    with pytest.raises(CivicMirrorAPIError) as ctx:
        client.request("/races/")
    assert "super-secret-key" not in str(ctx.value)


class _FailingSession:
    def get(self, url, headers=None, params=None, timeout=None):
        import requests
        raise requests.ConnectionError(f"cannot connect to {url}")
