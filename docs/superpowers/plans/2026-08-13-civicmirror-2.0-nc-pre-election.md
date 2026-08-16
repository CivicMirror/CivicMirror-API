# CivicMirror 2.0 North Carolina Pre-election Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover North Carolina elections from the official upcoming-election page, normalize every people-based contest in the 2026 candidate filing CSV, exclude measures safely, and persist an idempotent pre-election dataset through the CivicMirror 2.0 ingestion framework.

**Architecture:** Add an isolated `cm2_nc` package rather than expanding the legacy `integrations.nc_sbe` adapter. Pure parsers convert frozen, sanitized fixtures into explicit NC source records; state mapping converts those records into a complete `PreElectionBatch`; shared persistence remains the only domain write path. The candidate artifact is the batch artifact, while Elections discovered from the official page retain their own artifact provenance through a per-record override.

**Tech Stack:** Python 3.13, Django 5.2, requests, Beautiful Soup 4, dataclasses, pytest-django, PostgreSQL 16, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-13-civicmirror-2.0-nc-pilot-design.md`

## Global Constraints

- Only `NC` is enabled in the CivicMirror 2.0 capability registry.
- State-specific code parses and maps; it never writes normalized domain models directly.
- Upcoming-election HTML is the primary source for public election names and types.
- Candidate CSV rows use their own `election_dt`; the annual file is never treated as one election roster.
- CSV-only election type may be inferred only from explicit source fields such as `party_contest` and `has_primary`; date/month heuristics are forbidden.
- Do not restore per-contest special-election splitting or reuse the legacy `election_type_from_date()` heuristic.
- Candidate rows repeated across counties become one normalized candidacy with every source row preserved as evidence.
- Names, party, contact data, jurisdiction, or office history never authorize automatic Person linking.
- Measure filtering is word-aware, examines only normalized contest names, and never examines candidate names.
- Filing address, phone, and email remain protected evidence and never appear in public models, SyncLog aggregates, exceptions, or public fixtures.
- Tests use frozen sanitized fixtures and require no network access.
- The user-owned `docs/state-research/Full Core/NC/results_pct_20260303.txt` file remains untouched.
- No production task, scheduler, database, queue, or credential is modified.
- Development API remains bound to `0.0.0.0:58000`; PostgreSQL and Redis remain internal-only.

---

### Task 1: Preserve Multi-artifact Provenance and Structured Mapping Notices

**Files:**
- Modify: `backend/cm2_ingestion/contracts.py`
- Modify: `backend/cm2_ingestion/capabilities.py`
- Modify: `backend/cm2_ingestion/persistence.py`
- Modify: `backend/cm2_ingestion/tests/test_contracts.py`
- Modify: `backend/cm2_ingestion/tests/test_persistence.py`

**Interfaces:**
- Produces: `IngestionNotice(code: str, subject_type: str, subject_public_id: str)`.
- Extends: `ElectionRecord.source_artifact_public_id: str | None`.
- Extends: `PreElectionBatch.notices: tuple[IngestionNotice, ...]`.
- Changes: `CandidateSource.parse(content: bytes, *, discovered_elections: tuple[ElectionRecord, ...] = ()) -> PreElectionBatch`.

- [x] **Step 1: Write failing contract tests**

Add literal tests proving duplicate notices, malformed notice codes, and empty notice subjects are rejected without echoing source evidence. Prove a valid `csv_only_election` notice is accepted.

- [x] **Step 2: Run contract tests and verify RED**

Run: `python -m pytest -c pytest-v2.ini cm2_ingestion/tests/test_contracts.py -v`

Expected: collection fails because `IngestionNotice` and the new fields do not exist.

- [x] **Step 3: Implement immutable notice and provenance contracts**

Use frozen/slotted dataclasses. Notice codes must match `^[a-z][a-z0-9_]*$`; `(code, subject_type, subject_public_id)` must be unique within a batch. Change the candidate capability protocol to return a complete normalized batch.

- [x] **Step 4: Write failing persistence tests**

Create a separate election-discovery `SourceArtifact`, set its public ID on `ElectionRecord`, and prove the persisted Election uses that artifact while Contest, Candidacy, and source evidence use the candidate artifact. Assert notice counts are numeric SyncLog aggregates and notice details contain public IDs only.

- [x] **Step 5: Run persistence tests and verify RED**

Run: `python -m pytest -c pytest-v2.ini cm2_ingestion/tests/test_persistence.py -v`

Expected: Election still uses the candidate artifact and notice data is absent.

- [x] **Step 6: Implement provenance override and notice persistence**

Resolve an optional Election artifact public ID inside the domain transaction. A missing artifact raises a sanitized `ContractValidationError` and rolls back the batch. Add `notices_<code>` integer counts to SyncLog and `{code, subject_type, subject_public_id}` entries to ReconciliationReport.

- [x] **Step 7: Run ingestion framework tests and verify GREEN**

Run: `python -m pytest -c pytest-v2.ini cm2_ingestion -v`

Expected: all ingestion framework tests pass.

### Task 2: Add Frozen NC Source Fixtures and Pure Parsers

**Files:**
- Create: `backend/cm2_nc/__init__.py`
- Create: `backend/cm2_nc/apps.py`
- Create: `backend/cm2_nc/constants.py`
- Create: `backend/cm2_nc/source_records.py`
- Create: `backend/cm2_nc/sources/__init__.py`
- Create: `backend/cm2_nc/sources/upcoming_elections.py`
- Create: `backend/cm2_nc/sources/candidate_filings.py`
- Create: `backend/cm2_nc/tests/__init__.py`
- Create: `backend/cm2_nc/tests/fixtures/upcoming_elections_2026.html`
- Create: `backend/cm2_nc/tests/fixtures/candidate_listing_2026_sanitized.csv`
- Create: `backend/cm2_nc/tests/fixtures/layout_candidate_listing.txt`
- Create: `backend/cm2_nc/tests/test_sources.py`
- Modify: `backend/config/settings/v2.py`
- Modify: `backend/pytest-v2.ini`

**Interfaces:**
- Produces: `NcCandidateRow` with typed date, boolean, integer, party, contest, name, filing, and protected fields.
- Produces: `parse_upcoming_elections(content: bytes, *, source_artifact_public_id: str | None = None) -> tuple[ElectionRecord, ...]`.
- Produces: `parse_candidate_rows(content: bytes) -> tuple[NcCandidateRow, ...]`.
- Produces: `NcUpcomingElectionsSource` and `NcCandidateFilingsSource` acquisition/capability objects.

- [x] **Step 1: Add sanitized fixtures and failing parser tests**

The HTML fixture contains explicit March 3 primary and November 3 general sections plus unrelated deadline dates. The CSV fixture uses the official 25-column layout, replaces all contact values, includes repeated county rows, primary/general rows, federal/state/judicial/county/municipal contests, a measure-like contest, and a valid candidate whose personal name contains `Resolution`.

- [x] **Step 2: Run source tests and verify RED**

Run: `python -m pytest -c pytest-v2.ini cm2_nc/tests/test_sources.py -v`

Expected: collection fails because `cm2_nc.sources` does not exist.

- [x] **Step 3: Implement strict privacy-safe parsing**

Parse election types only from section labels. Parse candidate dates as `%m/%d/%Y`, booleans as `TRUE/FALSE`, and positive `vote_for`/`term` integers. Validate the official required headers before reading rows. Structural exceptions identify only row number and field name, never the rejected value.

- [x] **Step 4: Implement injectable source acquisition**

Use the official HTTPS constants, a fixed timeout, and an injectable requests session. Return response bytes after `raise_for_status()`; normal tests use a local fake response and never call the network.

- [x] **Step 5: Install the isolated NC package and verify GREEN**

Add `cm2_nc` to v2 settings and test paths. Run the source tests and expect all to pass.

### Task 3: Map Every People-based NC Contest and Exclude Measures

**Files:**
- Create: `backend/cm2_nc/mapping/__init__.py`
- Create: `backend/cm2_nc/mapping/identity.py`
- Create: `backend/cm2_nc/mapping/measures.py`
- Create: `backend/cm2_nc/mapping/jurisdictions.py`
- Create: `backend/cm2_nc/mapping/offices.py`
- Create: `backend/cm2_nc/tests/test_mapping.py`

**Interfaces:**
- Produces: `stable_public_id(kind: str, *parts: str) -> str` using normalized source parts plus a collision-resistant digest.
- Produces: `is_measure_contest(contest_name: str) -> bool`.
- Produces: `map_jurisdiction(contest_name: str, county_name: str) -> tuple[JurisdictionRecord, ...]`.
- Produces: `map_office(contest_name: str, jurisdiction: JurisdictionRecord, *, term_years: int, vote_for: int) -> OfficeRecord`.

- [x] **Step 1: Write failing measure and identity tests**

Prove singular/plural measure terms match on word boundaries, `Bondsman` does not match `bond`, and candidate name `Jordan Resolution` does not exclude a valid `US SENATE` contest. Prove stable IDs do not collide for judicial seats, party contests, or similarly normalized municipal names.

- [x] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest -c pytest-v2.ini cm2_nc/tests/test_mapping.py -v`

