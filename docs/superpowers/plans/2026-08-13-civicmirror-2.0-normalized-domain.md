# CivicMirror 2.0 Normalized Domain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the isolated CivicMirror 2.0 normalized election domain, database constraints, protected source evidence, review records, Admin registrations, privacy-safe serializers, and fresh-database migrations.

**Architecture:** Keep the legacy applications untouched and split the new domain across collision-free apps with one-way dependencies: `cm2_core` owns source artifacts and shared abstract fields; `cm2_elections` owns jurisdictions, offices, elections, people, and candidacies; `cm2_results` owns current contest results and choices; `cm2_review` owns auditable identity-review cases and suggestions. The apps are installed only by `config.settings.v2` and use UUID database keys plus separate stable `public_id` values.

**Tech Stack:** Python 3.13, Django 5.2, Django REST Framework, PostgreSQL 16, pytest-django, Ruff, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-13-civicmirror-2.0-nc-pilot-design.md`

## Global Constraints

- Work only on `feat/civicmirror-2.0-nc-pilot`; do not modify production infrastructure or legacy domain migrations.
- New Django app names and labels start with `cm2_`; `config.settings.v2` must continue excluding every legacy domain app.
- Every persisted 2.0 domain entity uses a UUID primary key. Public domain entities also receive a separate unique `public_id`; names are never Person identifiers.
- Source artifacts are content-addressed and idempotent by source, URL, and SHA-256 checksum.
- Names, contact fields, addresses, party, jurisdiction, and office history never authorize an automatic Person merge.
- Personal filing address, phone, and email evidence is stored only on `PersonSourceRecord`, never in public serializers, health payloads, or logs.
- A matched result choice requires a Candidacy. A write-in aggregate forbids a Candidacy and uses `not_applicable` resolution.
- Named write-ins may remain unresolved without creating a Person or Candidacy.
- Empty-database migrations must create only Django framework tables and `cm2_*` tables.
- Existing Phase 1 verification remains canonical through `make verify-v2`.
- The user-owned NC result sample remains unmodified.
- Do not stage, commit, push, or deploy without a separate request.

---

### Task 1: Add Source Artifacts and Shared Model Foundations

**Files:**
- Modify: `backend/cm2_core/models.py`
- Create: `backend/cm2_core/tests/test_source_artifact.py`
- Modify: `backend/cm2_core/admin.py`
- Modify: `backend/config/settings/v2.py`
- Modify: `backend/pytest-v2.ini`

**Interfaces:**
- Produces: `cm2_core.models.UUIDModel`, `PublicIdentityModel`, and `SourceTrackedModel` abstract models.
- Produces: `SourceArtifact` with `SourceType`, `ProcessingStatus`, checksum validation, version linkage, and idempotent uniqueness.
- Consumed by: all later Phase 2 apps and migrations.

- [x] **Step 1: Write failing source-artifact tests**

Test real database behavior for UUID/public-id separation, rejection of duplicate `(source_system, url, content_sha256)` artifacts, acceptance of changed checksums as a new version, SHA-256 format validation through `full_clean()`, and preservation of source/election/retrieval/parser context.

```python
@pytest.mark.django_db
def test_unchanged_source_artifact_is_idempotent(source_artifact):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SourceArtifact.objects.create(
                source_system=source_artifact.source_system,
                source_type=source_artifact.source_type,
                url=source_artifact.url,
                retrieved_at=source_artifact.retrieved_at,
                content_sha256=source_artifact.content_sha256,
                parser_version="different-parser",
            )
