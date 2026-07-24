# New York Stage 1 + Flateau Results Repair Implementation Plan

**Revised:** 2026-07-23 (codebase-validation update)  
**Issues:** #40 (NY results lookup/ingestion), #87 (Near Core → Full Core)  
**Primary research:** `docs/state-research/NY/NY-Election_Research.md`  
**Prototype artifacts:** `ny_cert_parser.py`, `ny_cert_2026.json`

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. Implement task-by-task and keep the checkboxes current.

## Goal

Deliver two related but independently verifiable outcomes:

1. **Close #40:** make the production New York Flateau adapter resolve and ingest all applicable per-county-board result feeds for one CivicMirror `Election`, without race collisions, silent county omissions, or repeated missing-metadata warnings.
2. **Complete #87 for New York:** add a native NYSBOE Stage 1 pipeline that discovers supported certification documents and creates elections, races, and candidates before results arrive.

Do not treat “the adapter returned rows” as sufficient. Stage 1 and Stage 2 must share a tested contest-identity contract so every Flateau row attaches to the correct NYSBOE-created race.

## Why this work is required

Issue #40 originally reported:

```text
ny_sos.adapter.no_election_name election=None pk=1907
```

Live investigation found two underlying conditions:

1. The June 23, 2026 primary is not represented by one Flateau `electionName`. It is split across approximately 15 county-board election records. Backfilling one name would silently omit the others.
2. Election pk=1907 had no native Stage 1 races. The current generic results pipeline can bootstrap races after result rows arrive, but that fallback groups/matches primarily by office title unless a source identity is supplied. That is unsafe for New York, where many party and district contests share the same office title.

The production NY adapter currently reads a single `source_metadata["election_name"]`, makes one `/api/downloads` request, hashes one payload, and emits no `contest_code`/`party_code` identity for the generic result matcher. This plan repairs that behavior and adds native Stage 1.

## Delivery strategy

The implementation is divided into three phases:

- **Phase A — Close #40:** establish the identity contract, automatically resolve multiple Flateau names, batch-fetch them, merge safely, and verify pk=1907 end-to-end.
- **Phase B — Native Stage 1:** productionize the NYSBOE certification parser and create elections/races/candidates through `aggregation.ingest`.
- **Phase C — Promotion and documentation:** verify production behavior, close #40, and promote NY under #87 only after the repository’s Full Core gates are met.

The Phase A work may ship before the complete Phase B work. Do not hold the visible #40 production fix behind unrelated future enhancements.

## Scope

### Included

- Multiple Flateau `electionName` resolution and fetching.
- One Playwright/Cloudflare session per host and fetch batch.
- Deterministic combined source hashing.
- Explicit partial-fetch behavior.
- A shared Stage 1 ↔ Stage 2 NY contest identity.
- Native NYSBOE certification discovery and parsing.
- Race/candidate reconciliation when an amended certification removes or changes entries.
- Task triggers, locks, scheduler documentation, tests, and production verification.

### Explicitly out of scope

- “Who Filed” and county candidate-filing early-signal ingestion.
- ENR near-election-day structural cross-checking.
- OpenElections historical backfill.
- Candidate biography/platform enrichment.
- Ballot-order amendment UI beyond retaining source metadata.
- Parsing “Offices to be Filled” as though it were a candidate certification. It is a different document type and needs its own mapper/parser if later added.

These omissions mean the first native pipeline is authoritative certification-stage coverage, not the earliest possible local filing signal. Document that limitation when updating coverage claims.

---

# Global constraints and data contracts

## 1. Source boundaries

- New Stage 1 code lives in `backend/integrations/ny_boe/`.
- Existing Stage 2 code remains in `backend/results/adapters/ny.py`.
- Add `Race.Source.NY_BOE = "ny_boe", "New York BOE"`.
- Keep any surviving Civic-created NY records attributed to `CIVIC_API`.
- Use `aggregation.ingest.ingest_election`, `ingest_race`, and `ingest_candidate`; do not bypass aggregation with direct bulk creation.

## 1A. NY source-precedence contract

