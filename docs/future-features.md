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

## Done

### 2026-05-28 — Decision: keep non-migrated schedulers paused through Phase 2
**Completed 2026-05-31** — All Phase-2 adapters merged (PRs #3–#9). All 10 paused
schedulers resumed. Phase 2 is complete.

### ~~Phase-2 follow-up: results adapters filter by `source`, not `contributing_sources`~~ ✅ FIXED
See entry above — fixed in `ab79ebe`.
