# Nov 3, 2026 poll — code triage

Source: CivicMirror API poll, 2026-11-02 (`CivicMirror_API_2026_Midterm_Poll.md`).
Scope of this document: map each reported anomaly to the code that produces it.
Public v1 API serves the **legacy `elections` domain** (`api/views.py:12` imports
`elections.models`), not `cm2_*` — so every fix below is in `backend/results/`,
`backend/integrations/`, or `backend/elections/`.

## P0 — will serve wrong data on election night

### 1. Missouri serves certified 2024 results under a 2026 election
**Confirmed code bug.** `results/adapters/mo.py:44` hardcodes
`_GRAND_TOTALS_URL = ".../2024GeneralElection.pdf"`, and `fetch_results`
(`results/adapters/mo.py:80`) accepts `election_date` and **never reads it** —
it fetches the 2024 PDF for any election id it is handed. The module docstring
(`mo.py:19-22`) admits this: "hardcoded to the 2024 general election's known PDF
URL for this historical POC."

Then `results/tasks.py:565-573`: rows come back `result_type="official"`, so
every matched race is set `RESULTS_CERTIFIED` + `ARCHIVED`, and
`_certify_election_if_complete` (`results/tasks.py:327`) marks the whole
election certified. That is the four MO races (Trump/Harris, Hawley/Kunce,
Kehoe/Quade, Lt Gov) the poll found.

MO is the only adapter with a hardcoded cycle URL (grepped all 50).

**Fix (small, no migration):** guard `fetch_results` to return an empty
`AdapterResult(mapping_confidence="none")` unless `election_date ==
date(2024, 11, 5)`. The `tasks.py` guard in item 2 does **not** cover this —
it blocks the status flip, not the `OfficialResult.update_or_create` at
`results/tasks.py:541`. MO needs its own adapter-level guard.

Prod cleanup is more than a status reset: delete the `OfficialResult` rows for
those four races, clear any winner flags `derive_winners` set on their
candidates (`results/management/commands/derive_winners.py:28` selects exactly
`RESULTS_CERTIFIED` races, so it will have run on them), then reset race and
election status — or delist the MO Nov 3 election. **Deploy the guards before
cleaning**, otherwise the next ingestion run re-pollutes. No `beat_schedule`
exists in this repo, so the trigger cadence is external (Cloud Scheduler or
manual) and needs checking.

### 2. Illinois certified/archived before the polls open
**Confirmed code bug, same transition.** `results/adapters/il_aggregate.py:65`
and `:81` stamp `result_type="official"` unconditionally — there is no
"are these actually final" signal from IL SBE. `results/tasks.py:565-573` then
certifies + archives on `all_official`, with **no check that the election date
has passed**. Result: 141 IL races `race_status: archived` /
`certification_status: results_certified` for tomorrow's election, and
`Election.status = results_certified`.

Candidate names look like genuine 2026 because the IL election-id token
(`results/adapters/il.py:19-22`, resolved from IL SBE) most likely resolved to
the 2026 **primary**, whose CSVs are legitimately official.

**Fix (small, no migration):** in `results/tasks.py`, refuse the
`RESULTS_CERTIFIED`/`ARCHIVED` transition when
`race.election.election_date >= today`; fall back to `RESULTS_PENDING`.
Blast radius is wide and in our favour: **13 adapters** stamp
`result_type="official"` unconditionally (il_aggregate, mo_parse, me, hi, ma,
md_aggregate, oregon, tn, vt, nc, wi, oh, ny), so this one guard protects
every one of them tomorrow night.

**Unverified:** the primary-token hypothesis. `il_sbe_election_value` is read
from `Election.source_metadata` (`results/adapters/il.py:71`), i.e. it is
configured per-election, not auto-resolved to "latest". One prod read of that
key on the IL Nov 3 record settles it. It matters for cleanup: if the value
points at the 2026 primary, primary vote totals are sitting under general-
election races and the `OfficialResult` rows must be deleted, not just
restatused.

## P1 — wrong shape, visible tomorrow

### 3. Record #2232 is a Google Civic catch-all, not a national layer
**Confirmed code bug.** `integrations/civic/mappers.py:36-41`: when the Civic
payload's `ocd_division_id` has no `state:` segment (i.e.
`ocd-division/country:us`), the election is mapped
`jurisdiction_level = NATIONAL` with `state = None`. Google Civic returns one
such "2026 General Midterm Election", so **every** race Civic yields for any
queried address — Michigan's statewide slate, Lansing city measures, Richmond
VA's sales tax, Virginia's amendments — is ingested into that one bucket.
That is why MI's Senate and Governor races exist only inside #2232.

**Fix:** derive the election's state from each *race's* own OCD id (the mapper
already has `parse_state_from_ocd`, `mappers.py:20`) and route races to the
matching per-state election, rather than to the country-level record.
Non-trivial; needs a backfill. Mitigation for tomorrow: document #2232 as a
Civic staging bucket and tell consumers not to read it as national.

### 4. Michigan's statewide slate is absent from its own record (#1891)
**Consequence first:** no results adapter targets a `state=None` election, so
if MI's Senate and Governor races live only in #2232, **their results will land
nowhere tomorrow night.** That makes this P0-adjacent for Michigan, not a
cosmetic shape problem.

What #1891's 41 races actually are is **unverified** — the poll artifacts
referenced at `~/workspace/cm-api-2026-midterms/` are not on this machine, so
the `source` field of #1891, #2232, #56615 and #60939 could not be read.

One contributing defect is confirmed: `integrations/mi_sos/tasks.py:80-88`
ingests MI races without passing `geography_scope`, and
`aggregation/ingest.py:151` takes it straight from `fields` with `""` as the
default — it does not infer. So any race `mi_sos` did create carries a blank
scope, which is consistent with "#1891 contains zero statewide-scope races".
That does not explain an absent race, only an unlabelled one. One-line fix for
the labelling: pass `elections.geography.infer_geography_scope(office_title)`.

