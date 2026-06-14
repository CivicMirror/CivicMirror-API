# ADR-009: Washington VoteWA Election, Race, and Results Adapter

## Status
Proposed - 2026-06-12

## Context

Washington has enough public election infrastructure to support a full CivicMirror state adapter, but the data is split across several official surfaces:

- `results.votewa.gov` exposes a public, anonymous JSON results API used by the public results application.
- `sos.wa.gov` election archive and election-specific data pages expose official election, result, data, voter pamphlet, and file-download links.
- `voter.votewa.gov` exposes public candidate-list pages, but its `portal2023/login.aspx` flow is a voter portal and should not be used for public ingestion.
- `data.wa.gov` / PDC exposes a structured candidate disclosure dataset (`3h9x-7bvm`) that is useful for candidate and local-office enrichment, but it is not an election-results feed.

The repository already contains:

- `backend/results/adapters/wa.py`, a thin `EnhancedVotingAdapter` wrapper with `state_name = "washington"` and base URL `https://results.votewa.gov/results/public/api`.
- `backend/results/adapters/enhanced_voting.py`, a generic adapter that reads `Election.source_metadata["enr_slug"]`, fetches `/elections/{state_name}/{slug}` and `/data`, and normalizes top-level `ballotItems[]`.
- `backend/integrations/wa_pdc/`, a PDC enrichment task for matching PDC candidate records to existing WA candidate rows.
- `backend/results/tasks.py`, which can bootstrap Race, Candidate, and MeasureOption rows from result adapter output if an election has no races.

The WA research folder contains two different HAR captures that must be treated differently:

- `results.votewa.gov.har` captured the public results application at `https://results.votewa.gov/results/public/washington/elections/20260428`.
- `voter.votewa.gov.har` captured the voter-portal login flow at `https://voter.votewa.gov/portal2023/login.aspx`.

The public results HAR confirms reusable API endpoints:

```text
GET /results/public/api/elections/{jurisdictionSlug}/{yyyymmdd}
GET /results/public/api/elections/{jurisdictionSlug}/{yyyymmdd}/data
GET /results/public/api/elections/{jurisdictionSlug}/{yyyymmdd}/data/ballot-item/{ballotItemId}
GET /results/public/api/elections/{jurisdictionSlug}/{yyyymmdd}/closeraces
```

For the captured April 28, 2026 special election, the state-level data endpoint returned:

- `jurisdiction` with `shortName`, `childLocalities`, and `mediaExportPath`.
- `election` with `id`, `electionDate`, `asOf`, `lastUpdated`, `isOfficialResults`, report metadata, and count/status fields.
- `localityElections[]` for 15 participating counties.
- `ballotItems[]` for aggregate contests.
- `statistics[]`, `voterRegistration[]`, and an empty state-level `voterTurnout[]`.

The Mason County locality endpoint returned the same top-level shape, but with county-local `ballotItems[]`, 16 `precincts[]`, and 16 `voterTurnout[]` rows. A statewide ballot-item drilldown returned `ballotItemWithBreakdown.breakdownResults[]`, linking aggregate contests to county-local contest IDs via `parentBallotItemId`.

The voter-portal HAR confirms the wrong boundary: it contains static UI JSON and inferred personalized voter-data endpoints keyed by a voter identifier. Those endpoints must stay out of scope for public election/race/results ingestion.

### Requirements

- Discover or seed WA Election records without manual admin-only configuration.
- Populate `Election.source_metadata["enr_slug"]` with the public VoteWA route key, for example `20260428`.
- Ingest races from VoteWA `ballotItems[]`, including both candidate contests and ballot measures where present.
- Ingest results from VoteWA summary rows and preserve official/unofficial status from `isOfficialResults`.
- Support county fan-out for local contests, county-level totals, and precinct/turnout metadata where the public API exposes it.
- Use PDC as candidate and local-office enrichment, not as the primary results authority.
- Avoid voter-specific VoteWA portal endpoints and any data requiring voter identity or approval.
- Follow the existing `integrations/*` plus `results/adapters/*` patterns and aggregation ingest service.

### Constraints

- The captured public results election only included ballot measures; candidate contest payloads are inferred from the same `ballotItems[]` / `ballotOptions[]` model and existing Enhanced Voting adapter behavior, but not directly observed in this WA HAR.
- VoteWA identifiers are scope-relative: state aggregate ballot-item IDs, county-local ballot-item IDs, and option IDs can differ for the same contest.
- Statewide aggregate summary fields are not always internally consistent; concrete arrays and locality rows are more reliable than broad count fields.
- The public results API is not documented as a stable contract; build conservative parsing, schema tests, and payload retention in `raw_payload`.
- `voter.votewa.gov` portal login endpoints may expose personalized voter/ballot state and must not be probed for ingestion.

