# ADR-007: Phase 3 State Expansion Strategy

## Status
Accepted — 2026-05-31

## Context

Phase 2 of the aggregation migration is complete. Every existing state adapter (CA, WV, CO, SC, MA, VA, IA) routes through the normalize-on-write ingest service. The next step is extending coverage to the remaining 40+ US states.

The challenge is that states vary enormously in data quality:
- A few have full REST APIs with JSON election + race + candidate data
- ~35 states use Clarity Elections (ENR) for live results but provide race/candidate data only as PDFs or web tables
- Some have structured FTP or Socrata feeds
- Many have only PDF downloads or human-readable web portals

Building a full SOS adapter for every state is not practical in a single sprint. A tiered approach is needed.

The summer 2026 primary wave (NJ June 3, NY June 25, AZ July 28, WA/MI August 4, FL August 18) provides a concrete near-term deadline.

### Requirements
- Results coverage for major summer 2026 primary states before each primary date
- Statewide races as primary focus; county-level when the state portal provides it in the same feed
- New state integrations must use the existing aggregation ingest service (`ingest_election/race/candidate`)
- Low-effort path for states that only need results (not full election/race discovery)

### Constraints
- Single developer; cannot build full adapters for 40+ states simultaneously
- No budget for paid data sources
- All adapters must pass existing test patterns (`pytest --no-migrations`)

## Decision

### 1. Three-Tier Adapter Model

Use effort proportional to available data quality:

**Tier A — Clarity-only results adapter** (`results/adapters/XX.py`, 2 lines)
- For states running Clarity ENR where Civic API already provides elections and races
- Inherits all logic from `ClarityAdapter`; requires only `results_url` per election in Django admin
- ~1–2 hours per state

**Tier B — Full SOS adapter** (`integrations/XX_sos/` + results adapter)
- For states with a structured programmatic source (REST API, FTP, Socrata)
- Follows the IA/CO two-stage task pattern: Stage 1 = election discovery, Stage 2 = race/candidate population
- ~2–5 days per state

**Tier C — Civic-only** (no new code)
- For states with no machine-readable source
- Civic API populates elections and races wherever Google VIP data exists
- Do not build screen scrapers or brittle PDF parsers for these states

### 2. Source Precedence Defaults for New States

All new states follow the established pattern:
- State SOS wins `results` and `date` (rank 0)
- Civic API wins `contacts` (rank 0) — state portals never provide candidate contact info
- Civic API wins `identity` (rank 0) for states with Civic VIP coverage (more complete OCD IDs, office normalization)
- If a state has no Civic VIP coverage, flip identity so state SOS wins (rank 0)

### 3. Local Election Scope

Include county/local races **only when the state portal exposes them in the same data feed** as state races — no additional HTTP calls, no separate parsers. Do not build separate local-only adapters in Phase 3.

### 4. Clarity Verification Before Build

Always probe the live endpoint before creating a Tier A adapter:
```bash
curl -s "https://results.enr.clarityelections.com/{STATE}/{electionId}/current_ver.txt"
```
A version string confirms Clarity. Only create the adapter after confirmation. Never assume a state uses Clarity from documentation alone.

### 5. Results-First Prioritization

A Tier A results adapter has immediate value even without a full SOS adapter — `poll_pending_results` fires nightly and will pick up results for any election already in the DB (from Civic API). Ship Tier A adapters before waiting for Tier B work.

## Consequences

### Positive
- Clarity sweep can add live results coverage for ~15–20 states in a single sprint (1–2 hours each)
- Full SOS adapters are built only where data quality justifies the investment
- Consistent adapter pattern across all states — new contributors can use IA or CO as a reference and follow the same structure
- Local elections are naturally included for states where the portal provides them (IA, CO already demonstrate this) without extra complexity

### Negative
- Tier C states (no programmatic source) get elections only when Civic API has VIP data, which is incomplete for many state primaries
- Tier A states have results but no race/candidate metadata until a full adapter is built — results will match races that Civic created, which may be incomplete
- `results_url` per election must be set manually in Django admin for Clarity states — no auto-discovery

## Alternatives Considered

### Universal Clarity-first for all states
Build Clarity adapters for every state immediately regardless of verification. Rejected because ~15 states were confirmed NOT on Clarity (returned 404), and building unverified adapters creates dead code.

### Scraper-based adapters for Tier C states
Build HTML scrapers for states with no API. Rejected — scrapers are fragile, break silently, and create maintenance burden exceeding their value for states with low election volume.

### Single phased rollout (all states in one PR)
Ship all states at once. Rejected — too large to review, debug, or roll back; primary deadlines require incremental delivery.

## Implementation Plan

See `docs/design/Phase3-State-Expansion.md` for the full prioritized state list, implementation checklist per tier, and verification steps.
