# Release idempotency locks on terminal task state

**Date:** 2026-05-27
**Status:** Approved
**Area:** `backend/internal/` task triggers & idempotency locks

## Problem

Scheduler-trigger views (`internal/views.py`) acquire a Redis idempotency lock
(`cache.add(key, 1, ttl)`) before enqueuing a Celery task, but nothing ever
releases that lock — it lives for the full TTL (55 min hourly / 6 h six-hourly /
23 h daily). If a task crashes mid-run, its window stays locked until the TTL
expires, so the next scheduled fire (and manual retriggers) are silently skipped
for hours. This is the documented root cause of the recurring "stuck lock"
failures and the reason `clear_task_locks` has to exist.

## Decision

Release the lock when the triggered task reaches a **terminal state — success
or failure** — while keeping it held during the active run and across retry
backoff. Acquisition stays in the view; release happens via a Celery callback.

Rationale (chosen over failure-only release): the lock's real job is "no
concurrent runs," not "ran once today." Releasing on either terminal outcome
fixes stuck-on-crash locks and lets ops re-trigger immediately after a run,
while the lock still blocks overlapping runs for the entire active lifecycle.

## Mechanism

Celery `link` / `link_error` callbacks, verified against Celery 5.6.3 in eager
mode:

- `link` (success) fires once on success.
- `link_error` fires once on **terminal** failure, **0 times** during retries.
- On retry→success: lock held across all retries, released once at the end.

### Components (only `internal/` changes; none of the 12 task modules touched)

1. **`backend/internal/tasks.py`** (new) — `release_task_lock(key)`: a tiny task
   that does `cache.delete(key)`. Idempotent, no DB access.
2. **`backend/internal/views.py`** — `_trigger()` computes the lock key once,
   then enqueues with:
   ```python
   celery_task.apply_async(
       link=release_task_lock.si(key),
       link_error=release_task_lock.si(key),
   )
   ```
   instead of `.delay()`. Immutable `.si()` signatures so each callback receives
   exactly the captured key, regardless of the parent's result/exception.

## Behavior & edge cases

- Lock held during run + retry backoff (critical: `poll_pending_results` has
  `max_retries=12, default_retry_delay=3600` → up to ~12 h of legitimate retries).
- Released exactly once on terminal success or failure.
- **TTL is unchanged** — its role shrinks to a backstop for *hard kills*
  (SIGKILL / OOM / deploy mid-run) where no callback can fire. `clear_task_locks`
  remains the manual recovery for that residual case.
- Lock not acquired → no enqueue, no callback (unchanged `already_running` 202).
- Redis unavailable at release / hard kill → lock persists to TTL (backstop).
- Task crosses a window boundary mid-run → releases the exact key captured at
  enqueue time (correct).

## Testing

Eager-mode tests (cache-only, no DB), via `CELERY_TASK_ALWAYS_EAGER`:

- success → lock released
- terminal failure → lock released
- retry→success → lock held across retries, released once at terminal success
- existing view tests updated: `.delay()` assertions become `.apply_async(...)`
  assertions (the mechanism change requires `apply_async` to attach callbacks).

## Out of scope (YAGNI)

No TTL shortening, no lock renewal/heartbeat, no moving acquisition into tasks,
no base-task-class refactor.
