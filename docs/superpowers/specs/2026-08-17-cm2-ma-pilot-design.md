# CivicMirror 2.0 — Massachusetts Pilot — Design

**Date:** 2026-08-17
**Branch:** `feat/civicmirror-2.0-nc-pilot`
**Prior art:** [`2026-08-13-civicmirror-2.0-nc-pilot-design.md`](2026-08-13-civicmirror-2.0-nc-pilot-design.md), [issue #192](https://github.com/CivicMirror/CivicMirror-API/issues/192) (tracking), [issue #194](https://github.com/CivicMirror/CivicMirror-API/issues/194) (Incapsula block)

## Summary

Massachusetts becomes the second `cm2_*` state adapter, following the NC pilot's
shared framework (`cm2_ingestion` contracts, `cm2_core`/`cm2_elections`/`cm2_review`
models, identity-review workflow). MA differs from NC in two structural ways that
shape this design:

1. **The Secretary of the Commonwealth's HTML pages (`sec.state.ma.us`) are
   Incapsula-blocked.** A nodriver+Xvfb stealth-browser microservice — the
   existing `cloudflare/cf-solver/` production service, already used by CM1's
   `oh_sos`/`ny_boe`/`mi_sos` adapters for Cloudflare — was verified live
   (2026-08-17) to bypass Incapsula with no code changes beyond a longer
   `wait_seconds`. See [Solver verification](#solver-verification).
2. **MA has no single source that covers election dates, candidates, offices,
   and results the way NC's upcoming-election page + candidate CSV + results
   ZIP do.** The pilot instead composes three independent official sources,
   each playing to its strength:

```text
Secretary of the Commonwealth (sec.state.ma.us, via solver)
    -> Election dates/calendar (regular + special)
    -> Ballot-qualification confirmation (who is actually on which contest)

OCPF (api-adjacent bulk files, ocpf2.blob.core.windows.net, plain HTTP)
    -> Person identity (stable CPF ID) + canonical Office/Jurisdiction
       reference data (district-code table)

ElectionStats (electionstats.state.ma.us, plain HTTP, already used by CM1)
    -> Post-election results, resolved through the same OCPF district-code
       identity scheme so results attach to the contest that already carries
       its candidates
```

The pilot targets state/federal/legislative/judicial/county-row contests only.
Municipal offices remain out of scope (351 decentralized municipalities, no
statewide manifest — consistent with the standing project-wide position on
county/city elections).

## Goals

- Create MA `Election` records for the regular state primary/general cycle and
  for special elections, from official Secretary calendar pages.
- Resolve `Office`/`Jurisdiction` identity from OCPF's coded district reference
  table rather than free-text parsing, so the same identity is reachable from
  both the pre-election and post-election paths.
- Anchor `Person` identity to OCPF's stable `CPF ID` wherever a confident match
  exists, reducing the review-queue churn NC saw from purely name-based
  provisional-person creation.
- Use the Secretary's candidate-list pages as the ballot-qualification source
  of truth: an OCPF-identified person only becomes a `Candidacy` once the
  Secretary confirms them on a specific contest.
- Cover regular state primary/general candidates (statewide, congressional,
  legislative, judicial-adjacent county row offices) and special-election
  candidates.
- Attach post-election results from ElectionStats to the same contests created
  pre-election, without creating duplicate result-only contests due to
  identity drift between sources.
- Reuse the existing `cm2_ingestion` contracts, persistence layer, and
  identity-review workflow unmodified.
- Keep the shared `cf-solver` microservice's production behavior for existing
  Cloudflare callers (OH, NY, MI) unchanged.

## Non-goals

- Municipal election/candidate coverage (mayor, city council, select board,
  school committee, etc.) — decentralized across 351 municipalities, no
  statewide manifest. Tracked as a standing future initiative, not part of
  this pilot.
- Ballot questions / constitutional amendments / other measures.
- OCPF campaign-finance enrichment beyond identity + office/district reference
  data (committee financials, incumbent-status tagging, photos) — deferred to
  a later enrichment pass, same role it plays in CM1 today.
- The Secretary's general-election candidate page, which does not exist yet as
  of this writing (2026 list not published). The batch/contract layer is
  shaped so adding it later is a new source class, not a redesign — but its
  row format is not implemented against real markup in this pilot.
- Building a general-purpose multi-vendor challenge-solving abstraction.
  `cf-solver`'s challenge-title guard was generalized additively; no broader
  rework of `cm2_ingestion.capabilities.StateCapabilities` was undertaken,
  since nothing calls that registry yet for any state.
- Migrating CM1's production `ma_sos` integration or its Celery tasks.
- Scheduling/triggering (Celery beat, cron, management command) for either NC
  or MA — neither pilot has this wired up yet; out of scope here.

## Solver verification

`sec.state.ma.us` (Incapsula) was confirmed reachable via the existing
`cloudflare/cf-solver/` service on 2026-08-17, using a locally built copy of
the production image (`docker build` from `cloudflare/cf-solver/`, unmodified
`app.py` at the time of the initial probe):

| URL | Result |
|---|---|
| `.../research-and-statistics/candidates2026.htm` | Real page (`title="2026 Candidates"`), links to Dem/Rep primary pages |
| `.../research-and-statistics/dem-state-primary-candidates2026.htm` | 66KB real HTML, full office/district/candidate hierarchy |
| `.../recent-updates/upcoming-elections.htm` | Real page, Sept 1 primary + Nov 3 general dates, office lists, deadlines |
| `.../recent-updates/special-elections.htm` | Real page, live special (6th Essex Representative District), links to per-election Calendar/Candidates/Results pages |

`navigator.webdriver` was undetected in all cases; no Incapsula challenge stub
was returned. `wait_seconds=25` (vs. Cloudflare callers' typical ~15s) was
sufficient.

### Shared solver generalization

Rather than build a separate MA-only solver service, `cloudflare/cf-solver/`
was generalized **additively**, since it is a standalone microservice (own
Docker container, no Django app, no shared tables) already proven
vendor-agnostic in its core mechanics — nothing in the nodriver/Xvfb/Chrome
launch logic was Cloudflare-specific to begin with:

- Docstring updated to note the service is not CF-specific and has been
  verified against Incapsula.
- The single hardcoded `"just a moment"` unsolved-challenge check became an
  extensible `_UNSOLVED_CHALLENGE_TITLE_MARKERS` tuple. No Incapsula-specific
  marker was added — Incapsula was not observed to render a distinct
  challenge title (it either resolves to the real title or serves an empty
  JS-stub body), so there is nothing confirmed to add yet.
- **No renames.** The container name (`civicmirror-cf-solver`), directory
  (`cloudflare/cf-solver/`), env vars (`CF_SOLVER_URL`, `CF_SOLVER_SECRET`),
  and the Django-side `core/cf_solver.py` client class (`CfSolverClient`) were
  left untouched, since they are wired into the live production
  `docker-compose.yml` (`/data/DockerConfigs/CivicMirror/`) and used today by
  `oh_sos`, `ny_boe`, and `mi_sos`. Renaming would have required coordinated
  deploy-config changes for zero functional benefit.
- Re-verified against MA after the change (identical result). Could not run
  the CM1 `oh_sos`/`ny_boe`/`mi_sos` test suites locally to confirm zero
  behavior change for CF callers — blocked by a pre-existing, unrelated
  environment issue (repo `.venv` is Python 3.14; project requires
  `>=3.13,<3.14`). Since `core/cf_solver.py` (what those tests exercise) was
  not touched at all, and the only changed file (`app.py`) runs in its own
  container outside that Python environment, this is a low-risk gap, not a
  blocker — but it should be closed out with a real test run before this
  lands in a state where CM1 production could be affected.

## Source assessment

### Election dates — Secretary of the Commonwealth (via solver)

- `https://www.sec.state.ma.us/divisions/elections/recent-updates/upcoming-elections.htm`
  — regular statewide cycle. Markup is one `<h2>` per event
  (`"September 1, 2026 – State Primaries"`) followed by sibling `<p>`/`<ul>`
  content (district, offices-on-ballot, deadlines) until the next `<h2>` —
  structurally close enough to NC's upcoming-election page to adapt its
  heading/date-extraction parser directly, with two changes: (a) the
  heading-must-contain-"election" filter is replaced with a MA label→type
  lookup (`"state primaries"` → `primary`, `"state election"` → `general`,
  etc.), since "State Primaries" doesn't contain the word "election"; (b) the
  offices-on-ballot `<ul>` is carried as a cross-check signal (raise an
  `IngestionNotice` on mismatch against what the candidate pages produce), not
  as authoritative office data.
- `https://www.sec.state.ma.us/divisions/elections/recent-updates/special-elections.htm`
  — a hub page, not a flat list. One entry per active special
  (e.g. "5 - 6th Essex Representative District"), linking to that special's
  own calendar page (`current-special-electionN.htm`), which carries the
  actual primary/general dates, vacancy reason, and constituent
  municipalities. Discovery is therefore a two-hop crawl: parse the index for
  calendar-page links, then fetch+parse each linked calendar page. Each hop
  goes through the solver.

### Offices, jurisdictions, and candidate identity — OCPF (plain HTTP)

Verified live (2026-08-17), no solver needed — plain Azure blob storage:

- `https://ocpf2.blob.core.windows.net/downloads/data2/district_code_list.zip`
  → `district_code_list.txt`, 714 rows, tab-delimited
  (`District_Code | Office_Type_Description | District_Description`). A
  stable, coded reference table covering Senate, House, Governor's Council,
  District Attorney, Sheriff, Register of Probate/Deeds, County Commissioner,
  Clerk of Courts, Statewide, and (unused in this pilot) Mayoral/City
  Councilor/Municipal.
- `https://ocpf2.blob.core.windows.net/downloads/data2/ocpf-filers-excel.zip`
  → `filer-spreadsheet.xlsx`, **"All Candidates"** sheet, 6,802 rows:
  `CPF ID, Candidate First/Last Name, Street/City/State/Zip, Organization
  Date, District Code Sought, Office Type Sought, District Name Sought,
  Closed Date, Party Affiliation`. Names and addresses are already
  structured (no NC-CSV-style comma-parsing risk). `District Code Sought`
  joins directly into `district_code_list.txt` (confirmed: code `231` →
  `House / 9th Essex`; code `1114` → `Statewide / Auditor`). Regenerated
  nightly at 3:30am per the source; the file fetched during this session was
  timestamped `2026-08-17 03:32:32`, confirming the cadence.
- `https://ocpf2.blob.core.windows.net/downloads/ocpf_data_dictionary.pdf` —
  field reference.

`Closed Date` empty does **not** mean "running in 2026" — it means "this
committee hasn't been formally closed," which includes standing committees
for sitting officeholders and old committees from candidates who lost and
never closed up (3,752 of 6,802 rows have no `Closed Date`, spanning
apparently many cycles). `Closed Date`-filtering narrows OCPF's full
historical set to a "plausibly active" pool for the current sync, but cannot
by itself determine which cycle or which specific contest a person is running
in — that determination is made by the Secretary confirmation step below.
Initial ingestion takes the full historical set (open and closed) for
identity continuity, per the recommendation that produced this file discovery.

### Candidate ballot confirmation — Secretary candidate-list pages (via solver)

- `https://www.sec.state.ma.us/divisions/elections/research-and-statistics/candidates2026.htm`
  links to party-specific pages:
  `dem-state-primary-candidates2026.htm`, `rep-state-primary-candidates2026.htm`.
- Confirmed markup (from the live solver probe): a clean `<h2>` (office) /
  `<h3>` (district, where applicable) / `<p>` (candidate row) hierarchy, e.g.:

```html
<h2 id="DA">District Attorney</h2>
<h3>Norfolk District</h3>
<p>Jim Barakat, 280 Liberty St., Braintree</p>
<p>No Nominations</p>
```

  Unlike NC's flat CSV, MA's own page structure directly encodes office (h2)
  and district (h3) — no regex inference against a contest-name string is
  needed for the office/district split, only office-label normalization
  (`"Senator in Congress"` → U.S. Senator, `"Councillor"` → Governor's
  Councillor, `"Senator/Representative in General Court"` → State
  Senator/Representative, etc.).
- **Candidate-line parsing edge case, confirmed in live data**: names can
  contain a comma before the address starts —
  `"Joseph D. Early, Jr., 36 Blackthorn Dr., Worcester"`. A naive
  split-on-first-comma misparses this. Parsing must check whether the segment
  immediately after the first comma matches a known-suffix list (Jr./Sr./II/
  III/IV) and fold it into the name before treating the remainder as address.
  The raw line is retained as `PersonSourceEvidence.reported_name` regardless
  of split accuracy, so an imperfect split loses no data — same fallback
  posture NC's provisional-person path already has.
- `"No Nominations"` rows are not candidates. They are skipped for
  `CandidateFilingRecord` purposes but still recorded as an `IngestionNotice`
  (e.g. `no_nominations`) rather than silently dropped.
- Party is a property of the page, not the row (`dem-...`/`rep-...` are
  entirely one party each) — `party_contest` is a fixed per-source-class
  parameter, unlike NC's per-row CSV column. `party_candidate == party_contest`
  is assumed for primary-ballot candidates; this is an assumption, not a
  verified fact about MA's candidacy rules.
- The general-election candidate page does not exist yet (see Non-goals).

### Results — ElectionStats (plain HTTP, already in production use)

- `electionstats.state.ma.us` — no solver needed, and no change to CM1's
  existing acquisition pattern: `get_election_ids(year, stage)` for per-race
  discovery (returns `office`/`district`/`stage` text per row), then
  `download_election_csv(election_id)` per matched race.
- **The identity-convergence risk this pilot must design around**: NC's
  post-election path (`cm2_nc/mapping/results.py`) re-derives office/
  jurisdiction/contest identity from the results file's own contest-name text,
  using the *same* mapping functions the pre-election path uses — so the
  computed `public_id`s converge automatically, because both stages read the
  same source. MA's three-source design breaks that assumption: if
  ElectionStats' office/district text is mapped into `OfficeRecord`/
  `JurisdictionRecord` independently, the computed identity will not match
  what the OCPF/Secretary-driven pre-election path produced.
  `cm2_ingestion.results_persistence._persist_results_batch` resolves
  contests by exact `public_id` lookup with no fuzzy fallback — a mismatch
  does not error, it silently creates a duplicate "result-only" contest
  (candidates on one record, results on another).
- **Resolution**: results mapping must resolve each ElectionStats
  `(office, district)` pair through the *same* OCPF district-code-anchored
  identity scheme the pre-election path uses (Section "Offices,
  jurisdictions..." above), not build a second, independent text-parsing
  scheme. This is the one genuinely new piece of shared MA-specific code
  (a small crosswalk/normalization function), not a rewrite of the results
  pipeline shape.
- One structural difference from NC worth naming: NC gets one ZIP with every
  statewide contest in a single download; MA is N separate per-race
  downloads. More requests, but no solver contention, since none of it uses
  the solver.

## Candidate identity: OCPF as source, Secretary as confirmation

The initially-planned direction (Secretary pages as the sole candidate/person
source, OCPF as later enrichment) was revised during design review. OCPF
becomes the primary identity source instead, for two concrete reasons found
in this pilot's own source material:

1. MA's Secretary pages have no stable candidate ID (this is also called out
   as the single biggest candidate-identity weakness in the underlying state
   research). OCPF's `CPF ID` is a real stable identifier.
2. `district_code_list.txt` is a more reliable office/jurisdiction identity
   source than free-text-parsing the Secretary's `<h3>` headings, since it's
   a coded, joinable reference table rather than prose.

The resulting shape, using a contract field that already exists and required
no changes — `CandidateFilingRecord.person_public_id: str | None`:

1. Fetch OCPF's district-code table and "All Candidates" sheet (plain HTTP,
   cheap, can run on its own cadence matching OCPF's nightly 3:30am refresh).
   `Closed Date`-empty rows form the "plausibly active" matching pool for
   this cycle. **This pool is not persisted through its own contract path** —
   it exists only in memory as a matching aid for the step below, avoiding
   any need for a new ingestion contract shape.
2. Fetch the Secretary's Dem/Rep candidate pages (via solver) and build
   `CandidateFilingRecord`s as usual. For each row, attempt a match against
   the OCPF pool by name + office/district (via the district-code crosswalk).
   On a confident match, set `person_public_id =
   stable_public_id("person", "ocpf", cpf_id)` — this pre-resolves identity
   and bypasses the fuzzy-match identity-review path entirely for that
   candidate. On no match, leave `person_public_id=None` and fall through to
   the existing provisional-person-plus-review-case path NC already has
   (meaningful either way: a real candidate OCPF hasn't caught up on, or
   worth a closer look).
3. `apply_pre_election_batch` (existing, unmodified) persists the result. An
   OCPF-identified person never becomes a `Candidacy` on its own — only a
   confirmed Secretary-page match creates one, which is the actual
   ballot-qualification gate.

## Orchestration

Mirrors `cm2_nc/ingest.py`'s shape — named byte parameters per source, each
registered as its own `SourceArtifact`, same idempotency-by-checksum pattern:

```python
ingest_ma_pre_election_contents(
    *,
    upcoming_content: bytes,               # solver
    special_index_content: bytes,          # solver
    special_calendar_contents: tuple[bytes, ...],  # solver, one per active special
    dem_candidates_content: bytes,         # solver
    rep_candidates_content: bytes,         # solver
    ocpf_district_content: bytes,          # plain HTTP
    ocpf_filers_content: bytes,            # plain HTTP
    retrieved_at: datetime,
) -> ReconciliationReport

ingest_ma_post_election_contents(
    *,
    election_date: date,
    retrieved_at: datetime,
) -> ReconciliationReport
```

Module layout mirrors `cm2_nc/` directly: `cm2_ma/{constants,capabilities,
source_records,ingest}.py`, `sources/{http.py, solver.py,
upcoming_elections.py, special_elections.py, candidate_pages.py, ocpf.py,
results.py}`, `mapping/{identity,jurisdictions,offices,batch,results}.py`,
`tests/`. The one new file NC didn't need: `sources/solver.py`, wrapping
`core.cf_solver.CfSolverClient.fetch_through_cf()` for the four solver-gated
page types, parallel to `NcPublicBytesSource`'s plain `requests.get()`.

`cm2_ingestion.capabilities.StateCapabilities`'s single `acquire()`/`parse()`
Protocol (one blob in, one batch out) does not cleanly fit MA's genuinely
multi-source design. Since nothing calls that registry today for any state
(not even NC), this pilot leaves `cm2_ma/capabilities.py` as a thin
declarative stub matching NC's shape, rather than redesigning the registry
for a consumer that doesn't exist yet. Flagged as a real design question for
whenever a generic multi-state orchestrator is actually built.

### Solver load, cadence

`cloudflare/cf-solver/app.py`'s `_browser_lock` is a single global
`asyncio.Lock()` — every solve request across *all* callers (OH, NY, MI, and
now MA) is fully serialized through one Chrome instance, ~25-30s per call. MA
discovery alone is at minimum two solver calls (upcoming + special index)
plus one per active special plus two for the candidate pages — meaningfully
more load than any current CF caller adds per run. This pilot does not
attempt to solve solver concurrency/scaling; it's noted here so that whoever
wires up scheduling (an open item for the whole CM2 project, not MA-specific)
accounts for shared contention with the existing nightly OH/NY/MI jobs when
choosing MA's polling cadence. The OCPF and ElectionStats sources, by
contrast, never touch the solver and can be polled independently and more
frequently.

## Testing

Following NC's pattern: fixtures captured from live solver probes (sanitized
of any personal contact information beyond what the Secretary already
publishes — residential addresses are already public on these pages, same as
NC's candidate CSV), unit tests per mapping module (`jurisdictions`,
`offices`, `identity`, `batch`, `results`), and an end-to-end fixture-driven
ingestion test mirroring `cm2_nc/tests/test_ingest.py`. The OCPF↔Secretary
identity-matching step and the results district-code crosswalk are the two
pieces of genuinely new logic (not adapted from NC) and need dedicated
matching-precision test coverage: confident match, no match, and ambiguous
match (multiple OCPF candidates with the same name in the same office pool).

## Open items

1. General-election candidate page — implement once the Secretary publishes
   it and its real markup can be inspected.
2. OCPF committee-financial enrichment (beyond identity + district reference)
   — deferred, same role it plays in CM1 today.
3. Confirm the `cf-solver` generalization against a real CM1 test run once
   the Python-version environment issue is resolved (tracked separately from
   this design).
4. Scheduling/triggering for both NC and MA ingestion — unbuilt for either
   pilot; whoever picks this up needs to account for shared solver load
   (see "Solver load, cadence").
5. `StateCapabilities`/`CapabilityRegistry` multi-source mismatch — worth a
   real design pass once a generic orchestrator consumer actually exists.