Adding the `Race.Source` enum is not sufficient. `aggregation.precedence.resolve_rank()` treats an unranked source as `+inf`, so an unseeded `ny_boe` source may only fill empty fields and may fail to take ownership from an existing Civic-backed row. `ingest_race()` also chooses the representative `Race.source` from identity-group precedence.

Add a `SourcePrecedence` data migration for New York, following the existing NC/VT state-source seed pattern. The required policy is:

- `ny_boe` outranks `civic_api` for authoritative election/race identity, date, status, party, district/geography, and results-structure fields such as `max_selections`;
- `civic_api` remains preferred for candidate/contact enrichment fields that NYSBOE does not supply;
- every field group used by the NY mapper must have an explicit NY rank rather than relying on the wildcard default or an `+inf` tie.

Recommended seed shape, adjusted only if an existing repository convention requires a narrower equivalent:

```python
_NY_ROWS = [
    ("NY", "identity", "ny_boe",    0),
    ("NY", "identity", "civic_api", 1),
    ("NY", "date",     "ny_boe",    0),
    ("NY", "date",     "civic_api", 1),
    ("NY", "status",   "ny_boe",    0),
    ("NY", "status",   "civic_api", 1),
    ("NY", "party",    "ny_boe",    0),
    ("NY", "party",    "civic_api", 1),
    ("NY", "district", "ny_boe",    0),
    ("NY", "district", "civic_api", 1),
    ("NY", "results",  "ny_boe",    0),
    ("NY", "results",  "civic_api", 1),
    ("NY", "contacts", "civic_api", 0),
    ("NY", "contacts", "ny_boe",    1),
]
```

Add tests proving that NYSBOE can update/own authoritative fields across merged records: election date/status, race identity/district/max selections, and candidate identity/party/status, while higher-precedence Civic candidate contact fields remain intact.

## 1B. Source metadata merge contract

`aggregation.ingest._apply_fields()` writes field values with plain `setattr()` and does not deep-merge JSON. Any NY task or mapper that passes `source_metadata` through `ingest_election`, `ingest_race`, or `ingest_candidate` must first merge with the existing model metadata or intentionally force-write a preserved merged dictionary afterward.

This is required for:

- `Election.source_metadata`: keep certification landing/PDF/version metadata, `flateau_election_names`, legacy `election_name`, and any curated/admin keys together.
- `Race.source_metadata`: keep `contest_code`, `party_code`, NY identity fields, source document fields, ballot/order metadata, and any existing curated keys together.
- `Candidate.source_metadata`: keep ballot order, litigation/running-mate/source-row metadata, and any Civic/contact/enrichment metadata together.

Add tests that prove re-running Stage 1 after Flateau metadata is present does not remove `flateau_election_names`, and that updating NY identity metadata on a race/candidate does not erase unrelated existing `source_metadata` keys.

## 2. Shared Cloudflare fetch helper

Extract the production Playwright-stealth pattern into a reusable helper only after checking whether an equivalent helper already exists.

Required capabilities:

```python
fetch_bytes(url: str, *, landing_url: str) -> bytes
fetch_json(url: str, *, landing_url: str) -> Any
fetch_json_many(urls: list[str], *, landing_url: str) -> list[FetchOutcome]
```

`fetch_json_many` must:

- launch Chromium once;
- create one browser context/page;
- navigate to the same-origin landing page once;
- issue every API fetch inside that cleared page context;
- return success/failure per requested URL without aborting the whole batch;
- close browser resources in `finally` blocks.

Do not assume one clearance context works across `flateau.elections.ny.gov` and `elections.ny.gov`; use a separate batch/context per host unless a live test proves otherwise.

## 3. NY race identity contract

The certification prototype’s authoritative Stage 1 identity remains:

```text
office | district | district2 | party
```

Production code must store structured matching metadata as well as the canonical key. Recommended shape:

```json
{
  "ny_identity_version": 1,
  "contest_code": "<normalized office>|<normalized district>|<normalized district2>",
  "party_code": "<normalized primary party>",
  "ny_office": "<normalized office>",
  "ny_district": "<normalized district>",
  "ny_district2": "<normalized district2>",
  "ny_party": "<normalized party>"
}
```