## Decision

Build Washington as a dedicated `wa_votewa` integration for election and race discovery, paired with an enhanced WA results adapter for results ingestion.

### Module structure

```text
backend/integrations/wa_votewa/
    __init__.py
    apps.py
    client.py        # SOS archive discovery + VoteWA public API client
    mappers.py       # Election, Race, Candidate, MeasureOption mapping
    tasks.py         # sync_wa_elections, sync_wa_races
    exceptions.py
    tests/
        test_client.py
        test_mappers.py
        test_tasks.py
```

Keep `backend/integrations/wa_pdc/` as a separate enrichment module. Do not merge PDC disclosure logic into the VoteWA integration.

### Election discovery

Use the SOS election archive and known public VoteWA route patterns to seed WA elections:

```text
https://www.sos.wa.gov/elections/data-research/election-data-and-maps/election-results-and-voters-pamphlets
https://results.votewa.gov/results/public/washington/elections/{yyyymmdd}
```

For each discovered election:

- Upsert `Election` through `aggregation.ingest.ingest_election`.
- Use source `wa_votewa`.
- Use source ID `wa_votewa:{yyyymmdd}`.
- Store `source_metadata.enr_slug = "{yyyymmdd}"`.
- Store `source_metadata.votewa_jurisdiction_slug = "washington"`.
- Store SOS archive/data/candidates/voters-guide URLs when discovered.
- Set `status` from election date and result availability.

The first implementation may seed known 2026 election dates from SOS calendar research while archive crawling is hardened. Manual seed lists should be isolated in `mappers.py` or a small constant, not embedded in the result adapter.

### Race and candidate discovery

Implement `sync_wa_races(election_pk)` against:

```text
GET https://results.votewa.gov/results/public/api/elections/washington/{yyyymmdd}/data
```

Map each `ballotItems[]` entry to a Race:

- `contestType == "BallotMeasure"` maps to `Race.RaceType.MEASURE`.
- Other contest types map to `Race.RaceType.CANDIDATE`.
- Store `source_metadata.votewa_ballot_item_id`.
- Store `source_metadata.votewa_parent_id` when present.
- Store `source_metadata.votewa_jurisdiction_slug`.
- Preserve full raw ballot item metadata needed for future county/precinct reconciliation.

For candidate contests, map `summaryResults.ballotOptions[]` to Candidate rows when present. For ballot measures, map options to `MeasureOption`. Candidate ingestion from VoteWA should be implemented with tests using synthetic candidate payloads until a primary/general HAR confirms real WA candidate contests.

After candidate rows exist, call or schedule `sync_wa_pdc_candidates(election_id)` as enrichment. PDC matching should improve contact/campaign metadata and local-office context, but VoteWA/SOS remains the authoritative source for election-specific race/result identity.

### Results ingestion

Keep `backend/results/adapters/wa.py` registered as the WA results adapter, but evolve WA behavior beyond the generic top-level Enhanced Voting parse.

The initial adapter path may continue to fetch:

```text
GET /results/public/api/elections/washington/{yyyymmdd}
GET /results/public/api/elections/washington/{yyyymmdd}/data
```

However, WA-specific logic should add:

- Version detection from `asOf` first, falling back to `lastUpdated`.
- County fan-out using `jurisdiction.childLocalities[]` or `localityElections[]`.
- County data fetches for participating localities:

```text
GET /results/public/api/elections/{countySlug}/{yyyymmdd}/data
```

- Aggregate contest drilldowns for county breakdowns:

```text
GET /results/public/api/elections/washington/{yyyymmdd}/data/ballot-item/{aggregateBallotItemId}
```

- Explicit raw IDs in `ResultRow.raw`, including aggregate ballot item ID, county-local ballot item ID, option/native ID, jurisdiction slug, and parent IDs.
- `jurisdiction_fragment` for county-scoped rows when emitting county breakdowns.

Do not rely on statewide summary count fields alone. Prefer concrete `ballotItems[]`, `localityElections[]`, `breakdownResults[]`, county `precincts[]`, and county `voterTurnout[]`.

### Precinct and turnout data

Treat precinct and turnout ingestion as a second phase inside the WA integration, not as part of the first `OfficialResult` path. The captured county data proves precinct rows and turnout rows exist, but the current `OfficialResult` model is candidate/measure result oriented and does not yet model precinct turnout as a first-class result artifact.

Store precinct/turnout plans in source metadata or defer to a future model/ADR if CivicMirror needs precinct-level reporting beyond raw payload retention.

### Voter portal boundary

Do not use these inferred or observed voter portal endpoints for adapter ingestion:

```text
https://voter.votewa.gov/portal2023/json/voters/{voter}.json
https://voter.votewa.gov/portal2023/jsonhandler.ashx?v={voter}
```

