# CM2.0 Incomplete-Election-Data Review Queue — Design

## Context

While scoping how Massachusetts's OCPF candidate-filer API (`api.ocpf.us`) could feed CivicMirror 2.0's ingestion pipeline (`cm2_ingestion` + a future `cm2_ma` state package, modeled on the existing `cm2_nc` pilot), a hard blocker surfaced: OCPF has no election-date field for municipal offices (Mayor, City Council). MA municipal election dates are set per-municipality by local charter and aren't published in any structured, unblocked source CivicMirror currently reaches (`sec.state.ma.us`'s local-election-office directory is Incapsula-blocked; see the `ma-sos-incapsula-block` memory).

`cm2_elections.Election.election_date` is a required, non-nullable field, and `cm2_ingestion.contracts.ElectionRecord.election_date` mirrors that at the batch-contract level — there is no way to construct a valid pre-election batch record for an election whose date isn't known yet. Candidates discovered for such elections (real people, real candidacies, sourced from a real OCPF filing) would otherwise simply be dropped on the floor with no trace.

This is not MA-specific: any state source that discovers candidates before a jurisdiction's exact election date is known (most obviously municipal races nationwide, which are set by local charter rather than a state calendar) hits the same wall. This spec defines a general, cross-state mechanism for capturing that "we have real candidate data, but can't build a complete Election/Contest/Candidacy yet" case, storing it for human resolution, and re-attempting ingestion once resolved — living in the shared `cm2_ingestion`/`cm2_review` apps, not in any one state's package.

**Explicitly out of scope for this spec:**
- The MA/OCPF adapter itself (source client, mapping module, `cm2_ma` package) — separate future work that will be the first consumer of this mechanism.
- Celery task / cron / trigger-endpoint wiring for any cm2 state pipeline. Confirmed with the user this stays dev-only (function-level, run via tests/management commands) for now — `cm2_nc` already has zero production wiring and that's an accepted, separate gap.
- A dedicated review-queue UI. Django admin (`cm2_review/admin.py`) is the review surface for this case type, same as it is today for person-identity cases.

## Problem

`cm2_ingestion.contracts.PreElectionBatch` requires every `ElectionRecord` to carry a real `election_date: date`. A state's mapping code that discovers a real candidate for an office whose election date isn't yet known (e.g. an OCPF-discovered mayoral candidate) has no way to include that discovery in a valid batch, and no existing mechanism to flag it for later completion. The closest existing construct, `cm2_review.IdentityReviewCase`, only supports subjects that are real persisted rows (`PersonSourceRecord`, provisional `Person`, `ResultChoice`) via a `CheckConstraint` requiring exactly one of those three FKs — none of which fit an Election that doesn't exist yet.

## Decision

Extend `IdentityReviewCase` (Approach A from brainstorming) rather than building a parallel review model or genericizing the subject into a bare string key. This keeps one review queue, one audit trail (`IdentityReviewAuditEvent`), one admin surface, and one status/resolution lifecycle for both person-identity and data-completeness cases, at the cost of one migration to a shared app.

## Schema Changes

One migration to `cm2_review`:

1. `IdentityReviewCase.CaseType` gains `INCOMPLETE_ELECTION_DATA = "incomplete_election_data", "Incomplete election data"`.
2. `IdentityReviewCase.ResolutionAction` gains `SUPPLY_MISSING_DATA = "supply_missing_data", "Supply missing data"`.
3. New field: `resolution_data = models.JSONField(default=dict, blank=True)` — a generic structured-answer field for case types that need a reviewer to supply a typed fact (starting with `{"election_date": "YYYY-MM-DD"}`), as opposed to picking among `IdentityReviewSuggestion` rows. Deliberately generic so a future case type (e.g. "missing OCD-ID") can reuse the same field rather than each needing its own migration.
4. `cm2_review_case_subject_required` `CheckConstraint` gets an OR-branch: allow all three of `source_record`/`provisional_person`/`result_choice` to be null when `case_type == "incomplete_election_data"`. That case type's subject lives entirely in `supporting_evidence` (JSON, already an existing field) and `deduplication_key` (already existing, already unique).