This deliberately uses the generic result pipeline’s existing `contest_code` and `party_code` identity keys. Both the Stage 1 mapper and NY result adapter must produce the same values.

Before finalizing normalization rules, inspect real Flateau rows for:

- the same office across multiple districts;
- separate party primaries for the same office/district;
- a district spanning several reporting county boards;
- statewide offices;
- judicial delegate and state committee contests;
- any local same-name contests present in the 15 county feeds.

Do not infer a party solely from candidate name. Prefer an explicit contest/party field when Flateau supplies one. If only `candidateParty` is available, prove with captured fixtures that it reliably identifies the primary contest; otherwise derive a safer rule or mark the row unresolved.

`source_authority`/Flateau `electionName` belongs in `ResultRow.raw` and the `jurisdiction_fragment`, but normally must **not** become part of the state/federal race identity because one district race can be reported by several counties.

## 4. Parser output contract

The production parser output must match the actual prototype JSON shape, not the inaccurate shape previously written in this plan:

```python
{
    "contests": [
        {
            "office": str,
            "district": str,
            "district2": str,
            "counties": str,
            "party": str,
            "vote_for": str,
            "candidates": [
                {
                    "ballot_order": str,
                    "name": str,
                    "running_mate": str,  # optional, only when present
                }
            ],
            "key": str,
        }
    ],
    "version_history": [
        {"date": str, "changes": list[str]}
    ],
}
```

`ballot_order` is candidate-level, not contest-level. Version-history entries use `changes`, not `description`.

The prototype code supports `running_mate`, but the supplied JSON contains no `running_mate` entries for the gubernatorial records. Treat joint-ticket extraction as **unverified**, not solved. Test against the real PDF and either correctly populate it or document that the source document does not expose the paired value in the expected table.

## 5. Wrapped-field correctness

The supplied JSON contains at least one truncated wrapped `Counties:` value ending in `"Part of"`. The production parser must append wrapped label continuations rather than taking only the first visual row.

Add validation that rejects or flags suspicious values such as:

- fields ending in `Part of`, `&`, or a comma;
- unexpected empty office/district/party values;
- empty candidate lists;
- duplicated ballot-order tokens within a contest where not valid.

Do not use `counties` as the primary Stage 1 ↔ Stage 2 join key.

## 6. Amendment reconciliation

A successful re-ingest cannot be upsert-only. When the certification version changes:

- upsert all current source races/candidates;
- identify existing `NY_BOE` races/candidates for that election absent from the new complete snapshot;
- deactivate/archive/withdraw them according to existing model conventions;
- never delete or deactivate records from other sources;
- perform reconciliation only after a complete parse passes validation;
- store counts of created, updated, unchanged, and retired records in the sync log.

## 7. Result fetch completeness and cache semantics

For multiple Flateau names:

- Sort names before fetching/hashing.
- Enrich every raw row with `_flateau_election_name` and normalized `_flateau_authority`.
- Hash a deterministic structure containing both the exact election name and its data.
- If all configured names succeed, return `mapping_confidence="full"`.
- If some succeed, return successful rows with `mapping_confidence="partial"`, detailed notes, and **do not advance the version cache**.
- If all fail, return no rows and `mapping_confidence="none"`.
- A temporary partial fetch must never become the cached authoritative version.

The production task currently caches any non-empty `result.source_version` after races are processed, without checking `mapping_confidence`. Therefore this plan requires both layers of protection:

1. **Task-level invariant:** change `backend/results/tasks.py::ingest_official_results` so the version cache is written only when `result.mapping_confidence == "full"`, in addition to the existing `races`, `source_version`, and `version_cache_key` checks.
2. **NY adapter defense in depth:** a partial or failed NY fetch must return the current adapter-contract empty string, `source_version=""`, and `unchanged=False`, even if the adapter calculated an internal diagnostic hash. Do not use `None` unless `AdapterResult.source_version` is intentionally changed to `str | None` everywhere.

Add shared task regression tests proving:

- a full result with a source version advances the cache;
- a partial result with rows and a source version does **not** advance the cache;
- a `none` result does not advance the cache;
- unchanged handling is reachable only from a previously complete cached snapshot.

