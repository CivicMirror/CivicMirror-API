"""
Read-only CivicMirror MCP server (stdio transport only).

Phase 1 of the MCP roadmap (issue #42) exposes exactly three read-only tools --
``get_results``, ``list_adapters`` and ``compare_sources`` -- over the existing
CivicMirror DRF API. No write tool, no remote transport, and no direct reading of
Civic-Data repository files: those belong to later phases (#197-#200).
"""

from __future__ import annotations

from .client import CivicMirrorAPIClient
from .schemas import CompareSourcesOutput, GetResultsOutput, ListAdaptersOutput

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised by runtime setup.
    try:
        from importlib.metadata import version as _installed_version

        _mcp_version = _installed_version("mcp")
    except Exception:  # noqa: BLE001 - the SDK is simply absent.
        _mcp_version = None

    if _mcp_version is None:
        _hint = "The MCP SDK is not installed."
    else:
        _hint = (
            f"MCP SDK {_mcp_version} does not provide mcp.server.fastmcp; this server targets the 1.x SDK."
        )
    raise SystemExit(
        f"{_hint} Install the pinned dependency with: "
        "python -m pip install -r mcp_server/requirements.txt"
    ) from exc


mcp = FastMCP("civicmirror-api")
client = CivicMirrorAPIClient()


@mcp.tool()
def get_results(ocd_id: str, election_date: str, contest: str | None = None) -> GetResultsOutput:
    """
    Official CivicMirror results for a jurisdiction on an election date.

    Args:
        ocd_id: OCD division id including a state segment, e.g.
            ``ocd-division/country:us/state:wa/county:king``.
        election_date: Election date as ``YYYY-MM-DD``. Matched exactly.
        contest: Optional case-insensitive substring of the office title or jurisdiction.

    Each race carries its reporting and certification status, source authority and
    retrieval time, and whether result rows are contest totals or sub-jurisdiction
    splits. Metadata the API did not report stays null; ``notes`` lists the resulting
    coverage caveats. Read-only.
    """
    return client.get_results(ocd_id=ocd_id, election_date=election_date, contest=contest)


@mcp.tool()
def list_adapters(state: str | None = None) -> ListAdaptersOutput:
    """
    Registered CivicMirror results adapters and their latest sync status.

    Args:
        state: Optional two-letter state code (case-insensitive) to filter by.

    Returns the adapter registry, per-state run status and coverage tiers as the API
    reports them, with ``as_of`` as the snapshot's freshness. Read-only.
    """
    return client.list_adapters(state=state)


@mcp.tool()
def compare_sources(ocd_id: str, contest: str, election_date: str | None = None) -> CompareSourcesOutput:
    """
    Compare one contest's result rows across every source CivicMirror holds.

    Args:
        ocd_id: OCD division id including a state segment.
        contest: Case-insensitive substring of the office title or jurisdiction.
        election_date: Optional ``YYYY-MM-DD`` filter.

    Candidates and options are matched by reported name; rows the API left unnamed are
    excluded from ``comparisons`` rather than matched on an invented label. ``conflict``
    marks a pair where both sources reported a count and the counts differ. The baseline
    source is the alphabetically first source key, so output is stable across calls.
    Read-only.
    """
    return client.compare_sources(ocd_id=ocd_id, contest=contest, election_date=election_date)


if __name__ == "__main__":
    mcp.run()
