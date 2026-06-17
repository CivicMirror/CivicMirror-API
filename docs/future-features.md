# Future Features & Improvements

A lightweight backlog of ideas surfaced during development that aren't urgent
enough to plan now but are worth remembering. Append new items under **Open**;
move completed ones to **Done** with the commit/PR that shipped them.

Each entry should answer: *what*, *where it'd land in the code*, *why*, and any
*notes / alternatives / caveats* worth keeping handy.

---

## Open

### ~~2026-05-28 — Phase-2 follow-up: results adapters filter by `source`, not `contributing_sources`~~ ✅ FIXED 2026-05-31
**Fixed in:** `backend/results/adapters/ca.py` and `backend/integrations/ca_sos/tasks.py`.
Used `source_metadata__has_key='ca_endpoint'` (portable SQLite + PostgreSQL) rather than
`contributing_sources__contains` (PostgreSQL-only). CA was the only results adapter with
a `Race.source` filter — MA uses `electionstats_id`, VA uses `enr_slug`, CO/IA use
ClarityAdapter (no source filter). Withdrawn-candidate sweep in `sync_ca_races` also fixed.

---

### 2026-05-28 — Phase-2 finish: drop `Election.source_id` and tighten `canonical_key`
**Where:** `backend/elections/models.py` + new migration + small downstream cleanup
in serializers / filters / admin / un-migrated adapters.

**Why:** During the incremental rollout `Election.source_id` was kept
`unique=True, null=True` so un-migrated adapters (sc_vrems, etc.) that
`bulk_create` with `unique_fields=["source_id"]` kept working. Once every adapter
goes through the aggregation ingest, the column has no readers and the unique
constraint is dead weight. Same for `Election.canonical_key`'s `null=True` — it's
a rollout hedge; once every adapter populates it, tighten to `NOT NULL`.

**Notes:**
- Do this **after** the last per-state adapter migration ships.
- Also remove `build_canonical_key()` and the parallel legacy helpers in
  state-specific mappers (civic, ma_sos, etc.).
- Drop `source_id` from the `ElectionSerializer` fields list at the same time.

---

### 2026-05-28 — Show Races inline on the Election admin change page
**Where:** `backend/elections/admin.py` — add a `RaceInline(admin.TabularInline)`
and reference it from `ElectionAdmin.inlines`.

**Why:** When clicking into an Election in Django admin (e.g.
`/admin/elections/election/1779/change/`), there's no way to see that election's
races without bouncing through the Race admin and filtering. An inline list at
the bottom of the Election change page would be much faster for spot-checks
after a sync.

**Notes:**
- ~15-line change. Read-only inline (sync tasks own writes — `can_delete=False`,
  `has_add_permission` returns False, all fields readonly).
- Suggested columns: `office_title`, `race_type`, `source`, `certification_status`,
  `race_status`, `last_synced_at` + `show_change_link=True`.
- Inlines **don't paginate**. CA primary will sit around ~160 races once CA SOS
  Stage-2 finishes — long but fine. If it ever gets unwieldy, the fallback is
  a read-only "N races (view all →)" line that links to a filtered changelist.
- Variant: add a Candidate inline on `RaceAdmin` for the same reason at the
  Race level.

---

### 2026-06-16 — CT + NE: migrate to TotalVote adapter when switchover happens

**Where:** `backend/results/adapters/` — add a thin adapter class per state (CT, NE),
each delegating to the existing TotalVote logic in `ar.py` with a different default `cId`.

**Why:** Both states are in-progress KNOWiNK TotalVote migrations that will eventually
point at the same `enr-results-api.totalresults.com` REST API already used by Arkansas.
The AR adapter already supports arbitrary `cId` values via `Election.source_metadata["totalvote_cid"]`,
so the per-state migration is low-effort (~5 lines + metadata update) once the endpoints go live.

**CT timeline:** Purchased TotalVote from KNOWiNK June 2024 ($1M+). PCC EMS
(`ctemspublic.tgstg.net`) confirmed active through at least Nov 2026. TotalVote
go-live date unannounced. Monitor `ct.totalvote.com` / `enr-results-api.totalresults.com?cId=connecticut`
before the Nov 2026 general. When live, retire `ct.py` (PCC adapter) and switch elections
to the new TotalVote adapter.

**NE timeline:** TotalVote infrastructure provisioned (subdomain + TLS cert exists) but
not yet serving data. Currently on the Clarity adapter (`ne.py`). Monitor
`enr-results-api.totalresults.com?cId=nebraska` (or equivalent slug).

**Migration steps (per state):**
1. Confirm `enr-results-api.totalresults.com/Contest/CheckCurrentVersion?cId=<slug>` returns data.
2. Add a 5-line adapter class (`CTTotalVoteAdapter` / `NETotalVoteAdapter`) mirroring the AR
   adapter with the correct state code and default cId.
3. Update `Election.source_metadata` records to set `totalvote_election_id` (and optionally `totalvote_cid`).
4. For CT: also remove or disable the PCC adapter and scheduler job.

**Notes:**
- The AR adapter (`ar.py`) is the reference implementation — no changes needed there.
- MI has a `michigan.totalvote.com` tenant but it runs a **different legacy backend**
  (`phillyresws.azurewebsites.us`) and is county-level only (Wayne County / Detroit).
  It is NOT compatible with the `enr-results-api.totalresults.com` adapter pattern.
- Future states: St. Louis MO is also a provisioned TotalVote tenant. Same migration
  path applies if/when it goes live.

---

## Done

### 2026-05-28 — Decision: keep non-migrated schedulers paused through Phase 2
**Completed 2026-05-31** — All Phase-2 adapters merged (PRs #3–#9). All 10 paused
schedulers resumed. Phase 2 is complete.

### ~~Phase-2 follow-up: results adapters filter by `source`, not `contributing_sources`~~ ✅ FIXED
See entry above — fixed in `ab79ebe`.