The public static portal files (`links.json`, `locales.json`, `sidebars.json`) may be inspected for navigation context, but they are not election/race/results sources.

## Justification

- The public VoteWA results HAR confirms the same endpoint family already used by the generic Enhanced Voting adapter, so WA can reuse existing code while adding state-specific county/locality handling.
- A dedicated `wa_votewa` integration matches the VA pattern: use an integration module to discover elections and races, then use the results adapter for vote totals.
- SOS archive pages are the right source for election discovery and official links; they avoid requiring manual `Election.source_metadata["enr_slug"]` entry.
- PDC is valuable but semantically different. It covers disclosure and candidacy records across state and local offices; it should enrich candidates after VoteWA/SOS establishes election-specific race identity.
- Explicitly excluding the voter portal reduces privacy risk and prevents the adapter from depending on personalized or login-adjacent endpoints.
- County fan-out is necessary because VoteWA IDs are scope-relative and local contests live below county jurisdiction slugs.

## Consequences

### Positive

- WA can move from a thin results-only wrapper to a full election/race/results integration.
- `poll_pending_results` can ingest WA results once `Election.source_metadata["enr_slug"]` is populated.
- Race bootstrapping remains available as an early fallback, but regular scheduled syncs can create higher-confidence races and candidates before election night.
- County-local contests and county breakdowns are supported by design instead of being flattened accidentally.
- PDC enrichment can improve candidate contact/campaign metadata without taking over result authority.

### Negative

- Requires a new integration module and tests.
- Candidate contest mapping remains partly inferred until a WA primary/general public results capture verifies candidate payloads directly.
- County fan-out increases request volume and requires careful polling cadence.
- Current result models do not fully represent precinct turnout or precinct-level contest results; raw retention or a future model is needed for that detail.
- Public VoteWA API shapes are undocumented, so schema drift must be handled defensively.

## Alternatives Considered

### Keep only the existing thin WA results adapter

Rejected. The current adapter can parse top-level `ballotItems[]` when `enr_slug` is manually populated, but it does not discover elections, create races ahead of time, fan out to counties, or preserve the state/county contest hierarchy confirmed by the HAR.

### Use PDC as the primary WA race and candidate adapter

Rejected. PDC is structured and broad, especially for local offices, but it is a disclosure/candidacy dataset. It does not provide election-night result totals and does not cleanly replace VoteWA/SOS election-specific ballot item identity.

### Build against the VoteWA voter portal

Rejected. The voter portal HAR captured login/static UI behavior and inferred personalized voter endpoints. Those are not public election results surfaces and create avoidable privacy and maintenance risk.

### Use only SOS XLSX/ZIP download files

Deferred. SOS downloads are a strong official fallback and validation source, especially for certified historical data, but the public VoteWA results API provides fresher election-night data, county fan-out, and a consistent JSON shape. Use SOS downloads for discovery, validation, and future certified-file imports rather than as the only first implementation.

### Add WA-specific complexity to the generic `EnhancedVotingAdapter`

Rejected for the first pass. Virginia and Washington share the Enhanced Voting API family, but WA's county hierarchy and scope-relative IDs require behavior that may not apply cleanly to VA. Keep generic parsing small and put WA-specific fan-out in `WashingtonAdapter` or `integrations.wa_votewa`.

## Implementation Plan

1. Add `backend/integrations/wa_votewa/` with a client for SOS archive discovery and VoteWA public API calls.
2. Implement election seeding with `enr_slug = yyyymmdd` and `votewa_jurisdiction_slug = washington`.
3. Implement race and option/candidate mapping from state-level `ballotItems[]`.
4. Add WA-specific tests using fixtures derived from `results.votewa.gov.har` for election metadata, state data, county data, and ballot-item drilldown.
5. Extend `WashingtonAdapter` to support WA version detection, county fan-out, and raw ID preservation.
6. Schedule PDC enrichment after WA candidate rows exist.
7. Capture or add a fixture from a WA primary/general candidate contest before marking candidate ingestion as full-confidence.
8. Validate `https://results.votewa.gov/cdn/results/{mediaExportPath}` as a possible bulk-export optimization after the basic API path works.

## Testing Notes

- Unit tests should mock HTTP; no network calls in CI.
- Use small JSON fixtures extracted from `results.votewa.gov.har` rather than checking in large HAR-derived payloads.
- Test that `voter.votewa.gov` portal endpoints are not used by the WA client.
- Test scope-relative IDs: aggregate ballot item ID, county-local ballot item ID, and `parentBallotItemId`.
- Test cache behavior when `asOf` is unchanged.
- Test ballot-measure rows and synthetic candidate rows separately until candidate contests are directly captured.
