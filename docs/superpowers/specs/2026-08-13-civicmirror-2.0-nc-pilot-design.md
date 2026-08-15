# CivicMirror 2.0 Normalized Election Domain and North Carolina Pilot — Design

**Date:** 2026-08-13
**Branch:** `feat/civicmirror-2.0-nc-pilot`
**External dependency:** [Civic-Data issue #4](https://github.com/CivicMirror/Civic-Data/issues/4)

## Summary

CivicMirror 2.0 replaces the legacy election model with normalized, reusable
entities and makes North Carolina the first complete state implementation. The
domain separates permanent civic structures from election-specific activity:

```text
Jurisdiction <- Office <- Contest -> Election
                         |    |
                         |    +-> ContestResult -> ResultChoice
                         |                          | optional match
                         v                          |
                    Candidacy <--------------------+
                         |
                         v
                       Person
```

North Carolina supplies the pilot sources, mappings, fixtures, and end-to-end
verification. State-specific code parses and interprets official sources. Shared
services own persistence, idempotency, identity review, reconciliation, privacy,
and result lifecycle behavior so later states can reuse the framework regardless
of whether their sources are APIs, HTML, CSV, spreadsheets, PDFs, or archives.

The pilot is isolated from production, uses a fresh database, and targets Python
3.13 consistently across development, containers, and CI.

## Goals

- Normalize elections, jurisdictions, offices, contests, people, candidacies,
  results, and officeholding roles.
- Discover NC elections and candidates before election day without relying on
  the ENRS results directory.
- Cover all people-based contests in the NC candidate filing source, including
  statewide, congressional, legislative, judicial, county, and municipal races.
- Treat party primaries as separate contests.
- Use post-election NC results as both result input and reconciliation evidence.
- Preserve source provenance and successive source versions.
- Make identity uncertainty explicit and subject ambiguous links to human review.
- Protect personal candidate filing contact information.
- Establish reusable state-source contracts and shared ingestion services.
- Provide a read-only Civic-Data comparison flow that can suggest, but never
  impose, identity links.
- Create a reproducible Python 3.13 development and verification environment.

## Non-goals

- Ballot questions, referenda, bonds, amendments, initiatives, or other measures.
- Automatic interpretation of candidate withdrawals or disappearance from a
  later filing source.
- Automatic person merging based on names or contact information.
- Publishing personal filing addresses, phone numbers, or email addresses.
- Storing precinct-level or raw vote data in Civic-Data.
- Automatically writing to Civic-Data or submitting Civic-Data pull requests.
- Migrating the current production database during the NC pilot.
- Porting every existing state adapter in the first 2.0 implementation.
- Authorizing a production release merely because the NC pilot succeeds.

## Source assessment

### Pre-election sources

The primary NC sources are:

- NCSBE upcoming elections:
  `https://www.ncsbe.gov/voting/upcoming-election`
- NCSBE candidate lists page:
  `https://www.ncsbe.gov/results-data/candidate-lists`
- 2026 candidate filing CSV:
  `https://s3.amazonaws.com/dl.ncsbe.gov/Elections/2026/Candidate%20Filing/Candidate_Listing_2026.csv`
- Candidate listing layout:
  `https://s3.amazonaws.com/dl.ncsbe.gov/Elections/layout_candidate_listing.txt`

The upcoming-election page supplies the public election name and date. The
candidate CSV supplies election dates, contests, candidate names, ballot names,
party information, filing metadata, contact evidence, `is_unexpired`,
`has_primary`, `is_partisan`, `vote_for`, and term information.

The CSV can contain multiple election dates. Each row must be associated with the
election identified by its own `election_dt`; the file must not be treated as a
single general-election roster.

### Post-election source

The ENRS S3 listing is:

```text
https://s3.amazonaws.com/dl.ncsbe.gov?list-type=2&prefix=ENRS/&delimiter=/&max-keys=1000
```

Date directories can expose result archives such as:

```text
https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2026_03_03/results_pct_20260303.zip
```

ENRS directory creation before election day is not guaranteed. It is therefore
not a pre-election discovery dependency. After an election, its result archive is
the primary results input when available and provides an independent comparison
against the pre-election contest and candidacy dataset.

The existence of a ZIP does not by itself establish that results are official or
certified.

## Normalized domain model

All core entities use UUID database primary keys and expose separate stable public
identifiers. Public identifiers are deterministic where the source data supports
that safely; names alone are never person identifiers.

### Jurisdiction

A stable geographic or governmental division.

Core fields include:

- UUID primary key
- Stable public identifier, preferably an OCD division identifier where available
- Name and classification
- State
- Optional parent jurisdiction
- Active dates where meaningful
- Source provenance

Examples include North Carolina, Congressional District 9, a county, a judicial
district, or a municipality.

### Office

A permanent civic position within a jurisdiction, independent of a particular
election.

Core fields include:

- UUID primary key
- Stable public identifier, such as `nc-9/us-representative`
- Jurisdiction
- Canonical name and role
- Default term length where known
- Number of positions where it is a stable office property
- Source provenance

Election-specific values such as the number voters may select, partisan ballot
scope, and whether a contest fills an unexpired term belong on `Contest`.

### Election

An election event on a date.

Core fields include:

- UUID primary key
- Stable public identifier, such as `nc/2026-11-03/general`
- Public name
- Date
- Type
- Lifecycle status
- Source provenance

An election inferred from candidate filings but absent from the upcoming-election
page may be provisional and must produce a review warning rather than a fabricated
official name.

### Contest

One office contested within one election.

Core fields include:

- UUID primary key
- Stable public identifier
- Election and Office
- Optional primary party scope
- `vote_for`
- Partisan flag
- Unexpired-term flag
- Lifecycle and result status
- Source provenance

Party primaries are separate contests that may reference the same Office:

```text
nc/2026-03-03/primary/democratic/us-senate
nc/2026-03-03/primary/republican/us-senate
nc/2026-11-03/general/us-senate
```

`party_contest` identifies primary ballot scope. `party_candidate` identifies the
candidate's affiliation and cannot alone determine contest identity.

### Person

A human identity independent of candidacy or officeholding.

Core fields include:

- UUID primary key
- Canonical and structured name fields
- Identity state: `provisional`, `resolved`, `disputed`, or `merged`
- Redirect target for merged records
- Source provenance and audit timestamps

A provisional Person may participate in candidacies and results. Identity
uncertainty must not block election ingestion.

### PersonIdentifier

A namespaced identifier attached to a Person.

Core fields include:

- Person
- Scheme, such as `civic-data`, `civicpatch`, or an official source scheme
- Identifier
- Verification method
- Reviewer and verification timestamp where human-approved

The pair `(scheme, identifier)` is globally unique. Adding a cross-project
identifier records an identity decision; it does not synchronize every field.

### PersonSourceRecord

An immutable or append-only projection of what a source said about a possible
person at a point in time.

It preserves:

- Source artifact and source row key
- Names and ballot name as reported
- Associated filing and contest data
- Protected address, phone, and email evidence
- Parser version and retrieval context
- Current Person association, if resolved

Source evidence remains available when people move, change contact details, or
use different name forms. Review may change a Person's canonical name or merge a
provisional Person into another Person, but it never overwrites the names or
ballot labels preserved in the source record.

### Candidacy

The relationship between a Person and a Contest.

Core fields include:

- Person and Contest
- Ballot name
- Candidate party
- Filing date
- Optional candidacy status
- Source records and provenance

The initial NC implementation is additive. A candidate missing from a later source
is not automatically withdrawn or deleted.

### ContestResult and ResultChoice

`ContestResult` records the current contest-level result projection and its source
status. `ResultChoice` records every aggregated choice reported for the Contest,
including choices that cannot yet, or can never, resolve to a Candidacy. Core
`ResultChoice` fields include:

- Source label and normalized label
- Choice type: `candidate`, `named_write_in`, or `write_in_aggregate`
- Resolution status: `matched`, `provisional`, `ambiguous`, `unresolved`, or
  `not_applicable`
- Nullable Candidacy
- Vote total, percentage, and supported winner flag
- Source artifact and source-choice provenance

A matched candidate choice links to a Candidacy and is that candidacy's current
result projection. An unresolved named write-in retains the reported name but may
have no Person or Candidacy until review. An aggregate choice such as
`Write-In (Miscellaneous)` never creates a Person or Candidacy, but its votes are
retained so contest totals, percentages, and reconciliation remain accurate.

Database constraints require a `matched` choice to reference a Candidacy and a
`write_in_aggregate` choice to leave Candidacy null. Source artifacts retain the
precinct observations, prior result versions, and corrections from which the
current aggregated projection was produced.

Supported result states are:

- `pending`
- `unofficial`
- `official`
- `certified`
- `corrected`

A winner is not exported to Civic-Data until the required official or certified
threshold is supported by explicit source evidence. Unresolved choices and
aggregate write-in choices are never exported as Civic-Data People or candidacies.

### OfficeTerm

An approved relationship between a Person and an Office over time.

Core fields include start and end dates, method of selection, role, and source.
Election victory may support later OfficeTerm creation, but a raw winner flag does
not silently create a current officeholder without the required lifecycle evidence.

### SourceArtifact

Every downloaded source is registered with:

- URL and source type
- Retrieval and source timestamps
- Content checksum
- Parser version
- Election date context
- Processing status and errors

An unchanged checksum is idempotent. Changed official content creates a new
artifact version and triggers reconciliation.

### IdentityReviewCase

A persistent, auditable decision record for uncertain identities. It contains the
source record, provisional Person, suggested matches, supporting and conflicting
evidence, private-evidence flags, Civic-Data candidates, review status, resolution,
reviewer, notes, and timestamps.

Review states are `open`, `approved`, `rejected`, `deferred`, and `superseded`.
Resolution actions are `link_existing`, `confirm_new`, `merge_people`,
`link_civic_data`, and `defer`.

Rejected comparisons are retained so unchanged evidence does not repeatedly create
the same review case.

## Reusable ingestion architecture

The framework has four boundaries:

```text
State source capability
        |
        v
Normalized contract records
        |
        v
Shared ingestion and reconciliation services
        |
        v
CivicMirror 2.0 entities
```

Shared contracts include records for discovered elections, contests, candidates,
precinct result observations, aggregated result choices, and certification
evidence. Shared services own:

- Source acquisition, checksums, and versioning
- Validation and transactional batch application
- Jurisdiction, Office, Election, Contest, Person, and Candidacy upserts
- Identity suggestions and review-case creation
- Measure filtering with state extensions
- Deterministic source keys and idempotency
- Result reconciliation and lifecycle handling
- Sync reports, retries, and error behavior

State-specific code owns:

- Source URLs, authentication, and transport details
- HTML, API, CSV, spreadsheet, PDF, ZIP, or other parsing
- Source-field interpretation
- State-specific jurisdiction and office mapping
- Evidence used to determine official or certified status

States implement independent capabilities rather than one oversized adapter:

```python
class ElectionDiscoverySource: ...
class CandidateSource: ...
class ResultsSource: ...
class CertificationSource: ...
```

A capability may have explicit primary and fallback sources. A missing capability
is reported as unsupported and never silently substituted with an unrelated source.

## Proposed package boundaries

```text
backend/elections/
  models/
  services/
    elections.py
    contests.py
    people.py
    identity.py
    reconciliation.py

backend/integrations/
  contracts/
    elections.py
    candidacies.py
    results.py
    certification.py
  framework/
    artifacts.py
    orchestration.py
    reporting.py
  nc_sbe/
    sources/
      upcoming_elections.py
      candidate_filings.py
      enrs_results.py
    mapping/
      jurisdictions.py
      offices.py
      contests.py
    tasks.py

backend/results/
  models/
  services/
```

The legacy NC results implementation is retired after its source behavior and
fixtures move into the NC results capability. State code does not write directly
to domain models.

## NC pre-election workflow

Each candidate CSV row flows through:

```text
Candidate filing row
  -> identify Election
  -> exclude non-person contest
  -> resolve Jurisdiction
  -> resolve Office
  -> resolve or create Contest
  -> create PersonSourceRecord
  -> resolve or provision Person
  -> create or update Candidacy
```

The candidate file can repeat the same contest and candidate across counties.
Parsing therefore preserves every source row, then deduplicates normalized filing
records by election, resolved contest identity, party scope, jurisdiction, and
source-row lineage before creating domain entities. People are never deduplicated
globally by name alone.

The upcoming-election page is primary for public election names and dates. The CSV
is a secondary election-date signal. A CSV-only election creates a review warning
and may create a provisional Election when its contests are usable.

An NC row for `US HOUSE OF REPRESENTATIVES DISTRICT 09` maps to a congressional
district Jurisdiction, a permanent US Representative Office, an election-specific
Contest, a Person or provisional Person, and a Candidacy.

NC fields map as follows:

- `party_contest`: primary ballot party scope
- `party_candidate`: candidate affiliation
- `is_unexpired`: Contest unexpired-term flag
- `has_primary`: source evidence about primary availability
- `is_partisan`: Contest partisan flag
- `vote_for`: number selectable in the Contest
- `term`: source evidence for the Office term or contest-specific override

Measure exclusion is word-aware and applies only to the normalized contest name.
The initial term set includes referendum/referenda, bond/bonds, amendment, measure,
proposition, question, initiative, levy, ordinance, and resolution. It must not
filter a candidate because their personal name contains one of these words.

## NC post-election workflow

After the election, CivicMirror locates the applicable `results_pct_YYYYMMDD.zip`,
registers and validates the artifact, and parses its precinct-level TSV. Before
updating the current result projection, CivicMirror:

1. Excludes measure contests using the same contest-name filter as pre-election
   ingestion.
2. Normalizes contest and choice labels while preserving the exact source labels.
3. Groups precinct observations by resolved contest identity and source choice,
   then sums `Total Votes` once to produce aggregate choice totals.
4. Matches result contests to existing normalized Contests.
5. Creates provisional Jurisdiction, Office, and Contest records for a usable
   people-based result contest absent from all pre-election artifacts, and creates
   a reconciliation review case for the mapping.
6. Matches ordinary candidate choices to Candidacies. A deterministic prior
   association may link automatically; fuzzy spelling matches remain unresolved
   and produce review cases without blocking the batch.
7. Creates a provisional Person and Candidacy for an unmatched ordinary named
   candidate when no plausible existing identity or candidacy is found.
8. Stores named write-ins as unresolved `ResultChoice` records using their reported
   names and without requiring a Person or Candidacy.
9. Stores `Write-In (Miscellaneous)` and equivalent anonymous write-in buckets as
   `write_in_aggregate` choices without creating People or Candidacies. These
   choices remain in vote totals and percentage denominators.
10. Stores vote totals, percentages, supported winner indicators, and explicit
    result-status evidence.
11. Reports pre-election Contests absent from results, result-only Contests,
    unmatched or ambiguous choices, and vote or percentage inconsistencies.

For example, a result-only `TOWN OF HARRELLSVILLE MAYOR` record creates a
provisional Contest within the applicable Election rather than silently creating a
separate Election for the same date. Its named write-ins remain unresolved choices
until review, while its aggregate write-in bucket remains a non-person result
choice. Review confirms the Jurisdiction and Office mapping and can identify an
additional pre-election source for future runs.

A missing archive leaves results pending. It does not delete the Election,
Contest, Person, or Candidacy. Corrections create new artifacts and update the
current projection without discarding history. Unresolved result choices do not
block creation or updating of the Election, its other Contests, or its resolved
results.

## Identity resolution and human review

Automatic linking is limited to deterministic, previously established evidence:

- The source record is already linked to a Person.
- A stable source identifier was previously approved for the Person.
- A Civic-Data identifier is already attached to the local Person.
- A merged-Person redirect is already established.

Names, contact fields, addresses, party, jurisdiction, and office history may rank
suggestions but never authorize a merge by themselves. Contradictory evidence is
shown alongside supporting evidence.

When candidate ingestion has no deterministic Person association, it creates a
provisional Person and Candidacy using the recorded ballot name. Exact or fuzzy
comparisons against existing People become review suggestions; a likely spelling
variant such as `DeDreana` versus `Dedreana` does not stop election ingestion or
silently merge the records. A reviewer may approve a link or merge and update the
Person's canonical name, while the Candidacy ballot name and every source-reported
spelling remain unchanged as provenance.

The initial interface is Django Admin. Authorized reviewers need prioritized cases,
side-by-side comparisons, protected evidence, Civic-Data suggestions, merge/link
actions, filters, and a complete audit trail. `SyncLog` receives aggregate counts
only and never private evidence. Specific result-only contests, fuzzy candidate
matches, and unresolved named choices live in persistent review cases and the
reconciliation report; `SyncLog` records counts and the associated ingestion run.

## Privacy and export rules

Personal filing addresses, phone numbers, and email addresses remain protected
inside CivicMirror. They are used only for ingestion, matching, auditing, and
authorized review. They are prohibited from public serializers, logs, URLs,
Civic-Data exports, GitHub issues, and pull-request evidence.

The Civic-Data contract distinguishes:

- Personal filing contact data: never export.
- Verified public office contact data: potentially export as office information.
- Verified campaign-headquarters contact data: potentially export if the final
  Civic-Data schema permits it.

A filing field is not reclassified as public office or campaign information merely
because NCSBE published it.

## Civic-Data contract

Civic-Data issue #4 owns the cross-repository schema work. Its proposed changes are:

- Replace `Official` with `Person`.
- Add `candidacies[]` and `roles[]`.
- Permit a Person to be a candidate, officeholder, or both.
- Store one Civic-Data `id` plus extensible namespaced identifiers for CivicMirror,
  CivicPatch, and future systems.
- Represent pre-election Contests with candidates and no winner.
- Add official or certified winner references later without storing raw results.
- Represent party primaries as separate Contests.
- Validate reciprocal Person-to-Contest candidacy references.
- Reject private candidate filing contact fields.
- Require reviewed identity links and merges.

The access boundary is:

```text
CivicMirror --reviewed PR proposal--> Civic-Data
CivicPatch  --reviewed PR proposal--> Civic-Data

CivicMirror <--read-only snapshot-- Civic-Data
CivicPatch  <--read-only snapshot-- Civic-Data
```

Neither consumer may automatically replace local names, contact information,
roles, candidacies, or identity decisions from Civic-Data. CivicMirror proposes
only reviewed, resolved People and candidacies; unresolved named choices and
aggregate write-in choices are never treated as Civic-Data identities.

## Read-only Civic-Data comparison

A scheduled workflow fetches and validates a pinned Civic-Data revision and builds
a local comparison index. It may recognize an existing approved identifier, suggest
possible matches, add evidence to an open review case, and report identifier
conflicts.

It may not modify local domain fields, merge People, accept a suggestion, import
contact information, or treat Civic-Data as an election-results source. New inferred
links require human approval. Existing exact CivicMirror identifiers are recognized
as previously approved links.

After approval, CivicMirror records the Civic-Data identifier with reviewer and
verification metadata. A reciprocal Civic-Data identifier is added only through a
separately reviewed pull request.

## Python 3.13 environment

Python 3.13 is an enforced project property. The repository will provide:

- A root version declaration for environment managers
- Package metadata requiring `>=3.13,<3.14`
- Python 3.13 development and production container targets
- Python 3.13 CI jobs
- An early version assertion with a clear unsupported-interpreter error

Supported development paths are a repository-managed Python 3.13 virtual
environment and the Python 3.13 development container. Commands must not silently
mix host Python 3.14, system packages, user packages, or partially activated Python
3.13 environments.

The development Compose configuration adds a non-root API/test service with runtime
and development requirements, source mounting, Postgres and Redis connections, and
a health check. Postgres and Redis are reachable only by services on the isolated
Compose network and are not published on host ports. The development API is
published on a main-stack-audited, configurable host port and listens on all host
interfaces so it is reachable from the local LAN. Django limits accepted hosts to
localhost, loopback, and the configurable development LAN address. The production
image excludes development tooling.

One container-backed verification command runs, in order:

```text
Python version assertion
Django system checks
Migration consistency check
Ruff
Pytest
```

Local containers and CI install from the same dependency inputs. Normal tests do
not require production credentials, live NCSBE access, live Civic-Data access, host
packages, or pre-existing database contents. Live source-contract tests are
separate and opt-in.

## Isolation and migration policy

The pilot remains on `feat/civicmirror-2.0-nc-pilot` with an explicitly named
development database, Docker volume, and task queues. Production credentials,
deployment workflows, databases, queues, and services are outside its scope.

The normalized domain replaces, rather than aliases, legacy concepts:

```text
Legacy                     CivicMirror 2.0
Election                   Election
Race                       Contest
Candidate                  Person + Candidacy
embedded jurisdiction      Jurisdiction
embedded office fields     Office
OfficialResult             ContestResult + ResultChoice
```

Historical migrations may remain during development. Before a 2.0 release, domain
migrations may be consolidated so a fresh installation does not retain obsolete
tables. Production data conversion requires a later, separately approved plan.

Only NC is registered as an enabled 2.0 state during the pilot. Legacy state tasks
must not write into the 2.0 database. Other states are enabled only after supplying
capabilities, fixtures, mappings, idempotency tests, privacy tests, and explicit
unsupported-capability declarations.

## Orchestration and failure behavior

The versioned task flow is:

```text
Acquire artifacts
  -> parse normalized records
  -> aggregate source observations where required
  -> validate the complete batch
  -> apply one database transaction
  -> reconcile prior state
  -> write SyncLog and review cases
```

A parser or validation failure prevents partial application of that source batch.
Retries reuse artifact and idempotency keys. Scheduled NC runs remain disabled until
fixture tests and manual isolated runs pass.

Public API serializers and routes are explicitly versioned and distinguish Person
from Candidacy, Office from Contest, current projections from source history,
provisional from resolved identities, matched from unresolved result choices, and
result lifecycle states. Protected source evidence is never public. Public output
never represents an unresolved or aggregate write-in choice as a Person.

## Verification fixtures and reports

A frozen 2026 NC fixture set includes representative versions of:

- The upcoming-election page
- Candidate listing CSV
- Candidate listing layout documentation
- ENRS directory response
- Results archive or extracted results
- Expected normalization manifest

Committed fixtures must remove or replace sensitive contact values while retaining
the structure needed for privacy and matching tests.

The expected manifest records counts and exact representative examples for
Elections, Jurisdictions, Offices, primary and general Contests, People,
Candidacies, excluded measures, aggregated Results, matched and unresolved
`ResultChoice` records, named write-ins, aggregate write-in buckets, result-only
Contests, unmatched records, and identity-review cases.

Each ingestion run writes a persistent reconciliation report containing:

- Elections discovered
- Entities created, updated, or excluded
- Provisional People and review cases
- Pre-election Contests absent from results
- Results absent from the pre-election dataset
- Provisional result-only Jurisdictions, Offices, and Contests
- Unmatched, ambiguous, and unresolved result choices
- Named and aggregate write-in choice counts
- Vote or percentage inconsistencies
- Artifact changes
- Result and certification status changes

Detailed record identities and review evidence remain in the reconciliation report
and review cases. `SyncLog` receives aggregate counts such as result-only Contests,
ambiguous matches, unresolved named choices, and aggregate write-in choices.

## Implementation phases

1. **Reproducible foundation:** Python 3.13 enforcement, development/test container,
   isolated database, and canonical verification command.
2. **Normalized domain:** models, constraints, identifiers, source records, Admin,
   serializers, and empty-database migrations.
3. **Reusable ingestion framework:** contracts, artifacts, shared persistence,
   reconciliation, reports, and capability registry.
4. **NC pre-election pilot:** upcoming-election discovery, candidate CSV ingestion,
   full people-based contest normalization, and measure exclusion.
5. **Identity review:** evidence, review cases, lifecycle states, Admin actions,
   audit trail, and privacy enforcement.
6. **NC results verification:** ENRS precinct aggregation, result-only provisional
   entities, matched and unresolved result choices, reconciliation, corrections,
   and explicit status evidence.
7. **Civic-Data comparison:** pinned read-only snapshot, suggestions, approved local
   identifiers, and proposal preparation without automatic submission.

## Acceptance criteria

The NC pilot is complete when:

- A fresh isolated database builds and verifies under Python 3.13.
- Repeating any source ingestion creates no duplicate entities.
- The pre-election workflow does not depend on ENRS directory availability.
- Primary and general contests remain distinct.
- All supported levels of people-based NC contests normalize through shared
  services.
- Measure contests are excluded by contest-name rules without candidate-name false
  positives.
- Provisional People do not block candidacy or result ingestion.
- Ambiguous identities create auditable review cases and no automatic merges.
- Approved merges and identifier links preserve redirects and audit history.
- A fuzzy source spelling such as `DeDreana` versus `Dedreana` preserves both
  source labels, remains reviewable, and does not block the remaining batch.
- Personal filing contact information is absent from public output and logs.
- Precinct result observations aggregate exactly once into the expected contest and
  choice totals before the current result projection is applied.
- Named write-ins may remain unresolved without a Person or Candidacy and retain
  their reported names for review.
- Aggregate write-in buckets create no Person or Candidacy but remain included in
  contest totals, percentages, and reconciliation.
- A usable people-based result Contest absent from pre-election artifacts creates
  provisional Jurisdiction, Office, and Contest records plus an auditable review
  case without creating a duplicate same-date Election.
- Results reconcile against the pre-election dataset and expose mismatches.
- Missing results remain pending and do not remove pre-election entities.
- Official or certified status requires explicit evidence.
- Civic-Data consumption is read-only and cannot mutate CivicMirror domain fields.
- Unit, model, service, fixture integration, privacy, migration, and reconciliation
  tests pass without normal-suite network access.
- No production service, database, queue, credential, or Civic-Data branch is
  modified.

## Release and rollback boundaries

The isolated pilot can be rebuilt by stopping its development services, preserving
failed artifacts and reports, rebuilding only the explicitly named 2.0 database,
and replaying artifacts. Existing production or shared development databases are
never reset as part of this process.

NC pilot completion does not authorize production release. Production requires a
separate approved design covering existing-data conversion, API consumers, all
remaining state adapters, scheduler cutover, backup and rollback, deployment
monitoring, and historical-data validation.

## Alternatives considered

### Expand the existing NC adapters in place

Rejected because it would continue embedding persistence and matching behavior in
state code and would not establish a reusable model for states with different
source formats.

### Preserve Race and Candidate as compatibility aliases

Rejected for the pilot because `Candidate` conflates a human with participation in
a particular Contest, and `Race` obscures the intended cross-repository terminology.
Compatibility work, if needed for production consumers, belongs in the later
production migration plan rather than the clean domain.

### Automatically merge strong identity matches

Rejected because contact information changes, names collide, and erroneous merges
are more damaging than temporary provisional duplicates. Match scoring prioritizes
human review instead.

### Use Civic-Data as a synchronization authority

Rejected because CivicMirror, CivicPatch, and Civic-Data have distinct ownership
and review responsibilities. Civic-Data can provide canonical linkage evidence but
cannot overwrite local records.
