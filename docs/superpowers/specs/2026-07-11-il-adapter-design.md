# Illinois (IL) Adapter — Design Spec

**Date:** 2026-07-11
**Status:** Approved, not yet implemented

## Context

IL is the next state slated for adapter work (per `docs/state-research/00-MASTER-INDEX.md` and the phase-3 build order). Prior research (`docs/state-research/IL/IL-Election_Research.md`) concluded "no public REST API identified" and recommended evaluating Clarity Elections or per-authority scraping for live results, with Stage 1 (election/race creation) assumed to come from the Google Civic API.

Live recon (2026-07-11, via direct HTTP probes and a Playwright session against `elections.il.gov`) found a better path than the research doc assumed:

- IL SBE's `votetotalsearch.aspx` page exposes pre-built category result pages as plain GET requests: `ElectionVoteTotals.aspx?ID=<election-token>&OfficeType=<category-token>`. Category tokens (`Federal / Statewide`, `Senate`, `Judicial`, ...) are **stable constants** across elections; only the `ID` (election) token changes per election.
- Each office/race block on a category page links directly to a **precinct-level CSV** at a predictable path: `/Downloads/ElectionOperations/ElectionResults/ByOffice/{electionId}/{electionId}-{contestId}-{OFFICE NAME}-{code}.csv`. Confirmed fetchable with a bare `curl` + browser `User-Agent`, no session/cookies/auth required.
- CSV columns: `JurisdictionID, JurisContainerID, JurisName, EISCandidateID, CandidateName, EISContestID, ContestName, PrecinctName, Registration, EISPartyID, PartyName, VoteCount`. Requires summing `VoteCount` by `CandidateName` within `ContestName` across precinct rows — same shape as the aggregation `results/adapters/nc.py` already does.
- The site sits behind Cloudflare, but plain requests from this (local/residential) host succeeded where a datacenter-IP tool call got a 403 — no CF-solver-style workaround appears necessary, unlike Ohio.
- The office list per election (~250 entries) enumerates President, US Senate, all 17 Congressional districts, all State Senate/House seats, statewide row offices, judicial retention/contested races, and (in some elections) statewide ballot measures — i.e., IL SBE itself can drive Stage 1 (election/race creation), not just Stage 2 (results). This is more reliable than depending on the Civic API, which the research doc flagged as untested for IL.
- The `ID` token per election is resolved via an ASP.NET WebForms auto-postback when the `Elections` dropdown changes; confirmed via a live browser session that switching the dropdown swaps in a new `ID` while `OfficeType` tokens stay fixed.

## Decisions

1. **Scope: Federal + State offices only**, matching the project's existing Full Core Coverage definition. Judicial races and statewide ballot measures use the identical CSV mechanism and are cheap to add later, but are explicitly deferred — not part of this build. `IL-Election_Research.md` will be updated to flag this as a noted future integration.
2. **Stage 1 built from IL SBE data, not the Civic API.** This gets IL to Full Core Coverage (both stages) in one build rather than landing in Near Core (Stage 2 only, CA/NC/NY-style).

## Architecture

Two new components, following existing per-state conventions.

### 1. `backend/integrations/il_sbe/` (Stage 1)

Modeled on `co_sos`/`ia_sos`: `apps.py`, `client.py`, `parsers.py`, `mappers.py`, `tasks.py`, `exceptions.py`, `tests/`.

- **`sync_il_elections`** (Celery task): parse the `ddlElections` option list off `votetotalsearch.aspx` → upsert `Election` rows. Only current/upcoming elections are actively tracked; the other ~40 historical entries are visible but not synced (historical backfill is a separate, later concern).
- **`sync_il_races`** (Celery task): for each tracked `Election`, resolve its `ID` token (see below), fetch the `Federal / Statewide` and `Senate` category pages (the `House` link needs one more confirmation pass during build — it rendered as a non-link `generic` element in recon, likely a flyout/submenu), parse the office list scoped to Federal + State offices, upsert `Race` rows. Each `Race` stores the resolved per-office CSV URL for Stage 2 to consume.

**Election `ID` token resolution:** try replaying the dropdown's ASP.NET auto-postback with plain `requests` first (`__EVENTTARGET`/`__VIEWSTATE`/`__EVENTVALIDATION` captured from an initial GET, since the category tokens are stable and only `ID` needs to be extracted from the response). This only needs to run when a new election appears, not on every sync, so it's low-frequency. If the plain-HTTP replay proves unreliable, fall back to a one-shot Playwright resolve (same tooling already used for Ohio), with the resolved token cached on the `Election` row.

### 2. `backend/results/adapters/il.py` (Stage 2)

Modeled on `nc.py`'s aggregation pattern, subclassing `StateResultsAdapter`:

- Given a `Race` (with its CSV URL set by Stage 1), fetch the CSV, aggregate precinct rows by `CandidateName` within `ContestName` (sum `VoteCount`), map to `ResultRow` (`candidate_name`, `vote_count`, `option_label`/party from `PartyName`).
- No `current_ver.txt`-style version endpoint exists (unlike Clarity). Use a content checksum of the fetched CSV (or `Content-Length`/`Last-Modified` response headers if present) as the change-detection signal, written to the version cache on successful processing — same cache-and-skip contract `AdapterResult.source_version`/`unchanged` already provide.

## Error Handling

- Missing or malformed CSV → return an empty `AdapterResult` with `mapping_confidence="none"` and an explanatory `notes` string, not an exception (same posture as the recent `nc.py` missing-ZIP fix).
- Network/retryable failures → follow the existing per-integration `*RetryableError` pattern (see `CivicAPIRetryableError` for the shape).
- NUL/control-byte sanitization on parsed text fields, consistent with the `nc.py` fix, applied defensively since upstream CSV text quality is unverified.

## Testing

- Fixture-based unit tests for CSV aggregation (candidate/contest summation, malformed-row handling) — pattern-matched to `test_nc_adapter.py`.
- Parser tests for the office-list HTML (category page → list of office/CSV-URL pairs).
- Mapper tests for `Election`/`Race` construction from parsed office data.
- No live network calls in CI; all tests run against fixtures.

## Docs

- Update `docs/state-research/IL/IL-Election_Research.md`: replace the "no public REST API identified" conclusion with the CSV mechanism found in recon, and add a note flagging Judicial races + ballot measures as deferred future integration (same mechanism, out of scope for this build).
- Update `docs/state-research/00-MASTER-INDEX.md` and the phase-3 progress memory once IL ships.

## Out of Scope (this build)

- Judicial races, statewide ballot measures (deferred, flagged in research doc).
- Historical backfill beyond current/upcoming elections.
- County-level jurisdiction breakdowns (the CSV's `JurisdictionID`/`JurisName` columns make this possible later, but Full Core Coverage only requires the statewide/office-level aggregate).
