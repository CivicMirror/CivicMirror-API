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
