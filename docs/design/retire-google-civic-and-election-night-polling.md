# Retiring Google Civic, and election-night polling cadence

Status: decided 2026-11-03. Supersedes the merge-based plan in this file's
earlier revision.
Origin: reported duplication between Election #1891 and #2232 (Michigan).
Evidence: live `civicmirror-postgres` (`civicmirror_api`), the running
`civicmirror-worker` / `civicmirror-scheduler` containers, and the live Google
Civic API. All read-only; no writes were made.

## Decision

1. **Crontab edit** — open the election-night cadence and stop the Civic sync,
   in one atomic change to one file.
2. **Retire the Google Civic API integration project-wide** (code).
3. **Audit the database** for Civic leftovers and duplicate records.

The reported Michigan duplication is a symptom of Civic's design. Step 1 is the
whole of the urgent work: it both fixes the election-night cadence and cuts off
new Civic writes, because `sync-elections` and the results pollers live in the
same crontab. Step 2 removes the now-dead code. Step 3 sweeps what earlier pulls
already wrote, and must come last — running it while the source is still live
would let the next sync re-create what the sweep removed.

---

## Part 1 — Crontab: election-night cadence + stop Civic

**One atomic change to one file**, `/data/DockerConfigs/CivicMirror/scheduler/crontab`
on the scheduler host. No code deploy. Both halves of the urgent work live here,
so there is no ordering window between them: cron reads the whole file.

### The problem

The scheduler is still in off-season mode, by its own admission:

```
# All tasks run once daily, overnight. Times are UTC and do not auto-shift for DST.
# Off-season schedule while there are no active elections to monitor hourly.
# Revisit before the November active window if sync-elections/poll-sc-enr/
# sync-sc-enr-results need to return to hourly cadence.
```

Today **is** the November active window. The revisit did not happen. Over the
last 72 hours the scheduler called:

```
1317  /internal/tasks/poll-ky-results/        every 2 minutes
   2  /internal/tasks/poll-upcoming-results/  daily, 08:05 UTC
   2  /internal/tasks/poll-results/           daily, 08:00 UTC
   2  /internal/tasks/sync-<state>/           daily, each
```

**Kentucky is the only state on a live cadence.** Worker logs for the last 48h
show `ingest_official_results` running for election #1883 (KY) and nothing else.
Michigan holds 534 races and **0 official results**; `results/adapters/mi.py`
pulls live MVIC county results and would populate them if asked.

### The change

```diff
-# All tasks run once daily, overnight. Times are UTC and do not auto-shift for DST.
-# Off-season schedule while there are no active elections to monitor hourly.
-# Revisit before the November active window if sync-elections/poll-sc-enr/
-# sync-sc-enr-results need to return to hourly cadence.
-0 4 * * * /usr/local/bin/trigger.sh /internal/tasks/sync-elections/
+# Times are UTC and do not auto-shift for DST.
+#
+# ACTIVE WINDOW (opened 2026-11-03 for the November general). The results
+# pollers below run on a live cadence; the per-state sync-* discovery jobs stay
+# daily on purpose -- several sit on non-default slots to dodge WAF/403 blocks
+# (see the PA and UT notes further down) and must not be hammered.
+# REVERT the two poll-* cadences to daily once results are certified.
+#
+# sync-elections (Google Civic) removed 2026-11-03 -- integration retired.
+# ... See issue #229.

-0 8 * * * /usr/local/bin/trigger.sh /internal/tasks/poll-results/
-5 8 * * * /usr/local/bin/trigger.sh /internal/tasks/poll-upcoming-results/
+*/30 * * * * /usr/local/bin/trigger.sh /internal/tasks/poll-results/
+*/15 * * * * /usr/local/bin/trigger.sh /internal/tasks/poll-upcoming-results/
```

Four functional lines: drop `sync-elections` (the only Civic entry in the file),
and move the two general pollers onto a live cadence.

### Why these cadences and not faster

An earlier draft proposed `*/5`. Measured load rules that out:

| poller | queues per run | **of which have races** |
|---|---|---|
| `poll_upcoming_results` | 251 | **30** |
| `poll_pending_results` | 207 | 100 |