```

- [x] **Step 2: Run the focused test and verify RED**

Run inside the development container with the existing v2 SQLite test environment:

```bash
python -m pytest cm2_core/tests/test_source_artifact.py -v --tb=short
```

Expected: collection fails because `SourceArtifact` does not exist.

- [x] **Step 3: Implement the shared models and source artifact**

`UUIDModel` supplies UUID `id`, created/updated timestamps. `PublicIdentityModel` adds a unique 255-character `public_id` defaulting to an independently generated UUID string. `SourceTrackedModel` adds nullable protected `source_artifact`, a 512-character `source_key`, and JSON `source_metadata`.

`SourceArtifact` fields are: `source_system`, `source_type`, `url` (2048 characters), `retrieved_at`, nullable `source_timestamp`, `content_sha256`, `parser_version`, nullable `election_date`, `processing_status`, `error`, `metadata`, nullable `supersedes`, and inherited identifiers/timestamps. Add a database unique constraint over source system, URL, and checksum, plus indexes for `(source_system, source_type, election_date)` and processing status.

- [x] **Step 4: Register `SourceArtifact` in Admin and expand v2 test discovery**

Admin list output contains source system, type, retrieval time, election date, status, and checksum prefix; source content identity and timestamps are readonly. Add `cm2_elections`, `cm2_results`, and `cm2_review` to `INSTALLED_APPS` only when their packages exist during the incremental TDD cycle. Set `pytest-v2.ini` test paths to all four `cm2_*` apps once created.

- [x] **Step 5: Run source-artifact tests and verify GREEN**

Expected: all source-artifact tests pass with no warnings.

### Task 2: Add the Election and Person Domain

**Files:**
- Create: `backend/cm2_elections/__init__.py`
- Create: `backend/cm2_elections/apps.py`
- Create: `backend/cm2_elections/models.py`
- Create: `backend/cm2_elections/tests/__init__.py`
- Create: `backend/cm2_elections/tests/conftest.py`
- Create: `backend/cm2_elections/tests/test_models.py`
- Modify: `backend/config/settings/v2.py`

**Interfaces:**
- Produces: `Jurisdiction`, `Office`, `Election`, `Contest`, `Person`, `PersonIdentifier`, `PersonSourceRecord`, `Candidacy`, and `OfficeTerm`.
- Consumes: `cm2_core.SourceArtifact`, `PublicIdentityModel`, and `SourceTrackedModel`.
- Produces relation names used later: `Election.contests`, `Contest.candidacies`, `Person.candidacies`, and `Office.contests`.

- [x] **Step 1: Write failing model and constraint tests**

Use real database rows and literal expected values. Cover:

- Two People may share the same canonical name and receive distinct IDs.
- A merged Person must have a different redirect target; every non-merged Person must leave `merged_into` null.
- `(scheme, identifier)` is globally unique and a human-reviewed identifier requires both reviewer and timestamp.
- A Jurisdiction cannot parent itself and active dates cannot be reversed.
- Office position count, Contest `vote_for`, and OfficeTerm date ranges must be valid.
- Primary party scope and unexpired status participate in Contest uniqueness.
- A Person may have only one Candidacy in a Contest, while ballot names remain election-specific.
- A PersonSourceRecord retains reported/ballot names and protected fields without exposing them through a Person relation serializer.

```python
@pytest.mark.django_db
def test_names_never_merge_people():
    first = Person.objects.create(canonical_name="Dedreana Freeman")
    second = Person.objects.create(canonical_name="Dedreana Freeman")
    assert first.id != second.id
    assert first.public_id != second.public_id


@pytest.mark.django_db
def test_primary_party_is_part_of_contest_identity(election, office):
    democratic = Contest.objects.create(
        election=election, office=office, party_contest="democratic", public_id="contest/democratic"
    )
    republican = Contest.objects.create(
        election=election, office=office, party_contest="republican", public_id="contest/republican"
    )
    assert democratic.id != republican.id
```

- [x] **Step 2: Run model tests and verify RED**

Expected: collection fails because `cm2_elections` does not exist.

- [x] **Step 3: Implement geography, office, election, and contest models**

Implement the exact domain fields from the design. Use `PROTECT` for permanent civic relationships and source evidence. Add database constraints for valid date ranges, positive stable office positions, positive `vote_for`, no self-parent, and unique `(election, office, party_contest, is_unexpired)` Contest identity. Contest lifecycle and result-status choices must retain provisional and pending states.

- [x] **Step 4: Implement Person, source record, candidacy, identifier, and office-term models**

Person identity states are exactly `provisional`, `resolved`, `disputed`, and `merged`. `PersonIdentifier` stores a reviewer foreign key and verification timestamp. `PersonSourceRecord` is the only model with protected address, phone, and email fields and has unique `(source_artifact, source_row_key)` lineage. Candidacy stores ballot name, candidate party, filing date, status, and source-record many-to-many provenance. OfficeTerm stores approved role history and date/method evidence.

- [x] **Step 5: Run model tests and verify GREEN**

Expected: every `cm2_elections` model and constraint test passes.

### Task 3: Add Current Result Projections and Unresolved Choices

**Files:**
- Create: `backend/cm2_results/__init__.py`
- Create: `backend/cm2_results/apps.py`
- Create: `backend/cm2_results/models.py`
- Create: `backend/cm2_results/tests/__init__.py`
- Create: `backend/cm2_results/tests/test_models.py`
- Modify: `backend/config/settings/v2.py`

**Interfaces:**
- Produces: `ContestResult` and `ResultChoice`.
- Consumes: `cm2_elections.Contest`, `cm2_elections.Candidacy`, and `cm2_core.SourceArtifact`.
- Produces: `Contest.current_result`, `ContestResult.choices`, and `Candidacy.result_choices`.

- [x] **Step 1: Write failing result-choice tests**

Cover all representational cases from the approved design:

```python
@pytest.mark.django_db
def test_unresolved_named_write_in_needs_no_person_or_candidacy(contest_result, source_artifact):
    choice = ResultChoice.objects.create(
        contest_result=contest_result,
        source_label="Jane Doe (Write-In)",
        normalized_label="jane doe",
        choice_type=ResultChoice.ChoiceType.NAMED_WRITE_IN,
        resolution_status=ResultChoice.ResolutionStatus.UNRESOLVED,
        vote_total=41,
        source_artifact=source_artifact,
        source_choice_key="jane-doe-write-in",
    )
    assert choice.candidacy is None


