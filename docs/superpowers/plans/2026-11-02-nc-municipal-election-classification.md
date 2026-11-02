# NC Municipal Election Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for implementation. This is the municipal package of #188, following the state-level and county packages. This planning revision authorizes no production writes or statewide research publication.

**Goal:** Classify municipal events using their actual municipality, statutory baseline and researched method/date exceptions, with an accepted November-general inference while research is incomplete.

**Architecture:** Maintain a versioned municipality schedule/evidence registry. Resolve each observed contest to a municipality, apply an effective-year method or specific event override when known, then use a recorded November-general fallback where permitted. Keep phase, municipal jurisdiction, special context, evidence status and research status separate.

**Tech Stack:** Existing Python 3.13/Django/Celery/PostgreSQL pipeline and shared classification/event-identity interfaces from the [parent plan](2026-11-02-nc-election-classification-closeout.md).

**Spec:** User direction: G.S. 163-279 supplies the baseline; November municipal contests may be inferred general; research each municipality for its method, exact dates and exceptions. The statutory runoff exception below qualifies the fallback. The [existing evidence inventory](../../nc-election-classification-inventory-2026-11-02.md) remains a factual snapshot.

## Global constraints

- Municipal jurisdiction is determined before election phase; a county conducting an election does not make the contest countywide.
- Preserve cross-county municipalities and district/ward electorates without merging them from similar names or shared reporting counties.
- A method, cycle or date rule needs an applicable period. Do not apply a current charter to historical elections without evidence that it was then in force.
- Inferred November general classifications are usable in normal processing when identity is resolved. Research pending is not itself a hold; contradictory evidence or unresolved identity can be.
- Existing historical identity/boundary holds remain protected. Municipal method research does not itself authorize applying those repairs.
- UNEXPIRED special context remains independent of primary/general/runoff phase. No inference establishes certification, winner rules or a missing event's occurrence.

## Statutory baseline and its limits

