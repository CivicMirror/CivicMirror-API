# CivicMirror 2.0 North Carolina Post-election Results Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest the NC State Board of Elections precinct-level results ZIP (`results_pct_YYYYMMDD.zip`) into the CivicMirror 2.0 normalized domain — matching result contests to existing pre-election `Contest`s (or provisioning them when result-only), aggregating precinct observations exactly once per contest/choice, resolving ordinary candidate choices to `Candidacy` records deterministically or via non-blocking human review, and recording named/aggregate write-ins per the spec's rules — without ever inferring certification or winners from the source alone.

**Architecture:** Mirrors the pre-election pipeline exactly: a pure `cm2_nc.mapping.results` module turns parsed `NcResultRow` records into a `PostElectionBatch` contract (jurisdictions/offices/contests to upsert, `PrecinctResultObservation`s to aggregate, exclusion notices); `cm2_ingestion.aggregation` (already built) sums precinct rows into `AggregatedResultChoice`s; a new `cm2_ingestion/results_persistence.py` applies the batch inside one transaction, reusing `cm2_review`'s existing `IdentityReviewCase`/`UNRESOLVED_RESULT_CHOICE` machinery for anything that can't be linked deterministically. Two small refactors happen first so both the pre-election and results persistence paths share one set of entity-upsert helpers and one contest-key formula, instead of duplicating them.

**Tech Stack:** Python 3.13, Django 5.2, `difflib` (stdlib, already used by `cm2_review.matching`), pytest-django, PostgreSQL 16.

**Spec:** `docs/superpowers/specs/2026-08-13-civicmirror-2.0-nc-pilot-design.md` (see "NC post-election workflow", lines 473–514, and "Identity resolution and human review"); issue #192 sections 9–11. Prior completed slices: `docs/superpowers/plans/2026-08-13-civicmirror-2.0-ingestion-framework.md`, `docs/superpowers/plans/2026-08-13-civicmirror-2.0-nc-pre-election.md`.

## Global Constraints