No changes to `cm2_elections` models. No changes to `cm2_ingestion.contracts` — `ElectionRecord.election_date` stays required; incomplete records simply never become one.

## Data Flow

**Flagging (shared helper, called from any state's mapping code):**

A new function in `cm2_ingestion`, e.g. `cm2_ingestion.review.flag_incomplete_election(*, deduplication_key, supporting_evidence)`:

- `deduplication_key` is computed by the calling state's mapping code, deterministically, from whatever identity it already has — e.g. `f"incomplete_election:{state}:{jurisdiction_public_id}:{office_public_id}:{cycle_year}"`. Stability of this key matters: if a state's identity-derivation logic changes between runs, an open case can silently orphan while a fresh duplicate is created under the new key. Adapter authors changing jurisdiction/office identity derivation should grep for open `INCOMPLETE_ELECTION_DATA` cases referencing the old key shape before shipping such a change.
- `supporting_evidence` carries: the `source_artifact` public_id the discovery came from (so it can be re-parsed later without a fresh fetch), and enough jurisdiction/office/candidate identity (names, not just public_ids) that a reviewer can recognize what they're looking at in Django admin without decoding raw JSON.
- The helper does a `get_or_create`-by-`deduplication_key` upsert: first call creates an `IdentityReviewCase(case_type=INCOMPLETE_ELECTION_DATA, status=OPEN, ...)`; subsequent calls with the same key update `supporting_evidence` in place (e.g. a new candidate discovered for the same still-dateless office) rather than duplicating.
- The batch itself omits the election/contest/candidates entirely — they are not partially persisted anywhere in `cm2_elections`.

**Resolution (human, via Django admin):**

A reviewer sets `status=APPROVED`, `resolution_action=SUPPLY_MISSING_DATA`, `resolution_data={"election_date": "2026-11-03"}`, `reviewed_by`/`reviewed_at` (already required together by the existing `cm2_review_terminal_metadata` constraint).

**Promotion (next ingestion run, not immediate):**

Since there's no scheduler yet, promotion isn't a standalone job — it's a check the state's mapping code performs on every run, before flagging: look up an `IdentityReviewCase` matching this run's `deduplication_key` with `status=APPROVED` and `resolution_action=SUPPLY_MISSING_DATA`. If found, use `resolution_data["election_date"]` to build the real `ElectionRecord`/`ContestRecord`/candidate records for this run's batch instead of flagging again. The original `source_artifact` referenced in `supporting_evidence` can be re-parsed deterministically (artifacts are content-addressed and immutable) if the candidate data itself needs re-deriving rather than re-fetching live.

## Error Handling

- If a promoted record still fails `validate_pre_election_batch` for an unrelated reason (e.g. a different required field also turns out to be missing), the ingest run must not silently drop it a second time. Transition the case back to `status=DEFERRED` (not re-open as a fresh `OPEN` case) and append the validation error to `conflicting_evidence`, so the review history shows it was attempted and why it didn't take.
- If the `source_artifact` recorded in `supporting_evidence` has since been superseded by a newer fetch at the same URL, promotion re-parses the artifact that was current *at flag time*, not the newest one — so what the reviewer approved is what gets applied. (Artifact lineage via `supersedes` already supports looking up the exact historical artifact.)

## Testing

- `cm2_ingestion.review.flag_incomplete_election`: creates on first call; updates (not duplicates) `supporting_evidence` on a repeat call with the same `deduplication_key`.
- DB-level constraint test: an `INCOMPLETE_ELECTION_DATA` case with all three subject FKs null saves successfully; every other existing `case_type` still enforces the original "exactly one subject" rule unchanged.
- Round-trip test: flag → set `resolution_data` + `APPROVED` + `SUPPLY_MISSING_DATA` → re-run the (test-double) mapping/ingest path → real `Election`/`Contest`/`Candidacy` rows exist → case reaches a terminal status.
- Failure-path test: promotion that still fails validation lands the case in `DEFERRED` with the error recorded, not silently dropped and not stuck `OPEN` forever without explanation.