At `*/5`, `poll_upcoming_results` alone is ~3,000 task-queues/hour, and **221 of
its 251 elections have no races** — overwhelmingly NC county and municipal rows,
each triggering a pointless adapter fetch against NC SBE. That is precisely how
the PA and UT WAF/403 blocks documented in this crontab were earned.

`*/15` + `*/30` takes Michigan from 1 results check per day to 96, which is the
difference that matters, at roughly a third of the request volume.
`ingest_official_results` short-circuits on an unchanged source version, so
repeat runs against quiet states are cheap.

### What is deliberately *not* accelerated

- **The 37 per-state `sync-*` jobs.** These are the discovery layer
  (`integrations/`), not results. Tonight's need is vote counts, which the two
  pollers drive via `results/adapters/` for all 50 states. PA and UT in
  particular are parked on non-default slots specifically to dodge WAF/403
  blocks — accelerating them risks losing the window entirely.
- **`poll-ky-results`** stays at `*/2`; it already works.

### Safety: this cannot amplify Civic

The results pollers and the Civic sync are separate paths. `sync-elections` is
the only Civic entry, and it is being removed, not accelerated. Independently,
both pollers filter `state__in=supported` and all three Civic buckets have
`state = NULL`:

```
'' in supported: False
#2232 state=None  poller-eligible=False
#2236 state=None  poller-eligible=False
#1772 state=None  poller-eligible=False
```

The pollers **cannot reach** the Civic buckets at any cadence. Note this
guarantee rests on `state` staying NULL on those rows — which is why Part 3
retires them as empty `needs_review` shells rather than backfilling a state.

### One accepted side effect

`poll-results` does reach MI #1890, CA #1778 and WA #1934 — `results_pending`
elections that still contain Civic orphans — so winner derivation re-runs over
duplicated races more often. This is not new breakage (it already happens daily)
and tonight's 2026-11-03 elections contain no Civic orphans. If the churn is
unwanted, `poll-results` can stay daily until Part 3 has swept, while
`poll-upcoming-results` (which covers tonight) goes live immediately.

### Follow-up

The 221-raceless-election amplification is worth fixing in code: an
election-night poller scoped to elections *with races* on *today's* date would
cut the volume by ~90%. Out of scope for a crontab-only change.

### Revert

Restore `poll-results` to `0 8 * * *` and `poll-upcoming-results` to
`5 8 * * *` once results are certified. The header carries a REVERT note; the
previous "revisit" note went un-actioned for a full cycle, so set a calendar
reminder rather than relying on the comment.

---

## Part 2 — Retire Google Civic (code)

### What the duplication actually was

#2232 is not a Michigan record. It is a **national Civic bucket**.

| | #1891 | #2232 |
|---|---|---|
| name | 2026 Michigan General Election | 2026 General Midterm Election |
| state | `MI` | *(empty)* |
| jurisdiction_level | `state` | `national` |
| canonical_key | `MI:general:2026-11-03:state` | **NULL** |
| source_id | — | `12000` (Civic election id) |
| races | 338 (all `candidate`, `mi_sos`) | 29 (all `civic_api`) |

Civic election `12000` carries `ocdDivisionId = "ocd-division/country:us"` —
confirmed by a live call, not inferred. It is country-scoped, so:

- `parse_state_from_ocd()` → `None`
- `parse_jurisdiction_level()` → `NATIONAL`

`ingest_election` then hits its guard:

```python
if not (state and election_date and election_type and jurisdiction_level):
    # Cannot form a canonical key — keep as its own row, flagged for review.
```

…and #2232 is created with `canonical_key = NULL`. `ingest_race` falls back to
the synthetic prefix `f"e{election.pk}"`, so every race is keyed
`e2232|<office>|NO_OCD|<type>` while #1891's are keyed
`MI:general:2026-11-03:state|<office>|NO_OCD|<type>`.

**The prefixes can never match**, so no Civic race can ever dedupe against a
state-adapter race. `mi_sos` ran at 08:45, found no match, and created its own
copies. That is the whole duplication — inherited from the election row, not
caused by anything about the races.

Because `_representative_addresses_for_election` falls through to a 10-state
sample when `election.state` is empty, and queues every address against the
*same* national election id, #2232 also mixes states. Confirmed in `ops_synclog`
for 2026-11-03 04:00: `MI-capital` wrote 93 records, `VA-capital` 7, the other
eight states 0.