The NY adapter defines `version_cache_key()` and returns a source version, so it must also define `VERSION_CACHE_TIMEOUT` before the first successful cache write. Use the repository’s standard adapter convention (30 days unless a documented Flateau-specific reason supports another value) and add a successful-ingest regression test that reaches the cache write without `AttributeError`.

## 8. Missing-name behavior

The original issue requested validation or repair before polling. The NY adapter must not emit the same warning indefinitely for every pre-results election.

Preferred behavior:

1. If metadata has `flateau_election_names`, use it.
2. Else if legacy `election_name` exists, treat it as a one-element list.
3. Else call the Flateau metadata resolver using election date/type.
4. If matching names are found, persist them and continue.
5. If no names are published yet, return an expected “not published/configured yet” result and log at `INFO`, not a recurring warning/error.
6. Reserve warnings for ambiguous matches or malformed metadata.

Manual metadata remains an explicit override, but automatic discovery is the normal future-election path.

## 9. Tests and fixtures

- Unit tests perform no live network calls.
- Use captured real Flateau JSON rows and a trimmed real PDF/page fixture where practical.
- Do not synthesize away the difficult layouts: include wrapped names, wrapped counties, contested ballot order, joint-ticket layout, and multi-seat contests.
- Full-document parser verification may be an opt-in integration/golden test if the 215-page source is too large for normal CI.
- Tests run with `pytest --no-migrations`.

---

# File structure

## Shared/Stage 2

- `backend/results/adapters/ny.py` — multi-name resolution/fetch/parse.
- `backend/results/adapters/playwright_stealth_utils.py` or an existing equivalent — shared batch fetch helper.
- `backend/results/tests/test_ny_adapter.py` — resolver, batch, identity, hashing, partial failures, cache-timeout contract.
- `backend/results/tests/fixtures/ny/` — captured Flateau metadata and result rows from multiple county boards.
- `backend/results/tasks.py` — require `mapping_confidence == "full"` before writing the version cache.
- `backend/results/tests/test_tasks.py` — regression tests for full/partial/none cache behavior and successful NY cache writes.

## Stage 1

- `backend/elections/models.py` — `Race.Source.NY_BOE`.
- `backend/aggregation/migrations/00xx_seed_ny_boe_precedence.py` — explicit NY source-precedence rows.
- `backend/aggregation/tests/` or the existing precedence test module — migration/rank and merged-row ownership tests.
- `backend/integrations/ny_boe/__init__.py`, `apps.py`.
- `backend/integrations/ny_boe/client.py`.
- `backend/integrations/ny_boe/parsers.py`.
- `backend/integrations/ny_boe/mappers.py`.
- `backend/integrations/ny_boe/tasks.py`.
- `backend/integrations/ny_boe/tests/fixtures/`.
- `backend/integrations/ny_boe/tests/test_client.py`.
- `backend/integrations/ny_boe/tests/test_parsers.py`.
- `backend/integrations/ny_boe/tests/test_mappers.py`.
- `backend/integrations/ny_boe/tests/test_tasks.py`.

## Operations/documentation

- `backend/internal/views.py`.
- `backend/internal/urls.py`.
- `backend/internal/task_locks.py`.
- `backend/ops/views.py`.
- `backend/ops/tests/test_views.py`.
- `backend/requirements/base.txt` — verify the existing `pdfplumber` dependency; no dependency addition is expected.
- `docs/state-research/NY/NY-Election_Research.md`.
- `docs/superpowers/plans/2026-07-23-ny-boe-stage1-certification.md`.

---

# Phase A — Close issue #40

## Task 0: Capture the real Stage 2 identity contract

**Files:** NY result fixtures and a short fixture README.

- [ ] Capture `/api/elections-metadata` entries for the June 23, 2026 county-board elections named in #40.
- [ ] Capture representative `/api/downloads?...category=results&format=json` rows from at least three county boards.
- [ ] Include fixtures for two same-titled offices in different districts, two party primaries for one office/district, and one district reported by multiple counties.
- [ ] Document which Flateau fields reliably represent office, district, party, contest jurisdiction, reporting authority, candidate, and ballot position.
- [ ] Decide and document the exact normalization rules used by `contest_code` and `party_code`.
- [ ] Prove with a fixture test that distinct NY races cannot collapse to the same identity.

