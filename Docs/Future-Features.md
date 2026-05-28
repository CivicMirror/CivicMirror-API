# Future Features & Improvements

A lightweight backlog of ideas surfaced during development that aren't urgent
enough to plan now but are worth remembering. Append new items under **Open**;
move completed ones to **Done** with the commit/PR that shipped them.

Each entry should answer: *what*, *where it'd land in the code*, *why*, and any
*notes / alternatives / caveats* worth keeping handy.

---

## Open

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

(none yet — move entries here with the commit/PR SHA when shipped)
