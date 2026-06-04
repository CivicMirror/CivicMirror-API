"""
Regression tests for idempotency-lock tooling.

These exercise the cache-only paths (no DB), guarding the bug where
``clear_task_locks`` assumed a plain ``YYYY-MM-DD`` window for every task and so
could never clear six-hourly (``sync_fec``) or hourly (``sync_elections``) locks.
"""
from io import StringIO

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings

from internal.task_locks import (
    TASK_LOCKS,
    WINDOW_DAILY,
    WINDOW_HOURLY,
    WINDOW_SIX_HOURLY,
    lock_key,
    windows_for_date,
)


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_windows_for_date_enumerates_each_granularity():
    assert windows_for_date(WINDOW_DAILY, "2026-05-27") == ["2026-05-27"]
    assert windows_for_date(WINDOW_SIX_HOURLY, "2026-05-27") == [
        "2026-05-27T00", "2026-05-27T06", "2026-05-27T12", "2026-05-27T18",
    ]
    assert windows_for_date(WINDOW_HOURLY, "2026-05-27") == [
        f"2026-05-27T{h:02d}" for h in range(24)
    ]


def test_clears_six_hourly_and_hourly_locks():
    """The original bug: six-hourly/hourly locks were never matched and cleared."""
    fec = lock_key("sync_fec", "2026-05-27T12")        # six-hourly bucket
    elections = lock_key("sync_elections", "2026-05-27T16")  # hourly bucket
    daily = lock_key("sync_ca_sos", "2026-05-27")
    for key in (fec, elections, daily):
        cache.add(key, 1, 9999)

    call_command("clear_task_locks", date="2026-05-27", stdout=StringIO())

    assert cache.get(fec) is None
    assert cache.get(elections) is None
    assert cache.get(daily) is None


def test_task_filter_only_clears_named_task():
    co = lock_key("sync_co_sos", "2026-05-27")
    ia = lock_key("sync_ia_sos", "2026-05-27")
    cache.add(co, 1, 9999)
    cache.add(ia, 1, 9999)

    call_command("clear_task_locks", date="2026-05-27", task="sync_co_sos", stdout=StringIO())

    assert cache.get(co) is None
    assert cache.get(ia) == 1  # untouched


def test_unknown_task_filter_reports_error():
    err = StringIO()
    call_command("clear_task_locks", task="not_a_task", stderr=err)
    assert "Unknown task" in err.getvalue()


@override_settings(CACHES={
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-clear-locks-locmem",
    }
})
def test_all_flag_falls_back_gracefully_on_non_redis_backend():
    """LocMem (dev/test) has no scan support; --all must not crash.

    Forces LocMem for this test so it works in environments where the default
    cache is Redis (e.g. CI).
    """
    err = StringIO()
    call_command("clear_task_locks", all=True, stdout=StringIO(), stderr=err)
    assert "requires the Redis cache backend" in err.getvalue()


def test_registry_covers_every_triggered_task():
    """Every task the internal views can trigger must be in the lock registry."""
    expected = {
        "sync_elections", "poll_sc_enr", "sync_sc_enr_results", "sync_fec",
        "sync_openstates", "sync_sc_vrems", "sync_ia_sos", "sync_co_sos",
        "sync_va_elect", "sync_ma_sos", "sync_ca_sos", "sync_az_sos",
        "sync_nc_sbe", "seed_2026_elections", "poll_pending_results",
    }
    assert set(TASK_LOCKS) == expected