### Why retirement rather than repair

**It is a lossy round-trip of data we already hold.** The project pulls state
feeds directly; those same feeds supply VIP, which supplies Civic. Civic then
strips the state identifier — which is precisely the defect above. Every state
in `_NATIONAL_SAMPLE_STATES` (CA TX NY FL PA OH GA NC MI VA) already has its own
adapter.

**Its one designed role is unfulfilled.** `SourcePrecedence` gives `civic_api`
rank 0 for `contacts` in 13 states — it was kept for candidate photos, bios and
websites. Actual delivery, attributed via `field_provenance`:

| | civic-owned |
|---|---|
| real photos | **13** (of 3,139 total) |
| real websites | **13** |
| real bios | **0** |

**And it actively blocks the better source.** Civic owns *empty* contact fields
on hundreds of candidates:

```
civic_owns_EMPTY_photo   503
civic_owns_EMPTY_site    503
civic_owns_EMPTY_bio     516
```

`_apply_fields` writes only when `incoming <= owner_rank`. Where Civic is rank 0
for contacts and the state adapter rank 1, `1 <= 0` is False — **Civic's empty
string permanently locks the state adapter out of that field.** It squats the
provenance lock and fills nothing.

**Its local data is a sample, not coverage.** `voterinfo` requires a geocodable
street address (a state-level address returns `200` with **0 contests** — tested).
It returns *that precinct's* ballot. #2232's "Michigan" content is Lansing's:
State Senate 21st, State House 77th, 30th Circuit, 54A District, Ingham Probate,
Lansing schools and city measures — one of 110 House districts. Importing that
into #1891 would have implied statewide coverage from a single precinct.

**Nothing depends on it exclusively.** Two states ever had Civic as their sole
race source — WI (24 races, #1938, Aug 11 primary) and LA (2 races, #1943,
Jun 27 primary). Both have registered results adapters. Their adapters simply
had nothing to pull at the time: WI publishes no election-night feed at all (72
independent county clerks; WEC posts one certified XLSX weeks after canvass, and
the listing page 403s to automation, so `Election.source_metadata
["wi_results_xlsx_url"]` must be captured once by hand — it is `{}` today), and
LA is a `ClarityAdapter` subclass awaiting posted results. Civic was filling a
**cadence** gap, not a coverage gap.

### Adapter coverage is complete

