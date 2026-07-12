# New Jersey (NJ) Adapter — Design Spec

**Date:** 2026-07-12
**Status:** Approved, not yet implemented

## Context

NJ is the next state slated for adapter work after IL (per the phase-3 build order; GA, ME, and IL have since shipped). Prior research (`docs/state-research/NJ/NJ-Election_Research.md`) established the key architectural fact: **NJ has no state-level results aggregator.** Each of NJ's 21 counties manages elections locally via its county clerk, and results are published per-county, on whatever platform that county happens to use — a materially different (and harder) shape than every other state adapter in this codebase, all of which have one canonical statewide (or near-statewide) source.

## Live Recon Findings (2026-07-12)

Fetched `https://nj.gov/state/elections/election-night-results.shtml` live and parsed the current county-to-URL table (21 rows). Findings, updating the prior research doc's May 2026 snapshot:

- **11 counties on Clarity with a live numeric election ID right now:** Atlantic, Burlington, Cape May, Essex, Gloucester, Mercer, Middlesex, Monmouth, Morris, Ocean, Union — all under `https://results.enr.clarityelections.com/NJ/{County}/{electionId}/...`.
- **1 county (Hudson) on Clarity via a different subdomain:** `https://admin.enr.clarityelections.com/files/NJ/Hudson/{electionId}/...` — same underlying platform, different host, confirmed live.
- **3 counties on Clarity but with no election ID posted for the current cycle yet:** Passaic, Somerset, Cumberland (Cumberland's link is present but HTML-commented-out on the page — i.e., explicitly disabled until the county posts one). Confirms election IDs are per-cycle and must be discovered dynamically, not hardcoded (the prior research doc's June 2026 IDs are already stale — current IDs are different, higher numbers).
- **1 county (Salem) on a legacy-branded Clarity deployment:** `https://www.livevoterturnout.com/ENR/salemnjenr/{id}/en/Index_{id}.html`. Confirmed via page asset inspection (`LiveResultsVerifierColors.css`, `LiveResultsScripts_v4.1.js` — identical filenames to OH's confirmed Clarity deployments) that this is genuinely the same Clarity platform, just under NJ's `livevoterturnout.com`-branded hosting rather than `enr.clarityelections.com`. The exact `current_ver.txt`/`summary.json` relative path for this host was **not** resolved during recon (tried two guesses, both 404) — needs confirming during implementation.
- **5 counties fully off-platform, no common mechanism:** Bergen (`bergencountyclerk.gov/Election/`), Camden (`camdencounty.com/.../election-results/`), Sussex (`sussex.nj.us/934/Primary-Election`), Warren (`warrencountyvotes.com/elections/past-election-results`), Hunterdon (`co.hunterdon.nj.us/236/County-Clerk`) — five different sites, five different (unknown) structures.

**Material consequence of scope:** Bergen and Camden are two of NJ's most populous counties and are both off-Clarity. Any "statewide total" built only from the Clarity-pattern counties will under-represent actual statewide vote totals, not just miss a rounding error. This is accepted and documented (see Decisions below), not silently glossed over.

**Additional resources checked, no material impact on design:**
- `election-chronological-timelines.shtml` / `2026-chron-special-primary-election.pdf` — PDF-only administrative deadline calendars (petition filing, canvass dates), no county URLs or candidate data. Useful for human awareness (confirms NJ ran a CD-11 special primary/general in Feb–May 2026), not a data source.
- `election-information-2026.shtml` — confirms results PDFs follow a predictable path (`/assets/pdf/election-results/2026/...`), relevant only if a future PDF-parsing fallback is built for the 5 off-platform counties. Not used in this build.

### Critical finding: office titles and candidate names are NOT consistent across counties

Live-fetched `summary.json` from 5 counties (Atlantic, Burlington, Essex, Mercer, Ocean) for the same statewide contest (2026 US Senate primary, DEM) to validate the "sum by `(office_title, candidate_name)`" aggregation this spec originally proposed. It does not hold:

**Office title, same race, five counties, five strings:**
| County | Office title |
|---|---|
| Atlantic | `DEM U.S. Senator` |
| Burlington | `US Senate (DEM)` |
| Essex | `United States Senator (DEM)` |
| Mercer | `U.S. Senate (DEM)` |
| Ocean | `DEM UNITED STATES SENATE` |

**Candidate name, same candidate, three variants:**
- `Cory BOOKER` (Atlantic, Mercer)
- `Cory Booker` (Burlington, Essex)
- `DEM Cory BOOKER` (Ocean — party prefix embedded directly in the candidate name field, not just the office title)

Plus per-county bookkeeping-row conventions that aren't candidates: `Write-in` (Mercer), `WRITE-IN` (Ocean), and Burlington's ballot design includes a `Personal Choice` line (NJ's write-in-adjacent ballot option) that needs the same exclusion/aggregation treatment as IL's `Under Votes`/`Over Votes`/write-in handling.

This means naive string-equality aggregation would produce up to 5 separate near-duplicate races (and duplicate candidates) for what is genuinely one statewide contest. **This finding changes Stage 2's aggregation approach — see the updated Architecture section below.**

## Decisions

1. **Scope: Clarity-pattern counties only for v1** (~15-16 of 21 — the 11 confirmed-live + Hudson + Salem + the 3 currently-ID-less-but-Clarity-platform counties, which will populate once their IDs are posted). The 5 fully off-platform counties (Bergen, Camden, Sussex, Warren, Hunterdon) are explicitly deferred, documented as future work — same treatment as OH's judicial-races deferral. This means NJ's statewide totals will be **partial coverage**, not full-state accuracy, until the deferred counties are built. This is a real, acknowledged limitation, not swept under the rug.
2. **Stage 1 stays on the Civic API**, unchanged. NJ's own candidate data is PDF-only (no CSV/HTML shortcut like IL had); building a custom Stage 1 isn't worth it for this scope. New addition: a lightweight *enrichment* task (not a replacement election-creation task) that scrapes the county-URL table and attaches it to existing Civic-API-created `Election` rows via `source_metadata`.
3. **Stage 2 is a new multi-county aggregator**, not a subclass usable via the existing single-URL `ClarityAdapter.fetch_results()` — that method is built around one `results_url` per election. NJ needs N county URLs fetched and merged into one result set per election. The adapter subclasses `ClarityAdapter` to reuse its `_parse_contests()` method (JSON → `ResultRow` parsing, the valuable/complex part) but overrides `fetch_results()` entirely with its own multi-county loop, per-county graceful skip (no ID posted yet), and cross-county aggregation.
4. **Build a normalization layer for cross-county office/candidate matching** (see the "Critical finding" above and the updated Architecture below), rather than aggregating on raw string equality or giving up on cross-county aggregation entirely. This is real, non-trivial reconciliation work — the office/candidate-naming inconsistency across counties is confirmed, not hypothetical.

## Architecture

### 1. `backend/integrations/nj_elections/` (Stage 1 enrichment)

New Django app, modeled loosely on existing per-state Stage 1 apps but scoped narrower (enrichment, not election creation):

- **`client.py`**: fetch `election-night-results.shtml`.
- **`parsers.py`**: parse the county table into `{county_name, url}` pairs (mirrors the `<td>{County} County<br /><a href="...">` structure confirmed live). Classify each URL by hostname against a known-Clarity-hosts set (`results.enr.clarityelections.com`, `admin.enr.clarityelections.com`, `livevoterturnout.com`) to separate in-scope (Clarity-pattern) from out-of-scope (5 off-platform) counties. For in-scope URLs, extract the numeric election ID from the path (absent for counties that haven't posted yet — those are skipped, not errored).
- **`tasks.py`**: `sync_nj_county_urls` (Celery task) — for each currently-tracked NJ `Election` (created by the existing Civic API sync), re-scrape and update `Election.source_metadata["nj_county_urls"]` with the current in-scope county → URL/ID mapping. Runs on the same daily cadence as other Stage 1 tasks, re-discovering IDs as counties post them (Passaic/Somerset/Cumberland today, potentially others next cycle).

### 2. `backend/results/adapters/nj_normalize.py` (office/candidate normalization)

New module, used by Stage 2 only (no Django/model dependencies — pure functions, same spirit as IL's `il_aggregate.py`):

- **`normalize_office(raw_title: str) -> tuple[str, str]`** → `(canonical_office_key, party)`. Extracts the party token (`DEM`/`REP`/`GOP`/`IND`/etc.) wherever it appears in the string (prefix, suffix-in-parens, or embedded — all three observed live), strips it, then normalizes the remainder against a small fixed set of known canonical office keys (`US_SENATE`, `US_HOUSE_01` … `US_HOUSE_12` — NJ has 12 congressional districts, `GOVERNOR`, etc.) via pattern matching that tolerates the `U.S./US`, `SENATOR/SENATE`, punctuation, and case variance confirmed live across Atlantic/Burlington/Essex/Mercer/Ocean. The canonical race identity for a primary is `(canonical_office_key, party)` — mirroring `co_sos`'s existing `(office, district, party)` grouping for primary races, a precedent already established in this codebase.
- **`normalize_candidate_name(raw_name: str) -> str | None`** → strips known party-prefix tokens from the front of the name (catches Ocean's `"DEM Cory BOOKER"` pattern), trims/normalizes whitespace and case for matching purposes. Returns `None` for non-candidate bookkeeping rows (`Write-in`, `WRITE-IN`, `Personal Choice`), which are aggregated separately as a write-in total per race — same pattern as IL's `Under Votes`/`Over Votes`/write-in handling in `il_aggregate.py`.

### 3. `backend/results/adapters/nj.py` (Stage 2)

`NewJerseyAdapter(ClarityAdapter)`:

- Reads `election.source_metadata["nj_county_urls"]` (populated by Stage 1's enrichment task). If empty/absent, return an empty `AdapterResult` with `mapping_confidence="none"` and a note — same graceful-failure posture as every other adapter in this codebase.
- For each county URL: fetch `current_ver.txt` (skip that county gracefully — log and continue, not abort — if the fetch fails or the county has no ID), fetch `summary.json`, call the inherited `self._parse_contests()` to get that county's `ResultRow`s, then run each row's `office_title` and `candidate_name` through `nj_normalize.py` before merging.
- **Aggregation**: group rows by `(canonical_office_key, party)` for statewide races (US Senate, Governor, President — offices that plausibly appear in every county) and sum `vote_count` by normalized candidate name within each group. District-scoped races (Congressional, State Senate/Assembly) only aggregate across counties that actually contain that district — no fabricated cross-county summing for a district a county doesn't have. The `ResultRow.office_title` emitted for a canonical group uses one fixed canonical display string (not whichever county's raw string happened to be seen first), so the resulting `Race.office_title` is stable regardless of county fetch order.
- **Version/change detection**: no single version string exists across N counties. Compute a checksum over all counties' concatenated `current_ver` values (same pattern IL used for its concatenated CSV-bytes checksum), written to cache only after a successful run.

## Error Handling

- Missing `nj_county_urls` metadata → empty `AdapterResult`, `mapping_confidence="none"`, explanatory note.
- A single county's fetch failing (network error, 404, unexpected JSON shape) → log and skip that county, continue with the rest. Never let one bad county abort the whole adapter run — this matters more for NJ than any prior state, since a 15-county fan-out has a much higher chance that *some* county has a transient issue on any given poll.
- Salem's exact API path is unresolved from recon — if it can't be found during implementation, Salem is treated the same as a "county with no ID posted" (skipped, not blocking), and the coverage gap is documented rather than blocking the whole adapter.

## Testing

- Fixture-based tests for the county-table parser (real HTML captured from `election-night-results.shtml`, following the same fixture-capture pattern as IL's).
- Unit tests for the Clarity-host classifier (in-scope vs. out-of-scope counties) using both real captured URLs and edge cases (a county with no `href` yet, the Cumberland HTML-comment case).
- Unit tests for `normalize_office`/`normalize_candidate_name` using the **real observed variants** captured above (all 5 office-title strings must normalize to the same `(US_SENATE, DEM)` key; all 3 candidate-name variants must normalize to the same matchable name; `Write-in`/`WRITE-IN`/`Personal Choice` must all return `None`).
- Unit tests for cross-county aggregation using real captured `summary.json` fixtures from at least 2-3 of the 5 counties already fetched during recon (not synthetic data — the whole point is exercising the real naming inconsistency); verify district races don't pull in counties that don't contain that district.
- No live network calls in CI.

## Binding lesson from the IL build (apply here up front, don't rediscover it)

IL's trigger endpoint shipped without an entry in `backend/internal/task_locks.py`'s `TASK_LOCKS` registry, causing a live 500 on first real invocation — caught only during post-merge manual verification, not by any test or review pass, because `manage.py check` doesn't exercise the runtime dict lookup. **The task that wires the NJ trigger endpoint must add a `TASK_LOCKS["sync_nj_county_urls"]` entry in the same commit**, and the plan must include a live-trigger verification step before considering the endpoint done.

## Out of Scope (this build)

- The 5 off-platform counties (Bergen, Camden, Sussex, Warren, Hunterdon) — different mechanism per county, explicitly deferred.
- PDF-based candidate/results parsing (would be needed for full Stage 1 replacement or for the 5 deferred counties).
- Historical backfill.

## Docs

- Update `docs/state-research/NJ/NJ-Election_Research.md` with the current live county-URL snapshot and the scope decision.
- Update `docs/state-research/00-MASTER-INDEX.md` once shipped — NJ will land as **Near Core Coverage** (Stage 2 partial — Clarity counties only; Stage 1 still Civic-API-dependent), not Full Core, given the acknowledged county-coverage gap. This should be stated explicitly, not implied.