**Gate:** Do not implement the final mapper identity from assumptions alone.

## Task 1: Extract shared Playwright-stealth batch fetching

**Files:** shared helper, existing NY adapter, helper tests.

- [ ] Write failing tests for one JSON fetch, several JSON fetches in one context, one failed URL among successful URLs, and guaranteed browser cleanup.
- [ ] Extract the existing home-page-first Cloudflare flow without changing its externally visible behavior.
- [ ] Add `fetch_json_many` with per-URL outcomes.
- [ ] Retain one-browser/one-context behavior for the full Flateau batch.
- [ ] Verify the existing single-name adapter test still passes through the helper.

## Task 2: Add automatic Flateau election-name resolution

**Files:** `backend/results/adapters/ny.py`, adapter tests/fixtures.

**Interface:**

```python
resolve_flateau_election_names(election) -> list[str]
```

- [ ] Query `/api/elections-metadata` through the shared stealth helper.
- [ ] Match on exact election date and normalized election type.
- [ ] Return every applicable county-board `electionName`, sorted and deduplicated.
- [ ] Reject ambiguous metadata records rather than guessing.
- [ ] Preserve manually configured `flateau_election_names` as an override.
- [ ] Accept legacy `election_name` as a one-element compatibility fallback.
- [ ] Persist automatically resolved names in `Election.source_metadata` by merging with existing metadata, without overwriting unrelated Stage 1, legacy, curated, or admin-managed keys.
- [ ] When no matching Flateau records exist yet, log informationally and return a non-error “not published yet” result.
- [ ] Add tests for exact match, no match, duplicate metadata, ambiguous date/type, manual override, and legacy fallback.

## Task 3: Implement multi-name fetch, enrichment, merge, hashing, and cache safety

**Files:** `backend/results/adapters/ny.py`, `backend/results/tests/test_ny_adapter.py`, `backend/results/tasks.py`, `backend/results/tests/test_tasks.py`.

- [ ] Add `NewYorkAdapter.VERSION_CACHE_TIMEOUT`, following the standard 30-day adapter convention unless a documented Flateau-specific TTL is chosen.
- [ ] Add a regression test that a successful NY ingest reaches the task cache write without `AttributeError`.
- [ ] Change `ingest_official_results` so it writes an adapter version only when `mapping_confidence == "full"`.
- [ ] Add task-level tests showing full results cache and partial/none results do not cache.
- [ ] Batch-fetch all resolved download URLs in one Flateau browser context.
- [ ] Enrich each raw row with `_flateau_election_name` and `_flateau_authority` before parsing.
- [ ] Generate `contest_code` and `party_code` according to Task 0’s proven contract.
- [ ] Include the reporting authority in `jurisdiction_fragment` so separate county totals cannot overwrite each other.
- [ ] Do not include reporting authority in the state/federal race identity when several counties report the same race.
- [ ] Combine and parse successful payloads.
- [ ] Produce a deterministic hash over sorted `{election_name, data}` entries.
- [ ] Return `full`, `partial`, or `none` confidence according to the completeness rules above.
- [ ] Never return `unchanged=True` from a partial fetch.
- [ ] Return `source_version=""` for partial/none NY results as defense in depth, preserving the current `AdapterResult.source_version: str` contract.
- [ ] Ensure the generic result task independently refuses to cache non-full results.
- [ ] Set a stable Flateau results page as `source_url`; retain exact per-feed URLs/names in notes/raw payload.

**Required tests:**

- [ ] Single legacy name.
- [ ] Multiple successful names.
- [ ] Input name ordering does not change the hash.
- [ ] One failed name returns partial rows, `source_version=""`, and no unchanged/cache advance.
- [ ] Generic task regression: partial rows cannot advance cache even if a future adapter accidentally supplies a source version.
- [ ] Successful NY result ingestion writes the cache using `VERSION_CACHE_TIMEOUT` without error.
- [ ] All names fail.
- [ ] Duplicate rows from repeated metadata do not double-count.
- [ ] Same office/different district remain separate identities.
- [ ] Same office/district/different party remain separate identities.
- [ ] Same race reported by multiple counties remains one race with separate jurisdiction fragments.