Expected: mapping imports fail.

- [x] **Step 3: Implement deterministic identity and measure filtering**

Normalize Unicode/whitespace/case for identity inputs but retain a SHA-256 prefix in every public ID. Match only these whole contest-name words: `referendum`, `referenda`, `bond`, `bonds`, `amendment`, `measure`, `proposition`, `question`, `initiative`, `levy`, `ordinance`, and `resolution`.

- [x] **Step 4: Implement jurisdiction mapping**

Map state, congressional district, state legislative district, judicial district, county, school district, municipality, soil/water district, sanitary district, and safe `other` fallback scopes. Always include North Carolina as the parent where applicable. District and seat tokens remain distinct.

- [x] **Step 5: Implement permanent-office mapping**

Strip only the explicit `(UNEXPIRED)` marker from canonical Office identity. Preserve district/ward/seat distinctions needed by the Contest uniqueness constraint. Derive bounded roles such as `senator`, `representative`, `judge`, `justice`, `mayor`, `commissioner`, `sheriff`, `clerk`, `board_member`, `supervisor`, or `elected_official`.

- [x] **Step 6: Run mapping tests and verify GREEN**

Expected: every representative supported scope and measure boundary passes.

### Task 4: Build Complete NC Pre-election Batches

**Files:**
- Create: `backend/cm2_nc/mapping/batch.py`
- Create: `backend/cm2_nc/tests/test_batch.py`
- Create: `backend/cm2_nc/tests/fixtures/expected_pre_election_manifest.json`

