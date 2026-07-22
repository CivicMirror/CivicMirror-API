from __future__ import annotations

from typing import Any

from .client import CivicMirrorAPIClient

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised by runtime setup.
    raise SystemExit(
        "The MCP SDK is not installed. Install this server with: "
        "python -m pip install -r mcp_server/requirements.txt"
    ) from exc


mcp = FastMCP("civicmirror-api")
client = CivicMirrorAPIClient()


@mcp.tool()
def get_results(ocd_id: str, election_date: str, contest: str | None = None) -> dict[str, Any]:
    """Return read-only CivicMirror race details and official results for a jurisdiction/date."""
    return client.get_results(ocd_id=ocd_id, election_date=election_date, contest=contest)


@mcp.tool()
def list_adapters(state: str | None = None) -> dict[str, Any]:
    """Return registered results-adapter states and latest sync status."""
    return client.list_adapters(state=state)


@mcp.tool()
def compare_sources(ocd_id: str, contest: str, election_date: str | None = None) -> dict[str, Any]:
    """Compare matching contest result rows across available CivicMirror race sources."""
    return client.compare_sources(ocd_id=ocd_id, contest=contest, election_date=election_date)


if __name__ == "__main__":
    mcp.run()
