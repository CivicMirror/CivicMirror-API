# NC Results Contest Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve NC SBE contest identity and metadata through results aggregation, race bootstrap, repeat ingestion, winner derivation, and a reviewable repair of existing affected records.

**Architecture:** Extend the NC adapter to emit explicit source identity and evidence for geography, party, and seat count. Make bootstrap and matching consume that identity without falling back to title-only matching when identity exists. Add a dry-run-first repair command that maps and reconciles existing records before any transactional mutation; keep winner eligibility conservative and dependent on #213 safeguards.

**Tech Stack:** Python 3.13, Django, PostgreSQL, pytest/pytest-django, NC SBE ENRS ZIP/TSV feeds.

**Spec:** [CivicMirror-API issue #214](https://github.com/CivicMirror/CivicMirror-API/issues/214). Related visible-data requirement: [issue #223](https://github.com/CivicMirror/CivicMirror-API/issues/223).

## Global Constraints

- Never identify a contest by an unqualified NC contest ID; IDs repeat across counties.
- Keep county contests distinct, preserve valid multi-county contests, and use electorate identity for local multi-county contests when evidence supports it.
- Do not infer a one-seat contest from missing, zero, or conflicting `Vote For` values.
- Do not bypass winner ambiguity safeguards or falsify `geography_scope` to make races eligible.
- Do not change Election keys as part of this work; #188 owns election rekeying/classification.
- Do not apply a production repair until a fresh dry-run, vote reconciliation, backup/rollback procedure, and operator review are complete.
- Preserve source provenance and legitimate candidate/result relationships; repeated repair runs must be safe.

## Review Focus

- Same contest name and local ID in different counties: tests must prove independent county contests stay separate.
- Same statewide, federal, or multi-county contest reported in multiple counties: tests must prove one contest identity and totals are not duplicated.
- Same-name local contests spanning counties: tests must prove the adapter does not blindly split or merge without electorate identity.
- `Vote For` missing, zero, inconsistent, or greater than one: tests must prove unresolved seat counts remain unresolved and valid multi-seat counts are retained.
- A race with source identity but no matching identity row: tests must prove matching skips it instead of using a title fallback.

---

### Task 1: Establish baseline and target the correct ingestion/API path

**Files:**
- Inspect: `backend/results/adapters/nc.py`
- Inspect: `backend/results/tasks.py`
- Inspect: `backend/elections/models.py`
- Inspect: `backend/results/winners.py`
- Inspect: `backend/results/management/commands/derive_winners.py`
- Inspect: `backend/cm2_*` NC ingestion/persistence modules if the issue #223 race IDs are stored in CM2 rather than legacy tables
- Inspect: `backend/results/tests/test_nc_adapter.py`, `backend/results/tests/test_tasks.py`

**Interfaces:**
- Produces: a checked-in baseline note or command output recording the 89-merged-race inventory across seven elections, the current skip counts, and the datastore/API path for the #223 race IDs.

- [ ] Rebuild the affected-race inventory from current source and DB state; do not rely on the historical counts without confirming them.
- [ ] Trace #223 race IDs `21825` and `49844` through the API response to their election, database/schema, source metadata, candidates, and results.
- [ ] Confirm whether the affected served records use the legacy `backend/results` path, CM2, or both; implement the canonical identity contract in the path that owns those records and add a parity task only if both are active.
- [ ] Record the pre-change per-election counts, skipped-winner reasons, and vote totals needed for later reconciliation.
- [ ] Confirm #213 source-winner/nomination safeguards are merged and applicable before enabling any expanded winner derivation; if not, keep that task gated.

### Task 2: Define and test NC contest identity and geography classification

**Files:**
- Create or modify: `backend/integrations/nc_sbe/` identity helper if shared parsing/mapping belongs there
- Modify: `backend/results/adapters/nc.py`
- Test: `backend/results/tests/test_nc_adapter.py`

**Interfaces:**
- Produces: one documented identity structure in row `raw` metadata, with stable names for source, contest ID, contest type, county/electorate scope, and party where relevant.
- Consumes: parsed ENRS fields `County`, `Contest Group ID`, `Contest Type`, `Contest Name`, `Choice Party`, and `Vote For`.

- [ ] Add fixture cases for a county ID collision, a statewide contest repeated across counties, a multi-county district, and same-name local contests with distinct electorate identity.
- [ ] Define a normalized contest key that qualifies county-scoped contests by county, preserves shared identities for verified multi-county contests, and represents unresolved local electorate scope explicitly.
- [ ] Update aggregation to group by contest identity plus candidate/choice, not `(Contest Name, Choice)` alone; sum only rows for the same candidate in the same contest.
- [ ] Preserve county, source contest ID, type, party, seat-count evidence, and source version in each output row's `raw` metadata.
- [ ] Add tests proving same-name/same-ID county contests remain distinct and statewide/multi-county data is not split or double counted.

### Task 3: Persist party, seat-count provenance, and source identity

**Files:**
- Modify: `backend/results/adapters/nc.py`
- Modify: `backend/results/tasks.py`
- Modify: `backend/elections/models.py` only if an explicit seat-count provenance field is needed
- Create migration only if schema changes are necessary
- Test: `backend/results/tests/test_nc_adapter.py`, `backend/results/tests/test_tasks.py`

**Interfaces:**
- Consumes: Task 2 identity structure.
- Produces: `Race.source_metadata` and each result row carry the same stable identity keys; candidate party is normalized and stored; seat count records both value and source evidence.

- [ ] Add a test that a sourced positive `Vote For` value becomes `Race.max_selections`, with `RaceType.MULTI_SEAT` when greater than one.
- [ ] Add tests proving missing, zero, or inconsistent `Vote For` does not overwrite the model default as if it were sourced evidence; retain an unresolved/provenance marker.
- [ ] Add tests proving NC `Choice Party` populates `Candidate.party` and normalized party consistently; do not assign a party to consolidated contests without evidence.
- [ ] Persist contest identity during bootstrap and verify subsequent source refetches match the same race.
- [ ] Preserve incumbent metadata when merging records if the source supplies it; NC results feed itself does not establish incumbency, so obtain it from the candidate-side source and retain its provenance rather than guessing.

### Task 4: Make matching identity-first and winner eligibility conservative

**Files:**
- Modify: `backend/results/tasks.py`
- Modify: `backend/results/winners.py`
- Modify: `backend/results/management/commands/derive_winners.py` only if reporting needs identity/skip detail
- Test: `backend/results/tests/test_tasks.py`
- Test: focused winner tests under `backend/results/tests/`

**Interfaces:**
- Consumes: persisted identity from Task 3.
- Produces: deterministic race-to-row matching; winner derivation accepts only sufficiently identified contests consistent with #213 rules.

- [ ] Add tests proving county contest identity takes precedence over office-title equality.
- [ ] Add a test proving an identity-bearing race with no matching identity row is skipped and never falls through to title-only matching.
- [ ] Add tests proving statewide/multi-county rows aggregate once and county/local races remain distinct.
- [ ] Update winner eligibility to use reliable identity and geography evidence while retaining conservative skips for ambiguous locality, election classification, party, seat count, or nomination rules.
- [ ] Ensure `derive_winners --dry-run --state NC` reports coverage and remaining skip reasons attributable to the repaired identity path.

### Task 5: Implement a dry-run-first repair for existing NC records

**Files:**
- Create: `backend/elections/management/commands/repair_nc_contest_identity.py` (or a results command if repository ownership conventions favor `backend/results/management/commands/`)
- Reuse/modify: `backend/elections/management/commands/merge_duplicate_races.py` only if its relationship handling and transaction semantics fit this repair
- Test: `backend/elections/tests/` and/or `backend/results/tests/`
- Document: `docs/` repair and rollback instructions

**Interfaces:**
- Consumes: fresh source refetch, new identity contract, and current database rows.
- Produces: dry-run report and an explicit `--apply` path with old-to-new race/candidate/result mapping, vote reconciliation, and idempotent transactional updates.

- [ ] Add a dry-run test fixture with distinct county collisions, a valid multi-county race, duplicate result-side/candidate-side race records, candidates with party/incumbency, and attached results.
- [ ] Report source refetch version, proposed canonical race, records to merge/retire, candidate matches, result remaps, per-contest totals before/after, conflicts, and unresolved records.
- [ ] Add explicit conflict output for ambiguous candidate identity, contradictory party/incumbency, seat-count disagreement, duplicate natural keys, or non-reconciling vote totals; do not auto-merge those rows.
- [ ] Make apply transactional and repeatable; preserve relationships and provenance, prevent duplicate active totals, and mark superseded records inactive/retired using existing model conventions.
- [ ] Test rollback behavior and rerun idempotency on PostgreSQL, including natural-key constraints.
- [ ] Document backup, dry-run review, apply, post-apply checks, and rollback commands before any production execution.

### Task 6: Verify the #223 served-data outcome and close the loop

**Files:**
- Test: API tests for the endpoint serving races/candidates, in the app that owns the affected datastore
- Document/update: issue #214 and related issue #223 after verified implementation

**Interfaces:**
- Consumes: repaired records and API serialization.
- Produces: one active canonical race per contest per election, with combined result certification/results and candidate party/incumbency where supported.

- [ ] Add an API-level regression test for the 2024 NC State Senate District 01 example: exactly one active race, certified results, candidate party, and preserved incumbency when sourced.
- [ ] Add an API-level regression test for the NC Governor example and assert candidate/result counts are not doubled.
- [ ] Compare all affected contests' totals and race/candidate counts against the dry-run inventory; explain any intentional unresolved exceptions.
- [ ] Run focused adapter/bootstrap/matching/repair/API tests and full backend checks required by CI; run repair transaction tests against PostgreSQL.
- [ ] Run the winner dry-run and attach before/after skip counts and remaining reasons.
- [ ] Only after review, execute the documented repair in the target environment, verify API output and DB integrity, then update #214/#223 with evidence and close only when their acceptance criteria are met.
