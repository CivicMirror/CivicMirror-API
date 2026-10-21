# CivicMirror MCP Server

Read-only MCP server for querying the CivicMirror DRF API from Claude Code,
Claude Desktop, or any MCP client. Phase 1 of the MCP roadmap (#42, hardening in #196).

Three tools, stdio transport, HTTP `GET` only. No write tool, no remote transport,
and no direct reading of Civic-Data files — those are later phases (#197–#200).

## Setup

From the repository root:

```bash
python -m venv .venv-mcp
source .venv-mcp/bin/activate
python -m pip install -r mcp_server/requirements.txt
```

The SDK requirement is pinned to `mcp>=1.10,<2`: `FastMCP` lives at
`mcp.server.fastmcp` in the 1.x SDK and moved in 2.x, so an unpinned install
aborts the server at import time.

Configure the target API:

```bash
export CIVICMIRROR_API_BASE_URL="http://127.0.0.1:8000/api/v1"
export CIVICMIRROR_MCP_API_KEY="your-local-or-production-api-key"
export CIVICMIRROR_MCP_TIMEOUT=30   # optional, seconds
```

`CIVICMIRROR_MCP_API_KEY` holds your service API key. Use a CivicMirror **service API key**
(a `read` key is enough, since all tools are read-only). See `docs/api/API-Reference.md` →
Authentication for how to request one. Your key's rate limit and revocation apply to MCP
requests too. The key is sent as `X-Api-Key` and never appears in tool output or error text.

`get_results` and `compare_sources` read `/races/`, which requires a key. `list_adapters`
reads `/coverage/sync-status/`, which is public — it answers without a key.

> **Coming soon:** a hosted CivicMirror MCP server for approved developers (#200). It will accept the
> same service API keys, so no local install will be needed.

## Run

```bash
python -m civicmirror_mcp.server
```

Run it from the repository root (the package is imported from there), or set
`PYTHONPATH` to the repository root.

## Claude Code registration

The repository ships a project-scoped `.mcp.json`, so with the two environment
variables exported, Claude Code offers the `civicmirror-api` server when you open
this repository — nothing else to run. Verify with `claude mcp list`, which should show
`civicmirror-api … ✔ Connected`.

`CIVICMIRROR_MCP_API_KEY` must be exported before Claude Code starts; with it unset the
server still loads but every `/races/` call fails authentication (`list_adapters` keeps
working, since sync-status is public). If you registered this server by hand in an earlier
session, `claude mcp list` will report conflicting scopes — drop the old entry with
`claude mcp remove civicmirror-api -s local`.

To register it yourself instead (local scope, absolute paths):

```bash
claude mcp add civicmirror-api \
  --env PYTHONPATH=/path/to/CivicMirror-API \
  --env CIVICMIRROR_API_BASE_URL=http://127.0.0.1:8000/api/v1 \
  --env CIVICMIRROR_MCP_API_KEY="$CIVICMIRROR_MCP_API_KEY" \
  -- /path/to/CivicMirror-API/.venv-mcp/bin/python -m civicmirror_mcp.server
```

Pass the key by shell expansion as shown; do not paste the literal key into a
committed file or a shell history entry.

## Tools

- `get_results(ocd_id, election_date, contest=None)` — races and official result rows for an OCD
  jurisdiction on an election date. `ocd_id` must contain a `state:xx` segment.
- `list_adapters(state=None)` — registered results-adapter states, per-state sync status and
  coverage tiers from `/coverage/sync-status/`, with `as_of` as the snapshot's freshness.
- `compare_sources(ocd_id, contest, election_date=None)` — one contest's result rows across every
  source CivicMirror holds, with per-candidate vote-count and vote-percent deltas.

All three publish JSON input **and output** schemas (`civicmirror_mcp/schemas.py`). Each response
preserves what CivicMirror knows about the data's standing:

| Dimension | Fields |
|---|---|
| Result status | `race_status`, `certification_status`, `result_type`, `is_winner` |
| Source authority | `source`, `sources`, `source_url`, `field_provenance` |
| Freshness | `last_synced_at`, `certified_at`, `as_of` |
| Partial reporting | `jurisdiction_fragment` (blank = contest total), `contest_total_rows` / `sub_jurisdiction_rows`, `race_status` |
| Source conflict | `comparisons[].conflict`, `vote_count_delta`, `vote_pct_delta`, `baseline_present` / `comparison_present` |

Values the API did not report stay `null`; the server never substitutes a placeholder. A result row
the API left unnamed gets `label: null` and is excluded from `comparisons` rather than matched on an
invented identity, and a record with no reported source is keyed `source:unreported`. Every response
carries a `notes` list spelling out the resulting coverage limits (missing source, unknown freshness,
sub-jurisdiction rows with no contest total, fewer than two sources to compare).

`compare_sources` uses the alphabetically first source key as its baseline, so repeated calls return
the same deltas regardless of API ordering. If `contest` matches more than one race from the same
source (e.g. "commissioner" matching District 1 and District 3), the tool returns an error naming
both offices rather than comparing one district's candidates against another's — narrow `contest`
or pass `election_date`.

## Example queries

- "List CivicMirror adapters for Washington."
- "Get U.S. Senate results for `ocd-division/country:us/state:wa` on `2026-08-04`."
- "Compare sources for County Commissioner in `ocd-division/country:us/state:co/county:mesa`."

## Tests

Client, schema and protocol-level tests (no Django, no database):

```bash
# from the repository root, in an env with mcp installed
PYTHONPATH=. python -m pytest mcp_server/tests -p no:django
```

End-to-end stdio test against a live API and a real `read` service key:

```bash
cd backend
python -m pytest api/tests/test_mcp_stdio_integration.py
```

The integration test starts `python -m civicmirror_mcp.server` as a subprocess, speaks MCP over
stdio, mints a `read` key, and drives all three tools against a Django live server. It skips
automatically when the MCP SDK is absent. Both suites run in CI (`.github/workflows/ci.yml`).
