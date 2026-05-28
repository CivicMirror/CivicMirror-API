"""
Tests for releasing idempotency locks on terminal task state.

The lock is acquired in the trigger view and must be released when the triggered
task terminally succeeds or fails -- but held during the run and across retries.
Cache-only + Celery eager mode, so these run without a DB or broker.
"""
from celery import shared_task
from django.core.cache import cache
from django.test import RequestFactory, override_settings

import internal.views as views
from internal.task_locks import TASK_LOCKS, current_window, lock_key

rf = RequestFactory()

# Shared probe so dummy tasks can report what they observed mid-run.
_PROBE: dict = {"key": None, "seen_during_run": [], "attempts": 0}


def _reset_probe():
    _PROBE["key"] = None
    _PROBE["seen_during_run"] = []
    _PROBE["attempts"] = 0


@shared_task
def _ok_task():
    _PROBE["seen_during_run"].append(cache.get(_PROBE["key"]))
    return "ok"


@shared_task(bind=True)
def _boom_task(self):
    raise ValueError("boom")


@shared_task(bind=True, max_retries=3, default_retry_delay=0)
def _retry_then_ok(self):
    _PROBE["attempts"] += 1
    _PROBE["seen_during_run"].append(cache.get(_PROBE["key"]))
    if _PROBE["attempts"] < 3:
        raise self.retry()
    return "ok"


def _expected_key(task_name):
    window_type, _ = TASK_LOCKS[task_name]
    return lock_key(task_name, current_window(window_type))


import pytest


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    _reset_probe()
    yield
    cache.clear()
    _reset_probe()


def test_release_task_lock_deletes_key():
    from internal.tasks import release_task_lock
    cache.set("task_lock:foo:2026-05-27", 1, 9999)
    release_task_lock("task_lock:foo:2026-05-27")
    assert cache.get("task_lock:foo:2026-05-27") is None


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
def test_trigger_releases_lock_on_success():
    key = _expected_key("sync_ca_sos")
    _PROBE["key"] = key

    resp = views._trigger("sync_ca_sos", _ok_task, rf.post("/"))

    assert resp.status_code == 202
    # held while the task body ran...
    assert _PROBE["seen_during_run"] == [1]
    # ...released once it terminally succeeded
    assert cache.get(key) is None


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
def test_trigger_releases_lock_on_failure():
    key = _expected_key("sync_ma_sos")
    _PROBE["key"] = key

    resp = views._trigger("sync_ma_sos", _boom_task, rf.post("/"))

    assert resp.status_code == 202
    assert cache.get(key) is None


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
def test_trigger_holds_lock_across_retries_then_releases_once():
    key = _expected_key("sync_co_sos")
    _PROBE["key"] = key

    resp = views._trigger("sync_co_sos", _retry_then_ok, rf.post("/"))

    assert resp.status_code == 202
    assert _PROBE["attempts"] == 3
    # lock was present on every attempt, including the retried ones
    assert _PROBE["seen_during_run"] == [1, 1, 1]
    # and released exactly once at terminal success
    assert cache.get(key) is None