[G.S. 163-279](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-279.html) sets schedules according to election method. The [NCSBE explanation](https://www.ncsbe.gov/about-elections/types-elections) describes the four methods and notes that some municipalities elect in even-numbered years.

| Method | Baseline stages | November phase |
| --- | --- | --- |
| Nonpartisan plurality | November election; no primary | General |
| Partisan primary and election | September nomination; possible October second primary; November election | General |
| Nonpartisan primary and election | October primary if needed; November election | General |
| Nonpartisan election and runoff | October election; November runoff if needed | General runoff, when actually held |

Exact dates come from the applicable statutory formulas and official event notices, not a fixed day of the month. Under [G.S. 163-290](https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_163/GS_163-290.html), methods can change through legislation or the legally provided charter-amendment process. Research must identify the applicable charter/local act/order/notice; the software must not assume municipalities can choose arbitrary dates without a legal basis.

Worked research lead: [Nash County's official municipal page](https://nashcountync.gov/480/Municipal-Elections) identifies Rocky Mount's October election/November runoff method and November plurality elections for other listed towns. This establishes why a municipality-specific override is necessary. It is not a dated historical method record or proof that a runoff occurred in any particular year.

## Accepted fallback and override rules

1. Resolve municipality and applicable contest/ward identity. An unresolved place cannot use the municipal fallback just because its title contains MAYOR or COUNCIL.
2. Apply a specific official event notice or exceptional schedule for the target year when available.
3. Otherwise apply an election method and cycle whose effective period covers the event, and calculate its regular stages.
4. If the method is unknown and an observed municipal contest is in November with no conflicting event evidence, allow `phase=general`, `evidence_status=inferred`, `reason=municipal_november_default`, `research_status=pending`.
5. For a known applicable election-and-runoff method, route an observed November runoff as `phase=general_runoff`. Do not create a runoff solely because the statutory calendar reserves a date for one.
6. Preserve the original observed date. A nonstandard November day triggers a research flag, not silent conversion to the statutory date or automatic special classification.
7. Keep the UNEXPIRED inference and other sourced special/rerun context. Known evidence may promote or revise the fallback; confidence-only promotion must not create duplicate event identities.
8. Unknown October/September phase requires method/event research. Non-November does not imply special.

If an official source contradicts another source for the same municipality, contest and period, retain both and hold the conflicting assignment for reconciliation. An unpublished runoff or unknown exact date remains conditional/unknown rather than being manufactured from a calendar formula.

## Municipality research registry

Create one stable municipality identity with period-specific method records and year-specific event overrides. Keep source assertions distinct from derived dates. Required fields:

| Field group | Evidence to record |
| --- | --- |
| Identity | Municipality ID, official name/aliases, state, constituent counties and ward/district identifiers when relevant |
| Method | One of the four methods, partisan/nonpartisan status, charter or official election-method source |
| Cycle | Election years, two-/four-year terms and staggered seats as applicable; do not assume every municipality votes every odd year |
| Effective period | First/last applicable dates or years, amendment dates and explicit gaps in historical coverage |
| Calendar | Calculated regular stages, published exact dates, conditional runoff/second-primary dates and whether those stages actually occurred |
| Exceptions | Local acts, charter changes, court/board orders, postponed elections, reruns or special events, scoped to the affected years/offices |
| Provenance | Source URL/document locator, retrieval date, source/evidence version and confirmation/inference status |
| Research status | Pending, researched for specified periods, conflicting, or awaiting an identified source; next research action |

An empty exceptions list on a pending record means **not yet researched**, not **confirmed no exceptions**. Historical coverage may be partial even where current rules are confirmed.

## Research and implementation steps

### Task 1: Establish the research universe and source order

- [ ] Build a municipality list covering the official municipality universe and names found in the ingestion inventory. Record unmatched names and cross-county places explicitly; deduplicate only with supported identity evidence.
- [ ] Research official municipal charters/codes, county election-board pages and notices, NCSBE materials, local acts and official orders. Use dated event notices for exact dates and charter/method records for recurrence; they serve different purposes.
- [ ] Define the registry schema above and a coverage ledger. Prioritize observed records currently labeled special, November runoff candidates, postponed/rerun years, cross-county municipalities and upcoming events.
- [ ] Pilot on Rocky Mount and a documented November plurality municipality, then expand across the full municipality list. A pilot does not constitute completion of statewide research.

**Exit:** Every included municipality has a stable research entry or an explicit unresolved-identity entry, and the first researched examples demonstrate both default and override handling.

### Task 2: Research method, cycle and exact dates for every municipality

- [ ] Record current method/cycle and the specific source supporting them; determine the covered historical periods rather than assuming continuity.
- [ ] Capture published primary, second-primary, general and runoff dates for relevant years; distinguish reserved/conditional dates from elections actually held.
- [ ] Identify and scope exceptions and method/cycle changes. Record a precise remaining research question where authoritative documentation is absent.
- [ ] Reconcile derived statutory dates with published notices. Preserve disagreements as conflicts rather than replacing either source silently.

**Exit:** Each municipality is researched for the requested periods or has an explicit actionable gap. Accepted inference may cover that gap without falsely claiming research completion.

### Task 3: Implement municipal inference and overrides

**Planned files:** Shared NC classification/event-identity modules, municipal registry/evidence loader, relevant adapter/task paths, API projection and app-local tests.

- [ ] Write failing tests for all four methods, a November unknown-method fallback, a known November runoff, a normal October election/primary, an even-year municipality and a dated schedule exception.
- [ ] Implement applicable-period method lookup, date calculation and event overrides before the fallback. Test dates when November 1 is a Tuesday so the legal election date is not computed as the first Tuesday indiscriminately.
- [ ] Test that one municipality's exception does not affect other municipalities on the same date, and one municipality's current method does not overwrite an older method.
- [ ] Test unknown-method inferred general promotion, correction to runoff with reviewed evidence, and source conflicts. A phase/key change needs the shared reconciliation path; confidence-only confirmation does not mint another event.
- [ ] Reuse scoped candidate/result routing and accepted/deferred/held accounting. Test cross-county reporting and distinct full/unexpired terms without guessing electorate boundaries.

**Exit:** Known municipality rules override the usable fallback, historical periods remain separate, and every observed source contest is accounted for.

### Task 4: Repair, verify and complete the municipal package

- [ ] Prepare fresh municipality/event-scoped dry-runs separating confirmed mappings, permitted inferred mappings, unchanged records, pending research and blocking conflicts.
- [ ] Follow the parent plan's identity-preservation, fingerprint, isolated rehearsal, backup, pilot and controlled writer-cutover requirements. Do not revive earlier held identity repairs as a side effect.
- [ ] Verify API classification/evidence status, unchanged result values and repeated/scheduled-sync convergence.
- [ ] Publish aggregate coverage and remaining research/follow-up accounting when authorized. Distinguish usable inferred classification from completed per-municipality research.

**Municipal completion rule:** Every in-scope municipality and observed event has an explained classification and research disposition; known exceptions override the fallback; remaining gaps are explicit; approved repair and production validation are complete. The parent issue can close only under its agreed package and residual-work scope.

## Review focus

- November is an inferred general baseline, not proof that a known runoff is general.
- A municipality's election method, cycle and exceptional event dates need effective periods and primary-source support.
- Conditional runoffs must not become invented events; actual November runoffs must not lose their phase.
- County administration and multi-county reporting must not change municipal electorate identity.
- Research pending, permitted inference and blocking contradiction are distinct outcomes.
