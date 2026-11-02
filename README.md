# CivicMirror API

Election data aggregation and normalization platform. Ingests results from multiple public sources, normalizes them using FIPS codes and OCD-IDs, and serves a unified REST API for the [CivicMirror](https://github.com/tokendad/CivicMirror) web app.

## CivicMirror 2.0 development

CivicMirror 2.0 requires Python `>=3.13,<3.14`. Host Python 3.14 is not
supported; use a repository-managed Python 3.13 environment or the development
container.

Run the canonical foundation verification from the repository root:

```bash
make verify-v2
```

Start the isolated development API with:

```bash
docker compose -f docker-compose.v2.yaml up -d db redis api
```

The API listens on `0.0.0.0:58000` by default and is available at
`http://127.0.0.1:58000/api/v2/health/` or, on the current development host,
`http://192.168.1.102:58000/api/v2/health/`. Set
`CIVICMIRROR_V2_API_PORT` or `CIVICMIRROR_V2_LAN_HOST` in the shell before the
Compose command if the host port or LAN address changes. Only the API port is
published; the 2.0 Postgres and Redis services remain private to the Compose
network.

The Compose project, database, test database, volumes, Redis databases, and
Celery queue are all 2.0-specific. The existing `docker-compose.dev.yaml` and
legacy Django settings remain separate.

---

## At a Glance — State Coverage

Use this table to identify the next best integration target. States with multiple ⚠️ columns and a clear public data source are the highest-value additions.

| Symbol | Meaning |
|---|---|
| ✅ | Complete — dedicated state integration working |
| ⚠️ | Partial — cross-cutting sources only (Google Civic API / OpenStates / OpenFEC) |
| ❌ | Not yet implemented |

> **Base coverage for all states via cross-cutting integrations:**
> Elections (Google Civic API) · Races (OpenStates) · Candidate Info (OpenStates — state legislative candidates, all 50 states)

---

## State Coverage

| State | Elections | Races | Community | Ballots | Live | Results | Candidate Info |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **AK** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **AL** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **AR** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **AZ** | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **CA** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **CO** | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **CT** | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ | ✅ |
| **DE** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **FL** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **GA** | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ | ✅ |
| **HI** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **IA** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **ID** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **IL** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **IN** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **KS** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **KY** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **LA** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **MA** | ✅ | ✅ | ⚠️ | ✅ | ❌ | ✅ | ✅ |
| **MD** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **ME** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **MI** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **MN** | ⚠️ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **MO** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **MS** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **MT** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **NC** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **ND** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **NE** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **NH** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **NJ** | ⚠️ | ⚠️ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **NM** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **NV** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **NY** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **OH** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **OK** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **OR** | ✅ | ✅ | ⚠️ | ⚠️ | ❌ | ⚠️ | ✅ |
| **PA** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **RI** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **SC** | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **SD** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **TN** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **TX** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **UT** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **VA** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **VT** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **WA** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **WI** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **WV** | ⚠️ | ⚠️ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **WY** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |

---

## Column Definitions

| Column | Description |
|---|---|
| **Elections** | Election metadata — date, type, jurisdiction |
| **Races** | Individual contests per election (Senator, Auditor, Clerk, etc.) |
| **Community** | Local/town/city coverage (⚠️ = select municipalities; ✅ = statewide) |
| **Ballots** | Ballot measures — referendums, initiatives, questions |
| **Live** | Live results feed during an active election night |
| **Results** | Official certified results post-election |
| **Candidate Info** | Candidate contact, images, phone, website, platform |

---

## Priority Targets

States closest to a full ✅ row based on available public data:

| State | Opportunity | Source |
|---|---|---|
| **MD** | Stage 1 + results shipped; pending production verification to confirm Full Core | Maryland SBE |
| **NJ** | Results adapter built (multi-county Clarity); add Stage 1 (native election/race creation) to drop Civic API reliance | NJ county Clarity portals |
| **CA** | Results adapter built; add Stage 1 — note results are currently down (issue [#88](https://github.com/CivicMirror/CivicMirror-API/issues/88), CA SOS ENR API 500s) | CA SOS |
| **KY** | Add certified recap/live results ingestion to existing SOS race/candidate adapter; blocked on Akamai bot-protection 403 (issue [#44](https://github.com/CivicMirror/CivicMirror-API/issues/44)) | Kentucky SOS recaps / election-night portal |
| **TN** | Stage 1 + certified results shipped; live election-night dashboard still needs endpoint discovery | Tennessee SOS / ENR |

> Tracking issue [#87](https://github.com/CivicMirror/CivicMirror-API/issues/87) tracks the wave of migrations from Results-Coverage-Only / Near Core to Full Core Coverage.
> See [`docs/state-research/COVERAGE-ANALYSIS-RESULTS.md`](docs/state-research/COVERAGE-ANALYSIS-RESULTS.md) for the full source analysis on all 48 researched states.

---

## MCP Server

This repo includes a read-only Python MCP server for querying the CivicMirror DRF API from MCP clients.
See [`mcp_server/README.md`](mcp_server/README.md) for setup, Claude Code stdio registration, and example queries.

---

*Last updated: 2026-07-22*
