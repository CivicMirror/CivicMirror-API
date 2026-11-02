"""
Tool discovery over the MCP protocol itself (issue #196).

These tests drive a real ``ClientSession`` against the server object over an
in-memory transport, so they check what an MCP client actually receives --
tool names, input schemas and output schemas -- rather than inspecting the
FastMCP decorators.
"""

from __future__ import annotations

import pytest

pytest.importorskip("mcp", reason="the MCP SDK is required for tool-discovery tests")

from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402

from civicmirror_mcp import server as server_module  # noqa: E402

PHASE_1_TOOLS = {"get_results", "list_adapters", "compare_sources"}


@pytest.fixture
def mcp_server():
    return server_module.mcp._mcp_server


@pytest.mark.anyio
async def test_client_discovers_exactly_the_phase_1_tools(mcp_server):
    async with create_connected_server_and_client_session(mcp_server) as session:
        tools = (await session.list_tools()).tools

    assert {tool.name for tool in tools} == PHASE_1_TOOLS


@pytest.mark.anyio
async def test_every_tool_publishes_input_and_output_schemas(mcp_server):
    async with create_connected_server_and_client_session(mcp_server) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}

    for name, tool in tools.items():
        assert tool.description, f"{name} has no description"
        assert tool.inputSchema and tool.inputSchema.get("properties"), f"{name} has no input schema"
        assert tool.outputSchema, f"{name} has no output schema"


@pytest.mark.anyio
async def test_tool_input_schemas_declare_the_documented_arguments(mcp_server):
    async with create_connected_server_and_client_session(mcp_server) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}

    assert set(tools["get_results"].inputSchema["properties"]) == {"ocd_id", "election_date", "contest"}
    assert set(tools["get_results"].inputSchema["required"]) == {"ocd_id", "election_date"}
    assert set(tools["list_adapters"].inputSchema["properties"]) == {"state"}
    assert not tools["list_adapters"].inputSchema.get("required")
    assert set(tools["compare_sources"].inputSchema["properties"]) == {"ocd_id", "contest", "election_date"}
    assert set(tools["compare_sources"].inputSchema["required"]) == {"ocd_id", "contest"}


@pytest.mark.anyio
async def test_output_schemas_retain_status_authority_freshness_and_conflict_fields(mcp_server):
    async with create_connected_server_and_client_session(mcp_server) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}

    defs = tools["get_results"].outputSchema["$defs"]
    race_fields = set(defs["Race"]["properties"])
    assert {"race_status", "certification_status"} <= race_fields          # status
    assert {"source", "sources", "field_provenance"} <= race_fields        # authority
    assert "last_synced_at" in race_fields                                 # freshness

    row_fields = set(defs["ResultRow"]["properties"])
    assert {"result_type", "is_winner"} <= row_fields                      # status
    assert {"source_url", "certified_at"} <= row_fields                    # authority / freshness
    assert "jurisdiction_fragment" in row_fields                           # partial reporting

    comparison_fields = set(tools["compare_sources"].outputSchema["$defs"]["SourceComparison"]["properties"])
    assert {"conflict", "vote_count_delta", "baseline_present", "comparison_present"} <= comparison_fields

    assert "as_of" in tools["list_adapters"].outputSchema["properties"]     # freshness


@pytest.mark.anyio
async def test_calling_an_unknown_tool_is_rejected(mcp_server):
    async with create_connected_server_and_client_session(mcp_server) as session:
        result = await session.call_tool("propose_results", {"payload": {}})

    assert result.isError
