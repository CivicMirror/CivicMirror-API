"""
End-to-end MCP integration over stdio against a live CivicMirror API (issue #196).

The server runs as a real subprocess (``python -m civicmirror_mcp.server``), speaks the
MCP protocol over stdio, and reaches a live Django test server authenticated with a real
read-level service API key. Tool discovery and all three tool invocations are exercised
through the MCP client, not through the Python client class.

Run with::

    cd backend && python -m pytest api/tests/test_mcp_stdio_integration.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="the MCP SDK is required for the stdio integration test")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
ELECTION_DATE = date(2026, 11, 3)
OCD_ID = "ocd-division/country:us/state:co/county:mesa"
API_KEY = "mcp-integration-read-key"

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def seeded_contest(db):
    """One contest held from two sources, with a vote-count disagreement between them."""
    from elections.models import Candidate, Election, Race
    from results.models import OfficialResult

    election = Election.objects.create(
        name="Mesa County General 2026",
        election_date=ELECTION_DATE,
        jurisdiction_level=Election.JurisdictionLevel.LOCAL,
        state="CO",
        status=Election.Status.RESULTS_PENDING,
    )

    def make_race(source, certification_status, counts, result_type, synced):
        race = Race.objects.create(
            election=election,
            race_type=Race.RaceType.CANDIDATE,
            office_title="County Commissioner District 1",
            jurisdiction="Mesa County",
            geography_scope="county",
            ocd_division_id=OCD_ID,
            source=source,
            certification_status=certification_status,
            last_synced_at=synced,
            contributing_sources=[source],
            field_provenance={"office_title": source},
        )
        for name, votes in counts.items():
            candidate = Candidate.objects.create(race=race, name=name, party="Unaffiliated")
            OfficialResult.objects.create(
                race=race,
                candidate=candidate,
                vote_count=votes,
                result_type=result_type,
                source_url=f"https://example.test/{source}",
            )
        return race

    from django.utils import timezone

    clarity = make_race(
        Race.Source.RESULTS_ADAPTER,
        Race.CertificationStatus.PARTIAL_RESULTS,
        {"Ada Example": 1000, "Bo Sample": 900},
        "unofficial",
        timezone.now(),
    )
    certified = make_race(
        Race.Source.CO_SOS,
        Race.CertificationStatus.RESULTS_CERTIFIED,
        {"Ada Example": 1004, "Bo Sample": 900},
        "official",
        timezone.now(),
    )
    return {"election": election, "races": [clarity, certified]}


def _server_params(base_url: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "civicmirror_mcp.server"],
        cwd=str(REPO_ROOT),
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(REPO_ROOT),
            "CIVICMIRROR_API_BASE_URL": f"{base_url}/api/v1",
            "CIVICMIRROR_MCP_API_KEY": API_KEY,
            "CIVICMIRROR_MCP_TIMEOUT": "30",
        },
    )


def run_mcp(base_url: str, call):
    """Start the MCP server over stdio, hand ``call`` an initialized session, return its result."""

    async def _main():
        async with stdio_client(_server_params(base_url)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await call(session)

    return asyncio.run(_main())


def structured(result):
    """Return a tool result's structured payload, falling back to parsing its text content."""
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    return json.loads(result.content[0].text)


def test_stdio_client_discovers_the_three_read_only_tools(live_server, make_api_key, seeded_contest):
    make_api_key(raw=API_KEY, access_level="read", throttle_rate="none")

    async def call(session):
        return await session.list_tools()

    tools = run_mcp(live_server.url, call)
    names = {tool.name for tool in tools.tools}

    assert names == {"get_results", "list_adapters", "compare_sources"}
    for tool in tools.tools:
        assert tool.inputSchema and tool.outputSchema


def test_get_results_over_stdio_returns_live_api_data_with_provenance(live_server, make_api_key, seeded_contest):
    make_api_key(raw=API_KEY, access_level="read", throttle_rate="none")

    async def call(session):
        return await session.call_tool("get_results", {
            "ocd_id": OCD_ID,
            "election_date": ELECTION_DATE.isoformat(),
            "contest": "commissioner",
        })

    result = run_mcp(live_server.url, call)
    assert not result.isError, result.content
    payload = structured(result)

    assert payload["race_count"] == 2
    assert payload["ocd_id"] == OCD_ID
    sources = {entry["race"]["source"] for entry in payload["races"]}
    assert sources == {"results_adapter", "co_sos"}

    for entry in payload["races"]:
        race = entry["race"]
        assert race["certification_status"] in {"partial_results", "results_certified"}
        assert race["last_synced_at"]                       # freshness survived the round trip
        assert race["sources"]                              # source authority
        assert entry["result_count"] == 2
        assert entry["contest_total_rows"] == 2             # no sub-jurisdiction splits seeded
        assert all(row["source_url"] for row in entry["results"])


def test_compare_sources_over_stdio_flags_the_seeded_disagreement(live_server, make_api_key, seeded_contest):
    make_api_key(raw=API_KEY, access_level="read", throttle_rate="none")

    async def call(session):
        return await session.call_tool("compare_sources", {
            "ocd_id": OCD_ID,
            "contest": "commissioner",
            "election_date": ELECTION_DATE.isoformat(),
        })

    result = run_mcp(live_server.url, call)
    assert not result.isError, result.content
    payload = structured(result)

    assert payload["source_count"] == 2
    assert payload["conflict_count"] == 1
    by_label = {row["label"]: row for row in payload["comparisons"]}
    ada = by_label["Ada Example"]
    assert ada["baseline_source"] == "co_sos"               # alphabetically first, deterministic
    assert ada["comparison_source"] == "results_adapter"
    assert ada["baseline_vote_count"] == 1004
    assert ada["comparison_vote_count"] == 1000
    assert ada["vote_count_delta"] == -4
    assert ada["conflict"] is True
    assert by_label["Bo Sample"]["conflict"] is False


def test_list_adapters_over_stdio_returns_sync_status(live_server, make_api_key, seeded_contest):
    make_api_key(raw=API_KEY, access_level="read", throttle_rate="none")

    async def call(session):
        return await session.call_tool("list_adapters", {"state": "co"})

    result = run_mcp(live_server.url, call)
    assert not result.isError, result.content
    payload = structured(result)

    assert payload["state"] == "CO"
    assert isinstance(payload["adapter_states"], list)
    assert isinstance(payload["by_state"], dict)


def test_race_tools_fail_cleanly_without_a_valid_api_key(live_server, seeded_contest):
    """
    No key is minted here, so ``/races/`` (which requires ``HasAPIKey``) rejects the request.
    The tool must surface that as an error without echoing the presented key.
    """

    async def call(session):
        return await session.call_tool("get_results", {
            "ocd_id": OCD_ID,
            "election_date": ELECTION_DATE.isoformat(),
        })

    result = run_mcp(live_server.url, call)

    assert result.isError
    text = " ".join(getattr(item, "text", "") for item in result.content)
    assert "request failed" in text
    assert API_KEY not in text


def test_list_adapters_needs_no_key_because_sync_status_is_public(live_server, seeded_contest):
    """Documents the split: coverage/sync-status is AllowAny, the race endpoints are not."""

    async def call(session):
        return await session.call_tool("list_adapters", {"state": "co"})

    result = run_mcp(live_server.url, call)

    assert not result.isError, result.content
