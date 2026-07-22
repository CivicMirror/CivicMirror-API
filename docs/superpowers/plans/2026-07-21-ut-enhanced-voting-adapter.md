# Utah (UT) Enhanced Voting Results Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Utah (UT) to the existing, shared `EnhancedVotingAdapter` (`results/adapters/enhanced_voting.py`) — the same base class already serving Virginia, Washington, and Georgia — bringing UT to "Results Coverage Only" tier with zero changes to shared parsing logic.

**Architecture:** Unlike Maryland, Missouri, and New Mexico (each of which needed a bespoke parser for a state-unique data format), Utah's research doc (`docs/state-research/UT/UT-Election_Research_V3.md`) confirms Utah runs an **Enhanced Voting "Enhanced Results" tenant** — the identical platform and JSON API shape already implemented generically in this codebase. This was independently re-verified live (2026-07-21): `GET https://electionresults.utah.gov/results/public/api/jurisdictions/Utah` and the per-election `/elections/Utah/{slug}` (meta) and `/elections/Utah/{slug}/data` endpoints return payloads that match `EnhancedVotingAdapter.fetch_results`'s existing parsing code exactly — `election.publicElectionId`, multilingual `name[]` arrays, `ballotItems[].contestType`/`summaryResults.ballotOptions[]`, `party.abbreviation`, `nativeId`, `isWriteIn`, `asOf` for version caching — field-for-field, with no schema differences requiring code changes.

This plan mirrors `results/adapters/ga.py` exactly (Georgia — the closest existing precedent: a self-hosted Enhanced Voting deployment at its own domain, not the shared `app.enhancedvoting.com`): a ~10-line subclass setting `state`, `state_name`, and `base_url`, plus tests. **No new parser, no new client, no new Django app.**

## Files to create/modify

- **Create** `backend/results/adapters/ut.py`:
  ```python
  """
  Utah results adapter using the Enhanced Voting ENR API.

  Utah self-hosts the Enhanced Voting platform at electionresults.utah.gov —
  same API shape as VA ELECT, WA VoteWA, and GA (results.sos.ga.gov),
  different base URL. Independently re-verified live 2026-07-21 against
  docs/state-research/UT/UT-Election_Research_V3.md: GET .../jurisdictions/Utah,
  .../elections/Utah/{slug}, and .../elections/Utah/{slug}/data all match
  EnhancedVotingAdapter's existing parsing exactly, field-for-field.

  Election slugs (enr_slug) are opaque, case-sensitive, and inconsistently
  formatted (e.g. "primary08122025", "Primary06232026", "general11052024") —
  discover them from GET .../jurisdictions/Utah's elections[].publicElectionId
  for the election matching the target date; do not derive from the date.
  One catalog entry ("primary09052023_Demo") is an explicit demo election —
  exclude demo/test elections by policy when building the discovery step
  (out of scope for this plan; see "Follow-up work").
  Set election.source_metadata = {"enr_slug": "<publicElectionId>"}.

  Confirmed live (2026-07-21, Primary06232026, 12 ballot items, 0/27 ballot
  options had a votePercent key) — Utah never sends votePercent, so
  ResultRow.vote_pct is always None for this adapter; this is a real,
  confirmed data characteristic, not a bug (the field is Optional and the
  existing _safe_float(opt.get("votePercent")) already handles a missing
  key gracefully by returning None).

  Race names carry a party PREFIX ("REP U.S. House District 2"), unlike
  GA's party SUFFIX convention ("Governor - Rep") — stored verbatim, same
  as GA; cross-source race matching handles normalization downstream.

  The research doc documents several real data-quality issues in Utah's
  feed (top-level ballotsCast/turnout reported as 0 despite real contest
  votes; isOfficialResults=false even when signed canvass documents exist)
  — none of these affect this adapter, since it only reads per-contest
  ballotItems/ballotOptions data (already correct, matching the doc's own
  reconciliation example: DEM U.S. House District 1's 57,295 candidate
  votes + overvotes + undervotes = 57,455 ballots cast) and the existing
  isOfficialResults -> result_type mapping already treats it as an
  advisory signal, consistent with how GA/VA/WA are handled today. The
  top-level turnout/reporting fields this doc warns about are not parsed
  by this adapter at all (out of scope — see "Follow-up work").
  """
  from __future__ import annotations

  from .enhanced_voting import EnhancedVotingAdapter
  from .registry import register

  _UTAH_API_BASE = "https://electionresults.utah.gov/results/public/api"


  @register
  class UtahAdapter(EnhancedVotingAdapter):
      state = "UT"
      state_name = "Utah"
      base_url = _UTAH_API_BASE
  ```