**Interfaces:**
- Produces: `build_pre_election_batch(rows: tuple[NcCandidateRow, ...], *, discovered_elections: tuple[ElectionRecord, ...] = ()) -> PreElectionBatch`.
- Produces complete Jurisdiction, Office, Election, Contest, CandidateFiling, source-evidence, and notice tuples accepted by `validate_pre_election_batch()`.

- [x] **Step 1: Write failing batch and manifest tests**

Assert literal fixture totals and representative IDs. Prove repeated county rows create one Candidacy with two `PersonSourceEvidence` rows, primary DEM/REP and general contests stay distinct, the measure-like contest is absent with a `measure_excluded` notice, and the valid candidate named `Jordan Resolution` remains.

- [x] **Step 2: Run batch tests and verify RED**

Run: `python -m pytest -c pytest-v2.ini cm2_nc/tests/test_batch.py -v`

Expected: `build_pre_election_batch` is missing.

- [x] **Step 3: Implement explicit election association**

Match discovery elections by `(election_dt, explicit election_type)`. For candidate dates absent from discovery, create one provisional Election: use `primary` only when any row has nonblank `party_contest` or true `has_primary`; otherwise use `other`. Emit one `csv_only_election` notice. Never inspect the month.

- [x] **Step 4: Implement contest and candidacy grouping**