## Task 4: Backfill and verify pk=1907

- [ ] Run the resolver against the live June 23, 2026 election.
- [ ] Compare the resolved list against the approximately 15 county-board names documented in #40.
- [ ] Store the exact verified list on pk=1907 (or its production successor).
- [ ] Run `ingest_official_results` in staging/production-safe mode.
- [ ] Confirm the nightly warning `ny_sos.adapter.no_election_name` no longer occurs for this election.
- [ ] Confirm `OfficialResult` rows are written for more than one county authority.
- [ ] Confirm same-title district/party races are not cross-populated.
- [ ] Re-run unchanged data and confirm `unchanged=True` only after a complete successful ingest.
- [ ] Confirm the successful run writes the version cache without a `VERSION_CACHE_TIMEOUT` `AttributeError`.
- [ ] Force one county fetch to fail and confirm the prior complete cache value is unchanged.
- [ ] Record row, race, candidate, authority, and failure counts in the #40 verification comment.

**#40 closure gate:** Complete the checklist in “Issue #40 acceptance criteria” below before closing the issue.

---

# Phase B — Native NYSBOE Stage 1 (#87)

## Task 5: Add `Race.Source.NY_BOE`, seed precedence, and verify dependency

**Files:** `backend/elections/models.py`, model tests, `backend/aggregation/migrations/00xx_seed_ny_boe_precedence.py`, precedence/ingest tests, `backend/requirements/base.txt`.

- [ ] Write a failing test asserting `Race.Source.NY_BOE == "ny_boe"`.
- [ ] Add the TextChoices value.
- [ ] Follow repository migration precedent; run `makemigrations --check` and create a migration if Django detects a choices-field alteration.
- [ ] Add the NY `SourcePrecedence` data migration described in Global Constraint 1A, following the existing NC/VT seed-and-reverse pattern.
- [ ] Test the exact NY rank rows after migration.
- [ ] Test that `ingest_election(source="ny_boe")` updates/owns authoritative NY date and status fields over an existing Civic contribution.
- [ ] Test that `ingest_race(source="ny_boe")` becomes the representative race source and updates/owns identity, district/geography, and results-structure fields such as `max_selections`.
- [ ] Test that `ingest_candidate(source="ny_boe")` updates/owns authoritative candidate identity/party/status fields while Civic remains preferred for candidate contact fields.
- [ ] Verify `pdfplumber` remains present in `backend/requirements/base.txt` and that `import pdfplumber` works in the test container; do not add a duplicate dependency.

## Task 6: Port and harden the certification parser

**Files:** `parsers.py`, parser tests, real fixtures.

**Interfaces:**

```python
parse_certification_pdf(pdf_bytes: bytes) -> dict
parse_version_history_text(text: str) -> list[dict]
validate_certification_snapshot(doc: dict) -> list[str]
```

- [ ] Port the validated word-position clustering and `ORDER_TOKENS`-anchored footer fix.
- [ ] Preserve `ROW_TOL=3.0` and `BAND=13.0` unless a real fixture demonstrates a necessary change.
- [ ] Correctly append wrapped `Counties:` and other label-value continuation rows.
- [ ] Match the actual JSON contract: candidate-level `ballot_order`; version entries `{date, changes}`.
- [ ] Verify joint-ticket behavior against the real PDF; do not assume the existing golden JSON proves running-mate extraction.
- [ ] Test a normal contest, contested ballot order, litigation-pending status, wrapped candidate name, wrapped counties, joint-ticket layout, and multi-seat contest.
- [ ] Add validation for truncated/suspicious fields and empty candidate lists.
- [ ] Golden-check 433 contests and 1,285 candidates against the supplied JSON.
- [ ] Correct the research document’s stale supporting-files count of 1,239 candidates to 1,285.
- [ ] If the full PDF cannot be committed, keep a documented opt-in full-document verification command and committed expected JSON hash/counts.

## Task 7: Implement NYSBOE discovery and PDF retrieval

**Files:** `client.py`, client tests.

**Interfaces:**

