# CivicMirror MCP Server

Read-only MCP server for querying the CivicMirror DRF API from Claude Code,
Claude Desktop, or any MCP client.

## Setup

From the repository root:

```bash
python -m venv .venv-mcp
source .venv-mcp/bin/activate
python -m pip install -r mcp_server/requirements.txt
```

Configure the target API:

```bash
export CIVICMIRROR_API_BASE_URL="http://127.0.0.1:8000/api/v1"
export CIVICMIRROR_MCP_API_KEY="your-local-or-production-api-key"
```

`CIVICMIRROR_MCP_API_KEY` is preferred for MCP usage. If it is not set, the
server falls back to `CIVICMIRROR_API_KEY`.

## Run

```bash
python -m civicmirror_mcp.server
```

## Claude Code Stdio Registration

Use this command from the repository root, adjusting paths as needed:

```bash
claude mcp add civicmirror-api --env CIVICMIRROR_API_BASE_URL=http://127.0.0.1:8000/api/v1 --env CIVICMIRROR_MCP_API_KEY=your-key -- python -m civicmirror_mcp.server
```

## Tools

- `get_results(ocd_id, election_date, contest=None)`: fetches matching races and official result rows for an OCD jurisdiction on an election date.
- `list_adapters(state=None)`: returns registered results-adapter states and latest sync status from `/coverage/sync-status/`.
- `compare_sources(ocd_id, contest, election_date=None)`: fetches matching contest results and reports vote-count / vote-percent deltas between available sources.

All tools use HTTP `GET` requests only. No write endpoints are exposed.

## Example Queries

- "List CivicMirror adapters for Washington."
- "Get U.S. Senate results for `ocd-division/country:us/state:wa` on `2026-08-04`."
- "Compare sources for County Commissioner in `ocd-division/country:us/state:co/county:mesa`."