`results/adapters/` registers **50 of 50 states** at runtime
(`list_supported_states()`); only DC is absent. Both pollers filter
`state__in=supported`, so every state is already scheduled. Results adapters also
bootstrap races ("auto-bootstraps Race/Candidate/MeasureOption rows from the
result data"), so they are a discovery path too, not only a results path.

2026 production, 34 of 50 states with races:

| tier | states |
|---|---|
| races + results | KY GA NM TX NC PA SC IA VT MA NY WA AR OH CA WV IL FL MN TN HI MD OR AZ CT VA AL MO ME (29) |
| races, **zero** results | **MI (534) UT (96) WI (24) CO (10) LA (2)** |
| no 2026 races | AK DE ID IN KS MS MT ND NE NH NJ NV OK RI SD WY (16) |

### Accepted losses

- **Ballot measures.** `mi_sos` supplies 338 races, all `candidate`, zero
  measures; `va_elect` has 0 races on #1933. Retiring Civic drops the MI
  proposals and the three VA constitutional amendments, which exist only in
  #2232. Measures are explicitly **not in project focus** — accepted as a happy
  accident, not a regression. Worth a separate issue for measure coverage.
- **WI and LA primary races** (26 rows, both past elections) lose their only
  source. Their adapters remain the correct long-term path.

### Retirement steps

All of these are **done** as of commits `3d98c71` and the follow-up cleanup commit.

1. ~~Remove the `0 4 * * *` `sync-elections` crontab entry~~ — done in Part 1;
   that alone stops all new Civic ingestion.
2. ~~Remove `'integrations.civic'` from `INSTALLED_APPS`~~.
3. ~~Remove the trigger route, view, task-lock entry and the
   `elections/management/commands/sync_elections.py` command~~.
4. ~~Delete the `integrations/civic/` package~~.
5. ~~Remove the `CIVIC_*` settings and their `.env.example` block~~. Note
   `integrations/openstates/client.py` was reading `CIVIC_HTTP_TIMEOUT_SECONDS`,
   `CIVIC_MAX_RETRIES` and `CIVIC_RETRY_BACKOFF_SECONDS`; it now has its own
   `OPENSTATES_*` settings with the same defaults.
6. ~~Remove `civic_api` from the orchestrator's `FIELD_PRIORITY` and
   `SOURCE_PRIORITY`~~, and from `ops/views.py`'s `_GLOBAL_SOURCES`.
7. ~~Keep `Race.Source.CIVIC_API` and `SourceRecord.SourceType.CIVIC`~~ so
   historical rows still load; stop writing them.
8. ~~Correct the stale docs and comments~~: `oh_sos` / `nj_elections` docstrings,
   the `va_elect` comment, `DEPLOYMENT.md` (the `civic-api-key` secret and the
   hourly `sync-elections` scheduler job), `API-Reference.md`,
   `endpoint-reference.md`, `openapi.yaml`, `README.md`, `BUILD-PLAN.md`,
   `Sources.md` and `.github/copilot-instructions.md`.

**Database cleanup is deliberately *not* part of this step — it is Part 3.** An
earlier revision listed the contact-lock release and the `SourcePrecedence`
deletions here; they are sequenced last on purpose, because running them while
the source is still live would let the next sync re-create what the sweep
removed. Until Part 3 runs, the 52 `civic_api` precedence rows (including the
`(*, *, 0)` wildcard) and ~516 empty contact locks remain in place. They are
pre-existing conditions, not regressions from the code removal, but they do mean
**no state adapter can yet fill a contact field Civic owns**.

Retirement requires **no merge, no title aliasing, no candidate reconciliation
and no precedence reordering** — the entire risky path in the previous revision
of this document disappears. With Part 1 already applied, nothing in this part
is time-sensitive.

---

## Part 3 — Audit the database for Civic leftovers

Retirement stops new writes; it does not remove what earlier pulls left behind.
The audit below was run read-only against production on 2026-11-03 and should be
re-run after retirement ships, since numbers will have moved.

### What is actually there

**147 Civic races across 9 elections. 139 of them (95%) never merged with
anything.**

| election | state | date | merged | **civic-orphan** |
|---|---|---|---|---|
| #1778 California Primary | CA | 2026-06-02 | 8 | **30** |
| #2232 General Midterm | *(none)* | 2026-11-03 | 0 | **29** |
| #1938 Wisconsin Primary | WI | 2026-08-11 | 0 | **24** |
| #1890 Michigan Primary | MI | 2026-08-04 | 0 | **22** |
| #1888 Maryland Primary | MD | 2026-06-23 | 0 | **17** |
| #1934 Washington Primary | WA | 2026-08-04 | 0 | **12** |
| #1943 Louisiana Primary | LA | 2026-06-27 | 0 | **2** |
| #1928 Utah Primary | UT | 2026-06-23 | 0 | **2** |
| #1932 Virginia Dem Primary | VA | 2026-08-04 | 0 | **1** |

Only California ever merged Civic into state-adapter races, 8 times.

### The leftovers are invisible to exact matching

A query for same-election races sharing a `normalized_office_title`, one Civic
and one not, returns **zero rows**. That is not good news — it means every race
whose title matched *already merged*, and **what remains are precisely the
differently-modeled duplicates that no key comparison will catch.**

Worked example, MI #1890 (August primary):

| source | office | scope |
|---|---|---|
| `mi_sos` | `Governor` | statewide |
| `civic_api` | `Governor — Democratic Primary` | statewide |
| `civic_api` | `Governor — Republican Primary` | statewide |

Same contest, three rows. Note Civic's party-split model is arguably the *more*
correct one for a primary — `mi_sos` collapses both party ballots into a single
`Governor` race, which is exactly what `ingest.py`'s
`aggregation.ingest_race.primary_missing_party` warning exists to flag. Retiring
Civic removes the duplicate and leaves the collapsed `mi_sos` model in place;
**the primary party-split modelling gap in `mi_sos` is a separate issue and
should be filed as one.**

The same shape repeats across the orphan set: `United States Senator —
Democratic/Republican Primary`, `Representative in Congress — D/R Primary`,
`State Senator — D/R Primary`.

### Sampling signature confirms these are not coverage

MI #1890's orphans are Lansing and Detroit only — Ingham County millages,
Capital Area District Library, Wayne County Executive, `CITY OF DETROIT 144,
PRECINCT 06144` convention delegates. That is `MI-capital` + `MI-largest`, the
two representative addresses, not Michigan. Deleting them removes a biased
sample, not coverage.

### Audit scope — what to sweep

1. **Orphan races**: `contributing_sources = ["civic_api"]` → 139 rows. Retire
   with their candidates and `MeasureOption` rows.
2. **Merged races** (`contributing_sources` length > 1, includes `civic_api`) →
   8 rows, CA only. **Do not delete.** Strip `civic_api` from
   `contributing_sources` and reassign any `field_provenance` entries it owns to
   the next-ranked contributing source.
3. **Contact provenance locks**: ~516 candidates where `civic_api` owns an empty
   `image_url` / `website_url` / `description`. Clear those entries so state
   adapters can fill them. This is the one step that *improves* data rather than
   removing it.
4. **Keyless elections**: #2232 (29 races), #2236 (0), #1772 (0) — the three
   `canonical_key IS NULL` rows. Retire as empty `needs_review` shells; keep the
   `Election` rows so `ElectionSourceLink` history survives.
5. **Civic-created election stubs**: #1777, #2226 (AR), #2224 (PA), #2228, #2229
   (SC). Civic created the election row but the races came from
   `results_adapter`. **Keep the elections**; drop only the `civic_api`
   `ElectionSourceLink` and contributing-source entry.
6. **`SourcePrecedence`**: 52 `civic_api` rows including the `(*, *, 0)`
   wildcard.
7. **Post-sweep verification**: re-run the orphan and exact-match queries; both
   should return zero. Confirm no `Race` or `Candidate` row still carries
   `civic_api` in `field_provenance` or `contributing_sources`.

### Audit queries

```sql
-- orphans vs merged, per election
SELECT e.id, e.state, e.name,
  count(*) FILTER (WHERE jsonb_array_length(r.contributing_sources) > 1) AS merged,
  count(*) FILTER (WHERE r.contributing_sources = '["civic_api"]'::jsonb) AS orphan
FROM elections_race r JOIN elections_election e ON e.id = r.election_id
WHERE r.contributing_sources @> '["civic_api"]'::jsonb
GROUP BY 1,2,3 ORDER BY orphan DESC;

-- same-election title collisions (expect 0 before AND after)
SELECT a.election_id, a.office_title, b.office_title, b.source
FROM elections_race a JOIN elections_race b
  ON a.election_id = b.election_id AND a.id <> b.id
 AND a.normalized_office_title = b.normalized_office_title
WHERE a.contributing_sources @> '["civic_api"]'::jsonb
  AND NOT b.contributing_sources @> '["civic_api"]'::jsonb;

-- contact locks held with empty values
SELECT count(*) FROM elections_candidate
WHERE (field_provenance->>'image_url'   = 'civic_api' AND image_url   = '')
   OR (field_provenance->>'website_url' = 'civic_api' AND website_url = '')
   OR (field_provenance->>'description' = 'civic_api' AND description = '');
```

### Execution

A management command with `--dry-run`, transactional and idempotent, reporting
counts per category before and after. Rehearse against a clone (the
`civicmirror-*-test-db` pattern) and run it only after retirement has shipped and
the 04:00 Civic sync is confirmed stopped — otherwise the next sync re-creates
what the sweep removed.

**Do not run this while results are live.** It touches `Race` and `Candidate`
rows in elections that are currently being updated.

---

## Sequencing

1. **Crontab** (Part 1) — do first and immediately. Election-day urgent, no code
   deploy, and it stops new Civic writes in the same edit.
2. **Retire Civic code** (Part 2) — normal branch, normal review. Nothing
   time-sensitive once the crontab entry is gone.
3. **Audit** (Part 3) — last. Must follow retirement, or the next sync re-creates
   what the sweep removed. Dry-run against a clone (the `civicmirror-*-test-db`
   pattern) and do not run it while results are actively landing.

The current branch for Parts 2 and 3 is `chore/retire-google-civic`. Tracking
issue: #229.