```python
get_current_certification_documents() -> list[CertificationDocument]
fetch_certification_pdf(url: str) -> bytes
```

`CertificationDocument` must carry at least document type, title, election date, election type, landing URL, and PDF URL.

- [ ] Discover actual links from the NYSBOE page; do not construct current dates from a URL pattern alone.
- [ ] Distinguish primary candidate certifications from “Offices to be Filled” and unsupported document types.
- [ ] Fetch through the shared same-origin stealth helper.
- [ ] Validate content type/magic bytes before parsing.
- [ ] Add mocked tests for discovery, amended-link replacement, unsupported documents, missing PDF link, and Cloudflare fetch failure.

## Task 8: Implement mappers and the shared identity

**Files:** `mappers.py`, mapper tests.

**Interfaces:**

```python
normalize_ny_office(value: str) -> str
normalize_ny_district(value: str) -> str
normalize_ny_party(value: str) -> str
build_ny_source_identity(contest: dict) -> dict[str, str]
build_canonical_key(contest: dict) -> str
map_contest_to_race(contest, election) -> dict
map_candidate(candidate_row) -> dict
```

- [ ] Use the exact same normalization contract established in Phase A.
- [ ] Store `contest_code` and `party_code` in `Race.source_metadata` so the existing generic result matcher uses source identity rather than office title.
- [ ] Merge `Race.source_metadata` and `Candidate.source_metadata` with any existing keys before passing mapper fields through `aggregation.ingest`; do not replace unrelated metadata dictionaries wholesale.
- [ ] Build canonical keys with election context plus `office|district|district2|party`.
- [ ] Set `max_selections` from `Vote For`.
- [ ] Normalize “Governor and Lt. Governor” consistently with the Flateau office title without losing the source title.
- [ ] Map paired candidates only after Task 6 proves what the source exposes.
- [ ] Preserve ballot order and litigation status in candidate/source metadata.
- [ ] Add cross-pipeline tests: the Stage 1 contest fixture and corresponding Flateau row fixture must produce identical `contest_code`/`party_code`.
- [ ] Add metadata-preservation tests proving NY race/candidate identity updates keep unrelated existing `source_metadata` keys.

## Task 9: Implement Stage 1 sync and amendment reconciliation

**Files:** `tasks.py`, task tests.

- [ ] `sync_ny_elections` discovers supported certification documents and upserts one election per unique date/type.
- [ ] Store certification landing/PDF URLs separately from Flateau result metadata.
- [ ] Fetch the document and read the latest version-history date.
- [ ] Create a newly discovered election even when no prior version metadata exists.
- [ ] Queue/perform race sync only when the version date or document identity changes.
- [ ] `sync_ny_races` parses and validates the complete snapshot before writing.
- [ ] Upsert races/candidates through aggregation.
- [ ] Reconcile missing `NY_BOE` races/candidates only after a complete successful parse.
- [ ] Do not retire Civic or community records.
- [ ] Keep Stage 1 metadata, `flateau_election_names`, legacy `election_name`, and curated/admin keys when updating the same `Election.source_metadata` dictionary; explicitly merge before `ingest_election` or force-write the merged metadata afterward.
- [ ] Log created/updated/retired/error counts.
- [ ] Add idempotency, amendment-removal, failed-validation-no-retirement, and metadata-preservation tests.

## Task 10: Wire triggers, locks, and scheduler documentation

**Files:** internal views/URLs/task locks and scheduler documentation.

- [ ] Add `sync_ny_elections_trigger` and `sync_ny_races_trigger`.
- [ ] Add `tasks/sync-ny-elections/` and `tasks/sync-ny-races/` URLs.
- [ ] Add daily `TASK_LOCKS` entries following existing state-sync conventions.
- [ ] Draft but do not apply root-owned scheduler crontab lines.
- [ ] Ensure Stage 1 sync timing reflects certification cadence; daily checks are acceptable because unchanged version dates skip reconciliation.
- [ ] Run the internal test suite with `--no-migrations`.

---

# Phase C — End-to-end verification and Full Core promotion

## Task 11: End-to-end race/result matching

Use the real June 23, 2026 election or an isolated copy of it.