### 5. `geography_scope` is unreliable across the board
There is a shared, correctly-ordered inferrer at
`elections/geography.py:65` (district checked before statewide), but at least
five integrations ship their **own** `infer_geography_scope` with different
precedence: `integrations/ca_sos/mappers.py:113`,
`integrations/co_sos/mappers.py:99`, `integrations/ma_sos/mappers.py:125`,
`integrations/ia_sos/mappers.py:105`. TN tagging its House districts
"statewide" and WA tagging school propositions "statewide" are this divergence.
**Fix:** consolidate on `elections/geography.py` and backfill. Not an
election-night fix.

### 6. Florida's duplicate Governor race
"Governor" (#56615) and "Governor and Lieutenant Governor" (#60939) with
identical ballots. There is **no cross-source race-title normalization** at
ingest — each integration normalizes in its own mapper
(`integrations/pa_sos/mappers.py:70`, `integrations/mi_sos/mappers.py:47`,
`integrations/al_sos/mappers.py:36`, …) and `aggregation/identity.py` matches on
`office_title` as given. Two sources, two titles, two races. Dedupe is a data
fix plus an identity-layer change.

### 7. SC/TN Senate races carrying 14 candidates
Consistent with primary filing fields never culled to the general ballot —
same class as IL above. Needs a per-state check against certified general
ballots; not reproducible from code alone.

## P2 — known / out of scope tonight

- **NC county shells (~100 with 0 races).** `d8a20ac` (#224) already added
  `results/nc_repair.py` and `repair_nc_contest_identity`; check whether the
  shells are in its scope before writing anything new.
- **Massachusetts** has only a single state-rep record (#1837) and no statewide
  record — a sync gap, not a code bug.
- **Coverage: 30 shell states, 25 missing Senate races, 24 missing Governor
  races, DC entirely absent.** This is unstaged ingestion, not a bug. It cannot
  be closed by tomorrow and is deliberately excluded from this triage.

## Deployability

Items 1, 2 and the item-4 labelling fix are small, migration-free code changes.
Items 3, 5 and 6 need data backfills. Nothing here has been changed yet.

## What could not be verified from this machine

- Poll artifacts (`~/workspace/cm-api-2026-midterms/`) are absent, so no
  record's `source` field was read: #2232-is-Civic, #1891's 41 races, and
  whether FL's two Governor races come from one source or two are all
  inferences from code, not confirmations.
- `Election.source_metadata['il_sbe_election_value']` on the IL Nov 3 record
  (settles whether IL is serving primary data).
- Whether MI's Senate/Governor races exist in #1891 at all.
- Ingestion trigger cadence (no `beat_schedule` in this repo).

---

# Fixes applied (2026-11-02)

## How pre-election data got in at all

`results/tasks.py:675` — `poll_upcoming_results` **deliberately** polls
elections dated up to `_UPCOMING_WINDOW_DAYS` ahead, "so candidate lists
populate ahead of election day". `poll_pending_results` (`election_date <
today`) was never the route in. That task ran MO's adapter (which returned 2024
rows) and IL's, and the unguarded certification transition then froze both
records — once certified, they drop out of `poll_upcoming_results`' status
filter and stop being refreshed.

## 1. `results/adapters/mo.py` — cycle guard

`_SUPPORTED_ELECTION_DATE = date(2024, 11, 5)`. `fetch_results` now returns an
empty `AdapterResult(mapping_confidence="none")` for any other date, before any
HTTP request, and accepts an ISO-string date. Tests:
`results/tests/test_mo_adapter.py` — unsupported cycle, unparseable/None date,
2024 still works via string.

## 2. `results/tasks.py` — nothing certifies before the canvass

New `can_certify(election)` (used by three call sites) is true only when
`election_date + 1 day < timezone.localdate()`.

**Why the extra day.** `config/settings/base.py:272` sets `TIME_ZONE = 'UTC'`,
so `localdate()` rolls over at 00:00 UTC — **8pm ET on election night, with
polls still open in the Mountain, Pacific, Alaska and Hawaii zones.** A plain
`election_date < localdate()` would have let certification begin mid-evening
tomorrow; NC's adapter stamps `official` unconditionally and has live ENRS
returns, so its races could have gone certified+archived at 8:01pm ET. The
buffer (`_CERTIFY_BUFFER`) removes that window and costs nothing: canvasses
take days to weeks, and `poll_pending_results` runs daily until the election
certifies.

Guarded:

- the per-race `RESULTS_CERTIFIED` + `ARCHIVED` flip — now logs a warning and
  falls back to `RESULTS_PENDING`, leaving `race_status` active;
- `_certify_election_if_complete` — returns False for an unheld election;
- `_certified_at_for_row` — returns None, so no `certified_at` stamp.

Vote rows are still persisted throughout. The behaviour is self-healing: races
stay `results_pending`, the election stays pollable, and `poll_pending_results`
certifies once the buffer has passed.

Covers all 13 adapters that stamp `result_type="official"` unconditionally
(il_aggregate, mo_parse, me, hi, ma, md_aggregate, oregon, tn, vt, nc, wi, oh,
ny). Tests: `results/tests/test_election_certification.py` — `can_certify`
boundaries incl. election day, election-level refusal, pre-election official
rows leaving the race live with `certified_at IS NULL`, post-election rows
still certifying normally.

## 3. `results/management/commands/repair_premature_certification.py`

Previews by default, writes only with `--apply`. Scope: every unheld election
(`election_date >= today`) carrying certified state, narrowable with
`--election-id` (repeatable) and `--state` (repeatable). On apply, per race:
`clear_derived_winners` (which touches only flags we derived, never
source-supplied ones), then either clear `certified_at` and set
`results_pending`, or — with `--delete-results` — delete the `OfficialResult`
rows and set `upcoming`; `archived` → `active`.

Only races actually carrying premature certification are touched, including by
`--delete-results`, so a mixed election cannot lose legitimate rows. The
election goes to `upcoming`, or `results_pending` if today is polling day —
not `active`, because `poll_pending_results` only queues `RESULTS_PENDING`
elections, and that avoids depending on a per-state sync to restamp the status
later. One transaction. JSON report to stdout and optionally `--report <path>`.

It never deletes races or candidates. Missouri has no 2026 Governor or U.S.
Senate race at all, so those four races still need delisting by hand — the
report lists their ids.

Tests: `results/tests/test_repair_premature_certification.py` (11 cases,
including that `--delete-results` spares unaffected races in the same
election).

## Runbook

Deploy first, then clean, or `poll_upcoming_results` re-pollutes.

```
# 1. preview everything affected
python manage.py repair_premature_certification --report /tmp/premature.json

# 2. Illinois — genuine 2026 candidates, wrong claim: keep rows, un-certify
python manage.py repair_premature_certification --state IL --apply

# 3. Missouri — 2024 rows under a 2026 record: delete them
python manage.py repair_premature_certification --state MO --delete-results --apply
```

Then delist MO's four races by id, and check
`Election.source_metadata['il_sbe_election_value']` on the IL Nov 3 record —
after the repair the election returns to `upcoming` and
`poll_upcoming_results` will re-fetch whatever that key points at. If it points
at the 2026 primary, the same rows come back (uncertified now, but still the
wrong contest set) until the key is corrected.
`integrations/il_sbe/mappers.py:104-110` restamps IL's election status from its
date on each sync, so IL also returns to `results_pending` on its own after
Nov 3.

## Test run

Full suite in the repo's Python 3.13 dev container (the local `.venv` is 3.14,
which `config/python_version.py` rejects):

```
docker build --target development -t civicmirror-dev:local backend/
docker run --rm -v "$PWD/backend":/app -v "$PWD/docs":/docs -w /app \
  -e DJANGO_SETTINGS_MODULE=config.settings.dev civicmirror-dev:local \
  python -m pytest -q
```

`1 failed, 2368 passed, 2 skipped`. The one failure is **pre-existing and
unrelated**:
`integrations/election_calendar/tests/test_tasks.py:111` asserts the Nov 3,
2026 TX general is `upcoming`. That assertion expires today — the seeder sets
`results_pending` once `election_date <= today`. It needs a relative date or a
frozen clock. `api/tests/test_mcp_stdio_integration.py` needs
`civicmirror_mcp/` from the repo root, so it is excluded when only `backend/`
is mounted; it is unaffected by these changes.

`ruff check .` from `backend/` — clean.

## Not changed

Items 3–7 above (Civic national bucket, MI slate, `geography_scope` duplication,
FL duplicate Governor, SC/TN candidate lists) and the coverage gap. No commits
made.

---

# Civic national bucket (#2232) — diagnosis and plan

## Why #2232 holds ten states' ballots

`integrations/civic/mappers.py:36-41` maps a Civic election whose
`ocd_division_id` has no `state:` segment to `jurisdiction_level=NATIONAL`
with `state=None`. Google Civic returns exactly one such record for 2026,
"2026 General Midterm Election".

`state=None` then has two consequences:

1. `aggregation/ingest.py:66-91` — `ingest_election` cannot build a canonical
   key without a state, so the record took the **`needs_review` branch**: it
   exists with `needs_review=True` and a populated `Election.source_id`,
   outside the normalized identity scheme.
2. `integrations/civic/tasks.py:31-39` —
   `_representative_addresses_for_election` falls back, for a state-less
   election, to one address from each of `_NATIONAL_SAMPLE_STATES`
   (`CA TX NY FL PA OH GA NC MI VA`). Those addresses are each state's
   **capital**: `MI-capital` is Lansing, `VA-capital` is Richmond
   (`integrations/civic/addresses.py:81,185`). `sync_election_races` ingests
   every contest returned for all ten addresses into that single election.

That is the poll's "Michigan's statewide slate, Lansing city measures,
Richmond VA's sales-tax question, Virginia's three constitutional
amendments" — not a national layer, a ten-capital sample sheet.

## What Michigan actually looks like (pulled 2026-11-02)

- **#1891 "2026 Michigan General Election"** — state-level, `upcoming`,
  sources `election_calendar` + `mi_sos`, 41 races, **every one judicial**:
  Supreme Court (1), Circuit (10), District (24), Probate (6). No Governor,
  U.S. Senator, U.S. House, state legislature, AG, Secretary of State or
  ballot proposals. All 41 carry a blank `geography_scope` and jurisdiction
  "Michigan".
- **#2232** holds Michigan's entire partisan and statewide ballot.

So Michigan's statewide slate has exactly one copy, and it is in the bucket.

### This kills two earlier assumptions

- **Stopping the fan-out is not safe containment.** It would freeze
  Michigan's only statewide slate in a `needs_review` record and stop Civic
  refreshing it.
- **Routing Michigan's races will not duplicate anything.** `mi_sos`
  contributes judicial offices only; Civic contributes everything else. Zero
  office overlap, so the `_normalize_ocd` extension (collapsing a bare
  statewide division to `""` so Civic key-matches no-OCD state sources) and
  its key backfill are **not** needed for Michigan. They are still needed for
  the general duplicate problem (item 6, FL's twin Governor races), which is
  separate work.

## Michigan serves no statewide results tomorrow night as things stand

This is the consequence that matters on Nov 3, and it follows from #1891 being
judicial-only.

- `ingest_official_results("MI", 1891)` fetches MI SOS results via the
  registered `mi` adapter and matches rows against #1891's races — 41 judicial
  contests. Governor, U.S. Senator, AG and Secretary of State rows match
  nothing, so they are logged as unmatched and dropped. The
  results-bootstrap path cannot save them either: `results/tasks.py:92-93`
  only bootstraps races when the election has **none**, and #1891 has 41.
- #2232, which does hold those races, has `state=None`, and both
  `poll_pending_results` and `poll_upcoming_results` filter
  `state__in=supported`. It is never polled at all.

So Michigan's statewide results have no race to land on in one record and no
poller in the other. This is an election-night defect, not cleanup.

## Superseded: Michigan never needed Civic at all

The plan above (move Michigan's races out of #2232) was abandoned once the real
cause came to light. Michigan has its own authoritative pre-election feed, and
**our parser was discarding 90% of it**. See "MI BOE listing parser" below.
Fixing that gives Michigan its full ballot from `mi_sos` into #1891, with no
race moving, no key recomputation and no dependence on Civic.

The Civic diagnosis above stays accurate and still needs the routing fix, but
it is now ordinary cleanup for after Nov 3 rather than an election-night
dependency.

## Routing design

In `sync_election_races`, resolve each contest's target election instead of
always using the one passed in:

- `election.state` set → use it unchanged. No behaviour change for the normal
  per-state Civic elections.
- `election.state` is None → derive the state from the contest's own OCD id
  (`district.id` / `officeDivisionId`, via the existing
  `parse_state_from_ocd`) and `ingest_election` the target with identity
  `{state, election_type: infer_election_type(election.name), election_date,
  jurisdiction_level: STATE}`.
- No state derivable → fall back to the state-less election. That is where
  the genuinely national row belongs (the poll's generic "Member, United
  States Senate" with jurisdiction "United States Of America").

`jurisdiction_level` is always `STATE`, never derived from the contest's OCD
depth: Lansing's city measures go on Michigan's state record, matching how
KY (3,328 mostly-local races) and NM (599, all local) already model local
contests. Splitting local elections out is out of scope.

**Pass no `name` when the target election already exists.**
`aggregation/migrations/_seed_data.py:3` seeds `("*", "*", "civic_api", 0)` —
Civic holds rank 0 for every state and every field group, and `mi_sos` has no
`SourcePrecedence` rows at all (rank ∞). `_apply_fields` would otherwise
overwrite `Election.name` and rename #1891 to "2026 General Midterm
Election". Compute the target's `election_canonical_key` first; pass `name`
and `status` only on creation.

`ElectionSourceLink` is unique on `(election, source)`, not
`(source, source_id)`, so several state elections may each carry a
`civic_api` link with the same Civic source id. No constraint problem.

## Backfill

Forward-only routing is not enough: a race already in #2232 has a
`canonical_key` built from that election's key, so the next sync would create
a second MI race on #1891 and leave the first in place. The move must happen
in the same change.

Move, don't delete-and-resync — race ids are what consumers reference. Same
command shape as `repair_premature_certification`: dry-run default, and for
each race on a state-less `civic_api` election, derive the state from
`race.ocd_division_id`, resolve or create the target election, recompute
`race.canonical_key` (and candidate keys, which embed the race key), reparent,
and on a canonical-key collision skip and report rather than merge — that
collision *is* the duplicate problem, and it is not this change's job.

## Status

Diagnosis complete, no code written. The decision outstanding is whether to
land routing + move before Nov 3 or after.

---

# MI BOE listing parser — Michigan's ballot was being discarded

## What the source actually serves

`sync_mi_elections` (`integrations/mi_sos/tasks.py:38`) fetches the Michigan
BOE "Official Candidate Listing" for `electionType=GEN&electionYear=2026` —
candidate filings, not results. Pulled live 2026-11-02, that document contains
Michigan's whole ballot: Governor/Lt. Governor, U.S. Senate, Secretary of
State, Attorney General, all 13 congressional districts, 38 State Senate
districts, 110 State House districts, the State Board of Education, the three
university governing boards, and the judicial offices.

`parse_boe_candidate_listing` returned **73 candidates across 41 offices — all
judicial**. The repaired parser returns **716 candidates across 338 offices**.
That gap is exactly why #1891 was judicial-only, and why the Civic bucket
looked like Michigan's only source.

## Two causes, both verified against the live document

1. **Nested tables.** The report is wrapped in a one-cell layout table.
   `tr.find_all(["td", "th"])` recurses, so the outer row returned **9,995
   cells** (3 with `recursive=False`). That row failed every shape heuristic
   and left `current_office` empty, so the partisan section was dropped before
   any column was read.
2. **Hardcoded column indices.** Every row is
   `['', Status, '', Party / Incumbent, Candidate Name, Filed On, Filing Method, '']`.
   The parser read `status = cells[3]`, which holds `"Democratic Party"` — not
   in `_STATUS_CODES`, so **every partisan row was rejected**. Non-partisan
   (judicial) offices have no party, so `cells[3]` was blank, blank *is* a
   valid status code, and they passed by accident.

The repo's only fixture for this parser was an 877-byte synthetic file whose
seven invented columns matched the parser's indices, so the mismatch was never
caught. Columns are now located by **header text**, which handles the primary
listing's layout and the general listing's alike.

## Also fixed in the same area

- **`party_abbrev` truncated every multi-word party.** The general listing says
  "Green Party" where the primary says "Green", the suffix was never stripped,
  and the fallback produced `GRE`, `U.S`, `WOR`, `NAT`. Now `GRN`, `UST`,
  `WCP`, `NLP`, plus `NPA` for "No Party Affiliation", and `INCUMBENT` can
  never be read as a party.
- **The general listing's office wording was unrecognised.** It says "U.S.
  Senate", "Representative in Congress" and "Representative in State
  Legislature" where the primary says "United States Senator", "United States
  Representative" and "State Representative". Both spellings now normalize to
  one title — which matters because `result_office_title` runs the same
  function, so this is what lets tomorrow's MVIC result rows key-match the
  races.
- **"Governor of Wayne State University" collapsed into "Governor".** A bare
  `"GOVERNOR" in upper` test would have put two university-board candidates on
  Michigan's gubernatorial ballot. The statewide boards are matched first and
  the governorship now requires the title to start with "Governor". A
  collision check across all 338 live offices reports none.
- **`geography_scope` was never passed** by `mi_sos`, which is why all 41
  existing races have it blank. Now set. Michigan elects its education and
  university boards statewide, which a title-based inferrer cannot know —
  `elections.geography` reads "State Board of Education" as `local` (that rule
  exists for county boards such as NC's) and does not recognise the university
  boards at all — so `mi_sos.mappers.geography_scope` names those four
  explicitly and defers to the shared inferrer for everything else.
- **`Candidate.incumbent`** is now set from the listing instead of only being
  kept as raw metadata.

## Tests

`integrations/mi_sos/tests/fixtures/boe_candidate_listing_2026_general.html` —
trimmed from the live document (7 offices, 34 candidate rows, 10 KB).
Presentation attributes were stripped; **the row and cell structure, including
the table nesting, is verbatim**, because that nesting is what the test
exercises. 13 new cases in `test_parsers.py`, `test_mappers.py` and
`test_tasks.py`, the last ingesting the fixture end to end and asserting that
`result_office_title("UNITED STATES SENATOR")` equals the race title created.

Full suite: `1 failed, 2380 passed, 2 skipped` — the one failure is the same
pre-existing `test_seed_2026_elections_sets_correct_status` date expiry.
`ruff check .` clean.

## Running it

Nothing changes in the database until the fix is deployed **and**
`sync_mi_elections` runs. It is triggered by
`POST /internal/tasks/sync-mi-sos/`, or locally with
`python manage.py trigger_internal_task sync_mi_sos`.

Order for tonight:

1. Deploy. `fix/mi-boe-parser` is stacked on `fix/premature-certification`, so
   either one PR from the top of the stack or two PRs merged in that order.
2. `repair_premature_certification` for MO and IL (see the runbook above).
3. `POST /internal/tasks/sync-mi-sos/` — this creates Michigan's 338 races and
   716 candidacies, and backfills `geography_scope` on the 41 judicial races
   that already exist.

The re-sync is idempotent: a second run updates in place rather than
duplicating, and it rewrites a blank `geography_scope`, both covered by
`test_resyncing_the_general_listing_is_idempotent_and_backfills_scope`.

## Will the results match tomorrow night

`results/adapters/mi.py:47` sets each result row's `office_title` from
`result_office_title(raw["contest"])` — the same `normalize_office_title` the
listing goes through, which is what makes the match possible. MVIC names
contests in the primary listing's wording, in capitals: the 705 fixture shows
`35TH DISTRICT STATE SENATOR PARTIAL TERM ENDING 1/1/2027`. Those spellings
are covered.

The one thing not verifiable before the election is MVIC's exact wording for
Governor and U.S. Senate in a November general; no such result file exists
yet. The rules are written to tolerate the variants: `GOVERNOR`,
`GOVERNOR / LT. GOVERNOR` and a prefixed `STATE OF MICHIGAN - GOVERNOR` all
normalize to "Governor", which is why the governorship is matched by
containment rather than a prefix test, with explicit phrase guards keeping the
university boards out. Worth one check against the first real result file
tomorrow.

## Still open for Michigan
- Multi-seat offices (Supreme Court 2 positions, the university boards 2 each,
  36th District Court 3) are still ingested as single-seat: `mi_sos` sets
  neither `vote_method` nor `max_selections`, so `results/winners.py` will
  report `skipped_unknown_seats` and derive no winner for them. The seat count
  is right there in the raw title ("8 Year Terms (2) Positions") and is kept in
  `source_metadata["mi_office_raw"]`, so this is a contained follow-up.
- Disqualified and withdrawn filings still create races and candidates, marked
  `DISQUALIFIED`/`WITHDRAWN` — unchanged behaviour, but it means an office
  whose only filing was disqualified appears as a race with no live candidate.
- Civic's copies of Michigan's statewide races remain in #2232. They are inert
  — #2232 is `needs_review` with `state=None` and is never polled — but they
  are now genuine duplicates of #1891's races and should be cleaned when the
  Civic routing fix lands.

---

# MVIC election-id discovery — Michigan's results adapter had never run

## The second Michigan blocker

`results/adapters/mi.py:76` reads `Election.source_metadata["mi_mvic_election_id"]`
and returns `rows=[], mapping_confidence="none"` when the key is absent, before
it builds a URL. **Nothing in the repo ever wrote that key** — the adapter was
its only reference. So Michigan's results adapter, which is otherwise complete
and tested, had never fetched anything.

The code to find the id already existed and was **dead**:
`parse_mvic_elections` reads `{election_id, date, name}` out of the MVIC
vote-history dropdown, and `fetch_votehistory_page` fetches that page. Neither
was called by any task or adapter.

`00-MASTER-INDEX.md` lists Michigan results as "✅ Complete (MVIC)", which on
this evidence is wrong and worth correcting.

## Michigan's two hosts

| | System | Host | Supplies |
|---|---|---|---|
| BOE | Bureau of Elections filings (entellitrak) | `mi-boe.entellitrak.com` | candidates and races, pre-election |
| MVIC | Michigan Voter Information Center | `mvic.sos.state.mi.us` | vote totals, and the election id above |

Exact URLs:

```
https://mi-boe.entellitrak.com/etk-mi-boe-prod/page.request.do?page=page.miboePublicReport&electionType=GEN&electionYear=2026
https://mvic.sos.state.mi.us/votehistory/
https://mvic.sos.state.mi.us/VoteHistory/GetElectionResultFile?electionId={mvic_id}
https://mvic.sos.state.mi.us/VoteHistory/GetCountyVoteRecords?electionId={mvic_id}
```

## The fix

`sync_mi_elections` now runs `_discover_mvic_election_ids` once per run, maps
each dropdown date to its id, and passes `mi_mvic_election_id` through
`ingest_election`'s `source_metadata` for the spec whose date matches.

- **Routed through the CF solver.** `fetch_votehistory_page` was a plain GET,
  which would have 403'd in production. Checked 2026-11-02: `/`,
  `/votehistory/`, `GetElectionResultFile` **and** `GetCountyVoteRecords` all
  return 403 Cloudflare challenges to a plain request. There is no open list
  endpoint, so the solver is unavoidable here.
- **Non-fatal by construction.** MVIC and the BOE are different hosts; a solver
  outage or an unset `CF_SOLVER_URL` must not stop Michigan's ballot from
  syncing. Fetch failures catch `(MiSosRetryableError, CfSolverError)` — which
  covers `CfSolverUnavailableError` — and the parse step catches broadly on
  purpose, so a shape change in MVIC's page degrades this enrichment instead of
  taking candidate ingestion down with it. Both paths log and return `{}`.
- **Written through the merge engine, not around it**, since `_apply_fields`
  replaces `source_metadata` wholesale: the BOE keys and the MVIC id go in one
  dict. If a higher-precedence source owns the field the id will not land, so
  that case logs `mi_sos.mvic_id_not_applied` rather than failing quietly.
  Neither `mi_sos` nor `election_calendar` has a `SourcePrecedence` row today
  (both rank ∞, and `inf <= inf` passes), so it lands — but `civic_api` is
  seeded `("*", "*", 0)`, so if Civic ever contributes to a Michigan election
  record this write stops. That exposure is pre-existing, and now audible.
- One CF solve per run; `fetch_through_cf` caches 25 minutes and the task is
  daily, so no pre-check.

Tests: `test_client.py` covers the solver path and the unconfigured-solver
mapping; `test_tasks.py` covers the id landing on the matching election only,
the BOE sync surviving an MVIC outage, a later sync filling in an id MVIC had
not published yet, and undatable dropdown entries being skipped.

Full suite: `1 failed, 2387 passed, 2 skipped` — the same pre-existing
date-expiry failure. `ruff check .` clean.

## This may not produce results tomorrow

MVIC's dropdown is a *vote history* list. It may not include Nov 3, 2026 until
results start posting. If so, discovery runs, finds nothing, logs
`mi_sos.mvic_discovery_unavailable` or simply no match, and the id stays unset
until a later `sync_mi_elections` run — which is its own trigger
(`POST /internal/tasks/sync-mi-sos/`), not something the results pollers fire.

**So for tomorrow specifically, setting `mi_mvic_election_id` on election #1891
by hand is still the reliable move.** This wiring is what stops it being a
manual step for every future Michigan election.

## Related finding, not fixed

`results/adapters/mi.py:93-94` falls back to `GetCountyVoteRecords` with a
plain request when the solved bulk fetch fails, and
`test_fetch_county_vote_records_uses_plain_requests` enshrines that. That
endpoint returned 403 to a plain request in my check, so the fallback is
probably dead in production too — unless Cloud Run's egress is treated
differently from my IP, which is possible and untested. Worth confirming
against the first real result fetch; if it 403s, the fallback needs the solver
as well.

---

# MVIC verified against the live site (via a local FlareSolverr, 2026-11-02)

Run as a one-off experiment through a local FlareSolverr container, not through
the project's `core.cf_solver`. Read-only requests to a public SOS site.

## 1. The 403 is bot fingerprinting, not an active challenge

FlareSolverr fetched `https://mvic.sos.state.mi.us/votehistory/` with
`status: ok, message: "Challenge not detected!"`, HTTP 200, 44 KB. A plain
request with a browser User-Agent still gets 403, so the block is below the
UA layer (TLS/JA3 fingerprint). Any real browser session defeats it, which is
why `core.cf_solver` works — and means a lighter solver would do for the HTML
pages.

## 2. `parse_mvic_elections` works perfectly on the real page

51 dropdown entries, every date and id extracted cleanly. The discovery code
committed in `4532599` does what it claims.

## 3. Nov 3, 2026 is not in MVIC's dropdown, and has no id yet

Newest entries: `2026-08-04 → 706`, `2026-05-05 → 705`, `2026-02-03 → 708`.
Note the ids are not ordered by date, so Nov's cannot be extrapolated — and
`707` is unassigned. Probing `GetCountyVoteRecords` for **707, 709, 710, 711
and 712** returned `"No election results for selected election date"` for every
one.

**This corrects the advice in the previous section.** There is no
`mi_mvic_election_id` to set by hand tonight; MVIC has not published the
election. Discovery is therefore not merely the long-term answer, it is the
only one — it will pick the id up on the first `sync_mi_elections` run after
MVIC publishes, which on this evidence happens when results start posting.

## 4. `parse_mvic_county_results_html` cannot parse real MVIC output

`GetCountyVoteRecords?electionId=706` returns 867 KB of genuine Aug 4, 2026
primary results — `STATE PRIMARY, OFFICIAL`, `Counties: 83/83`,
`GOVERNOR 4 YEAR TERM (1) POSITION / DEMOCRATIC / Benson, Jocelyn 1,251,160
83.22%`.

`parse_mvic_county_results_html` returns **0 rows** from it.

Cause: the real document puts each field in its own table cell, so
`soup.get_text("\n")` yields

```
'GOVERNOR 4 YEAR TERM (1) POSITION'
'DEMOCRATIC'
'Benson, Jocelyn'
'1,251,160'
'83.22%'
'Party Votes:'
'1,503,406'
```

while the parser requires name, votes and percent on **one** line separated by
two or more spaces:

```python
re.match(r"^(?P<name>.+?)\s{2,}(?P<votes>[\d,]+)\s{2,}(?P<pct>[\d.]+)%?$", line)
```

which is exactly how the 332-byte `mvic_county_records_705.html` fixture was
written. Same root cause as the BOE listing parser: **all three Michigan
fixtures are synthetic and were built to match the code rather than captured
from the source.** The real document also carries `Party Votes:` subtotal rows
that any rewrite must skip.

One good sign for the title matching: MVIC's contest wording is
`GOVERNOR 4 YEAR TERM (1) POSITION`, which `result_office_title` already
normalizes to `Governor` — matching the race the BOE listing creates.

## 5. The bulk path remains unverified

`GetElectionResultFile?electionId=706` is a file download, so FlareSolverr
returned a blank browser tab rather than the payload; a cookie-replay attempt
was blocked locally. So `parse_mvic_result_file` and its 318-byte synthetic
TSV fixture are **still unvalidated against real data**. Given that both other
Michigan parsers failed on real input, assume this one needs checking too.
`core.cf_solver` can retrieve it — `fetch_through_cf` fetches the payload from
inside the browser session — so this is testable in the deployed environment
today.

## Michigan's results path, current state

| Step | State |
|---|---|
| Races for results to match | fixed, `612f798` |
| `mi_mvic_election_id` populated | wired, `4532599`; no id published yet |
| Bulk TSV fetch + parse (primary path) | **unverified** |
| County-records fetch + parse (fallback) | **broken — 0 rows on real input** |

So Michigan will still serve no results until the parsers are validated
against real output, independently of everything fixed so far.

---

# MVIC county-records parser rewritten against the real document

## What MVIC actually renders

Not a table — a Bootstrap grid inside the "Election Results" tab
(`div#tab-target-voteResults`), which holds 1,225 direct `div.row` children in
three shapes:

| Rows | Shape | Meaning |
|---|---|---|
| 170 | no column children | contest banner |
| 552 | `col-md-2`, `col-md-4`, `col-md-2 text-right`, `col-md-1 text-right`, `col-md-3` | a candidate's result |
| 503 | same, but the label cell adds `text-right bold` | "Party Votes:" subtotal |

Each candidate row carries **its own party**; MVIC does not use party header
rows. Subtotals are distinguished from results only by that `bold` class, so
they have to be filtered on it rather than on text.

## The rewrite

`parse_mvic_county_results_html` now walks the results pane's rows, treats a
row with no columns as the contest banner, reads party, candidate, votes and
percent from the column cells, and skips `bold`-labelled subtotals. The old
implementation flattened the page with `get_text("\n")` and required name,
votes and percent on one line separated by two or more spaces.

| | Old | New |
|---|---|---|
| Live `electionId=706` (867 KB) | **0 rows** | **552 rows, 170 contests** |

Spot-checked against the live document: `Benson, Jocelyn DEMOCRATIC 1,251,160
83.22%`, `James, John REPUBLICAN 466,714 50.05%`. No subtotal rows leak in and
no row has empty votes. The data is also self-consistent with the candidate
listing — James won the Republican gubernatorial primary and appears as the
`James, John / DeBoyer, Jay` ticket on the general ballot.

Contest titles from the real document normalize onto the races the BOE listing
creates, which is the whole point:

```
GOVERNOR 4 YEAR TERM (1) POSITION                                -> Governor
UNITED STATES SENATOR 6 YEAR TERM (1) POSITION                   -> U.S. Senate
1ST DISTRICT REPRESENTATIVE IN CONGRESS 2 YEAR TERM (1) POSITION -> U.S. House - District 1
35TH DISTRICT STATE SENATOR 4 YEAR TERM (1) POSITION             -> State Senate - District 35
```

## The fetch was broken too

`fetch_county_vote_records` was a plain GET. Every MVIC path 403s, so the
fallback could never have received anything — and the failure would not have
been contained: `results/adapters/mi.py` wraps only the *bulk* fetch in its
`try/except`, so a raise from the fallback propagates out of `fetch_results`
and retries the task. Now solver-routed like the other two.

## Fixtures

`mvic_county_records_705.html` (332 bytes, synthetic) is **deleted** — it
encoded a text shape MVIC does not produce and was the reason this went
unnoticed. Replaced by `mvic_county_records_706.html`, trimmed from the live
document (4 contests, 20 result rows, 9 KB) with style and aria attributes
stripped and the row/column structure verbatim.

`results/tests/test_mi_adapter.py`'s fallback test used inline text in the same
invented shape; it now feeds the real fixture and asserts vote counts, the
normalized office title, the empty jurisdiction fragment and write-in
aggregation.

Full suite: `1 failed, 2391 passed, 2 skipped` — the same pre-existing date
expiry. `ruff check .` clean.

## Michigan's results path now

| Step | State |
|---|---|
| Races for results to match | fixed, `612f798` |
| `mi_mvic_election_id` populated | wired, `4532599`; MVIC has not published Nov 3 yet |
| County-records fetch + parse (fallback) | **fixed and verified against real output** |
| Bulk TSV fetch + parse (primary path) | **still unverified** |

The bulk path is the one remaining unknown. `GetElectionResultFile` is a file
download, so it could not be retrieved with a browser-based solver locally, and
`mvic_result_file_705.tsv` (318 bytes) is synthetic like the other two were —
so `parse_mvic_result_file` should be assumed broken until a real file proves
otherwise. `core.cf_solver` can fetch it in the deployed environment today
using `electionId=706`, which would settle it before tomorrow night. Note the
fallback now works, and when it is used the adapter reports
`mapping_confidence="partial"`, so those races stay `partial_results` and never
auto-certify.

---

# MVIC bulk result file — rewritten against the real files

Both real files supplied 2026-11-02:
`2024STATE_GENERAL_MI_CENR_BY_COUNTY.txt` (electionId 699, 6,111 lines) and
`2026STATE_PRIMARY_MI_CENR_BY_COUNTY.txt` (706, 2,538 lines).

## The format, and why nothing parsed

It is tab-delimited but it is not a bare CSV:

```
TOTAL VOTER TURNOUT: 97,057,730                     <- preamble
ElectionDate  OfficeCode(text)  ...  CandidateVotes <- header, 18 columns
2024-11-05  1  0  0  1  ALCONA  ELECTORS OF ...  5  GREEN  5006  STEIN  JILL ...
RECORDS: 6108   RESULTS: OFFICIAL                   <- trailer
```

Two independent failures in `parse_mvic_result_file`:

1. It fed the whole file to `csv.DictReader`, so **line 1 became the header** and
   every record keyed off `"TOTAL VOTER TURNOUT: 97,057,730"`.
2. Even with the right header, **every column name differs** from the ones it
   looked for. It wanted `contest`/`office`/`race`, `candidate`/`candidate_name`
   and `votes`/`vote_total`/`total_votes`; the file has `OfficeDescription`,
   `CandidateLastName` + `CandidateFirstName` + `CandidateMiddleName` (split
   across three columns) and `CandidateVotes`.

The trailer also crashes naive parsing — it yields one all-`None` record.

## The rewrite

- Locate the header by its `OfficeDescription` marker; drop the preamble and the
  `RECORDS:` trailer.
- Map the real columns. Assemble the name as `"Last, First Middle"`, which is the
  shape the BOE candidate listing uses — that correspondence is what lets results
  match candidates at all.
- Flag write-ins. The header says `WriteIn(W)/Uncommitted(Z)` but the files
  carry `Y`; `PartyDescription` is also `WRITE-IN` on those rows, so either
  signal identifies them.
- **Sum the county rows into contest totals.** The file reports county splits
  only, and `results/winners.py` derives winners solely from contest-total rows
  (`jurisdiction_fragment == ""`), deliberately refusing to sum sub-jurisdiction
  rows because fragments can overlap in general. Michigan's 83 counties
  partition the state, so summing is sound here. The parser emits both: the
  totals and the per-county detail.

| | Old | New |
|---|---|---|
| 2024 general (699) | 0 rows | 630 totals + 6,108 county rows, 319 contests, 83 counties |
| 2026 primary (706) | 0 rows | 550 totals + 2,535 county rows, 170 contests, 83 counties |

**The aggregation is independently verified.** The summed totals reproduce
MVIC's own published statewide figures exactly — Benson 1,251,160, Swanson
252,236, James 466,714, Cox 121,261, Johnson 328,194, Nesbitt 16,295, write-ins
10 — matching the HTML results page parsed by the separate county-records path,
and the contest count agrees at 170.

## MVIC states whether results are official, and we now read it

The trailer carries `RESULTS: OFFICIAL`. Almost no source in this repo exposes
that, which is why 13 adapters hardcode `result_type="official"` and why the
pre-election certification guard was needed at all.

`parse_mvic_result_status` reads it, and `results/adapters/mi.py` uses it in
place of the hardcoded value. Unknown or missing is treated as **unofficial**,
not assumed final. So Michigan's election-night returns will be stored as
unofficial and cannot certify a race, and the switch to certified happens when
MVIC itself says the canvass is done — which is the behaviour the `can_certify`
guard approximates for every other state.

## Fixtures

`mvic_result_file_705.tsv` (318 bytes, synthetic, invented column names) is
**deleted**, replaced by `mvic_result_file_706.txt` — real rows for Governor and
U.S. Senator across three counties, with the genuine preamble, 18-column header
and trailer (33 rows, 4 KB).

`results/tests/test_mi_adapter.py`'s bulk test used inline text with the invented
columns, which is precisely what hid this; it now feeds the real fixture,
asserts that county rows sum to the totals, and has a second case confirming
that an `UNOFFICIAL` trailer yields unofficial rows.

Full suite: `1 failed, 2398 passed, 2 skipped` — the same pre-existing date
expiry. `ruff check .` clean.

## Open: the Governor ticket will not match

`results/tasks.py:529-541` matches candidates on `name_match_key` — normalized
tokens, sorted — then exact/iexact name. There is no surname fallback.

- The BOE **general** listing gives Michigan's gubernatorial candidate as
  `"Benson, Jocelyn / Brinks, Winnie"` (a running-mate ticket) →
  `benson brinks jocelyn winnie`.
- MVIC lists only the top of the ticket. The 2024 general file is the precedent:
  office `ELECTORS OF PRESIDENT AND VICE-PRESIDENT OF THE UNITED STATES`, with
  candidate `STEIN, JILL` and no running mate → `benson jocelyn` for Governor.

Those keys differ, so **Michigan's Governor result rows will find no candidate
and be dropped**, logged as `no candidate match`. The same applies to any
Lieutenant Governor pairing.

This cannot be confirmed until MVIC publishes a 2026 general file, but the 2024
precedent is strong. The contained fix is in `mi_sos`: ingest the ticket's
candidate under the top-of-ticket name and keep the full ticket in
`source_metadata` (or as a candidate alias, which `d8a20ac` added for NC),
rather than teaching the shared matcher about tickets. Worth deciding before
tomorrow night.

## Michigan's results path now

| Step | State |
|---|---|
| Races for results to match | fixed, `612f798` |
| `mi_mvic_election_id` populated | wired, `4532599`; MVIC has not published Nov 3 |
| Bulk TSV fetch + parse (primary path) | **fixed and verified against both real files** |
| County-records fetch + parse (fallback) | fixed and verified, `8ab0fec` |
| Governor/Lt. Governor ticket matching | **open — see above** |
