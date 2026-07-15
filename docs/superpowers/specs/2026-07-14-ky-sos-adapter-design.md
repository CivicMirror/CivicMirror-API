# Kentucky SOS Stage 1 Adapter (KY-Elections + KY-Candidates) — Design

**Date:** 2026-07-14
**Branch:** `ky-sos-adapter`
**Source research:** `docs/state-research/KY/KY-Election_Research_UPDATED.md`

## Scope

This spec covers **Stage 1 only**: election discovery + race/candidate creation for
Kentucky federal and state-legislative offices. It intentionally excludes:

- `KY-Ballots` (sample-ballot PDF indexing)
- `KY-Measures` (constitutional amendments)
- `KY-ResultsCertified` (120-county recap PDF parser — separate, larger effort)
- `KY-ResultsLive` (explicitly not to be built — Akamai bot-protection risk, no
  established automation permission per the research doc)
- Judicial office groups (Justice of the Supreme Court, Court of Appeals, Circuit,
  District, Family Court) and the Constitutional Amendment candidate-filing group
- County-filed local candidates
- PDF parsing of the annual election calendar / 2026-2036 schedule (future-election
  discovery deferred; this build only ingests the currently active/upcoming election
  from the HTML summary page)

Each of the above is a candidate for its own future spec/PR, following the same
per-state incremental pattern used for GA, IL, OH, etc. (see project memory
`phase-3-state-expansion-progress`).

## Sources used

- **Upcoming Election Summary** — `https://elect.ky.gov/calendar/Pages/Upcoming-Elections.aspx`
  — server-rendered HTML with election name/date, registration deadline, absentee
  window, early-voting dates.
- **SOS Candidate Filings** — `https://web.sos.ky.gov/CandidateFilings/` — searchable
  HTML application, office-group pages (US Senate, US House, KY Senate, KY House)
  plus a Withdrawn/Deceased/Disqualified group.

Both are official, publicly accessible, server-rendered HTML with no observed bot
restrictions (unlike the live-results system).

## Architecture

New package `backend/integrations/ky_sos/`, following the standard adapter shape
used by `il_sbe`, `oh_sos`, etc.:

```text
ky_sos/
  __init__.py
  apps.py
  client.py        # KentuckySosClient — HTTP fetch only
  parsers.py        # HTML -> raw structured rows/fields
  mappers.py         # raw rows -> ingest_election/ingest_race/ingest_candidate payloads
  exceptions.py       # KySosRetryableError
  tasks.py            # sync_ky_elections, sync_ky_candidates
  tests/
```

Two Celery tasks:

- **`sync_ky_elections`** — fetches the Upcoming Election Summary page, maps it to
  one `Election` via `aggregation.ingest_election`, then queues
  `sync_ky_candidates` for that election.
- **`sync_ky_candidates`** — fetches the Candidate Filings home page for the current
  election, enumerates the four in-scope office-group pages (US Senate, US House,
  KY Senate, KY House), parses each, and ingests races via `aggregation.ingest_race`
  and candidates via `aggregation.ingest_candidate`. Also fetches the
  Withdrawn/Deceased/Disqualified group and updates matching `Candidate` rows to
  `candidate_status = WITHDRAWN` or `DISQUALIFIED`.

## Data flow & normalization

1. `client.py`: plain `requests` GET, standard UA, no auth — `fetch_upcoming_election()`,
   `fetch_candidate_filings(office_group)` for each of the 4 groups, and
   `fetch_withdrawn_group()`.
2. `parsers.py`: BeautifulSoup HTML parsing.
   - Summary page → election name, date, election type, registration deadline,
     absentee request window, early-voting dates.
   - Office-group page → candidate rows: name, running mate (if any), office,
     district/division, party, filed date, candidate-detail link.
   - Withdrawn group → same row shape plus status label (withdrawn / deceased /
     disqualified).
3. `mappers.py`:
   - `map_election(parsed_summary)` → `ingest_election` payload (election_type
     inferred from name, canonical key fields, source URL + retrieval timestamp in
     `source_metadata`).
   - `map_race(office, district_or_division)` → `ingest_race` payload (office title
     built from office + district/division, matching the doc's "office plus
     district/division" race-key rule).
   - `map_candidate(row)` → `ingest_candidate` payload (name, party,
     `source_metadata` with SOS filing URL and filed date).
4. Reconciliation: after active candidates are ingested for a run, the withdrawn
   group is parsed and matched by (race, normalized name) to mark the corresponding
   `Candidate.candidate_status` as `WITHDRAWN` or `DISQUALIFIED` — no new status
   values needed, `Candidate.CandidateStatus` already has both
   (`elections/models.py`).
5. New source choice `Race.Source.KY_SOS = 'ky_sos', 'Kentucky SOS'` added to
   `elections/models.py`, with a migration — mirrors `GA_SOS`, `IL_SBE`, `OH_SOS`,
   etc. already in that enum.

## Error handling

- `exceptions.py`: `KySosRetryableError` for network/5xx failures; unexpected page
  structure raises without retry (surfaces as a task failure rather than silently
  producing bad data).
- Tasks use `@shared_task(bind=True, max_retries=3, default_retry_delay=60)` and log
  via `SyncLog(source="ky_sos", ...)`, matching `il_sbe`/`oh_sos`.
- A parse failure on one office-group page is logged and the task continues to the
  next group rather than aborting the whole run — partial coverage beats total
  failure, consistent with other adapters.

## Scheduling & wiring

- Runs **daily**, matching other Stage-1 adapters. (Research doc notes candidate
  counts can shift during an open filing window; daily polling with
  `ingest_candidate`'s existing upsert/precedence behavior handles that without
  extra logic.)
- Registered in `internal/task_locks.py` `TASK_LOCKS` under the daily window.
- Manual-trigger endpoint added to `internal/views.py`
  (`sync_ky_sos_trigger`), matching the `il_sbe` pattern.
- The actual Cloud Scheduler cron entry is deployment-side and out of scope for
  this code PR — tracked as a follow-up once the adapter is merged.

## Testing

- `tests/` with fixture HTML captured from the research HARs: Upcoming Election
  Summary page, one office-group page (US House, since it has districts 1-6 to
  exercise district parsing), and the Withdrawn/Deceased/Disqualified group.
- Parser unit tests: correct field extraction from each fixture.
- Mapper unit tests: correct `ingest_election`/`ingest_race`/`ingest_candidate`
  payload shape, including district/division normalization.
- Task-level tests (mocking the client): `sync_ky_elections` creates the `Election`
  and queues `sync_ky_candidates`; `sync_ky_candidates` creates races/candidates and
  correctly flips withdrawn/disqualified candidates to inactive status.
- Run via `pytest --no-migrations` per repo convention (project memory
  `run-tests-no-migrations`).

## Follow-up work (not in this PR)

1. PDF calendar parsing for future-election discovery beyond the active election.
2. Judicial office groups and Constitutional Amendment candidate-filing group.
3. County candidate filings (separate source, local-office coverage).
4. `KY-Ballots` — sample-ballot PDF indexing for reconciliation/enhanced coverage.
5. `KY-Measures` — constitutional amendments.
6. `KY-ResultsCertified` — 120-county recap PDF parser (own spec; PDF layout
   variance expected, start with a small diverse subset of counties).
7. Contact KY SBE about approved live-data access before ever prototyping
   `KY-ResultsLive`.
8. Cloud Scheduler cron wiring for the new daily task.