@pytest.mark.django_db
def test_aggregate_write_in_forbids_candidacy(contest_result, candidacy, source_artifact):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ResultChoice.objects.create(
                contest_result=contest_result,
                source_label="Write-In (Miscellaneous)",
                normalized_label="write in miscellaneous",
                choice_type="write_in_aggregate",
                resolution_status="not_applicable",
                candidacy=candidacy,
                vote_total=17,
                source_artifact=source_artifact,
                source_choice_key="misc-write-in",
            )
```

Also prove that matched choices require a Candidacy, provisional ordinary candidates may reference a provisional Candidacy, totals are nonnegative, percentages stay between 0 and 100, and source-choice keys are unique within a ContestResult.

- [x] **Step 2: Run result tests and verify RED**

Expected: collection fails because `cm2_results` does not exist.

- [x] **Step 3: Implement result models and exact database constraints**

`ContestResult` is a one-to-one current projection for a Contest and stores status (`pending`, `unofficial`, `official`, `certified`, or `corrected`), nullable source artifact, total votes, report/certification times, source evidence JSON, and inherited identifiers/timestamps.

`ResultChoice` stores exact and normalized labels, choice/resolution enums, nullable Candidacy, vote total, four-decimal percentage, nullable winner support, required source artifact/key, and observation lineage JSON. Constraints implement the approved matched and aggregate rules exactly and do not require a Person for unresolved named write-ins.

- [x] **Step 4: Run result tests and verify GREEN**

Expected: all result model tests pass.

### Task 4: Add Persistent Identity Review Records

**Files:**
- Create: `backend/cm2_review/__init__.py`
- Create: `backend/cm2_review/apps.py`
- Create: `backend/cm2_review/models.py`
- Create: `backend/cm2_review/tests/__init__.py`
- Create: `backend/cm2_review/tests/test_models.py`
- Modify: `backend/config/settings/v2.py`

**Interfaces:**
- Produces: `IdentityReviewCase` and `IdentityReviewSuggestion`.
- Consumes: Person, PersonSourceRecord, ResultChoice, and Django reviewer users.
- Produces: unique `deduplication_key` behavior preventing unchanged rejected evidence from reopening duplicate cases.

- [x] **Step 1: Write failing review-model tests**

Cover unique review deduplication, open-case defaults, required review metadata for approved/rejected states, local Person suggestions, Civic-Data external suggestions, retention of supporting/conflicting evidence, and explicit private-evidence flags. Do not assert private values in test failure messages.

- [x] **Step 2: Run review tests and verify RED**

Expected: collection fails because `cm2_review` does not exist.

- [x] **Step 3: Implement review case and suggestion models**

Review states are exactly `open`, `approved`, `rejected`, `deferred`, and `superseded`. Resolution actions are exactly `link_existing`, `confirm_new`, `merge_people`, `link_civic_data`, and `defer`. A case references a source record and/or provisional Person and optionally a ResultChoice. Suggestions reference either a local Person or a namespaced external identifier, preserve evidence JSON, and carry a private-evidence flag. Database constraints prevent an empty suggestion target and require reviewer/timestamp for approved or rejected cases.

- [x] **Step 4: Run review tests and verify GREEN**

Expected: all review model tests pass.

### Task 5: Add Admin, Privacy-safe Serializers, and Empty-database Migrations

**Files:**
- Create: `backend/cm2_elections/admin.py`
- Create: `backend/cm2_elections/serializers.py`
- Create: `backend/cm2_elections/tests/test_serializers.py`
- Create: `backend/cm2_results/admin.py`
- Create: `backend/cm2_results/serializers.py`
- Create: `backend/cm2_results/tests/test_serializers.py`
- Create: `backend/cm2_review/admin.py`
- Create: generated `backend/cm2_core/migrations/0001_initial.py`
- Create: generated `backend/cm2_elections/migrations/0001_initial.py`
- Create: generated `backend/cm2_results/migrations/0001_initial.py`
- Create: generated `backend/cm2_review/migrations/0001_initial.py`
- Modify: `backend/cm2_core/tests/test_foundation.py`

**Interfaces:**
- Produces: public `PersonSerializer`, `CandidacySerializer`, election/geography serializers, `ContestResultSerializer`, and `ResultChoiceSerializer`.
- Produces: Django Admin list/filter/search pages for all Phase 2 models.
- Produces: a fresh v2 schema containing only framework and `cm2_*` tables.

- [x] **Step 1: Write failing privacy and serializer tests**

Serialize a Person and Candidacy backed by a PersonSourceRecord containing unmistakable protected address/phone/email values. Recursively inspect serialized output and prove none of the protected field names or values appear. Prove Candidacy retains the source ballot spelling and unresolved ResultChoice output retains the reported name without inventing a Person.

- [x] **Step 2: Run serializer tests and verify RED**

Expected: imports fail because the serializers do not exist.

- [x] **Step 3: Implement public serializers**

Expose public IDs and normalized public domain fields. Never add a public PersonSourceRecord serializer. Represent foreign relationships with stable public IDs, not database UUIDs. Keep review records and source artifacts out of public serializers.

- [x] **Step 4: Register all Phase 2 models in Admin**

Use raw-ID/autocomplete relationships for large tables. PersonSourceRecord protected evidence is readonly in Admin and never included in list display or broad search results. Identity review lists expose status, case type, timestamps, and reviewer but not protected evidence.

- [x] **Step 5: Generate initial migrations in dependency order**

Run:

```bash
python manage.py makemigrations cm2_core cm2_elections cm2_results cm2_review --settings=config.settings.v2
```

Inspect generated migrations for dependencies on `cm2_core`, `cm2_elections`, Django auth, and `cm2_results`; reject any dependency on a legacy application.

- [x] **Step 6: Extend the foundation schema test**

Assert that expected `cm2_core_*`, `cm2_elections_*`, `cm2_results_*`, and `cm2_review_*` tables exist after test migration while legacy table prefixes remain absent.

- [x] **Step 7: Run all Phase 2 tests and verify GREEN**

Run `python -m pytest -c pytest-v2.ini -v --tb=short` in the v2 container environment.

### Task 6: Canonical Verification and Runtime Inspection

**Files:**
- Modify: `docs/superpowers/plans/2026-08-13-civicmirror-2.0-normalized-domain.md` checkboxes only.

**Interfaces:**
- Consumes: all Phase 1 and Phase 2 code.
- Produces: verification evidence for the normalized-domain checkpoint.

- [x] **Step 1: Run canonical verification**

```bash
make verify-v2
```

Expected: Python assertion, Django checks, migration consistency, Ruff, and all `cm2_*` tests pass without warnings.

- [x] **Step 2: Inspect the isolated PostgreSQL schema**

Run migrations only against the `civicmirror_2_0` Compose database, then list public tables. Expected: Django framework tables and `cm2_*` tables only; no legacy election, results, aggregation, accounts, community, operations, internal, or state-integration tables.

- [x] **Step 3: Recheck runtime and LAN health**

Confirm the API remains healthy on `0.0.0.0:58000` and both loopback and `192.168.1.102` return the version 2.0 NC health payload. PostgreSQL and Redis must still have no host port mappings.

- [x] **Step 4: Inspect final scope without committing**

Run `git diff --check`, YAML/shell syntax checks, and `git status --short`. Confirm the protected NC sample is unchanged and do not stage, commit, push, deploy, or alter production containers.