- **Create** `backend/results/tests/test_ut_adapter.py` — mirrors `results/tests/test_ga_adapter.py`'s structure exactly (registration check, `base_url`/`state`/`state_name` check, a parsing test using a **real** UT ballot item as fixture data, `fetch_results` integration tests with mocked HTTP). Real fixture data (captured live 2026-07-21 from `Primary06232026`, `RaceID` n/a — Enhanced Voting uses ballot-item UUIDs, not numeric race IDs):
  ```python
  _UT_BALLOT_ITEM = {
      "id": "01000000-b2af-048e-2bcd-08dec58ce469",
      "contestType": "Candidate",
      "name": [{"languageId": "en", "text": "REP U.S. House District 2"}],
      "summaryResults": {
          "ballotOptions": [
              {
                  "name": [{"languageId": "en", "text": "BLAKE D. MOORE"}],
                  "voteCount": 52673,
                  "isWinner": None,
                  "isWriteIn": False,
                  "nativeId": "BLAKED.MOORE-1-Republican",
                  "party": {"abbreviation": "REP"},
              },
              {
                  "name": [{"languageId": "en", "text": "KARIANNE LISONBEE"}],
                  "voteCount": 40271,
                  "isWinner": None,
                  "isWriteIn": False,
                  "nativeId": "KARIANNELISONBEE-2-Republican",
                  "party": {"abbreviation": "REP"},
              },
          ]
      },
  }
  ```
  Note this fixture deliberately omits `votePercent` (confirmed real: 0/27 real UT ballot options have that key) — the parsing test should assert `vote_pct is None` for both rows, which is different from GA's test (GA's fixture includes `votePercent` and asserts a real value) and is the one behavioral difference worth a dedicated assertion.
- **Modify** `backend/results/apps.py` — add `"ut"` to `adapter_modules`, alphabetically between `"tx"` and `"va"` (line 17: `"ok", "oregon", "pa", "ri", "sc", "sd", "tn", "tx", "va",` → insert `"ut"` before `"va"`).

## Task breakdown (2 tasks, TDD, one commit each)

1. **`ut.py` + tests.** Write the failing tests first (registration, `base_url`/`state`/`state_name`, parsing the real ballot item — including the `vote_pct is None` assertion — `fetch_results` with a mocked meta+data fetch confirming requests hit `electionresults.utah.gov` not the shared Enhanced Voting domain, no-slug handling, version-unchanged short-circuit), confirm they fail, implement the ~10-line subclass, confirm they pass. Mirror `results/tests/test_ga_adapter.py` line-for-line where the scenario is identical (no-slug, version-unchanged) and only diverge where UT's real data differs (the missing `votePercent`, the party-prefix vs. party-suffix race-name convention — informational only, no different assertion needed there since both are stored verbatim either way).
2. **Register + end-to-end verification.** Add `"ut"` to `results/apps.py`. Verify via the registry smoke test (`get_adapter("UT")` returns `UtahAdapter`), full test suite, ruff, `manage.py check`.

## Follow-up work (explicitly out of scope for this plan)

- **`enr_slug` discovery/automation** — this plan (like GA/VA/WA before it) requires `Election.source_metadata["enr_slug"]` to be set manually (Django admin or the aggregation ingest layer) per election; no automated catalog-polling discovery task is built. The research doc's own election catalog includes a demo election (`primary09052023_Demo`) — any future discovery automation must explicitly exclude demo/test elections, not just take the newest catalog entry.
- **Locality/county-level results** — this adapter only reads the statewide `/elections/Utah/{slug}/data` payload's top-level `ballotItems`. County-level `/elections/{locality-slug}/{slug}/data` endpoints (confirmed live for `beaver-county-ut` and `sanpete-county-ut`) and the ballot-item breakdown endpoint (`/data/ballot-item/{uuid}`, which links `parentBallotItemId` to statewide contests) are not fetched.
- **Turnout/registration/reporting-status fields** — the research doc documents real inconsistencies here (top-level `ballotsCast: 0` despite tens of thousands of real contest votes) that this adapter doesn't need to worry about, since it never reads those fields — but a future adapter that does would need the doc's Section 5 reconciliation rules (treat zero as unknown/unpopulated when contest totals show activity, never overwrite a known nonzero with zero, don't trust `ballotItemCount`).
- **Reports/exports** ("All Results Excel" 4-sheet workbook, media-export JSON, PDF/canvass documents) — not fetched by this adapter. The XLSX workbook is the doc's recommended source for overvotes/undervotes/count-groups/precinct totals and would need a dedicated parser (more MD/MO-shaped work) if pursued.
- **Utah Vote Search** (pre-election candidate/race discovery, sample-ballot lookups) — separate system, separate concerns (address-based lookups, privacy-sensitive), explicitly recommended by the doc as supplementary only, never the primary results source.
- **Historical backfill** (structured XLSX canvass workbooks back to ~2000s, scanned/OCR-required PDFs back to 1960) — separate, much larger effort per the doc's own Phase 6.
- **Certification/status evidence modeling** — the doc recommends a multi-field evidence model (`publication_status`, `certification_documents[]`, `certified_at`, etc.) rather than trusting `isOfficialResults` alone; this adapter still passes that flag straight through to `result_type` (`"official"`/`"unofficial"`), matching the existing GA/VA/WA convention exactly — no different or new behavior for UT specifically.

## Verification

- `cd backend && .venv/bin/python -m pytest --no-migrations -q results/tests/test_ut_adapter.py -v` after Task 1.
- `cd backend && .venv/bin/ruff check .` before every commit.
- Full suite (`pytest --no-migrations -q`) and `manage.py check` after Task 2, plus the registry smoke test (`get_adapter("UT")` returns `UtahAdapter`) — same pattern as every prior state's final task.
