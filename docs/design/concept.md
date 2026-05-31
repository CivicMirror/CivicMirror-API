---
date: 05/17/2026
developer: Walter LeFort
ai_tools: Copilot Pro, Claude, ChatGPT
companion_app: https://github.com/tokendad/CivicMirror
---

# Election Data Aggregator — Concept

> ✅ **Status: Production** — API deployed to Cloud Run (`civicmirror-api` + `civicmirror-worker`); all Phase 1–6 work complete. This document is the original concept; see `docs/design/BUILD-PLAN.md` for the full phased delivery history.

## Purpose

The purpose of this project is to provide a normalized source of election and ballot data for the [CivicMirror](https://github.com/tokendad/CivicMirror) web app.

## AI Prompt

> Source election and ballot data from multiple free sources for federal, state, and local contests, and normalize that data into an aggregate API for CivicMirror and possibly public use.

---

## Data Points

The following data points are not a complete list, but represent minimum standards when sourcing data.

- **Elections**
  - Primary
    - Open
    - Closed
    - Non-Partisan
  - General
  - Special
  - Mid-Term
  - Party
- **Ballot Measures**
  - Resolutions
  - Referendums
  - Direct
  - Indirect
- **Candidates**
  - General Information
    - Contact Information
    - Website
    - Phone
  - Party Affiliation
  - CV / Résumé
  - Platform Statement
- **Officials**
  - Incumbent Status
  - Office Currently Held
  - District Represented
  - Term Start / End Dates
- **Districts & Jurisdictions**
  - Federal (House, Senate, Presidential)
  - State (Legislative, Gubernatorial)
  - Local (County, Municipal, School Board, Special District)
  - Geographic Boundaries (GeoJSON / FIPS codes)

---

## Data Sources

The following are target sources for aggregation. This list is not exhaustive and will evolve as the project matures.

| Source | Coverage | Format | Notes |
|---|---|---|---|
| [Google Civic Information API](https://developers.google.com/civic-information) | Federal, State, Local | REST/JSON | Election & rep data by address |
| [OpenStates API](https://openstates.org/api/v3/) | State Legislative | REST/JSON | Bills, legislators, votes |
| [Ballotpedia](https://ballotpedia.org/API_documentation) | Federal, State, Local | REST/JSON | Candidate & ballot measure data |
| [OpenFEC (FEC API)](https://api.open.fec.gov/developers/) | Federal | REST/JSON | Campaign finance, candidates, filings |
| [MIT Election Data Lab](https://electionlab.mit.edu/data) | Federal, State | CSV/JSON | Historical results |
| [EAVS (EAC)](https://www.eac.gov/research-and-data/election-administration-voting-survey) | State | CSV | Election admin statistics |
| [Clarity Elections (SOE Software)](https://www.soesoftware.com/product/clarity-election-night-reporting/) | State, Local | XML/JSON | Live ENR for 40+ states via `results.enr.clarityelections.com` |

---

## Clarity Elections — Results Ingestion

[Clarity Elections](https://www.soesoftware.com/product/clarity-election-night-reporting/) (by SOE Software, now Scytl) powers election night reporting for roughly 40 states and hundreds of counties. Results sites are recognizable by URLs beginning with `https://results.enr.clarityelections.com/{STATE}/{electionId}/`.

### How Clarity Works

Results are published in two formats:
- **ZIP + XML** (`detailxml.zip`) — full precinct-level detail; the canonical format
- **JSON API** — summary-level results; lighter weight, good for live polling

The data version is exposed at `/{state}/{electionId}/current_ver.txt`. Always fetch this first and re-fetch the data only when the version changes (efficient live polling).

### Useful Libraries

| Repo | PyPI | Description |
|---|---|---|
| [`openelections/clarify`](https://github.com/openelections/clarify) | `clarify` | Discovers sub-jurisdiction URLs and parses Clarity XML into Python objects (`Jurisdiction`, `Parser`, `Contest`, `Result`). Handles state → county → precinct hierarchy. |
| [`washingtonpost/elex-clarity`](https://github.com/washingtonpost/elex-clarity) | `elex-clarity` | CLI tool for fetching and formatting Clarity results at state, county, or precinct level; outputs normalized JSON; supports local file parsing for testing. |

> **Note:** [`clearcontracts.github.io/clarity-api`](https://clearcontracts.github.io/clarity-api/) documents a blockchain/DAO governance platform that also uses the "Clarity" name — it is **not** related to election night reporting.

### Integration Strategy

- Use `clarify` (`Jurisdiction` class) to walk the state → county → precinct hierarchy and locate `detailxml.zip` URLs for detailed results
- Use `elex-clarity` as a reference implementation for JSON-based live polling and result normalization
- Cache `current_ver.txt` value; skip re-fetch if unchanged (reduces load, avoids rate limits)
- Result type should be `UNOFFICIAL` during live reporting; only promote to `OFFICIAL` via an explicit admin action or a confirmed certification signal

### States Known to Use Clarity

WV, CO, IA, SC, GA (partial), and others. Access varies — some states return 403; consult `docs/state-research/` for per-state access status.

---

## Normalization Strategy

The goal is to ingest data from heterogeneous sources and output a unified, queryable API.

### Output Format
- **REST API** with JSON responses (primary)
- Potential **GraphQL** endpoint for CivicMirror front-end flexibility

### Key Normalization Goals
- Standardize jurisdiction identifiers using **FIPS codes** and **OCD-IDs** (Open Civic Data Division Identifiers)
- Map source-specific election types to a common taxonomy (e.g., "primary," "general," "special")
- Deduplicate candidates appearing across multiple sources using name + district + party matching
- Normalize dates to **ISO 8601** format

### Intended Consumers
- CivicMirror web app (primary)
- Potential public API endpoint (future)

---

## Scheduled Ingestion

Background data ingestion uses **Google Cloud Scheduler** (not Celery Beat) to trigger jobs via authenticated HTTP POST to internal Django endpoints. This is required for Cloud Run compatibility — Celery Beat is a long-running process that does not survive Cloud Run scale-to-zero events.

| Job | Endpoint | Interval |
|---|---|---|
| Election sync | `POST /internal/tasks/sync-elections/` | Every hour |
| Results polling | `POST /internal/tasks/poll-results/` | Daily 06:00 UTC |

Cloud Scheduler authenticates using OIDC (GCP service account). Local development uses a shared secret fallback (`INTERNAL_TASK_TOKEN` env var). Celery workers handle actual task execution and run as a separate Cloud Run service.

See **ADR-002** for the full scheduler architecture, security model, idempotency strategy, and local dev setup.

---

## Deployment Target

The API is a **standalone service** (separate from the CivicMirror front-end app), following the same pattern as the SeaQuacks project: a dedicated API container runs alongside the main application.

| Component | Google Cloud service |
|---|---|
| Django/DRF API | Cloud Run (HTTP service) |
| Celery workers | Cloud Run (min-instances=1) or Cloud Run Jobs |
| PostgreSQL | Cloud SQL |
| Redis (Celery broker) | Cloud Memorystore |
| Scheduled triggers | Cloud Scheduler (OIDC) |
| Secrets | Secret Manager |

Local development uses `docker-compose.dev.yaml` with PostgreSQL, Redis, Django, and Celery worker — matching the SeaQuacks local compose pattern.

---

## Roadmap

- [x] Define canonical data schema / JSON structure
- [x] Prototype ingestion pipeline for Google Civic API
- [x] Add OpenStates and FEC adapters *(Ballotpedia: no free API found)*
- [x] Build normalization / deduplication layer *(aggregation ingest service — Phase 2)*
- [x] Expose unified REST API
- [x] CivicMirror integration
- [ ] Public API documentation

--- 
## Summary Table Design

**Primary Function is State and Federal data,  But community/Local/Town Data is always a plus.**

- Elections: Source of data for Elction information,  Date, Time, Candidates, 
- Races: Source The individual Contest per Election, Senator, Auditor, Clerk...etc
- Comminuity:  Sources for Local towns and citys.  Complete coverage would mean the entire state is covered.  Partial Would me towns and communities would be covered.  *Design note: add a percentage of coverage here possible?*
- Ballots: Ballots information has been sourced
- Live:  Access to live results during an active election
- Results: Official published results 
- Candidate Info:  Source of Information about specific Candidate(contact information, images, phone, website...)
- 