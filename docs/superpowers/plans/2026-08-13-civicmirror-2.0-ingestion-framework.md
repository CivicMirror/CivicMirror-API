# CivicMirror 2.0 Reusable Ingestion Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build format-independent normalized contracts, exact-once precinct aggregation, capability registration, content-addressed artifact registration, transactional pre-election persistence, reconciliation reports, and aggregate-only sync logs for CivicMirror 2.0.

**Architecture:** Add an isolated `cm2_ingestion` app between state parsers and the normalized domain. Frozen contract records contain no Django models; framework services validate complete batches before entering a transaction, use deterministic public/source keys for idempotency, create provisional People and persistent review cases without name-based linking, and keep detailed identities in reconciliation reports while SyncLog stores numeric aggregates only.

**Tech Stack:** Python 3.13 dataclasses and protocols, Django 5.2 transactions, PostgreSQL 16, pytest-django, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-13-civicmirror-2.0-nc-pilot-design.md`

## Global Constraints

- State parser code supplies normalized contract records and never writes domain models directly.
- The initial registry accepts only enabled state `NC`; unsupported capabilities fail explicitly.
- Complete batches validate before any domain entity is written.
- Precinct observations have stable source-observation keys and are summed exactly once before result persistence.
- Names, contact information, party, jurisdiction, and office history never authorize automatic Person linking.
- Existing source-row lineage, a supplied stable Person public ID, an approved identifier, or a merged-Person redirect may be reused deterministically.
- Every newly provisioned Person creates an open identity-review case without blocking the remaining batch.
- SyncLog stores aggregate numeric counts and a sanitized error summary only. Detailed public record IDs belong in ReconciliationReport; private filing values belong only in protected source records/review evidence.
- A successful artifact/run replay is idempotent and returns the existing report.
- One failed batch cannot leave partial domain entities.
- No network access is required by normal tests.
- The user-owned NC source sample remains untouched; no production services are modified.

---

### Task 1: Add Pure Normalized Contracts and Batch Validation

**Files:**
- Create: `backend/cm2_ingestion/__init__.py`
- Create: `backend/cm2_ingestion/apps.py`
- Create: `backend/cm2_ingestion/contracts.py`
- Create: `backend/cm2_ingestion/tests/__init__.py`
- Create: `backend/cm2_ingestion/tests/test_contracts.py`
- Modify: `backend/config/settings/v2.py`
- Modify: `backend/pytest-v2.ini`

**Interfaces:**
- Produces frozen records: `ElectionRecord`, `JurisdictionRecord`, `OfficeRecord`, `ContestRecord`, `PersonSourceEvidence`, `CandidateFilingRecord`, `PreElectionBatch`, `PrecinctResultObservation`, `AggregatedResultChoice`, and `CertificationEvidence`.
- Produces: `validate_pre_election_batch(batch: PreElectionBatch) -> None`.
- Raises: `ContractValidationError` containing safe structural errors but no protected contact values.

- [x] **Step 1: Write failing contract tests**

Cover duplicate public/source keys, missing relationship targets, reversed/invalid numeric values, duplicate evidence-row keys, and a valid NC batch with multiple source evidence rows for one normalized candidacy. Prove validation errors do not contain protected address, phone, or email values.

- [x] **Step 2: Run tests and verify RED**

Expected: collection fails because `cm2_ingestion.contracts` does not exist.

- [x] **Step 3: Implement immutable contracts and whole-batch validation**

Contracts use `@dataclass(frozen=True, slots=True)` and tuples. Candidate records contain a stable batch `filing_key`, optional deterministic `person_public_id`, normalized candidacy fields, and one or more `PersonSourceEvidence` rows. Validation checks uniqueness and relationship integrity without logging or interpolating protected field values.

- [x] **Step 4: Install the app and verify GREEN**

Add `cm2_ingestion` only to v2 settings and test discovery. Expected: all contract tests pass.

### Task 2: Add Exact-once Precinct Aggregation

**Files:**
- Create: `backend/cm2_ingestion/aggregation.py`
- Create: `backend/cm2_ingestion/tests/test_aggregation.py`

**Interfaces:**
- Produces: `aggregate_precinct_observations(observations: Iterable[PrecinctResultObservation]) -> tuple[AggregatedResultChoice, ...]`.
- Raises: `ContractValidationError` for duplicate observation keys, negative totals, or conflicting choice metadata.

- [x] **Step 1: Write failing aggregation tests**

Use hand-derived NC-style observations to prove two rows totaling `5,000 + 6,968` produce exactly `11,968`, anonymous write-in votes remain in contest totals/percentages, named write-ins remain distinct, and a duplicate observation key is rejected instead of double-counted.

- [x] **Step 2: Run tests and verify RED**

Expected: import fails because aggregation is absent.

- [x] **Step 3: Implement deterministic grouping and percentage calculation**

Group by contest and source-choice key, require label/type metadata consistency, sum integer votes once, compute four-decimal percentages from the full contest denominator, preserve sorted observation lineage, and return a stable sort order.

- [x] **Step 4: Run tests and verify GREEN**

Expected: every aggregation test passes with the exact literal totals and percentages.

### Task 3: Add Capability and Artifact Registries

**Files:**
- Create: `backend/cm2_ingestion/capabilities.py`
- Create: `backend/cm2_ingestion/artifacts.py`
- Create: `backend/cm2_ingestion/tests/test_capabilities.py`
- Create: `backend/cm2_ingestion/tests/test_artifacts.py`

**Interfaces:**
- Produces protocols: `ElectionDiscoverySource`, `CandidateSource`, `ResultsSource`, and `CertificationSource`.
- Produces: `CapabilityRegistry(enabled_states: tuple[str, ...])`, `StateCapabilities`, and `UnsupportedCapabilityError`.
- Produces: `register_source_artifact(..., content: bytes) -> tuple[SourceArtifact, bool]`.

- [x] **Step 1: Write failing registry and artifact tests**

Prove only NC registers, missing capabilities fail explicitly, duplicate registration is rejected, identical bytes return the same artifact, changed bytes create a successor, and SHA-256 is computed from content rather than caller input.

- [x] **Step 2: Run tests and verify RED**

Expected: imports fail because capability/artifact services do not exist.

- [x] **Step 3: Implement pure capability registry and transactional artifact registration**

Capabilities are optional independent protocols. Registration normalizes state to uppercase, rejects disabled states and duplicate state registration, and never substitutes one capability for another. Artifact registration computes SHA-256, uses `(source_system, URL, checksum)` idempotency, and links changed content to the most recent artifact for that source/URL.

- [x] **Step 4: Run tests and verify GREEN**

Expected: all registry/artifact tests pass.

### Task 4: Add Transactional Persistence, Reports, and Aggregate SyncLog

**Files:**
- Create: `backend/cm2_ingestion/models.py`
- Create: `backend/cm2_ingestion/persistence.py`
- Create: `backend/cm2_ingestion/admin.py`
- Create: `backend/cm2_ingestion/tests/test_persistence.py`
- Create: generated `backend/cm2_ingestion/migrations/0001_initial.py`
- Modify: `backend/cm2_core/tests/test_foundation.py`

**Interfaces:**
- Produces: `SyncLog` and `ReconciliationReport`.
- Produces: `apply_pre_election_batch(*, artifact: SourceArtifact, batch: PreElectionBatch) -> ReconciliationReport`.
- Consumes: all normalized Phase 2 models plus `IdentityReviewCase`.

- [x] **Step 1: Write failing persistence tests**

Prove a valid batch creates each normalized entity, all source evidence rows, one candidacy, an open review case for a new provisional Person, aggregate SyncLog counts, and detailed public IDs in the report. Replay the same artifact and prove row counts and report identity are unchanged. Prove two equal names without deterministic lineage create two People, stable prior source-row lineage reuses a Person across artifact versions, and a structurally invalid batch writes no domain entities while retaining a failed SyncLog.

- [x] **Step 2: Run tests and verify RED**

Expected: imports fail because persistence/models do not exist.

- [x] **Step 3: Implement reporting models and privacy constraints**

`SyncLog` uses UUID identity, unique `run_key`, state/source/capability/status/timestamps, optional artifact, `aggregate_counts`, and sanitized `error_summary`. Its `clean()` accepts only nonnegative integer aggregate values. `ReconciliationReport` is one-to-one with SyncLog and stores public IDs/counts in JSON but no protected evidence.

- [x] **Step 4: Implement pre-election persistence**

Validate first. Create/reset the run log, then apply Jurisdictions, parent links, Offices, Elections, Contests, People, source records, Candidacies, review cases, and report in one `transaction.atomic()` block. Resolve People only through prior source-row lineage, explicit `person_public_id`, or merged redirects. Never query People by name/contact fields for automatic linking. On failure, roll back the domain transaction and persist a sanitized failed SyncLog.

- [x] **Step 5: Run tests and verify GREEN**

Expected: all persistence/idempotency/rollback/privacy tests pass.

- [x] **Step 6: Generate and inspect migration**

Generate `cm2_ingestion.0001_initial`; it may depend only on `cm2_core` and must not depend on a legacy app. Extend the schema test for the two new tables.

### Task 5: Canonical Verification and Runtime Inspection

**Files:**
- Modify: this plan's checkboxes only.

- [x] **Step 1: Run `make verify-v2`**

Expected: Python/Django/migration/Ruff gates and all `cm2_*` tests pass.

- [x] **Step 2: Apply migration only to isolated PostgreSQL and inspect tables**

Expected: framework and `cm2_*` tables only, with zero legacy domain tables.

- [x] **Step 3: Rebuild API and verify loopback/LAN health**

Expected: healthy `0.0.0.0:58000` API; successful health payloads through `127.0.0.1` and `192.168.1.102`; no Postgres or Redis host mapping.

- [x] **Step 4: Run final scope and syntax checks without committing**

Run `git diff --check`, shell/YAML validation, migration dependency search, and `git status --short`. Leave the protected NC source sample untouched.
