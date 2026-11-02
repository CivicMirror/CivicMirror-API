# NC State-Level Election Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for implementation. This plan covers the first jurisdiction package of #188. No application code or production data changes are authorized by this planning revision.

**Goal:** Establish jurisdiction first, identify regular state-level primary/general elections from law and official schedules, and accept a documented UNEXPIRED inference for special-election context.

**Architecture:** Resolve each contest's jurisdiction and office, assign its phase from the applicable regular calendar or a specific official exception, and independently determine special context. Share this result across discovery, candidate ingestion, result routing and a scoped repair. Confirmed and permitted inferred classifications are usable outcomes; contradictions and unresolved identity remain held.

**Tech Stack:** Existing Python 3.13/Django/Celery/PostgreSQL pipeline; reuse aggregation keys and NC contest identity safeguards.

**Spec:** User direction in the [revised parent plan](2026-11-02-nc-election-classification-closeout.md#revised-direction-jurisdiction-first-state-level-first), supported by the [November 2 inventory](../../nc-election-classification-inventory-2026-11-02.md). Remaining storage/API projection decisions belong in the state-level design before code.

## Global constraints

- First package: state-level processing. County and municipal classification are separate subsequent packages.
- Working office scope: the existing candidate adapter's federal, state executive and legislative offices, including their districts. This is an explicit drafting assumption pending the user's scope clarification, not an approved exclusion of statewide judicial offices.
- Freeze the exact first-package office list before implementation. Do not conflate statewide electorate, state office, federal office and a state-level processing package.
- Preserve district jurisdiction and geographic scope. Do not set every included contest's electorate to all of NC, or use reporting county as its jurisdiction.
- County, municipal, school and other unmatched district rows must have an accounted-for deferred/held disposition; they are not automatically absorbed into the first package.
- Existing historical identity/boundary holds and superseded records remain protected. The new inference permission concerns classification, not approval to resolve identity disputes.
- Use confirmed/inferred/held evidence status separately from upcoming/pending/certified lifecycle status. An inferred special classification does not certify results or winners.
- Phase values are `primary`, `primary_runoff`, `general`, `general_runoff` or `unknown`; special context and `confirmed`/`inferred`/`held` evidence status are separate fields.

## Source hierarchy and classification rules

1. **Jurisdiction/office:** establish the contest's electorate before using calendar or UNEXPIRED signals. Record office, district/territory and source evidence.
2. **Regular calendar:** use [G.S. 163-1](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-1.html) and the NC State Board of Elections' dated schedules. The statute provides the regular election/primary framework; applicable laws, court/board orders and published changes override the baseline. Current primary rules must not be back-applied to historical years indiscriminately.
3. **Specific events:** official contest/event notices establish specials, reruns and exceptions. For second primaries, use official event evidence and the applicable [G.S. 163-111](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-111.html) framework rather than assuming every later date is a runoff.
4. **Permitted special inference:** a case-insensitive whole-word `UNEXPIRED` in the source's contest title, or an explicit TRUE value in the filing field `is_unexpired`, sets special context to inferred when there is no conflicting stronger evidence. Record the original field/token, source URL/file version and inference-rule version. Do not search arbitrary candidate/contact text for the token.
5. **Negative evidence:** no token, a blank field or a FALSE flag does not prove that an election is regular. CD09 in 2019 is a required counterexample. Contradictory signals for the same contest require reconciliation; missing fields must not be coerced into FALSE.
6. **Normal processing:** an otherwise resolved inferred special is eligible for ingestion/routing and the approved public representation. It does not require a hold merely because no authoritative special notice was found. A general-date calendar entry and an UNEXPIRED contest can coexist without conflict.

The official calendar identifies the [March 3, 2026 primary](https://www.ncsbe.gov/news/events/election-day-2026-primary-election) and [November 3, 2026 general](https://www.ncsbe.gov/voting/upcoming-election). Those are explicit calendar entries, not month-based classifications. A scheduled date can exist before an ENRS folder or results ZIP is published.

## Decision table

| Jurisdiction and evidence | Result |
| --- | --- |
| Resolved included office; regular primary date; no special evidence | Regular primary classification based on the official calendar |
| Resolved included office; regular general date; no special evidence | Regular general classification based on the official calendar |
| Same, with UNEXPIRED token or explicit TRUE flag | Special primary/general context, recorded as inferred; preserve the calendar-derived phase |
| Known second-primary event with UNEXPIRED signal | Special second primary; inferred special context and independently established runoff phase |
| Official special notice, but no token or TRUE flag | Special context from authoritative evidence; do not let the missing heuristic negate it |
| UNEXPIRED signal with unresolved phase | Special context may be inferred; unknown phase remains explicit and routing is held if phase is needed for identity |
| Conflicting contest-specific evidence | Hold with both sources retained |
| County or municipal contest sharing the date | Deferred to its jurisdiction package; do not change it as part of the state package |
| Reporting county repeats for one known state/district contest | Preserve one contest for the known electorate; county repetition alone does not create county Elections |

Example public description: **Special Primary Election — inferred from UNEXPIRED**, with the phase and evidence exposed separately. The exact existing-enum projection must preserve both facts and is a design output, not permission to replace nomination phase with an undifferentiated `special` label.

## Implementation steps

### Task 1: Freeze jurisdiction and calendar inputs

- [ ] Map and approve the exact first-package offices, distinguishing statewide and district electorates. Explicitly assign judicial/school/special-district ownership rather than guessing from a reporting county.
- [ ] Define `NcJurisdiction` and the versioned calendar/event evidence consumed by the classifier. Keep source retrieval and parsing separate from pure classification.
- [ ] Define exact calendar dates for the initial supported years, including published exceptions. Generate future regular baseline dates from applicable rules, check them against official notices, and retain source provenance without requiring a results archive.
- [ ] Document independent jurisdiction, phase, special context and evidence status fields; specify their public/API projection and event-key grouping.

**Exit:** The first office list, geographic mapping and calendar contract are concrete and testable. This is the only scope/design gate before state-level implementation.

### Task 2: Implement the permitted inference

**Planned files:** `backend/integrations/nc_sbe/classification.py`, `event_identity.py`, reviewed evidence records, and app-local classification tests.

- [ ] Write failing tests for regular primary/general dates, whole-word/case-insensitive title tokens, explicit TRUE/false/missing flags, and inferred special context without any special notice.
- [ ] Implement separate dimension/evidence outputs. Confirmed and inferred inputs may produce resolved event identities; preserve provenance and a machine-readable reason such as `unexpired_title` or `unexpired_flag`.
- [ ] Test a special primary and a special second primary so UNEXPIRED does not erase the phase distinction.
- [ ] Test promotion from inferred to confirmed: changing evidence confidence alone must not change event identity or duplicate an Election. Contradictory classification evidence must produce an explicit hold.
- [ ] Test regular and unexpired contests for the same office/date: they must not collapse into one contest or cause the whole date to become special.

**Exit:** A permitted inference works as an ordinary, traceable classification outcome; no authoritative-only bottleneck remains.

### Task 3: Integrate state-level routing

**Planned files:** NC source client/mappers/tasks, NC results adapter/identity/tasks, relevant secondary writers, API projection and their tests.

- [ ] Create known upcoming state-level events from calendar/filing evidence before results exist. ENRS discovery supplements the calendar.
- [ ] Replace one-Election-per-date candidate selection with jurisdiction/event-scoped routing for the included office set.
- [ ] Filter state-level results by the same event contract before bootstrap or persistence; record accepted, deferred and held source groups separately.
- [ ] Preserve existing NC contest IDs/party variants and prevent Civic/calendar syncs from recreating legacy bare-key records.
- [ ] Expose inferred versus confirmed classification consistently. A classification inference must not mark results certified, set winners, or widen unsupported nomination rules.
- [ ] Verify that county/municipal rows on a shared date and their existing relationships are unchanged and assigned to their deferred packages. Freeze mixed-parent behavior before changing keys so the deferred writers cannot contaminate new state events.

**Exit:** New state-level ingestion converges independently while shared-date deferred records remain intact and accounted for.

### Task 4: Preview and rehearse the scoped state-level repair

**Planned files:** The parent plan's dry-run-first repair module/command/tests and state-level runbook sections.

- [ ] Generate a fresh report selecting only included state-level contest components. Separate confirmed changes, permitted inferred changes, unchanged records and held conflicts.
- [ ] Verify a coherent mixed-parent split/rekey plan and unchanged county/municipal relationships. The inference policy does not authorize guesses about electorate boundaries or previously held identity cases.
- [ ] Rehearse transaction/fingerprint rejection, stable IDs/results, cache invalidation, repeated candidate/result sync and rollback in an isolated database snapshot.
- [ ] Check that inferred-to-confirmed evidence changes do not require rekeying solely because confidence changed, and that genuine reclassification changes trigger the reviewed repair path.

**Exit:** The state-level package has a concrete apply report and proven rollback; the November 2 inventory is not its approval token.

### Task 5: Complete the state-level milestone

- [ ] Follow the parent plan's reviewed backup, writer-drain, pilot/cutover and production validation sequence for the state-level scope.
- [ ] Observe a successful scheduled NC cycle and verify no duplicate events, cross-jurisdiction routing or new winner/certification assertions appear.
- [ ] Record remaining state-level holds and the deferred county/municipal ledger. Review the next jurisdiction package separately.

**State-level completion rule:** Every included contest is accounted for as confirmed, permitted inferred, intentionally unchanged or explicitly held; implemented routing preserves jurisdiction/phase/context, supported repair is applied safely, and production convergence is verified. Inferred special context is accepted without demanding an authoritative special notice for every UNEXPIRED contest.

**Parent closure:** This milestone completes the first piece of #188. County and municipal work must then be completed, or explicitly moved into agreed follow-ups with the parent scope changed before #188 is closed.

## Review focus

- A county reporting row must not turn a state/district contest into a county election.
- An UNEXPIRED nomination contest must remain a primary or second primary.
- Absent UNEXPIRED evidence must not erase an officially identified special/rerun.
- Inferred evidence is usable; true contradictions and unresolved identities remain held.
- Partial jurisdiction rollout must not alter deferred records or allow their writers to recreate or contaminate state-level identities.