- Python 3.13 only; every task ends with `docker exec civicmirror-2-0-api-1 python manage.py makemigrations --check --dry-run --settings=config.settings.v2` (no missing migrations expected — this feature adds no new models) and `make verify-v2` passing before that task's commit.
- Only `NC` is enabled in the capability registry; this plan does not touch other states.
- State-specific code (`cm2_nc`) parses and maps; it never writes domain models directly. All writes go through `cm2_ingestion/results_persistence.py`.
- A contest is excluded from ingestion when its normalized *base* name (after stripping `(UNEXPIRED)`/party suffixes) indicates a referendum, bond, amendment, measure, proposition, question, initiative, levy, ordinance, or resolution — reuse `cm2_nc.mapping.measures.is_measure_contest`, do not duplicate the word list.
- Contest identity is fully determined by `(election, office, party_contest, is_unexpired)`, using the same `stable_public_id`-based formula pre-election already uses. Results never invent a new `Election` — if no persisted `Election` matches the results file's date (optionally disambiguated by primary/general the same way pre-election CSV rows are), raise `ContractValidationError` rather than guess.
- Names, party, and contact fields never authorize an automatic `Person` merge. An ordinary candidate choice may auto-link to a `Candidacy` only via an exact normalized-name match that is unique within its `Contest`; anything fuzzy or ambiguous becomes a non-blocking `IdentityReviewCase` (`case_type=UNRESOLVED_RESULT_CHOICE` for choice-matching ambiguity, `case_type=PERSON_IDENTITY`/`FUZZY_PERSON_MATCH` for a genuinely new candidate, exactly like pre-election).
- Named write-ins (e.g. `Jane Doe (Write-In)`) become `ResultChoice(choice_type=NAMED_WRITE_IN, resolution_status=UNRESOLVED)` with **no** `Person`/`Candidacy`, and always get a review case. Anonymous write-in buckets (`Write-In (Miscellaneous)`, `Miscellaneous (Write-In)`, any casing) become `ResultChoice(choice_type=WRITE_IN_AGGREGATE, resolution_status=NOT_APPLICABLE, candidacy=None)` and stay in vote/percentage totals.
- Results are never treated as official or certified by this ingestion. Every `ContestResult` this path creates gets `status=UNOFFICIAL`; on a re-run/correction, `status` is left untouched unless it is still `PENDING`, so a later, separate certification capability can't be silently downgraded by a correction replay.
- `ResultChoice.is_winner` is always left `NULL` by this ingestion — the source TSV carries no winner signal, and the design forbids deriving winners from vote totals.
- A missing results ZIP leaves the `Contest` in its existing `result_status`; it does not delete or alter the `Election`, other `Contest`s, `Person`s, or `Candidacy`s.
- Re-running with the same content is idempotent (same `SyncLog.run_key`, replay returns the existing `ReconciliationReport`); re-running with corrected content upserts by `(contest_result, source_choice_key)` — **never delete-then-recreate** `ResultChoice` rows, because `IdentityReviewCase.result_choice` is `on_delete=PROTECT` and would crash a correction that touches a choice with an open case.
- Tests use frozen, sanitized, in-memory-built fixtures (a small subset of `docs/state-research/Full Core/NC/results_pct_20260303.txt`, zipped in test setup — never commit a new binary fixture) and require no network access. The user-owned `docs/state-research/Full Core/NC/results_pct_20260303.txt` file remains untouched.
- Follow existing conventions: no docstrings beyond the sparse module-level style already used in `cm2_nc`/`cm2_ingestion`, no comments explaining *what* code does, `from __future__ import annotations` only where the file already uses it (none of the touched files currently use it — don't add it).

---

## File Structure

- `backend/cm2_ingestion/contracts.py` — **modify**. Add `choice_party` to `PrecinctResultObservation`/`AggregatedResultChoice`; add `PostElectionBatch` and `validate_post_election_batch`.
- `backend/cm2_ingestion/aggregation.py` — **modify**. Propagate `choice_party` through the metadata grouping tuple.
- `backend/cm2_ingestion/entities.py` — **new**. Shared entity upsert/tracking helpers (`upsert_public`, `track`, `persist_jurisdictions`, `persist_offices`, `persist_contests`) extracted from `persistence.py` so both pre-election and results persistence use one implementation.
- `backend/cm2_ingestion/persistence.py` — **modify**. Delegate to `entities.py` instead of its private inline helpers; no behavior change.
- `backend/cm2_ingestion/capabilities.py` — **modify**. `ResultsSource.parse` gains `existing_elections` and returns `PostElectionBatch`.
- `backend/cm2_ingestion/results_persistence.py` — **new**. `apply_post_election_batch`, mirroring `apply_pre_election_batch`.
- `backend/cm2_nc/mapping/identity.py` — **modify**. Add shared `contest_public_id(...)` helper.
- `backend/cm2_nc/mapping/batch.py` — **modify**. `_contest_key` delegates to the shared helper (no behavior change).
- `backend/cm2_nc/mapping/offices.py` — **modify**. `map_office(term_years: int | None = None, ...)`.
- `backend/cm2_nc/mapping/results.py` — **new**. `split_contest_label`, `classify_choice`, `normalized_choice_label`, `build_post_election_batch`.
- `backend/cm2_nc/source_records.py` — **modify**. Add `NcResultRow`.
- `backend/cm2_nc/sources/results.py` — **new**. `parse_results_rows` (ZIP → rows), `results_zip_url`, `NcResultsZipSource`.
- `backend/cm2_nc/constants.py` — **modify**. Add results parser version + S3 base/prefix constants.
- `backend/cm2_nc/capabilities.py` — **modify**. Register `results=NcResultsZipSource()` — constructed lazily per-election, see Task 6.
- `backend/cm2_nc/ingest.py` — **modify**. Add `ingest_nc_post_election_contents`.
- Tests: `backend/cm2_ingestion/tests/test_contracts.py`, `test_aggregation.py` (modify); `backend/cm2_ingestion/tests/test_results_persistence.py` (new); `backend/cm2_nc/tests/test_mapping.py`, `test_sources.py`, `test_ingest.py` (modify); `backend/cm2_nc/tests/fixtures/results_pct_sanitized.txt` (new, small hand-built TSV fixture, zipped in-memory by tests).

---

## Task 1: Extend result contracts with `choice_party` and `PostElectionBatch`

**Files:**
- Modify: `backend/cm2_ingestion/contracts.py`
- Modify: `backend/cm2_ingestion/aggregation.py`
- Test: `backend/cm2_ingestion/tests/test_contracts.py`
- Test: `backend/cm2_ingestion/tests/test_aggregation.py`

**Interfaces:**
- Produces: `PostElectionBatch(state, new_jurisdictions=(), new_offices=(), new_contests=(), observations=(), notices=())`; `validate_post_election_batch(batch: PostElectionBatch) -> None`; `PrecinctResultObservation.choice_party: str = ""`; `AggregatedResultChoice.choice_party: str = ""`.
- Consumes: `_unique_keys`, `_validate_jurisdiction_hierarchy`, `_NOTICE_CODE_RE` already in `contracts.py`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/cm2_ingestion/tests/test_contracts.py`:

```python
from cm2_ingestion.contracts import (
    ContestRecord,
    IngestionNotice,
    JurisdictionRecord,
    OfficeRecord,
    PostElectionBatch,
    PrecinctResultObservation,
    validate_post_election_batch,
)


def _results_jurisdiction():
    return JurisdictionRecord(
        public_id="nc/jurisdiction/state/north-carolina/aaaaaaaaaaaaaaaa",
        name="North Carolina",
        classification="state",
        state="NC",
        record_status="verified",
        source_key="NC",
    )


def _results_office(jurisdiction):
    return OfficeRecord(
        public_id="nc/office/us-senator/aaaaaaaaaaaaaaaa",
        jurisdiction_public_id=jurisdiction.public_id,
        canonical_name="U.S. Senator",
        role="senator",
        record_status="provisional",
        source_key="US SENATE",
    )


def _results_contest(office):
    return ContestRecord(
        public_id="nc/contest/us-senator/aaaaaaaaaaaaaaaa",
        election_public_id="nc/election/2026-03-03/primary/aaaaaaaaaaaaaaaa",
        office_public_id=office.public_id,
        party_contest="REP",
        vote_for=1,
        is_partisan=True,
        source_key="US SENATE (REP)",
    )


def test_post_election_batch_validates_state_and_uniqueness():
    jurisdiction = _results_jurisdiction()
    office = _results_office(jurisdiction)
    contest = _results_contest(office)
    batch = PostElectionBatch(
        state="NC",
        new_jurisdictions=(jurisdiction,),
        new_offices=(office,),
        new_contests=(contest,),
        observations=(
            PrecinctResultObservation(
                source_observation_key="obs-1",
                contest_public_id=contest.public_id,
                source_choice_key="choice-1",
                source_label="Elizabeth A. Temple",
                normalized_label="elizabeth a. temple",
                choice_type="candidate",
                choice_party="REP",
                vote_total=33,
            ),
        ),
    )
    validate_post_election_batch(batch)


def test_post_election_batch_rejects_lowercase_state():
    with pytest.raises(ContractValidationError):
        validate_post_election_batch(PostElectionBatch(state="nc"))


def test_post_election_batch_rejects_duplicate_contest_public_ids():
    jurisdiction = _results_jurisdiction()
    office = _results_office(jurisdiction)
    contest = _results_contest(office)
    with pytest.raises(ContractValidationError):
        validate_post_election_batch(
            PostElectionBatch(
                state="NC",
                new_jurisdictions=(jurisdiction,),
                new_offices=(office,),
                new_contests=(contest, contest),
            )
        )


def test_post_election_batch_rejects_invalid_notice():
    with pytest.raises(ContractValidationError):
        validate_post_election_batch(
            PostElectionBatch(
                state="NC",
                notices=(IngestionNotice(code="Bad Code", subject_type="x", subject_public_id="y"),),
            )
        )
```

Add `import pytest` at the top of the file if not already present (it already is, since `ContractValidationError` cases exist elsewhere in the file — verify with `grep -n "^import pytest" backend/cm2_ingestion/tests/test_contracts.py`).

Append to `backend/cm2_ingestion/tests/test_aggregation.py`, inside the existing `observation()` helper, add a `choice_party` passthrough and one new test:

```python
def observation(
    observation_key,
    choice_key,
    label,
    choice_type,
    votes,
    *,
    contest="nc/2026-03-03/primary/durham-mayor",
    choice_party="",
):
    return PrecinctResultObservation(
        source_observation_key=observation_key,
        contest_public_id=contest,
        source_choice_key=choice_key,
        source_label=label,
        normalized_label=label.lower(),
        choice_type=choice_type,
        choice_party=choice_party,
        vote_total=votes,
    )


def test_aggregation_preserves_choice_party():
    aggregated = aggregate_precinct_observations(
        (
            observation("precinct-a/candidate", "candidate", "Elizabeth A. Temple", "candidate", 33, choice_party="REP"),
        )
    )
    assert aggregated[0].choice_party == "REP"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_ingestion/tests/test_contracts.py cm2_ingestion/tests/test_aggregation.py -v`
Expected: FAIL — `ImportError`/`AttributeError` for `PostElectionBatch`, `validate_post_election_batch`, `choice_party`.

- [ ] **Step 3: Implement**

In `backend/cm2_ingestion/contracts.py`, modify `PrecinctResultObservation` and `AggregatedResultChoice` to add `choice_party: str = ""` (after `choice_type`, before `vote_total`), and append after `validate_pre_election_batch`:

```python
@dataclass(frozen=True, slots=True)
class PostElectionBatch:
    state: str
    new_jurisdictions: tuple[JurisdictionRecord, ...] = ()
    new_offices: tuple[OfficeRecord, ...] = ()
    new_contests: tuple[ContestRecord, ...] = ()
    observations: tuple[PrecinctResultObservation, ...] = ()
    notices: tuple[IngestionNotice, ...] = ()


def validate_post_election_batch(batch: PostElectionBatch) -> None:
    if len(batch.state) != 2 or batch.state != batch.state.upper():
        raise ContractValidationError("batch state must be an uppercase two-letter code")

    jurisdiction_ids = _unique_keys(batch.new_jurisdictions, "public_id", "jurisdiction")
    office_ids = _unique_keys(batch.new_offices, "public_id", "office")
    contest_ids = _unique_keys(batch.new_contests, "public_id", "contest")
    _validate_jurisdiction_hierarchy(batch.new_jurisdictions, jurisdiction_ids)

    for jurisdiction in batch.new_jurisdictions:
        if jurisdiction.state != batch.state:
            raise ContractValidationError("jurisdiction state does not match batch state")

    for office in batch.new_offices:
        if office.jurisdiction_public_id not in jurisdiction_ids:
            raise ContractValidationError("office references unknown jurisdiction")
        if office.positions <= 0:
            raise ContractValidationError("office positions must be positive")

    for contest in batch.new_contests:
        if contest.office_public_id not in office_ids:
            raise ContractValidationError("contest references unknown office")
        if contest.vote_for <= 0:
            raise ContractValidationError("contest vote_for must be positive")

    observation_keys: set[str] = set()
    for observation in batch.observations:
        if not observation.contest_public_id:
            raise ContractValidationError("result observation must reference a contest")
        if not observation.source_choice_key:
            raise ContractValidationError("result observation must have a choice key")
        if observation.source_observation_key in observation_keys:
            raise ContractValidationError("duplicate result observation key")
        observation_keys.add(observation.source_observation_key)

    notice_keys: set[tuple[str, str, str]] = set()
    for notice in batch.notices:
        if not _NOTICE_CODE_RE.fullmatch(notice.code):
            raise ContractValidationError("ingestion notice code is invalid")
        if not notice.subject_type or not notice.subject_public_id:
            raise ContractValidationError("ingestion notice subject is required")
        notice_key = (notice.code, notice.subject_type, notice.subject_public_id)
        if notice_key in notice_keys:
            raise ContractValidationError("duplicate ingestion notice")
        notice_keys.add(notice_key)
```

Note: `contest_ids` is computed for its uniqueness check side effect (raises on duplicate `new_contests` public IDs) even though it is not referenced afterward — this matches the existing style of `election_ids`/`office_ids` in `validate_pre_election_batch`, which are also used for the collection call before being read.

In `backend/cm2_ingestion/aggregation.py`, extend the grouped `metadata` tuple:

```python
        metadata = (
            observation.source_label,
            observation.normalized_label,
            observation.choice_type,
            observation.choice_party,
        )
```

and unpack it symmetrically where consumed:

```python
        source_label, normalized_label, choice_type, choice_party = group["metadata"]
```

and pass `choice_party=choice_party` into the `AggregatedResultChoice(...)` construction.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_ingestion/tests/test_contracts.py cm2_ingestion/tests/test_aggregation.py -v`
Expected: PASS, plus full regression: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_ingestion -v` (existing tests untouched by the additive field).

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ingestion/contracts.py backend/cm2_ingestion/aggregation.py backend/cm2_ingestion/tests/test_contracts.py backend/cm2_ingestion/tests/test_aggregation.py
git commit -m "feat(cm2_ingestion): add PostElectionBatch contract and choice_party field"
```

---

## Task 2: Extract shared entity-upsert helpers (pure refactor)

**Files:**
- Create: `backend/cm2_ingestion/entities.py`
- Modify: `backend/cm2_ingestion/persistence.py`

**Interfaces:**
- Produces: `entities.upsert_public(model, public_id, values) -> tuple[instance, created, updated]`; `entities.track(*, category, instance, created, updated, counts, details) -> None`; `entities.persist_jurisdictions(*, artifact, records, counts, details) -> dict[str, Jurisdiction]`; `entities.persist_offices(*, artifact, records, jurisdictions, counts, details) -> dict[str, Office]`; `entities.persist_contests(*, artifact, records, elections, offices, counts, details) -> dict[str, Contest]`.
- Consumes: `cm2_core.models.SourceArtifact`, `cm2_elections.models.{Jurisdiction,Office,Election,Contest}`, `cm2_ingestion.contracts.{JurisdictionRecord,OfficeRecord,ContestRecord}`.

This task has no new *behavior* to test — it is a refactor. The safety net is the existing `cm2_ingestion`/`cm2_nc` suites, which must pass unchanged before and after.

- [ ] **Step 1: Confirm the pre-refactor baseline passes**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_ingestion cm2_nc -v`
Expected: PASS (this is the regression baseline you'll compare against after the refactor).

- [ ] **Step 2: Create `entities.py`**

```python
# backend/cm2_ingestion/entities.py
from cm2_core.models import SourceArtifact
from cm2_elections.models import Contest, Election, Jurisdiction, Office

from .contracts import ContestRecord, JurisdictionRecord, OfficeRecord


def upsert_public(model, public_id: str, values: dict):
    instance, created = model.objects.get_or_create(public_id=public_id, defaults=values)
    if created:
        return instance, True, False

    changed_fields = []
    for field_name, value in values.items():
        if getattr(instance, field_name) != value:
            setattr(instance, field_name, value)
            changed_fields.append(field_name)
    if changed_fields:
        instance.save(update_fields=[*changed_fields, "updated_at"])
    return instance, False, bool(changed_fields)


def upsert_natural(model, lookup: dict, values: dict):
    instance, created = model.objects.get_or_create(**lookup, defaults=values)
    if created:
        return instance, True, False

    changed_fields = []
    for field_name, value in values.items():
        if getattr(instance, field_name) != value:
            setattr(instance, field_name, value)
            changed_fields.append(field_name)
    if changed_fields:
        instance.save(update_fields=[*changed_fields, "updated_at"])
    return instance, False, bool(changed_fields)


def track(
    *,
    category: str,
    instance,
    created: bool,
    updated: bool,
    counts: dict[str, int],
    details: dict,
) -> None:
    if created:
        counts[f"{category}_created"] += 1
        details["created"][category].append(instance.public_id)
    elif updated:
        counts[f"{category}_updated"] += 1
        details["updated"][category].append(instance.public_id)


def persist_jurisdictions(
    *,
    artifact: SourceArtifact,
    records: tuple[JurisdictionRecord, ...],
    counts: dict[str, int],
    details: dict,
) -> dict[str, Jurisdiction]:
    record_by_id = {record.public_id: record for record in records}
    persisted: dict[str, Jurisdiction] = {}

    def persist(record: JurisdictionRecord) -> Jurisdiction:
        if record.public_id in persisted:
            return persisted[record.public_id]
        parent = persist(record_by_id[record.parent_public_id]) if record.parent_public_id else None
        jurisdiction, created, updated = upsert_public(
            Jurisdiction,
            record.public_id,
            {
                "name": record.name,
                "classification": record.classification,
                "state": record.state,
                "parent": parent,
                "active_start": record.active_start,
                "active_end": record.active_end,
                "record_status": record.record_status,
                "source_artifact": artifact,
                "source_key": record.source_key,
            },
        )
        persisted[record.public_id] = jurisdiction
        track(category="jurisdictions", instance=jurisdiction, created=created, updated=updated, counts=counts, details=details)
        return jurisdiction

    for jurisdiction_record in records:
        persist(jurisdiction_record)
    return persisted


def persist_offices(
    *,
    artifact: SourceArtifact,
    records: tuple[OfficeRecord, ...],
    jurisdictions: dict[str, Jurisdiction],
    counts: dict[str, int],
    details: dict,
) -> dict[str, Office]:
    offices: dict[str, Office] = {}
    for record in records:
        office, created, updated = upsert_public(
            Office,
            record.public_id,
            {
                "jurisdiction": jurisdictions[record.jurisdiction_public_id],
                "canonical_name": record.canonical_name,
                "role": record.role,
                "default_term_months": record.default_term_months,
                "positions": record.positions,
                "record_status": record.record_status,
                "source_artifact": artifact,
                "source_key": record.source_key,
            },
        )
        offices[record.public_id] = office
        track(category="offices", instance=office, created=created, updated=updated, counts=counts, details=details)
    return offices


def persist_contests(
    *,
    artifact: SourceArtifact,
    records: tuple[ContestRecord, ...],
    elections: dict[str, Election],
    offices: dict[str, Office],
    counts: dict[str, int],
    details: dict,
) -> dict[str, Contest]:
    contests: dict[str, Contest] = {}
    for record in records:
        contest, created, updated = upsert_public(
            Contest,
            record.public_id,
            {
                "election": elections[record.election_public_id],
                "office": offices[record.office_public_id],
                "party_contest": record.party_contest,
                "vote_for": record.vote_for,
                "is_partisan": record.is_partisan,
                "is_unexpired": record.is_unexpired,
                "lifecycle_status": record.lifecycle_status,
                "result_status": record.result_status,
                "source_artifact": artifact,
                "source_key": record.source_key,
            },
        )
        contests[record.public_id] = contest
        track(category="contests", instance=contest, created=created, updated=updated, counts=counts, details=details)
    return contests
```

- [ ] **Step 3: Rewire `persistence.py` to delegate**

In `backend/cm2_ingestion/persistence.py`:

1. Add the import: `from . import entities`
2. Delete the module-level `_upsert_public`, `_upsert_natural`, `_track`, `_persist_jurisdictions` function definitions entirely.
3. Replace their call sites:
   - `_upsert_public(...)` → `entities.upsert_public(...)`
   - `_upsert_natural(...)` → `entities.upsert_natural(...)`
   - `_track(...)` → `entities.track(...)`
   - `jurisdictions = _persist_jurisdictions(artifact=artifact, records=batch.jurisdictions, counts=counts, details=details)` → `jurisdictions = entities.persist_jurisdictions(artifact=artifact, records=batch.jurisdictions, counts=counts, details=details)`
4. Replace the inline office-persistence loop in `_persist_batch` (the `for record in batch.offices:` block) with:
   ```python
       offices = entities.persist_offices(
           artifact=artifact,
           records=batch.offices,
           jurisdictions=jurisdictions,
           counts=counts,
           details=details,
       )
   ```
5. Replace the inline contest-persistence loop (the `for record in batch.contests:` block) with:
   ```python
       contests = entities.persist_contests(
           artifact=artifact,
           records=batch.contests,
           elections=elections,
           offices=offices,
           counts=counts,
           details=details,
       )
   ```
   (The `elections` loop stays inline in `persistence.py` — only pre-election creates `Election`s.)

- [ ] **Step 4: Run the full pre-refactor regression suite**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_ingestion cm2_nc -v`
Expected: PASS, identical test count and outcomes to Step 1's baseline. If anything fails, the refactor changed behavior — fix `entities.py` to match the original inline code exactly, don't change the tests.

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ingestion/entities.py backend/cm2_ingestion/persistence.py
git commit -m "refactor(cm2_ingestion): extract shared entity-upsert helpers into entities.py"
```

---

## Task 3: Shared contest-key formula and optional office term

**Files:**
- Modify: `backend/cm2_nc/mapping/identity.py`
- Modify: `backend/cm2_nc/mapping/batch.py`
- Modify: `backend/cm2_nc/mapping/offices.py`
- Test: `backend/cm2_nc/tests/test_mapping.py`

**Interfaces:**
- Produces: `identity.contest_public_id(*, election_public_id: str, office_public_id: str, party_contest: str, is_unexpired: bool) -> str`; `offices.map_office(contest_name, jurisdiction, *, term_years: int | None = None, vote_for: int) -> OfficeRecord`.
- Consumes: `identity.stable_public_id`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/cm2_nc/tests/test_mapping.py`:

```python
from cm2_nc.mapping.identity import contest_public_id


def test_contest_public_id_matches_manual_construction():
    key_a = contest_public_id(
        election_public_id="nc/election/2026-03-03/primary/aaaa",
        office_public_id="nc/office/us-senator/bbbb",
        party_contest="REP",
        is_unexpired=False,
    )
    key_b = contest_public_id(
        election_public_id="nc/election/2026-03-03/primary/aaaa",
        office_public_id="nc/office/us-senator/bbbb",
        party_contest="REP",
        is_unexpired=False,
    )
    key_different_party = contest_public_id(
        election_public_id="nc/election/2026-03-03/primary/aaaa",
        office_public_id="nc/office/us-senator/bbbb",
        party_contest="DEM",
        is_unexpired=False,
    )
    assert key_a == key_b
    assert key_a != key_different_party


def test_map_office_without_term_years_leaves_default_term_null():
    jurisdiction = map_jurisdiction("US SENATE (REP)".replace(" (REP)", ""), "")[-1]
    office = map_office("US SENATE", jurisdiction, vote_for=1)
    assert office.default_term_months is None
```

(`map_jurisdiction`/`map_office` are already imported at the top of `test_mapping.py` — verify with `grep -n "^from cm2_nc.mapping" backend/cm2_nc/tests/test_mapping.py`; add the import if either name is missing.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_nc/tests/test_mapping.py -v`
Expected: FAIL — `ImportError: contest_public_id`, and `map_office() missing 1 required keyword-only argument: 'term_years'`.

- [ ] **Step 3: Implement**

In `backend/cm2_nc/mapping/identity.py`, append:

```python
def contest_public_id(
    *,
    election_public_id: str,
    office_public_id: str,
    party_contest: str,
    is_unexpired: bool,
) -> str:
    return stable_public_id(
        "contest",
        election_public_id,
        office_public_id,
        party_contest or "all-voters",
        "unexpired" if is_unexpired else "regular-term",
    )
```

In `backend/cm2_nc/mapping/batch.py`, replace the body of `_contest_key`:

```python
def _contest_key(row: NcCandidateRow, *, election: ElectionRecord, office: OfficeRecord) -> str:
    return contest_public_id(
        election_public_id=election.public_id,
        office_public_id=office.public_id,
        party_contest=row.party_contest,
        is_unexpired=row.is_unexpired,
    )
```

and update the import line to add `contest_public_id`:

```python
from .identity import contest_public_id, normalize_identity_part, stable_public_id
```

In `backend/cm2_nc/mapping/offices.py`, change the signature and body of `map_office`:

```python
def map_office(
    contest_name: str,
    jurisdiction: JurisdictionRecord,
    *,
    vote_for: int,
    term_years: int | None = None,
) -> OfficeRecord:
    del vote_for
    contest = _strip_unexpired(contest_name)
    canonical_name = _office_name(contest, jurisdiction)
    return OfficeRecord(
        public_id=stable_public_id("office", jurisdiction.public_id, canonical_name),
        jurisdiction_public_id=jurisdiction.public_id,
        canonical_name=canonical_name,
        role=_role(canonical_name),
        default_term_months=term_years * 12 if term_years is not None else None,
        positions=1,
        record_status="provisional",
        source_key=contest,
    )
```

Every existing pre-election call site passes `term_years=` as a keyword (confirmed in Step 0 research), so moving it after `vote_for` and giving it a default is backward compatible without touching `cm2_nc/mapping/batch.py`'s `map_office(..., term_years=row.term_years, vote_for=row.vote_for)` call.

- [ ] **Step 4: Run tests to verify they pass, then run the full cm2_nc suite for regressions**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_nc/tests/test_mapping.py -v`
Expected: PASS.

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_nc cm2_ingestion -v`
Expected: PASS, no regressions in pre-election batch tests (contest public IDs must be byte-identical to before, since `contest_public_id` reproduces `_contest_key`'s exact prior formula).

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_nc/mapping/identity.py backend/cm2_nc/mapping/batch.py backend/cm2_nc/mapping/offices.py backend/cm2_nc/tests/test_mapping.py
git commit -m "refactor(cm2_nc): share contest-key formula and make office term optional"
```

---

## Task 4: NC results row parsing (ZIP → normalized rows)

**Files:**
- Modify: `backend/cm2_nc/source_records.py`
- Modify: `backend/cm2_nc/constants.py`
- Create: `backend/cm2_nc/sources/results.py`
- Test: `backend/cm2_nc/tests/test_sources.py`
- Create: `backend/cm2_nc/tests/fixtures/results_pct_sanitized.txt`

**Interfaces:**
- Produces: `NcResultRow` dataclass; `parse_results_rows(zip_bytes: bytes) -> tuple[NcResultRow, ...]`; `results_zip_url(election_date: date) -> str`; `NcResultsZipSource(election_date: date, *, session=None)`.
- Consumes: `cm2_nc.sources.http.NcPublicBytesSource`.

- [ ] **Step 1: Add the sanitized fixture**

Create `backend/cm2_nc/tests/fixtures/results_pct_sanitized.txt` (tab-separated; this mirrors the real header and a small hand-picked slice of `docs/state-research/Full Core/NC/results_pct_20260303.txt` covering: a statewide partisan contest, a county contest with an `(UNEXPIRED)` + party seat, a nonpartisan municipal contest, a named write-in, both spellings of the anonymous write-in bucket, and a measure to prove exclusion still works):

```
County	Election Date	Precinct	Contest Group ID	Contest Type	Contest Name	Choice	Choice Party	Vote For	Election Day	Early Voting	Absentee by Mail	Provisional	Total Votes	Real Precinct
BUNCOMBE	03/03/2026	19.1	2137	S	US HOUSE OF REPRESENTATIVES DISTRICT 11 (REP)	Chuck Edwards	REP	1	13	17	3	0	33	Y
BUNCOMBE	03/03/2026	20.1	2135	S	US HOUSE OF REPRESENTATIVES DISTRICT 11 (DEM)	Jamie Ager	DEM	1	99	199	1	1	300	Y
BUNCOMBE	03/03/2026	20.1	2135	S	US HOUSE OF REPRESENTATIVES DISTRICT 11 (DEM)	Jamie Ager (Write-In)	DEM	1	0	0	0	0	2	Y
PERSON	03/03/2026	1.1	3001	C	PERSON COUNTY BOARD OF COMMISSIONERS (UNEXPIRED) (REP)	Sample Commissioner	REP	1	40	10	2	0	52	Y
PERSON	03/03/2026	1.1	3001	C	PERSON COUNTY BOARD OF COMMISSIONERS (UNEXPIRED) (REP)	Write-In (Miscellaneous)		1	0	0	0	0	1	Y
BUNCOMBE	03/03/2026	20.1	20	C	CITY OF ASHEVILLE CITY COUNCIL	Nina Ireland		3	19	31	0	0	50	Y
BUNCOMBE	03/03/2026	20.1	20	C	CITY OF ASHEVILLE CITY COUNCIL	Miscellaneous (Write-In)		3	0	0	0	0	3	Y
HENDERSON	03/03/2026	4.1	4001	C	CITY OF HENDERSONVILLE TRANSPORTATION BONDS REFERENDUM	FOR		1	100	20	0	0	120	Y
```

(The header's `Choice Party` column has a leading space for nonpartisan choices in the real data — that's already represented above as an empty field; keep it that way.)

- [ ] **Step 2: Write the failing tests**

Append to `backend/cm2_nc/tests/test_sources.py`:

```python
import io
import zipfile
from datetime import date
from pathlib import Path

from cm2_nc.sources.results import NcResultsZipSource, parse_results_rows, results_zip_url

FIXTURES = Path(__file__).parent / "fixtures"


def _zip_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("results_pct_20260303.txt", text)
    return buffer.getvalue()


def test_parse_results_rows_reads_tab_delimited_zip_entry():
    content = (FIXTURES / "results_pct_sanitized.txt").read_text()
    rows = parse_results_rows(_zip_bytes(content))

    assert len(rows) == 8
    first = rows[0]
    assert first.county_name == "BUNCOMBE"
    assert first.election_date == date(2026, 3, 3)
    assert first.precinct == "19.1"
    assert first.contest_type == "S"
    assert first.contest_name == "US HOUSE OF REPRESENTATIVES DISTRICT 11 (REP)"
    assert first.choice == "Chuck Edwards"
    assert first.choice_party == "REP"
    assert first.vote_for == 1
    assert first.total_votes == 33
    assert first.is_real_precinct is True


def test_parse_results_rows_handles_blank_choice_party():
    content = (FIXTURES / "results_pct_sanitized.txt").read_text()
    rows = parse_results_rows(_zip_bytes(content))
    nonpartisan = next(row for row in rows if row.choice == "Nina Ireland")
    assert nonpartisan.choice_party == ""


def test_parse_results_rows_treats_data_unavailable_placeholder_as_empty():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Readme.txt", "Data Unavailable")
    assert parse_results_rows(buffer.getvalue()) == ()


def test_results_zip_url_uses_enrs_prefix():
    assert results_zip_url(date(2026, 3, 3)) == (
        "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2026_03_03/results_pct_20260303.zip"
    )


def test_nc_results_zip_source_builds_url_from_election_date():
    source = NcResultsZipSource(election_date=date(2026, 3, 3))
    assert source.url.endswith("ENRS/2026_03_03/results_pct_20260303.zip")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_nc/tests/test_sources.py -v -k results`
Expected: FAIL — `ModuleNotFoundError: cm2_nc.sources.results`.

- [ ] **Step 4: Implement**

Add to `backend/cm2_nc/constants.py`:

```python
S3_BASE_URL = "https://s3.amazonaws.com/dl.ncsbe.gov"
RESULTS_PARSER_VERSION = "nc-results-v1"
```

Add to `backend/cm2_nc/source_records.py`:

```python
@dataclass(frozen=True, slots=True)
class NcResultRow:
    row_number: int
    county_name: str
    election_date: date
    precinct: str
    contest_type: str
    contest_name: str
    choice: str
    choice_party: str
    vote_for: int
    total_votes: int
    is_real_precinct: bool
```

Create `backend/cm2_nc/sources/results.py`:

```python
import io
import zipfile
from datetime import date, datetime

from cm2_ingestion.contracts import ContractValidationError
from cm2_nc.constants import S3_BASE_URL
from cm2_nc.source_records import NcResultRow

from .http import NcPublicBytesSource

REQUIRED_COLUMNS = (
    "County",
    "Election Date",
    "Precinct",
    "Contest Type",
    "Contest Name",
    "Choice",
    "Choice Party",
    "Vote For",
    "Total Votes",
    "Real Precinct",
)
_NO_DATA_PLACEHOLDER = "Data Unavailable"


def results_zip_url(election_date: date) -> str:
    compact = election_date.strftime("%Y%m%d")
    folder = election_date.strftime("%Y_%m_%d")
    return f"{S3_BASE_URL}/ENRS/{folder}/results_pct_{compact}.zip"


def _is_no_data_placeholder(archive: zipfile.ZipFile) -> bool:
    if archive.namelist() != ["Readme.txt"]:
        return False
    with archive.open("Readme.txt") as handle:
        return handle.read().decode("latin-1").strip() == _NO_DATA_PLACEHOLDER


def _parse_election_date(raw: str, *, row_number: int) -> date:
    try:
        return datetime.strptime(raw.strip(), "%m/%d/%Y").date()
    except ValueError as exc:
        raise ContractValidationError(f"results row {row_number} has an invalid Election Date") from exc


def _parse_int(raw: str, *, row_number: int, field: str) -> int:
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ContractValidationError(f"results row {row_number} field {field} is invalid") from exc


def parse_results_rows(zip_bytes: bytes) -> tuple[NcResultRow, ...]:
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    if _is_no_data_placeholder(archive):
        return ()

    txt_names = [name for name in archive.namelist() if name.endswith(".txt")]
    if not txt_names:
        raise ContractValidationError("results ZIP has no .txt entry")

    with archive.open(txt_names[0]) as handle:
        lines = handle.read().decode("latin-1").splitlines()
    if not lines:
        return ()

    headers = [header.strip() for header in lines[0].split("\t")]
    if any(column not in headers for column in REQUIRED_COLUMNS):
        raise ContractValidationError("results TSV is missing required columns")
    index = {column: headers.index(column) for column in headers}

    rows = []
    for row_number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < len(headers):
            parts += [""] * (len(headers) - len(parts))

        def field(name: str) -> str:
            return parts[index[name]].strip()

        contest_name = field("Contest Name")
        choice = field("Choice")
        if not contest_name or not choice:
            continue

        rows.append(
            NcResultRow(
                row_number=row_number,
                county_name=field("County"),
                election_date=_parse_election_date(field("Election Date"), row_number=row_number),
                precinct=field("Precinct"),
                contest_type=field("Contest Type"),
                contest_name=contest_name,
                choice=choice,
                choice_party=field("Choice Party"),
                vote_for=_parse_int(field("Vote For"), row_number=row_number, field="Vote For"),
                total_votes=_parse_int(field("Total Votes"), row_number=row_number, field="Total Votes"),
                is_real_precinct=field("Real Precinct").upper() == "Y",
            )
        )
    return tuple(rows)


class NcResultsZipSource(NcPublicBytesSource):
    def __init__(self, *, election_date: date, session=None):
        super().__init__(session=session)
        self.election_date = election_date
        self.url = results_zip_url(election_date)

    def parse(self, content: bytes, *, existing_elections=()):
        from cm2_nc.mapping.results import build_post_election_batch

        return build_post_election_batch(
            parse_results_rows(content),
            existing_elections=existing_elections,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_nc/tests/test_sources.py -v`
Expected: PASS for the URL/parsing tests. The `NcResultsZipSource.parse` call is exercised in Task 8, not here — Task 4's tests only cover row parsing and URL construction, not `.parse()`.

- [ ] **Step 6: Commit**

```bash
git add backend/cm2_nc/source_records.py backend/cm2_nc/constants.py backend/cm2_nc/sources/results.py backend/cm2_nc/tests/test_sources.py backend/cm2_nc/tests/fixtures/results_pct_sanitized.txt
git commit -m "feat(cm2_nc): parse NC results ZIP into normalized rows"
```

---

## Task 5: Contest-label splitting and choice classification

**Files:**
- Create: `backend/cm2_nc/mapping/results.py` (label/choice helpers only in this task; `build_post_election_batch` lands in Task 6)
- Test: `backend/cm2_nc/tests/test_mapping.py`

**Interfaces:**
- Produces: `split_contest_label(raw_label: str) -> tuple[str, str, bool]` (base name, party code, is_unexpired); `classify_choice(source_label: str) -> str` (`"candidate" | "named_write_in" | "write_in_aggregate"`); `normalized_choice_label(source_label: str, choice_type: str) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/cm2_nc/tests/test_mapping.py`:

```python
from cm2_nc.mapping.results import classify_choice, normalized_choice_label, split_contest_label


def test_split_contest_label_extracts_party_only():
    base, party, is_unexpired = split_contest_label("US HOUSE OF REPRESENTATIVES DISTRICT 11 (REP)")
    assert base == "US HOUSE OF REPRESENTATIVES DISTRICT 11"
    assert party == "REP"
    assert is_unexpired is False


def test_split_contest_label_extracts_unexpired_only():
    base, party, is_unexpired = split_contest_label("GATES COUNTY BOARD OF EDUCATION DISTRICT 02 (UNEXPIRED)")
    assert base == "GATES COUNTY BOARD OF EDUCATION DISTRICT 02"
    assert party == ""
    assert is_unexpired is True


def test_split_contest_label_extracts_unexpired_and_party_in_order():
    base, party, is_unexpired = split_contest_label(
        "PERSON COUNTY BOARD OF COMMISSIONERS (UNEXPIRED) (REP)"
    )
    assert base == "PERSON COUNTY BOARD OF COMMISSIONERS"
    assert party == "REP"
    assert is_unexpired is True


def test_split_contest_label_with_no_suffix():
    base, party, is_unexpired = split_contest_label("CITY OF ASHEVILLE CITY COUNCIL")
    assert base == "CITY OF ASHEVILLE CITY COUNCIL"
    assert party == ""
    assert is_unexpired is False


def test_classify_choice_ordinary_candidate():
    assert classify_choice("Chuck Edwards") == "candidate"


def test_classify_choice_named_write_in():
    assert classify_choice("Jamie Ager (Write-In)") == "named_write_in"


def test_classify_choice_anonymous_write_in_both_spellings():
    assert classify_choice("Write-In (Miscellaneous)") == "write_in_aggregate"
    assert classify_choice("Miscellaneous (Write-In)") == "write_in_aggregate"
    assert classify_choice("MIscellaneous (Write-In)") == "write_in_aggregate"


def test_normalized_choice_label_strips_write_in_marker():
    assert normalized_choice_label("Jamie Ager (Write-In)", "named_write_in") == "jamie ager"
    assert normalized_choice_label("Chuck Edwards", "candidate") == "chuck edwards"
    assert normalized_choice_label("Write-In (Miscellaneous)", "write_in_aggregate") == "write-in"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_nc/tests/test_mapping.py -v -k "split_contest_label or classify_choice or normalized_choice_label"`
Expected: FAIL — `ModuleNotFoundError: cm2_nc.mapping.results`.

- [ ] **Step 3: Implement**

Create `backend/cm2_nc/mapping/results.py`:

```python
import re

from .identity import normalize_identity_part

_PARTY_SUFFIX_RE = re.compile(r"\s*\(([A-Z]{2,5})\)$")
_UNEXPIRED_SUFFIX_RE = re.compile(r"\s*\(UNEXPIRED\)$")
_WRITE_IN_MARKER_RE = re.compile(r"\(\s*WRITE-IN\s*\)", re.IGNORECASE)


def split_contest_label(raw_label: str) -> tuple[str, str, bool]:
    label = " ".join((raw_label or "").strip().upper().split())

    party = ""
    party_match = _PARTY_SUFFIX_RE.search(label)
    if party_match:
        party = party_match.group(1)
        label = label[: party_match.start()].strip()

    is_unexpired = False
    if _UNEXPIRED_SUFFIX_RE.search(label):
        is_unexpired = True
        label = _UNEXPIRED_SUFFIX_RE.sub("", label).strip()

    return label, party, is_unexpired


def classify_choice(source_label: str) -> str:
    if not _WRITE_IN_MARKER_RE.search(source_label or ""):
        return "candidate"
    remainder = _WRITE_IN_MARKER_RE.sub("", source_label).strip()
    if normalize_identity_part(remainder) in {"", "miscellaneous"}:
        return "write_in_aggregate"
    return "named_write_in"


def normalized_choice_label(source_label: str, choice_type: str) -> str:
    if choice_type == "write_in_aggregate":
        return "write-in"
    remainder = _WRITE_IN_MARKER_RE.sub("", source_label or "").strip()
    return normalize_identity_part(remainder)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_nc/tests/test_mapping.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_nc/mapping/results.py backend/cm2_nc/tests/test_mapping.py
git commit -m "feat(cm2_nc): split result contest labels and classify write-in choices"
```

---

## Task 6: Build the post-election batch and register the results capability

**Files:**
- Modify: `backend/cm2_nc/mapping/results.py`
- Modify: `backend/cm2_ingestion/capabilities.py`
- Test: `backend/cm2_nc/tests/test_mapping.py`

**Interfaces:**
- Consumes: `cm2_nc.mapping.measures.is_measure_contest`, `cm2_nc.mapping.jurisdictions.map_jurisdiction`, `cm2_nc.mapping.offices.map_office`, `cm2_nc.mapping.identity.{normalize_identity_part, stable_public_id, contest_public_id}`, `cm2_ingestion.contracts.{PostElectionBatch, PrecinctResultObservation, ElectionRecord, IngestionNotice, ContractValidationError, validate_post_election_batch}`.
- Produces: `build_post_election_batch(rows: tuple[NcResultRow, ...], *, existing_elections: tuple[ElectionRecord, ...]) -> PostElectionBatch`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/cm2_nc/tests/test_mapping.py`:

```python
from datetime import date

from cm2_ingestion.contracts import ContractValidationError, ElectionRecord
from cm2_nc.mapping.results import build_post_election_batch
from cm2_nc.source_records import NcResultRow


def _result_row(**overrides) -> NcResultRow:
    values = {
        "row_number": 2,
        "county_name": "BUNCOMBE",
        "election_date": date(2026, 3, 3),
        "precinct": "19.1",
        "contest_type": "S",
        "contest_name": "US HOUSE OF REPRESENTATIVES DISTRICT 11 (REP)",
        "choice": "Chuck Edwards",
        "choice_party": "REP",
        "vote_for": 1,
        "total_votes": 33,
        "is_real_precinct": True,
    }
    values.update(overrides)
    return NcResultRow(**values)


def _primary_election() -> ElectionRecord:
    return ElectionRecord(
        public_id="nc/election/2026-03-03/primary",
        name="2026 North Carolina Primary",
        election_date=date(2026, 3, 3),
        election_type="primary",
        lifecycle_status="active",
        source_key="2026-03-03-primary",
    )


def test_build_post_election_batch_matches_existing_election_and_produces_observation():
    batch = build_post_election_batch((_result_row(),), existing_elections=(_primary_election(),))
    assert batch.state == "NC"
    assert len(batch.observations) == 1
    observation = batch.observations[0]
    assert observation.choice_type == "candidate"
    assert observation.choice_party == "REP"
    assert observation.vote_total == 33
    contest = batch.new_contests[0]
    assert contest.election_public_id == "nc/election/2026-03-03/primary"
    assert contest.party_contest == "REP"
    assert contest.is_partisan is True


def test_build_post_election_batch_reuses_contest_public_id_formula_across_precincts():
    row_a = _result_row(precinct="19.1", total_votes=33)
    row_b = _result_row(precinct="20.1", total_votes=20)
    batch = build_post_election_batch((row_a, row_b), existing_elections=(_primary_election(),))
    contest_ids = {contest.public_id for contest in batch.new_contests}
    assert len(contest_ids) == 1
    assert len({observation.contest_public_id for observation in batch.observations}) == 1


def test_build_post_election_batch_excludes_measures_with_notice():
    row = _result_row(
        contest_name="CITY OF HENDERSONVILLE TRANSPORTATION BONDS REFERENDUM",
        contest_type="C",
        choice="FOR",
        choice_party="",
        vote_for=1,
    )
    batch = build_post_election_batch((row,), existing_elections=(_primary_election(),))
    assert batch.observations == ()
    assert batch.notices[0].code == "measure_excluded"


def test_build_post_election_batch_classifies_write_ins():
    named = _result_row(
        row_number=3,
        choice="Jamie Ager (Write-In)",
        choice_party="DEM",
        total_votes=2,
    )
    aggregate = _result_row(
        row_number=4,
        precinct="1.1",
        contest_name="PERSON COUNTY BOARD OF COMMISSIONERS (UNEXPIRED) (REP)",
        contest_type="C",
        choice="Write-In (Miscellaneous)",
        choice_party="",
        county_name="PERSON",
        total_votes=1,
    )
    batch = build_post_election_batch((named, aggregate), existing_elections=(_primary_election(),))
    by_type = {observation.choice_type for observation in batch.observations}
    assert by_type == {"named_write_in", "write_in_aggregate"}


def test_build_post_election_batch_raises_when_no_election_matches_date():
    with pytest.raises(ContractValidationError):
        build_post_election_batch((_result_row(),), existing_elections=())


def test_build_post_election_batch_disambiguates_by_party_presence():
    general = ElectionRecord(
        public_id="nc/election/2026-03-03/general",
        name="General",
        election_date=date(2026, 3, 3),
        election_type="general",
        lifecycle_status="active",
        source_key="2026-03-03-general",
    )
    batch = build_post_election_batch(
        (_result_row(),),
        existing_elections=(general, _primary_election()),
    )
    assert batch.new_contests[0].election_public_id == "nc/election/2026-03-03/primary"
```

(`pytest` is already imported at the top of `test_mapping.py`; verify with `grep -n "^import pytest" backend/cm2_nc/tests/test_mapping.py` and add it if missing.)

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_nc/tests/test_mapping.py -v -k build_post_election_batch`
Expected: FAIL — `ImportError: build_post_election_batch`.

- [ ] **Step 3: Implement `build_post_election_batch`**

Append to `backend/cm2_nc/mapping/results.py` (add the new imports at the top of the file):

```python
from collections import defaultdict
from datetime import date

from cm2_ingestion.contracts import (
    ContestRecord,
    ContractValidationError,
    ElectionRecord,
    IngestionNotice,
    JurisdictionRecord,
    OfficeRecord,
    PostElectionBatch,
    PrecinctResultObservation,
    validate_post_election_batch,
)
from cm2_nc.source_records import NcResultRow

from .identity import contest_public_id, stable_public_id
from .jurisdictions import map_jurisdiction
from .measures import is_measure_contest
from .offices import map_office
```

```python
def _put_unique(records: dict[str, object], record, *, label: str) -> None:
    existing = records.get(record.public_id)
    if existing is not None and existing != record:
        raise ContractValidationError(f"conflicting normalized {label} mapping")
    records[record.public_id] = record


def _select_election(
    *,
    election_date: date,
    has_party_signal: bool,
    existing_elections: tuple[ElectionRecord, ...],
) -> ElectionRecord:
    candidates = [record for record in existing_elections if record.election_date == election_date]
    if not candidates:
        raise ContractValidationError("results file references an unknown election date")
    if len(candidates) == 1:
        return candidates[0]

    preferred_type = "primary" if has_party_signal else "general"
    preferred = [record for record in candidates if record.election_type == preferred_type]
    if len(preferred) == 1:
        return preferred[0]
    raise ContractValidationError("results file date matches multiple elections ambiguously")


def _measure_notice(row: NcResultRow, base_name: str, party: str) -> IngestionNotice:
    identity = "\x1f".join((row.election_date.isoformat(), normalize_identity_part(base_name), party))
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return IngestionNotice(
        code="measure_excluded",
        subject_type="source_contest",
        subject_public_id=f"nc/source-contest/{digest}",
    )


def build_post_election_batch(
    rows: tuple[NcResultRow, ...],
    *,
    existing_elections: tuple[ElectionRecord, ...] = (),
) -> PostElectionBatch:
    split_by_row: dict[int, tuple[str, str, bool]] = {
        row.row_number: split_contest_label(row.contest_name) for row in rows
    }

    eligible_rows: list[NcResultRow] = []
    notices: list[IngestionNotice] = []
    seen_measures: set[tuple[date, str, str]] = set()
    for row in rows:
        base_name, party, _ = split_by_row[row.row_number]
        if is_measure_contest(base_name):
            measure_key = (row.election_date, normalize_identity_part(base_name), party)
            if measure_key not in seen_measures:
                seen_measures.add(measure_key)
                notices.append(_measure_notice(row, base_name, party))
            continue
        eligible_rows.append(row)

    party_signal_by_date: dict[date, bool] = defaultdict(bool)
    for row in eligible_rows:
        _, party, _ = split_by_row[row.row_number]
        if party:
            party_signal_by_date[row.election_date] = True

    election_by_date: dict[date, ElectionRecord] = {}
    for row in eligible_rows:
        if row.election_date not in election_by_date:
            election_by_date[row.election_date] = _select_election(
                election_date=row.election_date,
                has_party_signal=party_signal_by_date[row.election_date],
                existing_elections=existing_elections,
            )

    jurisdictions: dict[str, JurisdictionRecord] = {}
    offices: dict[str, OfficeRecord] = {}
    contests: dict[str, ContestRecord] = {}
    row_contest_id: dict[int, str] = {}

    for row in eligible_rows:
        base_name, party, is_unexpired = split_by_row[row.row_number]
        mapped_jurisdictions = map_jurisdiction(base_name, row.county_name)
        for jurisdiction in mapped_jurisdictions:
            _put_unique(jurisdictions, jurisdiction, label="jurisdiction")
        jurisdiction = mapped_jurisdictions[-1]
        office = map_office(base_name, jurisdiction, vote_for=row.vote_for)
        _put_unique(offices, office, label="office")

        election = election_by_date[row.election_date]
        contest_id = contest_public_id(
            election_public_id=election.public_id,
            office_public_id=office.public_id,
            party_contest=party,
            is_unexpired=is_unexpired,
        )
        if contest_id not in contests:
            contests[contest_id] = ContestRecord(
                public_id=contest_id,
                election_public_id=election.public_id,
                office_public_id=office.public_id,
                party_contest=party,
                vote_for=row.vote_for,
                is_partisan=bool(party),
                is_unexpired=is_unexpired,
                lifecycle_status="active",
                result_status="unofficial",
                source_key=f"{row.election_date.isoformat()}|{base_name}|{party or 'ALL'}|unexpired={str(is_unexpired).lower()}",
            )
        row_contest_id[row.row_number] = contest_id

    observations = []
    for row in eligible_rows:
        contest_id = row_contest_id[row.row_number]
        choice_type = classify_choice(row.choice)
        normalized_label = normalized_choice_label(row.choice, choice_type)
        source_choice_key = stable_public_id("result-choice", contest_id, normalized_label)
        observation_key = stable_public_id(
            "result-observation",
            contest_id,
            row.county_name,
            row.precinct,
            normalized_label,
        )
        observations.append(
            PrecinctResultObservation(
                source_observation_key=observation_key,
                contest_public_id=contest_id,
                source_choice_key=source_choice_key,
                source_label=row.choice,
                normalized_label=normalized_label,
                choice_type=choice_type,
                choice_party=row.choice_party,
                vote_total=row.total_votes,
                precinct=row.precinct,
            )
        )

    batch = PostElectionBatch(
        state="NC",
        new_jurisdictions=tuple(sorted(jurisdictions.values(), key=lambda record: record.public_id)),
        new_offices=tuple(sorted(offices.values(), key=lambda record: record.public_id)),
        new_contests=tuple(sorted(contests.values(), key=lambda record: record.public_id)),
        observations=tuple(observations),
        notices=tuple(sorted(notices, key=lambda notice: notice.subject_public_id)),
    )
    validate_post_election_batch(batch)
    return batch
```

Add `import hashlib` and `from .identity import normalize_identity_part` at the top of `results.py` alongside the existing `from .identity import normalize_identity_part` (already present from Task 5 — merge into one import line: `from .identity import contest_public_id, normalize_identity_part, stable_public_id`).

Note on `source_observation_key`: it deliberately omits `row.is_real_precinct` and the per-method vote columns — `Total Votes` is already the per-precinct total across all voting methods, matching the legacy adapter's aggregation approach and the spec's "sums Total Votes once" instruction. Two rows for the same `(contest, county, precinct, choice)` would collide, which is correct: the source data itself should never repeat that combination (verified against the full 103k-row sample during design — zero duplicates on that key).

Now update `backend/cm2_ingestion/capabilities.py`'s `ResultsSource` Protocol:

```python
class ResultsSource(Protocol):
    source_system: str

    def acquire(self) -> bytes: ...

    def parse(
        self,
        content: bytes,
        *,
        existing_elections: tuple[ElectionRecord, ...] = (),
    ) -> PostElectionBatch: ...
```

and update the top-of-file import to add `PostElectionBatch` and drop the now-unused `PrecinctResultObservation`:

```python
from .contracts import (
    CertificationEvidence,
    ElectionRecord,
    PostElectionBatch,
    PreElectionBatch,
)
```

- [ ] **Step 4: Run tests to verify they pass, and run the full cm2_nc + cm2_ingestion suites for regressions**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_nc/tests/test_mapping.py -v`
Expected: PASS.

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_nc cm2_ingestion -v`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_nc/mapping/results.py backend/cm2_ingestion/capabilities.py backend/cm2_nc/tests/test_mapping.py
git commit -m "feat(cm2_nc): build post-election batches matching existing NC contests"
```

---

## Task 7: Results persistence — contest resolution, aggregation, and choice-to-candidacy matching

**Files:**
- Create: `backend/cm2_ingestion/results_persistence.py`
- Test: `backend/cm2_ingestion/tests/test_results_persistence.py`

**Interfaces:**
- Consumes: `cm2_ingestion.entities.{persist_jurisdictions, persist_offices, persist_contests}`, `cm2_ingestion.aggregation.aggregate_precinct_observations`, `cm2_ingestion.contracts.{PostElectionBatch, ContractValidationError, validate_post_election_batch}`, `cm2_ingestion.models.{SyncLog, ReconciliationReport}`, `cm2_elections.models.{Contest, Person, Candidacy}`, `cm2_results.models.{ContestResult, ResultChoice}`, `cm2_review.workflow.create_review_case`, `cm2_review.models.IdentityReviewCase`, `cm2_review.matching.{find_person_match_candidates, generate_suggestions_for_case, normalize_name_for_matching}`.
- Produces: `apply_post_election_batch(*, artifact: SourceArtifact, batch: PostElectionBatch) -> ReconciliationReport`.

- [ ] **Step 1: Write the failing tests**

Create `backend/cm2_ingestion/tests/test_results_persistence.py`:

```python
from datetime import date

import pytest
from django.utils import timezone

from cm2_core.models import SourceArtifact
from cm2_elections.models import Candidacy, Contest, Election, Jurisdiction, Office, Person
from cm2_ingestion.contracts import (
    ContestRecord,
    ElectionRecord,
    JurisdictionRecord,
    OfficeRecord,
    PostElectionBatch,
    PrecinctResultObservation,
)
from cm2_ingestion.entities import persist_contests, persist_jurisdictions, persist_offices
from cm2_ingestion.models import ReconciliationReport, SyncLog
from cm2_ingestion.results_persistence import apply_post_election_batch
from cm2_review.models import IdentityReviewCase
from cm2_results.models import ContestResult, ResultChoice


@pytest.fixture
def artifact(db):
    return SourceArtifact.objects.create(
        source_system="nc_sbe",
        source_type=SourceArtifact.SourceType.RESULTS,
        url="https://example.test/nc/results.zip",
        retrieved_at=timezone.now(),
        content_sha256="e" * 64,
        parser_version="nc-results-v1",
        election_date=date(2026, 3, 3),
    )


@pytest.fixture
def existing_contest(db):
    jurisdiction = Jurisdiction.objects.create(
        public_id="nc/jurisdiction/state",
        name="North Carolina",
        classification="state",
        state="NC",
        record_status="verified",
    )
    office = Office.objects.create(
        public_id="nc/office/us-senator",
        jurisdiction=jurisdiction,
        canonical_name="U.S. Senator",
        role="senator",
    )
    election = Election.objects.create(
        public_id="nc/election/2026-03-03/primary",
        name="2026 Primary",
        election_date=date(2026, 3, 3),
        election_type="primary",
        lifecycle_status="active",
    )
    contest = Contest.objects.create(
        public_id="nc/contest/us-senator-rep",
        election=election,
        office=office,
        party_contest="REP",
        vote_for=1,
        is_partisan=True,
    )
    return contest


@pytest.fixture
def existing_candidacy(existing_contest):
    person = Person.objects.create(canonical_name="Elizabeth A. Temple", family_name="Temple")
    return Candidacy.objects.create(
        person=person,
        contest=existing_contest,
        ballot_name="Elizabeth A. Temple",
        party_candidate="REP",
    )


def _batch(contest: Contest, *observations: PrecinctResultObservation) -> PostElectionBatch:
    contest_record = ContestRecord(
        public_id=contest.public_id,
        election_public_id=contest.election.public_id,
        office_public_id=contest.office.public_id,
        party_contest=contest.party_contest,
        vote_for=contest.vote_for,
        is_partisan=contest.is_partisan,
    )
    return PostElectionBatch(state="NC", new_contests=(contest_record,), observations=observations)


@pytest.mark.django_db
def test_exact_name_match_links_result_choice_to_existing_candidacy(artifact, existing_contest, existing_candidacy):
    batch = _batch(
        existing_contest,
        PrecinctResultObservation(
            source_observation_key="obs-1",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-temple",
            source_label="Elizabeth A. Temple",
            normalized_label="elizabeth a. temple",
            choice_type="candidate",
            choice_party="REP",
            vote_total=33,
        ),
    )
    apply_post_election_batch(artifact=artifact, batch=batch)

    result = ContestResult.objects.get(contest=existing_contest)
    assert result.status == ContestResult.Status.UNOFFICIAL
    assert result.total_votes == 33
    choice = result.choices.get()
    assert choice.resolution_status == ResultChoice.ResolutionStatus.MATCHED
    assert choice.candidacy_id == existing_candidacy.id
    assert choice.is_winner is None


@pytest.mark.django_db
def test_unmatched_candidate_creates_provisional_person_candidacy_and_review_case(artifact, existing_contest):
    batch = _batch(
        existing_contest,
        PrecinctResultObservation(
            source_observation_key="obs-2",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-newcomer",
            source_label="Pat Newcomer",
            normalized_label="pat newcomer",
            choice_type="candidate",
            choice_party="REP",
            vote_total=10,
        ),
    )
    apply_post_election_batch(artifact=artifact, batch=batch)

    choice = ResultChoice.objects.get()
    assert choice.resolution_status == ResultChoice.ResolutionStatus.PROVISIONAL
    assert choice.candidacy is not None
    assert choice.candidacy.person.canonical_name == "Pat Newcomer"
    assert choice.candidacy.status == Candidacy.Status.PROVISIONAL
    assert IdentityReviewCase.objects.filter(provisional_person=choice.candidacy.person).exists()


@pytest.mark.django_db
def test_named_write_in_creates_unresolved_choice_and_review_case_without_candidacy(artifact, existing_contest):
    batch = _batch(
        existing_contest,
        PrecinctResultObservation(
            source_observation_key="obs-3",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-writein",
            source_label="Jamie Ager (Write-In)",
            normalized_label="jamie ager",
            choice_type="named_write_in",
            vote_total=2,
        ),
    )
    apply_post_election_batch(artifact=artifact, batch=batch)

    choice = ResultChoice.objects.get()
    assert choice.choice_type == ResultChoice.ChoiceType.NAMED_WRITE_IN
    assert choice.resolution_status == ResultChoice.ResolutionStatus.UNRESOLVED
    assert choice.candidacy is None
    assert Candidacy.objects.count() == 0
    assert IdentityReviewCase.objects.filter(
        case_type=IdentityReviewCase.CaseType.UNRESOLVED_RESULT_CHOICE,
        result_choice=choice,
    ).exists()


@pytest.mark.django_db
def test_anonymous_write_in_bucket_is_not_applicable_and_counts_toward_total(artifact, existing_contest, existing_candidacy):
    batch = _batch(
        existing_contest,
        PrecinctResultObservation(
            source_observation_key="obs-4",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-temple",
            source_label="Elizabeth A. Temple",
            normalized_label="elizabeth a. temple",
            choice_type="candidate",
            choice_party="REP",
            vote_total=33,
        ),
        PrecinctResultObservation(
            source_observation_key="obs-5",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-misc",
            source_label="Write-In (Miscellaneous)",
            normalized_label="write-in",
            choice_type="write_in_aggregate",
            vote_total=1,
        ),
    )
    apply_post_election_batch(artifact=artifact, batch=batch)

    result = ContestResult.objects.get(contest=existing_contest)
    assert result.total_votes == 34
    misc = ResultChoice.objects.get(source_label="Write-In (Miscellaneous)")
    assert misc.choice_type == ResultChoice.ChoiceType.WRITE_IN_AGGREGATE
    assert misc.resolution_status == ResultChoice.ResolutionStatus.NOT_APPLICABLE
    assert misc.candidacy is None


@pytest.mark.django_db
def test_replaying_the_same_artifact_returns_the_existing_report(artifact, existing_contest, existing_candidacy):
    batch = _batch(
        existing_contest,
        PrecinctResultObservation(
            source_observation_key="obs-1",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-temple",
            source_label="Elizabeth A. Temple",
            normalized_label="elizabeth a. temple",
            choice_type="candidate",
            choice_party="REP",
            vote_total=33,
        ),
    )
    first = apply_post_election_batch(artifact=artifact, batch=batch)
    second = apply_post_election_batch(artifact=artifact, batch=batch)
    assert first.pk == second.pk
    assert ResultChoice.objects.count() == 1


@pytest.mark.django_db
def test_correction_updates_vote_totals_without_deleting_choices(artifact, existing_contest, existing_candidacy):
    first_batch = _batch(
        existing_contest,
        PrecinctResultObservation(
            source_observation_key="obs-1",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-temple",
            source_label="Elizabeth A. Temple",
            normalized_label="elizabeth a. temple",
            choice_type="candidate",
            choice_party="REP",
            vote_total=33,
        ),
    )
    apply_post_election_batch(artifact=artifact, batch=first_batch)

    corrected_artifact = SourceArtifact.objects.create(
        source_system="nc_sbe",
        source_type=SourceArtifact.SourceType.RESULTS,
        url=artifact.url,
        retrieved_at=timezone.now(),
        content_sha256="f" * 64,
        parser_version="nc-results-v1",
        election_date=date(2026, 3, 3),
        supersedes=artifact,
    )
    second_batch = _batch(
        existing_contest,
        PrecinctResultObservation(
            source_observation_key="obs-1-corrected",
            contest_public_id=existing_contest.public_id,
            source_choice_key="choice-temple",
            source_label="Elizabeth A. Temple",
            normalized_label="elizabeth a. temple",
            choice_type="candidate",
            choice_party="REP",
            vote_total=40,
        ),
    )
    apply_post_election_batch(artifact=corrected_artifact, batch=second_batch)

    assert ResultChoice.objects.count() == 1
    choice = ResultChoice.objects.get()
    assert choice.vote_total == 40
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_ingestion/tests/test_results_persistence.py -v`
Expected: FAIL — `ModuleNotFoundError: cm2_ingestion.results_persistence`.

- [ ] **Step 3: Implement `results_persistence.py`**

```python
from difflib import SequenceMatcher

from django.db import transaction
from django.utils import timezone

from cm2_core.models import SourceArtifact
from cm2_elections.models import Candidacy, Contest, Person
from cm2_results.models import ContestResult, ResultChoice
from cm2_review.matching import find_person_match_candidates, generate_suggestions_for_case, normalize_name_for_matching
from cm2_review.models import IdentityReviewCase
from cm2_review.workflow import create_review_case

from . import entities
from .aggregation import aggregate_precinct_observations
from .contracts import AggregatedResultChoice, ContractValidationError, PostElectionBatch, validate_post_election_batch
from .models import ReconciliationReport, SyncLog

_COUNT_KEYS = (
    "jurisdictions_created",
    "jurisdictions_updated",
    "offices_created",
    "offices_updated",
    "contests_created",
    "contests_updated",
    "contest_results_created",
    "contest_results_updated",
    "result_choices_created",
    "result_choices_updated",
    "people_created",
    "candidacies_created",
    "review_cases_created",
)

_MATCH_SCORE_FLOOR = 0.72


def _new_counts() -> dict[str, int]:
    return {key: 0 for key in _COUNT_KEYS}


def _empty_details() -> dict:
    categories = ("jurisdictions", "offices", "contests")
    return {
        "created": {category: [] for category in categories},
        "updated": {category: [] for category in categories},
        "result_only_contests": [],
        "unmatched_choices": [],
        "review_cases": [],
        "notices": [],
    }


def _safe_error_summary(exc: Exception) -> str:
    if isinstance(exc, ContractValidationError):
        return "ContractValidationError: batch validation failed"
    return f"{type(exc).__name__}: persistence failed"


def _resolve_candidacy(*, contest: Contest, normalized_label: str) -> tuple[Candidacy | None, str, list[dict]]:
    candidacies = list(Candidacy.objects.filter(contest=contest).select_related("person"))
    exact = [
        candidacy for candidacy in candidacies
        if normalize_name_for_matching(candidacy.ballot_name) == normalized_label
    ]
    if len(exact) == 1:
        return exact[0], ResultChoice.ResolutionStatus.MATCHED, []
    if len(exact) > 1:
        return None, ResultChoice.ResolutionStatus.AMBIGUOUS, [
            {"candidacy_public_id": candidacy.public_id, "ballot_name": candidacy.ballot_name} for candidacy in exact
        ]

    matcher = SequenceMatcher(a=normalized_label)
    fuzzy = []
    for candidacy in candidacies:
        matcher.set_seq2(normalize_name_for_matching(candidacy.ballot_name))
        score = matcher.ratio()
        if score >= _MATCH_SCORE_FLOOR:
            fuzzy.append({"candidacy_public_id": candidacy.public_id, "ballot_name": candidacy.ballot_name, "score": round(score, 4)})
    if fuzzy:
        return None, ResultChoice.ResolutionStatus.UNRESOLVED, fuzzy
    return None, "", []


def _create_provisional_candidacy(
    *,
    artifact: SourceArtifact,
    contest: Contest,
    choice: AggregatedResultChoice,
) -> tuple[Candidacy, IdentityReviewCase | None]:
    person = Person.objects.create(
        canonical_name=choice.source_label,
        identity_state=Person.IdentityState.PROVISIONAL,
        source_artifact=artifact,
        source_key=choice.source_choice_key,
    )
    candidacy = Candidacy.objects.create(
        person=person,
        contest=contest,
        ballot_name=choice.source_label,
        party_candidate=choice.choice_party,
        status=Candidacy.Status.PROVISIONAL,
        source_artifact=artifact,
        source_key=choice.source_choice_key,
    )
    match_candidates = find_person_match_candidates(
        canonical_name=person.canonical_name,
        family_name="",
        exclude_person_id=person.id,
    )
    case_type = (
        IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH if match_candidates else IdentityReviewCase.CaseType.PERSON_IDENTITY
    )
    review_case, created = create_review_case(
        deduplication_key=f"new-result-person:{artifact.public_id}:{choice.source_choice_key}",
        defaults={
            "case_type": case_type,
            "provisional_person": person,
            "supporting_evidence": {"source_system": artifact.source_system, "source_choice_key": choice.source_choice_key},
        },
    )
    if created and match_candidates:
        generate_suggestions_for_case(review_case, match_candidates)
    return candidacy, review_case if created else None


def _persist_contest_result(
    *,
    artifact: SourceArtifact,
    contest: Contest,
    choices: tuple[AggregatedResultChoice, ...],
    counts: dict[str, int],
    details: dict,
) -> None:
    total_votes = sum(choice.vote_total for choice in choices)
    result, created = ContestResult.objects.get_or_create(
        contest=contest,
        defaults={
            "status": ContestResult.Status.UNOFFICIAL,
            "source_artifact": artifact,
            "total_votes": total_votes,
            "reported_at": timezone.now(),
        },
    )
    if created:
        counts["contest_results_created"] += 1
    else:
        update_fields = ["total_votes", "source_artifact", "reported_at", "updated_at"]
        result.total_votes = total_votes
        result.source_artifact = artifact
        result.reported_at = timezone.now()
        if result.status == ContestResult.Status.PENDING:
            result.status = ContestResult.Status.UNOFFICIAL
            update_fields.append("status")
        result.save(update_fields=update_fields)
        counts["contest_results_updated"] += 1

    for choice in choices:
        candidacy = None
        review_supporting_evidence: list[dict] = []
        if choice.choice_type == "write_in_aggregate":
            resolution_status = ResultChoice.ResolutionStatus.NOT_APPLICABLE
        elif choice.choice_type == "named_write_in":
            resolution_status = ResultChoice.ResolutionStatus.UNRESOLVED
        else:
            candidacy, resolution_status, review_supporting_evidence = _resolve_candidacy(
                contest=contest,
                normalized_label=choice.normalized_label,
            )
            if not resolution_status:
                candidacy, _ = _create_provisional_candidacy(artifact=artifact, contest=contest, choice=choice)
                resolution_status = ResultChoice.ResolutionStatus.PROVISIONAL
                counts["people_created"] += 1
                counts["candidacies_created"] += 1
                counts["review_cases_created"] += 1

        values = {
            "source_label": choice.source_label,
            "normalized_label": choice.normalized_label,
            "choice_type": choice.choice_type,
            "resolution_status": resolution_status,
            "candidacy": candidacy,
            "vote_total": choice.vote_total,
            "percentage": choice.percentage,
            "source_artifact": artifact,
            "observation_lineage": list(choice.observation_keys),
        }
        result_choice, choice_created = ResultChoice.objects.get_or_create(
            contest_result=result,
            source_choice_key=choice.source_choice_key,
            defaults=values,
        )
        if choice_created:
            counts["result_choices_created"] += 1
        else:
            for field_name, value in values.items():
                setattr(result_choice, field_name, value)
            result_choice.save(update_fields=[*values.keys(), "updated_at"])
            counts["result_choices_updated"] += 1

        if resolution_status == ResultChoice.ResolutionStatus.UNRESOLVED and choice.choice_type != "candidate":
            review_case, created = create_review_case(
                deduplication_key=f"unresolved-choice:{result_choice.public_id}",
                defaults={
                    "case_type": IdentityReviewCase.CaseType.UNRESOLVED_RESULT_CHOICE,
                    "result_choice": result_choice,
                    "supporting_evidence": {"source_label": choice.source_label},
                },
            )
            if created:
                counts["review_cases_created"] += 1
            details["review_cases"].append(review_case.public_id)
        elif resolution_status in (ResultChoice.ResolutionStatus.UNRESOLVED, ResultChoice.ResolutionStatus.AMBIGUOUS):
            review_case, created = create_review_case(
                deduplication_key=f"unresolved-choice:{result_choice.public_id}",
                defaults={
                    "case_type": IdentityReviewCase.CaseType.UNRESOLVED_RESULT_CHOICE,
                    "result_choice": result_choice,
                    "supporting_evidence": {"source_label": choice.source_label, "candidates": review_supporting_evidence},
                },
            )
            if created:
                counts["review_cases_created"] += 1
            details["review_cases"].append(review_case.public_id)
            details["unmatched_choices"].append(result_choice.public_id)


def _persist_results_batch(
    *,
    artifact: SourceArtifact,
    batch: PostElectionBatch,
    sync_log: SyncLog,
) -> ReconciliationReport:
    counts = _new_counts()
    details = _empty_details()
    for notice in batch.notices:
        count_key = f"notices_{notice.code}"
        counts[count_key] = counts.get(count_key, 0) + 1
        details["notices"].append(
            {"code": notice.code, "subject_type": notice.subject_type, "subject_public_id": notice.subject_public_id}
        )

    jurisdictions = entities.persist_jurisdictions(
        artifact=artifact, records=batch.new_jurisdictions, counts=counts, details=details
    )
    offices = entities.persist_offices(
        artifact=artifact, records=batch.new_offices, jurisdictions=jurisdictions, counts=counts, details=details
    )
    existing_election_ids = {contest.election_public_id for contest in batch.new_contests}
    from cm2_elections.models import Election

    elections = {
        election.public_id: election
        for election in Election.objects.filter(public_id__in=existing_election_ids)
    }
    if len(elections) != len(existing_election_ids):
        raise ContractValidationError("post-election batch references an election that does not exist")
    contests = entities.persist_contests(
        artifact=artifact, records=batch.new_contests, elections=elections, offices=offices, counts=counts, details=details
    )

    observations_by_contest: dict[str, list] = {}
    for observation in batch.observations:
        observations_by_contest.setdefault(observation.contest_public_id, []).append(observation)

    for contest_public_id, observations in observations_by_contest.items():
        contest = contests.get(contest_public_id) or Contest.objects.filter(public_id=contest_public_id).first()
        if contest is None:
            raise ContractValidationError("result observation references an unknown contest")
        aggregated = aggregate_precinct_observations(observations)
        _persist_contest_result(artifact=artifact, contest=contest, choices=aggregated, counts=counts, details=details)

    completed_at = timezone.now()
    sync_log.status = SyncLog.Status.SUCCESS
    sync_log.completed_at = completed_at
    sync_log.aggregate_counts = counts
    sync_log.error_summary = ""
    sync_log.save(update_fields=["status", "completed_at", "aggregate_counts", "error_summary", "updated_at"])
    return ReconciliationReport.objects.create(sync_log=sync_log, source_artifact=artifact, details=details)


def apply_post_election_batch(*, artifact: SourceArtifact, batch: PostElectionBatch) -> ReconciliationReport:
    run_key = f"results:{artifact.public_id}"
    sync_log, _ = SyncLog.objects.get_or_create(
        run_key=run_key,
        defaults={
            "state": batch.state,
            "source_system": artifact.source_system,
            "capability": SyncLog.Capability.RESULTS,
            "source_artifact": artifact,
            "started_at": timezone.now(),
        },
    )
    if sync_log.status == SyncLog.Status.SUCCESS:
        try:
            return sync_log.report
        except ReconciliationReport.DoesNotExist:
            pass

    SyncLog.objects.filter(pk=sync_log.pk).update(
        state=batch.state,
        source_system=artifact.source_system,
        capability=SyncLog.Capability.RESULTS,
        status=SyncLog.Status.STARTED,
        source_artifact=artifact,
        started_at=timezone.now(),
        completed_at=None,
        aggregate_counts={},
        error_summary="",
    )
    sync_log.refresh_from_db()

    try:
        validate_post_election_batch(batch)
        with transaction.atomic():
            return _persist_results_batch(artifact=artifact, batch=batch, sync_log=sync_log)
    except Exception as exc:
        SyncLog.objects.filter(pk=sync_log.pk).update(
            status=SyncLog.Status.FAILED,
            completed_at=timezone.now(),
            aggregate_counts={},
            error_summary=_safe_error_summary(exc),
        )
        raise
```

Note the two review-case branches in `_persist_contest_result` share the same `deduplication_key` shape (`unresolved-choice:{public_id}`) but are kept as separate `if`/`elif` arms because their `supporting_evidence` payloads differ (named write-ins carry no candidate list; unresolved/ambiguous candidate choices do) — don't collapse them into one branch, a reviewer needs that distinction in the case detail.

- [ ] **Step 4: Run tests to verify they pass, then run the full cm2_ingestion + cm2_review suites for regressions**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_ingestion/tests/test_results_persistence.py -v`
Expected: PASS.

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_ingestion cm2_review cm2_results -v`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ingestion/results_persistence.py backend/cm2_ingestion/tests/test_results_persistence.py
git commit -m "feat(cm2_ingestion): persist NC post-election results with review-case fallback"
```

---

## Task 8: Wire the NC results entrypoint end-to-end

**Files:**
- Modify: `backend/cm2_nc/ingest.py`
- Modify: `backend/cm2_nc/capabilities.py`
- Test: `backend/cm2_nc/tests/test_ingest.py`

**Interfaces:**
- Produces: `ingest_nc_post_election_contents(*, results_content: bytes, election_date: date, retrieved_at: datetime, results_url: str | None = None) -> ReconciliationReport`.
- Consumes: `cm2_ingestion.artifacts.register_source_artifact`, `cm2_ingestion.results_persistence.apply_post_election_batch`, `cm2_nc.sources.results.{NcResultsZipSource, results_zip_url}`, `cm2_elections.models.Election`.

- [ ] **Step 1: Write the failing wiring test**

Append to `backend/cm2_nc/tests/test_ingest.py`:

```python
import io
import zipfile
from datetime import date

from cm2_core.models import SourceArtifact
from cm2_elections.models import Election
from cm2_nc.ingest import ingest_nc_post_election_contents
from cm2_results.models import ContestResult, ResultChoice


def _results_zip_bytes() -> bytes:
    text = (FIXTURES / "results_pct_sanitized.txt").read_text()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("results_pct_20260303.txt", text)
    return buffer.getvalue()


@pytest.mark.django_db
def test_nc_post_election_ingestion_persists_results_for_existing_election():
    report = ingest_nc_pre_election_contents(**fixture_content(), retrieved_at=timezone.now())
    election = Election.objects.filter(election_date=date(2026, 3, 3)).first()
    if election is None:
        election = Election.objects.create(
            public_id="nc/election/2026-03-03/primary",
            name="2026 North Carolina Primary",
            election_date=date(2026, 3, 3),
            election_type="primary",
            lifecycle_status="active",
        )

    results_report = ingest_nc_post_election_contents(
        results_content=_results_zip_bytes(),
        election_date=date(2026, 3, 3),
        retrieved_at=timezone.now(),
    )

    assert isinstance(results_report, ReconciliationReport)
    assert SourceArtifact.objects.filter(source_type=SourceArtifact.SourceType.RESULTS).exists()
    assert ContestResult.objects.exists()
    assert ResultChoice.objects.exists()

    replay = ingest_nc_post_election_contents(
        results_content=_results_zip_bytes(),
        election_date=date(2026, 3, 3),
        retrieved_at=timezone.now(),
    )
    assert replay.pk == results_report.pk
```

Add the needed imports at the top of `test_ingest.py`: `import pytest` (verify it's not already imported), and `from cm2_ingestion.models import ReconciliationReport` (verify it's not already imported — both are likely already present since the file tests pre-election ingestion; only add what's missing).

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_nc/tests/test_ingest.py -v -k post_election`
Expected: FAIL — `ImportError: ingest_nc_post_election_contents`.

- [ ] **Step 3: Implement**

In `backend/cm2_nc/ingest.py`, add imports and the new function:

```python
from cm2_elections.models import Election
from cm2_ingestion.contracts import ElectionRecord
from cm2_ingestion.results_persistence import apply_post_election_batch
from cm2_nc.constants import RESULTS_PARSER_VERSION
from cm2_nc.sources.results import NcResultsZipSource, results_zip_url
```

(add these alongside the existing imports at the top of the file)

```python
def _existing_successful_results_report(results_artifact: SourceArtifact) -> ReconciliationReport | None:
    sync_log = SyncLog.objects.filter(
        run_key=f"results:{results_artifact.public_id}",
        status=SyncLog.Status.SUCCESS,
    ).first()
    if sync_log is None:
        return None
    try:
        return sync_log.report
    except ReconciliationReport.DoesNotExist:
        return None


def _elections_for_date(election_date) -> tuple[ElectionRecord, ...]:
    return tuple(
        ElectionRecord(
            public_id=election.public_id,
            name=election.name,
            election_date=election.election_date,
            election_type=election.election_type,
            lifecycle_status=election.lifecycle_status,
        )
        for election in Election.objects.filter(election_date=election_date)
    )


def ingest_nc_post_election_contents(
    *,
    results_content: bytes,
    election_date,
    retrieved_at: datetime,
    results_url: str | None = None,
) -> ReconciliationReport:
    url = results_url or results_zip_url(election_date)
    results_artifact, _ = register_source_artifact(
        source_system=SOURCE_SYSTEM,
        source_type=SourceArtifact.SourceType.RESULTS,
        url=url,
        content=results_content,
        retrieved_at=retrieved_at,
        parser_version=RESULTS_PARSER_VERSION,
        election_date=election_date,
    )

    existing_report = _existing_successful_results_report(results_artifact)
    if existing_report is not None:
        return existing_report

    try:
        source = NcResultsZipSource(election_date=election_date)
        batch = source.parse(results_content, existing_elections=_elections_for_date(election_date))
    except Exception as exc:
        _set_artifact_status(
            results_artifact,
            SourceArtifact.ProcessingStatus.FAILED,
            error=_sanitized_artifact_error(exc),
        )
        raise

    _set_artifact_status(results_artifact, SourceArtifact.ProcessingStatus.VALIDATED)
    try:
        report = apply_post_election_batch(artifact=results_artifact, batch=batch)
    except Exception as exc:
        _set_artifact_status(
            results_artifact,
            SourceArtifact.ProcessingStatus.FAILED,
            error=f"{type(exc).__name__}: batch application failed",
        )
        raise

    _set_artifact_status(results_artifact, SourceArtifact.ProcessingStatus.APPLIED)
    return report
```

Update `backend/cm2_nc/capabilities.py` to register a factory instead of a fixed instance, since `NcResultsZipSource` needs an `election_date` at construction time (unlike the other two sources, which have a fixed URL):

```python
from datetime import date

from cm2_ingestion.capabilities import StateCapabilities

from .sources.candidate_filings import NcCandidateFilingsSource
from .sources.results import NcResultsZipSource
from .sources.upcoming_elections import NcUpcomingElectionsSource


def build_nc_capabilities(*, results_election_date: date | None = None) -> StateCapabilities:
    return StateCapabilities(
        election_discovery=NcUpcomingElectionsSource(),
        candidates=NcCandidateFilingsSource(),
        results=NcResultsZipSource(election_date=results_election_date) if results_election_date else None,
    )
```

Check `backend/cm2_nc/tests/test_ingest.py` (or wherever `build_nc_capabilities` is currently tested) for any existing call sites of `build_nc_capabilities()` with no arguments — they continue to work since `results_election_date` defaults to `None`, and `results=None` is the documented "state doesn't support this capability yet" signal in `CapabilityRegistry.supported_capabilities`. Run `grep -rn "build_nc_capabilities" backend/cm2_nc` to confirm no other call site needs updating.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec civicmirror-2-0-api-1 python -m pytest cm2_nc/tests/test_ingest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_nc/ingest.py backend/cm2_nc/capabilities.py backend/cm2_nc/tests/test_ingest.py
git commit -m "feat(cm2_nc): wire NC post-election results ingestion entrypoint"
```

---

## Task 9: Full-suite verification and migration check

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend verification suite**

Run: `make verify-v2`
Expected: `System check identified no issues`, `No changes detected` (no missing migrations — this feature added no new models/fields to any Django model, only dataclasses and plain functions), and all tests passing (baseline 177 from before this plan, plus every test added in Tasks 1–8).

- [ ] **Step 2: Confirm no stray missing-migration state**

Run: `docker exec civicmirror-2-0-api-1 python manage.py makemigrations --check --dry-run --settings=config.settings.v2`
Expected: exits 0, no output.

- [ ] **Step 3: Commit (only if Steps 1–2 required any fixes)**

If everything already passed, there is nothing to commit for this task — it's a checkpoint, not a code change. If a fix was needed, commit it with a message describing what regressed and why.

---

## Self-Review Notes (for the plan author, not a task to execute)

- **Spec coverage:** #192 step 1 (source artifact/versioning) → `register_source_artifact` reused as-is in Task 8. Steps 2–3 (measure exclusion, contest/office/jurisdiction mapping reuse) → Task 6. Step 4 (match to existing Contests) → deterministic `contest_public_id` reuse, Task 3 + Task 6. Step 5 (provisional contest + review case for result-only contests) → upsert-always-emits pattern, Task 6/7 (no separate "is_new" plumbing needed — see Task 6's rationale note). Step 6 (deterministic/fuzzy candidacy matching) → `_resolve_candidacy` in Task 7. Step 7 (provisional Person+Candidacy) → `_create_provisional_candidacy`, Task 7. Step 8 (named write-ins unresolved, no Person/Candidacy) → Task 7. Step 9 (aggregate write-in bucket, `not_applicable`, stays in totals) → Task 7 (`aggregate_precinct_observations` already includes it in the denominator, per its existing test). Step 10 (vote totals/percentages/status, no winners) → Task 7 constraints. Step 11 (reconciliation report contents) → `_empty_details`/`ReconciliationReport.details` in Task 7 (result-only contests are visible via `details["created"]["contests"]`; unmatched/ambiguous choices via `details["unmatched_choices"]`).
- **Placeholder scan:** no TBD/TODO, every step has runnable code, no "similar to Task N" hand-waving — Task 5/6/7/8 each restate the full function bodies they build on.
- **Type consistency check:** `PostElectionBatch` fields (`new_jurisdictions`, `new_offices`, `new_contests`, `observations`, `notices`) are named identically everywhere they're consumed (Task 1 definition, Task 6 construction, Task 7 consumption). `contest_public_id(...)` keyword names (`election_public_id`, `office_public_id`, `party_contest`, `is_unexpired`) match between Task 3's definition and Task 6's call site. `NcResultRow` field names match between Task 4's dataclass and Task 6's `build_post_election_batch` usage.
