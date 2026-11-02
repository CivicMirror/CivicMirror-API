# NC Election Classification (#188) Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Complete the design gate in Task 1 before implementing Tasks 2–7. This document authorizes no production apply.

**Goal:** Close [#188](https://github.com/CivicMirror/CivicMirror-API/issues/188) after NC classification and ingestion are corrected, existing records are reconciled safely, and production evidence demonstrates that repeated syncs preserve the corrected identities.

**Architecture:** Establish election jurisdiction first, then implement separate state-level, county and municipal work packages in that order. Within each package, classify contests using a statutory/official calendar plus documented inference, then use one routing contract for discovery, candidates, results and repair. Preserve phase, special/rerun context, jurisdiction and evidence status independently.

**Tech Stack:** Python 3.13, Django, Celery, PostgreSQL, Redis, the existing aggregation identity service and NC SBE sources.

**Spec / design status:** This is a design-gated closeout roadmap. Its evidence baseline is [the refreshed inventory](../../nc-election-classification-inventory-2026-11-02.md) and [its JSON](../../nc-election-classification-inventory-2026-11-02.json), not an approved classification design. Task 1 produces the design at `docs/superpowers/specs/2026-11-02-nc-election-classification-design.md`; update subsequent interfaces if that design changes them.

## Revised direction: jurisdiction first, state-level first

The user's subsequent direction replaces the blanket no-inference rule in the initial plan. Use three separately reviewable work packages:

1. **State-level elections:** implement jurisdiction mapping, known regular primary/general dates and the permitted UNEXPIRED inference first. See the [state-level plan](2026-11-02-nc-state-election-classification.md).
2. **County elections:** apply the shared evidence/routing contract to county offices, county/district boundaries and local exceptions after the first package works.
3. **Municipal elections:** use G.S. 163-279 as the scheduling baseline, allow November-general inference, and research each municipality's method, cycle and exceptions. See the [municipal plan](2026-11-02-nc-municipal-election-classification.md). Preserve applicable November runoffs under subsection (a)(4).

These are processing scopes. Preserve the actual electorate: a congressional or legislative district is not statewide, and a reporting county does not define the contest's jurisdiction. School, judicial and special districts need explicit ownership in the scope map; do not force them into a county or municipal bucket merely because they are local.

Working scope for the first package is the existing candidate adapter's federal/state executive and legislative offices, including districts; this is an implementation assumption, not a user-approved exclusion of judicial offices. Freeze an explicit office list before implementation. County and municipal rows encountered in the same source file remain accounted for under their deferred packages.

### Permitted inference and authoritative evidence

- Establish regular dates from [G.S. 163-1](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-1.html), the applicable historical rules and the NC State Board of Elections' official calendar/notices. The current statute states a March primary baseline; do not retroactively apply that rule to every historical year or ignore dated exceptions.
- Treat an exact `UNEXPIRED` token in the official contest title, or the filing CSV's explicit `is_unexpired=TRUE`, as sufficient positive evidence for **inferred special-election context** when jurisdiction is resolved and no stronger evidence contradicts it. Store the particular signal, source and rule version.
- Inference is an accepted classification outcome, eligible for ordinary ingestion/routing when event identity is resolved. It does not automatically become a held case simply because authoritative confirmation of special status is absent.
- Preserve `primary`, `primary_runoff`, `general` or `general_runoff` separately. A special primary remains a nomination contest. An unexpired contest on the regular general date can be a special general without changing other contests on that date.
- Distinguish `confirmed`, `inferred` and `held` in stored evidence and the public classification contract. These are evidence statuses, not election lifecycle statuses.
- A missing UNEXPIRED token or FALSE flag does not rule out a special/rerun. Specific official notices outrank the heuristic; a general calendar date does not itself contradict a special contest sharing that date.
- Hold contradictory evidence, unresolved jurisdiction/event identity and unsupported phase assignments. The inference policy does not resolve historical identity/boundary conflicts or assert certification/winners.

**Revised closeout rule:** Complete each jurisdiction package using confirmed classifications **or explicitly recorded, permitted inferences**, with conflicts held and accounted for. A state-level completion milestone does not by itself close county/municipal work or the whole issue. Before closing #188, complete the agreed packages or explicitly narrow the parent scope and track the deferred work.

### Municipal calendar and research policy

- Use [G.S. 163-279](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-279.html) and the municipality's applicable election method. The standard schedule depends on method; November can contain a general election or, under subsection (a)(4), a nonpartisan runoff.
- For an observed contest with resolved municipal jurisdiction, a November date and no known conflicting method/event evidence may produce `phase=general`, `evidence_status=inferred`, with reason `municipal_november_default`. It is usable pending research, not automatically held. Preserve the observed date; do not silently replace it with the calculated standard date.
- Applicable researched methods and official notices override that fallback. A known November runoff is `general_runoff`; an October event is not automatically special, since it may be a regular primary or election under the chosen method. Preserve independent UNEXPIRED special context.
- Research every municipality's charter/method, election cycle, applicable years, exact published dates and exceptions through official municipal/county/state sources. Store effective periods and research status so today's method is not imposed on earlier years. A currently unknown method is a research gap, not proof that no exception exists.
- Municipalities can change election methods through the legal mechanisms described in [G.S. 163-290](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-290.html); do not model arbitrary local date selection as unrestricted authority. Record the actual legal/official basis of each exception.

## Global constraints

- Python `>=3.13,<3.14`; verify the execution environment rather than assuming `backend/.venv` uses that version.
- Scope is the legacy NC pipeline. CM2 migration, broader election-model replacement and other-state classification changes are excluded.
- Preserve unrelated KY changes and MA/KY research files. Use an isolated implementation checkout when implementation begins.
- The evidence snapshot covers **55 Elections**, not just 25 stored `special` rows. Its fingerprints are inventory evidence, not approved repair tokens.
- Existing unresolved historical components and local electorate splits remain held. This issue does not authorize their deletion, merging, splitting or supersession.
- Production is local Compose at `/data/DockerConfigs/CivicMirror`. Historical Cloud Run infrastructure is not the deployment target.
- No raw candidate contact fields, user identifiers or database dumps in commits, fixtures or issue comments.
- Separate code deployment, writer activation and data repair. New and old writers must not run concurrently against incompatible keys.

## Review focus

1. Jurisdiction, phase and special context are independent: same-day state, county and municipal contests must not acquire one another's classification or geographic scope.
2. An uncertain contest on a mixed date must neither contaminate a verified event nor be silently omitted from accepted/held accounting.
3. Changed source evidence with an unchanged results ETag must trigger reconciliation; failed/held routing must remain retryable.
4. Changing a stored election type can make winner derivation newly eligible. Classification alone must not assert certification, nomination rules or winners.
5. Secondary writers, retired parent Elections and existing race tombstones must not recreate old keys or reappear as ordinary duplicate API records.

## File responsibilities

These are planned locations; additions remain contingent on Task 1's approved contract.

| Files | Responsibility |
| --- | --- |
| `backend/integrations/nc_sbe/classification.py` (new) | Pure evidence classification and immutable result types; no database writes |
| `backend/integrations/nc_sbe/event_identity.py` (new) | Deterministic event grouping and source identifiers, shared by ingestion and repair |
| `backend/integrations/nc_sbe/client.py`, `mappers.py`, `tasks.py` | Source collection, flag preservation, discovery and candidate routing |
| `backend/integrations/nc_sbe/evidence/` (new) | Reviewed historical schedule assertions with source URLs, scope, dates and evidence versions; no guessed annual dates |
| `backend/results/adapters/nc.py`, `backend/results/tasks.py`, `backend/results/nc_identity.py` | Scoped result routing, bootstrap boundaries, existing contest identity preservation |
| `backend/results/winners.py` | Preserve classification and nomination safeguards when records move |
| `backend/aggregation/identity.py`, `ingest.py` | Reuse current key functions; change shared code only if demonstrated necessary |
| `backend/integrations/civic/ingest_adapter.py`, `backend/integrations/election_calendar/tasks.py` | Prevent lower-evidence NC writers from minting legacy bare-key siblings |
| `backend/integrations/nc_sbe/election_repair.py` (new) | Build and apply reviewed classification/reparenting plans |
| `backend/integrations/nc_sbe/management/commands/repair_nc_election_classification.py` (new) | Dry-run-first repair CLI, scope and fingerprint checks |
| `backend/elections/models.py`, a new elections migration if required | Only persistence/constraints required by the approved design |
| `backend/api/serializers.py`, `views.py` | Explicit public classification/review state and legacy-parent behavior |
| App-local tests and sanitized fixtures | Classification, routing, transactional repair and API regression coverage |
| `docs/nc-election-classification.md` (new) | Source rules, mapping decisions, repair/cutover/rollback runbook and held ledger |

---

### Task 1: Lock the classification, event identity and closure contract

**Inputs:** Issue body/comments, the November 2 inventory, existing canonical-key functions and the preserved historical holds.

**Deliverable:** A reviewed design with an explicit decision table; a corrected issue update prepared for later publication. This is the first decision gate, not another broad source audit.

- [ ] Freeze the state/county/municipal work-package boundaries and first-package office list. Map actual jurisdictions before classifying election type; preserve district identifiers and explicit unknowns.
- [ ] Define independent dimensions: jurisdiction, phase (`primary`, `primary_runoff`, `general`, `general_runoff`, `unknown`), special/rerun context, unexpired-term attribute and evidence status (`confirmed`, `inferred`, `held`). Implement the permitted inference above rather than the superseded blanket prohibition.
- [ ] Choose how these dimensions project onto `Election.election_type` and public API fields. **Recommended direction:** an NC-scoped, versioned classification record plus an explicit projection into the existing enum. A global enum/model redesign is unnecessary for this issue unless the design proves otherwise. Do not silently adopt phase-only typing as though it were already agreed.
- [ ] Define actual event grouping. Contests sharing a municipal ballot/event stay together; independently ordered specials can remain distinct even with the same date/type. `contest_group` must represent sourced event identity, not each office title or a guessed city boundary.
- [ ] Define stable source IDs for multiple events on one date. The old `nc_sbe_YYYY_MM_DD` identifier must not be reused ambiguously with `.first()` fallback matching.
- [ ] Specify behavior for a mixed legacy Election: in-place rekey when there is one supported destination; explicit race-to-event mapping when there are several; preserved legacy-parent references if retirement is necessary. Define list/detail/count behavior and link compatibility before choosing a tombstone or alias mechanism.
- [ ] Specify what a held classification looks like to API clients and scheduled jobs. A legacy `special` label cannot continue masquerading as a verified special event. An isolated hold must not silently certify or suppress unrelated contests.
- [ ] Complete a disposition ledger for every stored Election and every proposed moved contest: supported mapping, intentional unchanged identity, or held with a reason/source requirement. The 12 filing-only dates remain held unless primary evidence establishes an actual event.
- [ ] State per-package completion and parent-issue closure criteria. Confirmed classifications and permitted UNEXPIRED inferences both qualify; remaining contradictions/identity gaps require guarded holds and follow-up. A recorded inference is not an unexplained legacy bucket.

**Decision-table cases that must be settled:**

| Case | Required distinction |
| --- | --- |
| 2014-05-06 vs 2014-07-15 | Identical filing flags cannot distinguish first/second primary |
| 2016-06-07 | Congressional first primary on a June date, with other contest contexts |
| 2019-04-30 / 2019-07-09 | Special primary and special second primary both have unexpired TRUE |
| 2019-05-14 / 2019-09-10 CD09 | Special context with unexpired FALSE |
| 2019-09-10 | CD03/CD09 special generals alongside Charlotte nomination contests |
| 2020-06-23 | CD11 second primary alongside a new Columbus County primary |
| 2022-07-26 | Municipal elections alongside local second primaries |
| 2022-12-06 | School-board runoff without same-date annual filing rows |
| 2023-03-07 | Dobson rerun, not a March primary |
| 2024-05-14 | Second-primary evidence despite a missing ZIP |
| 2010–2013 municipal titles | Unprefixed filing titles; legacy results CSV layout |
| November municipal contest under an unknown versus known runoff method | Permit inferred general when method is unknown; override with applicable method/event evidence for a November runoff |
| 2026-11-03 captured on November 2 | Published zero-vote archive is pre-election evidence |

**Exit gate:** Design review settles projection, grouping, source-ID uniqueness, held-record behavior, legacy-parent compatibility and exact closure criteria. Rewrite the interfaces below if necessary. Do not start product implementation before this gate.

### Task 2: Implement and test the shared evidence classifier

**Files:** New `classification.py`, `event_identity.py`, reviewed evidence records and `tests/test_classification.py`; update `client.py`, `mappers.py` and existing client/mapper tests.

**Proposed interfaces, to finalize in Task 1:** `classify_nc_contest(evidence: NcContestEvidence) -> NcClassification`; `event_identity_for(classification: NcClassification) -> NcEventIdentity | None`. The output includes jurisdiction, independent dimensions, evidence status, source references, a rule/evidence version and a held reason when applicable. Confirmed and permitted inferred outputs can yield resolved event identities; held outputs cannot be treated as resolved.

- [ ] Write sanitized fixtures from the inventory's specific counterexamples. Strip all contact fields and include distinct term, county and party evidence without inventing electorate identity.
- [ ] Write failing tests for the active jurisdiction package's cases: permitted inference without an official special notice, inferred-to-confirmed promotion, conflicting evidence, same office with full/unexpired terms, and distinct specials sharing a date/type. Retain the complete decision table as the parent plan's cross-package coverage checklist.
- [ ] Implement strict flag parsing, the jurisdiction-specific calendar, permitted UNEXPIRED special-context inference and the municipal November-general fallback. Scope calendar assertions so they do not erase special context; apply researched method/event overrides to the municipal fallback. The UNEXPIRED token/flag does not independently decide phase or jurisdiction.
- [ ] Include unsupported source layouts, 404 and `Data Unavailable` as source states. The existence of a filing row or ENRS prefix must not establish that an event occurred.
- [ ] Run the focused classifier/client/mapper tests and inspect serialized outputs for deterministic grouping, evidence versions and held reasons. Commit this unit after its tests pass.

**Exit gate:** One deterministic contract can be consumed by all writers and the repair command. It makes no production writes on its own.

### Task 3: Route discovery and candidates through classified events

**Files:** `nc_sbe/tasks.py`, `mappers.py`, `tests/test_tasks.py`; relevant Civic/calendar writer paths and their tests.

**Inputs:** The classifier and event identity contract. **Outputs:** Event-scoped Elections/source links and candidate/race ingestion scoped to the same event identity.

- [ ] Replace month-based creation and the `{date: election}` lookup. Discover source dates without asserting classification, then materialize supported events from filing/schedule evidence. Record unresolved inputs with explicit held accounting.
- [ ] Preserve all four source flags and classification evidence. Check consistency before deduplicating repeated county rows or using a first row as representative.
- [ ] Route each contest to its own resolved event. Preserve party variants, verified NC contest identity, sourced seats and candidate metadata from previous repairs.
- [ ] Audit every NC `ingest_election` caller, including Civic and the seeded election calendar. Attach ambiguous low-evidence input only through a supported crosswalk or hold it; never recreate a bare-key parent beside corrected events.
- [ ] Test a mixed date, several same-day events of the same type, a municipal ballot with several offices, a date with no published results, and a lower-priority source with insufficient scope.
- [ ] Run discovery and candidate sync twice against seeded fixtures. Assert stable Election/race/candidate IDs and counts, stable source links, no old-key resurrection, and no terminal-status downgrade. Commit after focused tests pass.

**Exit gate:** Upcoming ingestion works without waiting for a results ZIP; new writes use the same identities the repair will produce.

### Task 4: Filter results before bootstrap and persistence

**Files:** NC adapter, results tasks/identity, winner safeguards and their app-local tests.

**Inputs:** Event identities from Task 2. **Output:** Every parsed contest is assigned to exactly one supported event or explicitly held before any database persistence.

- [ ] Add a scoped result-partition operation shared by ordinary ingestion and repair. Never send a whole date's ZIP to an empty split Election's bootstrap path.
- [ ] Handle historical comma-delimited files explicitly if they are required for classification/routing; absent legacy group IDs stay absent. Do not fabricate IDs or expand historical results imports merely because the audit could read those files.
- [ ] Preserve `nc_contest_key`, electorate qualification and existing ambiguous-local-contest holds. Confirm routing for Elections with existing races and for genuinely empty Elections.
- [ ] Include classification/evidence version in cache validity. Changed classification must reconcile an unchanged ZIP; an exception must not commit cache state. Preserve retryability for held/unmatched contests rather than caching them as fully processed.
- [ ] Test filtering before bootstrap, disjoint partitions, accepted-plus-held accounting, unchanged ETags with changed evidence, cache commit after persistence, and failure/retry behavior.
- [ ] Check certification and winner derivation after a type change. Keep source-set winners and all existing seat/party/nomination restrictions; retain unsupported cases as skips. Do not blanket-enable municipal/special winner derivation or run it automatically during repair.

**Exit gate:** Results cannot leak across classified events, and no new classification bypasses the current winner/certification safeguards.

### Task 5: Implement a transactional classification repair and public compatibility

**Files:** New repair module/command/tests; approved model migration if needed; API serializers/views/tests; `docs/nc-election-classification.md`.

**Proposed CLI:** `repair_nc_election_classification --election-id ID --dry-run --report PATH`; apply requires `--apply --approved-report PATH` and a different output report. Default mode is no-write preview. Exact options and report schema are fixed in Task 1.

- [ ] Build a source-qualified plan listing old/new event keys, projected types, group IDs, moved race IDs, rewritten existing race keys, source-link operations, parent disposition, review state, evidence and every hold/conflict. Inventory each foreign-key relation to Election/Race/Candidate before deciding the move set.
- [ ] Fingerprint the complete inspected dependency state and source/classification bytes. Require the same selected scope, unchanged source and unchanged database state on apply; bypass ETag cache during approval verification.
- [ ] Rekey supported single-destination Elections in place. Split only proven event groups and reparent existing races while preserving race/candidate/result IDs, result values, provenance and source-record/mock-vote references. Preserve intentionally blank race keys unless a separately validated assignment is necessary.
- [ ] Reject ambiguous key collisions and relation mappings. Preserve existing race tombstones and all previously held historical components; do not merge duplicates or rewrite result values as a side effect of classification.
- [ ] Implement the approved legacy-parent and API behavior, including review visibility, counts, filters and detail compatibility. Ensure all scheduled writers honor retirement/hold state.
- [ ] Lock the complete affected group, rebuild the plan under lock and apply atomically. A changed fingerprint, conflict, constraint failure or report-write failure must leave the database unchanged.
- [ ] Test no-write dry-run, in-place rekey, mixed-event split, preserved IDs/relationships, empty Elections, keyless races, held components, changed evidence/database rejection, induced rollback, parent visibility and repeated apply.

**Exit gate:** The repair is reviewable before mutation, safe to retry and compatible with Tasks 3–4. A preview report from this command, not the November 2 inventory, becomes the approval artifact.

### Task 6: Rehearse the complete change against an isolated production snapshot

**Files:** Integration/regression tests, repair reports and runbook. Private snapshots and full reports stay outside Git.

- [ ] Restore a fresh backup into an isolated PostgreSQL database with separate cache/broker settings. Confirm test commands cannot connect to production. Set a task-specific `NC188_PYTHON` to a verified Python 3.13 environment.
- [ ] Run focused classifier, NC client/mapper/task, aggregation identity/ingest, NC adapter/identity/repair, winner/certification, Civic/calendar and API tests. Run Ruff on changed Python files, Django checks, migration checks and the repository-required broader suite.
- [ ] Produce a full disposition report for the fresh NC scope: mapped, unchanged, held and blocked, with no omitted records. Compare the earlier 2024 repair's 1,216 active races and existing tombstones before/after; explain any intended changes rather than assuming counts must always be identical.
- [ ] Rehearse simple rekeys, a mixed date and a missing/placeholder-results case. Verify candidate/result IDs and values remain unchanged; explain Election-count changes from approved splits.
- [ ] Run the repair a second time, then actual discovery/candidate/result tasks twice against frozen source responses. The post-first-apply record counts and keys must stabilize. Include Civic/calendar syncs in this proof.
- [ ] Rehearse API checks and scoped rollback. Prefer a scoped reversal so unrelated state updates survive; a full-database restore is an emergency recovery path requiring explicit accounting for intervening writes.

**Exit gate:** Required checks pass, held records are accounted for, no cross-event contamination occurs, and rollback is demonstrated. Review the complete branch and address findings before rollout.

### Task 7: Deploy and apply in a controlled local production cutover

**Inputs:** Reviewed code, rehearsal evidence, a fresh no-conflict production preview and verified backup. This is a later authorized execution step, not part of the current planning request.

- [ ] Choose a maintenance window that protects current NC ingestion, especially around the November 3 election. Identify every scheduler/task writer that can touch the selected NC scope; pause or gate those writers and drain in-flight work.
- [ ] Deploy compatible code with classification writes disabled until repair/cutover. Apply required schema changes without starting new-key writers against unrepaired data.
- [ ] Verify a fresh backup and its restore/readability. With relevant writers quiescent, regenerate the production preview and review the exact source/database fingerprint, affected groups and held exclusions.
- [ ] After authorization for the concrete apply report, pilot a low-risk supported single-event rekey. Verify API responses, preserved IDs/results and repeated sync convergence. Expand to a reviewed mixed-date pilot, then remaining supported groups.
- [ ] Activate the new routing before resuming writers. Invalidate affected caches explicitly; resume controlled tasks first, then scheduled operation. Never resume the old month-based writer against rekeyed Elections.
- [ ] Verify local Compose health, public/API responses, NC task logs, source-version handling and one completed scheduled ingestion cycle. Compare with the approved post-repair expectations and held ledger.
- [ ] If validation fails, stop affected writers and use the rehearsed rollback. A source change or scope change requires a new preview/review rather than applying an old token.

**Exit gate:** Corrected records are served, production ingestion converges without recreating legacy identities, and the backup/report/rollback references are retained privately.

### Task 8: Publish closure evidence and close #188

**Files:** Final runbook and held ledger; linked implementation PR(s), issue update and follow-ups when authorized.

- [ ] Update the issue with the corrected historical coverage, the actual July 2019 runoff and CD03/CD09 flag evidence, approved classification rules and final scope. Preserve the original audit as history; clearly identify the superseding evidence.
- [ ] Link merged implementation PR(s), tests/rehearsal results, deployment revision, applied report summaries, API verification and the successful repeated/scheduled-sync checks. Exclude private dump paths/contents and candidate contacts from public attachments.
- [ ] Record each residual classification hold with its blocking evidence, safe runtime behavior and follow-up location. The older identity/boundary holds remain explicitly separate and untouched. If unresolved work still violates #188's agreed acceptance criteria, keep #188 open.
- [ ] Close the issue only when every item in the checklist below is satisfied. Merging code or finishing an audit is insufficient.

## Final acceptance checklist

- [ ] Jurisdiction is established before election type; the state-level package is completed before county/municipal implementation.
- [ ] Regular dates use applicable statutory rules plus official schedules/exceptions. The November-general fallback requires resolved municipal jurisdiction and recorded inferred status; month alone, a bare ENRS folder or a municipal-looking title does not establish jurisdiction/event identity.
- [ ] UNEXPIRED-token/TRUE-flag inference is accepted for special context, recorded as `inferred` with its evidence/rule version, and usable without automatic holding when identity and phase are resolved.
- [ ] Authoritative confirmation can promote inferred evidence without changing stable event identity solely because confidence changed; conflicting evidence is held for reconciliation.
- [ ] Municipal research accounts for every included municipality, identifies applicable methods/periods and exact dates or explicit gaps, and overrides the November fallback for known runoffs or other sourced exceptions.
- [ ] The approved representation preserves phase, special/rerun context and municipal scope, including the decision-table counterexamples.
- [ ] All stored NC records in the fresh execution scope have an explained disposition; supported corrections are applied, and residual holds are explicit and guarded under the agreed boundary.
- [ ] Candidate, results, Civic/calendar and repair paths agree on event identities and preserve idempotency.
- [ ] Split events receive only their own contests; all source contests are assigned or held.
- [ ] Existing IDs, relationship mappings, result values, verified contest identities and protected historical holds are preserved as specified.
- [ ] Type changes do not bypass winner/certification safeguards or manufacture historical outcomes.
- [ ] API list/detail/count behavior for corrected events, held records and retired parents matches the approved contract.
- [ ] Tests, isolated snapshot rehearsal, reviewed dry-run, backup verification, rollback rehearsal and production checks are recorded.
- [ ] At least one controlled repeated-sync proof and one successful scheduled NC cycle show no old-key resurrection.
- [ ] The issue contains the final evidence and follow-up accounting before closure.

## Suggested delivery sequence

1. Map jurisdictions and freeze the state-level scope/evidence contract (Task 1 and the linked state-level plan).
2. Deliver the state-level classifier and coordinated routing, result isolation, scoped repair and API compatibility (Tasks 2–5 applied to the state-level scope). Keep activation disabled until the full set is available.
3. Rehearse and deploy the state-level package, including its guarded historical repair (Tasks 6–7). Verify that deferred county/municipal records remain unchanged and accounted for.
4. Implement county, then municipal packages using the same task/check structure and their own approved scope, evidence rules and repair reports.
5. Publish per-package completion evidence and close the parent only under the revised scope/closure rule (Task 8).

The critical path for the first piece is **jurisdiction → known state election calendar → permitted special-context inference → state-level routing/repair → production convergence**. County and municipal classification are separate subsequent pieces. The refreshed inventory remains a factual snapshot; the inference policy above supersedes its earlier planning recommendation to prohibit unexpired-based classification.
