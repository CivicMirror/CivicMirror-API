"""
Shared idempotency-lock helpers.

Single source of truth for task-lock key construction, used by *both*:

  * the internal scheduler-trigger views (``views.py``) — to *acquire* a lock
    for the current schedule window, and
  * the ``clear_task_locks`` management command — to *clear* stuck locks for a
    given date.

Keeping the window granularity + TTL for every task in one registry stops the
trigger and the clearer from drifting apart. Previously the clearer assumed a
plain ``YYYY-MM-DD`` window for every task, which meant ``sync_fec``
(six-hourly) and ``sync_elections`` (hourly) locks could never actually be
cleared because the key format didn't match.
"""
from __future__ import annotations

from django.utils import timezone

LOCK_PREFIX = "task_lock:"

WINDOW_HOURLY = "hourly"
WINDOW_SIX_HOURLY = "six_hourly"
WINDOW_DAILY = "daily"

_HOUR = 60 * 60

# task lock name -> (window granularity, lock TTL in seconds)
# TTLs sit just under the schedule interval so the next window re-acquires cleanly.
TASK_LOCKS: dict[str, tuple[str, int]] = {
    "sync_elections":       (WINDOW_HOURLY,     55 * 60),
    "poll_sc_enr":          (WINDOW_HOURLY,     55 * 60),
    "sync_sc_enr_results":  (WINDOW_HOURLY,     55 * 60),
    "sync_fec":             (WINDOW_SIX_HOURLY, 6 * _HOUR),
    "sync_openstates":      (WINDOW_DAILY,      23 * _HOUR),
    "sync_sc_vrems":        (WINDOW_DAILY,      23 * _HOUR),
    "sync_ia_sos":          (WINDOW_DAILY,      23 * _HOUR),
    "sync_co_sos":          (WINDOW_DAILY,      23 * _HOUR),
    "sync_va_elect":        (WINDOW_DAILY,      23 * _HOUR),
    "sync_ma_sos":          (WINDOW_DAILY,      23 * _HOUR),
    "sync_ca_sos":          (WINDOW_DAILY,      23 * _HOUR),
    "sync_az_sos":          (WINDOW_DAILY,      23 * _HOUR),
    "sync_nc_sbe":          (WINDOW_DAILY,      23 * _HOUR),
    "poll_pending_results": (WINDOW_DAILY,      23 * _HOUR),
}


def current_window(window_type: str, now=None) -> str:
    """Return the lock-window token for the *current* time (used when acquiring)."""
    now = now or timezone.now()
    if window_type == WINDOW_HOURLY:
        return now.strftime("%Y-%m-%dT%H")
    if window_type == WINDOW_SIX_HOURLY:
        bucket = (now.hour // 6) * 6
        return f"{now.strftime('%Y-%m-%d')}T{bucket:02d}"
    if window_type == WINDOW_DAILY:
        return now.strftime("%Y-%m-%d")
    raise ValueError(f"Unknown window type: {window_type}")


def windows_for_date(window_type: str, date_str: str) -> list[str]:
    """
    Return every possible lock-window token for a ``YYYY-MM-DD`` date (used when
    clearing). A stuck hourly/six-hourly lock could sit in any bucket of the
    day, so we enumerate all of them.
    """
    if window_type == WINDOW_HOURLY:
        return [f"{date_str}T{hour:02d}" for hour in range(24)]
    if window_type == WINDOW_SIX_HOURLY:
        return [f"{date_str}T{bucket:02d}" for bucket in (0, 6, 12, 18)]
    if window_type == WINDOW_DAILY:
        return [date_str]
    raise ValueError(f"Unknown window type: {window_type}")


def lock_key(task_name: str, window: str) -> str:
    return f"{LOCK_PREFIX}{task_name}:{window}"