- [ ] Stage 1 creates the expected race/candidate population from the certification snapshot.
- [ ] Every Stage 1 race stores the shared NY source identity.
- [ ] NY precedence rows are installed, and `ny_boe` is the representative/field-owning source for authoritative NY race fields after merging with Civic data.
- [ ] Stage 2 resolves all applicable Flateau names automatically or uses the verified override.
- [ ] Results from multiple counties attach to the same district race where appropriate.
- [ ] Results from different districts never attach merely because office titles match.
- [ ] Different party-primary races never consume each other’s rows.
- [ ] Candidate names match successfully; document and fix any proven punctuation/suffix variance without introducing broad fuzzy matching.
- [ ] Partial county failure leaves affected races partial and does not certify/archive them as complete.
- [ ] A complete successful rerun can certify/archive races under existing result-task conventions.

## Task 12: Documentation, issue closure, and promotion

- [ ] Update `NY-Election_Research.md` parser counts and note the hardened wrapped-field/joint-ticket findings.
- [ ] Comment on #40 with the verified list of authorities, ingest counts, collision tests, and PR/commit links.
- [ ] Close #40 only after its acceptance criteria pass in the running stack.
- [ ] Update #87’s NY checklist only after native Stage 1 is deployed and has created browsable pre-results races/candidates.
- [ ] Add NY to `_FULL_CORE_STATES` only after the repository’s Full Core definition is satisfied in production.
- [ ] State clearly in coverage documentation that early “Who Filed”/county-local signals and ENR cross-checking remain follow-up work.

---

# Issue #40 acceptance criteria

Do not close #40 until all are true:

- [ ] pk=1907 (or its canonical replacement) has all applicable Flateau names resolved or explicitly configured.
- [ ] The adapter fetches every configured name in one batch session and does not silently omit failed authorities.
- [ ] Missing unpublished metadata is repaired automatically or treated as an expected informational state.
- [ ] The nightly run no longer emits `ny_sos.adapter.no_election_name` for pk=1907.
- [ ] Every result row retains its exact source `electionName`/authority.
- [ ] The adapter emits a race identity stronger than `office_title`.
- [ ] Same-title races in different districts do not collide.
- [ ] Separate party-primary races do not collide.
- [ ] Multi-county portions of one race remain one race with distinct jurisdiction fragments.
- [ ] One failed county produces partial confidence, returns an empty/non-authoritative source version, and does not advance the version cache at either adapter or task layer.
- [ ] All failed counties produce no rows, no cache advance, and no false `unchanged` result.
- [ ] A complete successful run reaches cache persistence without a cache-timeout attribute error.
- [ ] Deterministic combined hashing is independent of list order.
- [ ] A real ingest writes `OfficialResult` records from multiple authorities.
- [ ] A complete unchanged rerun returns `unchanged=True`.

# Full Core acceptance criteria (#87)

- [ ] A native NY source discovers an upcoming supported election without Google Civic.
- [ ] Races and candidates are created before result ingestion.
- [ ] Stage 1 source identity joins correctly to Stage 2 rows.
- [ ] Explicit NY `SourcePrecedence` rows allow NYSBOE to own/update authoritative fields while Civic retains enrichment fields.
- [ ] Certification amendments reconcile removals safely.
- [ ] Operational triggers, locks, schedule documentation, sync logs, and tests are in place.
- [ ] Production verification is complete and documented.

---

## Notes for implementers

- Treat `ny_cert_parser.py` as a proven starting point, not a proof that every field is production-clean.
- Treat `ny_cert_2026.json` as a golden output/count reference, while explicitly testing the missing running-mate and truncated-county concerns.
- Do not solve NY matching with `jurisdiction_fragment` alone; it is part of `OfficialResult` uniqueness after race selection, not a replacement for race identity.
- Do not rely on results bootstrap as New York’s Full Core Stage 1. It remains a fallback and must not collapse district/party contests.
- Do not rely on an adapter-only partial-cache safeguard; the generic result task must enforce full-confidence cache writes.
- Do not add a new `pdfplumber` dependency entry; it is already present in `backend/requirements/base.txt`.
- Keep #40 closure and #87 promotion independently testable even if implemented in one branch or PR series.