Group Contest identity by Election, Office, `party_contest`, and `is_unexpired`. Reject conflicting `vote_for`, `is_partisan`, or term values inside a normalized contest group. Group repeated source rows into a filing using public name components, party, filing date, and Contest; retain each row with a deterministic non-PII lineage key.

- [x] **Step 5: Map protected evidence without public leakage**

Store combined address, phone variants, and email only on `PersonSourceEvidence`. Keep public filing metadata to county, source row number, source flags, and Contest public ID. Do not place protected values in notices or public IDs.

- [x] **Step 6: Run batch tests and verify GREEN**

Expected: fixture output exactly matches `expected_pre_election_manifest.json` and passes shared contract validation.

### Task 5: Register and Persist the NC Pre-election Capability

**Files:**
- Create: `backend/cm2_nc/capabilities.py`
- Create: `backend/cm2_nc/ingest.py`
- Create: `backend/cm2_nc/tests/test_ingest.py`
- Modify: `backend/cm2_ingestion/capabilities.py`
- Modify: `backend/cm2_ingestion/tests/test_capabilities.py`

**Interfaces:**
- Produces: `build_nc_capabilities() -> StateCapabilities` with discovery and candidates only.
- Produces: `ingest_nc_pre_election_contents(*, upcoming_content: bytes, candidate_content: bytes, retrieved_at: datetime, upcoming_url: str = ..., candidate_url: str = ...) -> ReconciliationReport`.

- [x] **Step 1: Write failing capability and end-to-end tests**

Prove the NC registry exposes discovery/candidates and explicitly rejects results/certification. Ingest both fixtures into PostgreSQL and assert manifest entity counts, source-artifact provenance, protected source evidence, aggregate-only SyncLog data, public notice details, and zero legacy tables.

- [x] **Step 2: Run end-to-end tests and verify RED**

Run: `python -m pytest -c pytest-v2.ini cm2_nc/tests/test_ingest.py cm2_ingestion/tests/test_capabilities.py -v`

Expected: NC capability/ingest functions are absent.

- [x] **Step 3: Implement content-addressed orchestration**

Register separate election and candidate artifacts, parse/map both, then call `apply_pre_election_batch()` with the candidate artifact. On success mark both artifacts applied. On parse failure mark the responsible artifact failed with a structural sanitized summary and persist a failed pre-election SyncLog without domain rows.

- [x] **Step 4: Prove replay and changed-artifact behavior**

Replaying identical content returns the same report and creates no duplicate entities. A changed candidate artifact with the same non-PII source-row lineage reuses prior People; changed protected contact fields create new immutable source evidence without changing public identity automatically.

- [x] **Step 5: Run all NC and ingestion tests and verify GREEN**

Run: `python -m pytest -c pytest-v2.ini cm2_nc cm2_ingestion -v`

Expected: all tests pass without network access.

### Task 6: Canonical and Isolated Runtime Verification

**Files:**
- Modify: this plan's checkboxes only.

- [x] **Step 1: Run `make verify-v2`**

Expected: Python/Django/migration/Ruff gates and every `cm2_*` test pass.

- [x] **Step 2: Inspect the isolated PostgreSQL schema**

Expected: framework and `cm2_*` tables only, with zero legacy domain tables and no pending migration.

- [x] **Step 3: Rebuild and verify the development API**

Expected: healthy API through both `127.0.0.1:58000` and `192.168.1.102:58000`; Postgres and Redis have no host port mappings.

- [x] **Step 4: Run final scope and privacy checks**

Run `git diff --check`, shell/YAML validation, migration dependency inspection, protected-value searches limited to public outputs/log assertions, unchecked-plan scan, and `git status --short`. Confirm the user-owned NC results sample size and modification time are unchanged. Do not commit or stage files.
