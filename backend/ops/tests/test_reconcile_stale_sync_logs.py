from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from ops.models import SyncLog


def _make_log(*, source: str, task_name: str, status: str, age_minutes: int) -> SyncLog:
    log = SyncLog.objects.create(source=source, task_name=task_name, status=status)
    SyncLog.objects.filter(pk=log.pk).update(started_at=timezone.now() - timezone.timedelta(minutes=age_minutes))
    return SyncLog.objects.get(pk=log.pk)


@pytest.mark.django_db
def test_reconciles_old_started_rows():
    stale = _make_log(source="pa_sos", task_name="sync_pa_elections", status=SyncLog.Status.STARTED, age_minutes=180)

    call_command("reconcile_stale_sync_logs", stdout=StringIO())

    stale.refresh_from_db()
    assert stale.status == SyncLog.Status.FAILED
    assert stale.completed_at is not None
    assert stale.last_error


@pytest.mark.django_db
def test_leaves_recent_started_rows_alone():
    recent = _make_log(source="pa_sos", task_name="sync_pa_elections", status=SyncLog.Status.STARTED, age_minutes=5)

    call_command("reconcile_stale_sync_logs", stdout=StringIO())

    recent.refresh_from_db()
    assert recent.status == SyncLog.Status.STARTED
    assert recent.completed_at is None


@pytest.mark.django_db
def test_leaves_completed_rows_alone():
    completed = _make_log(source="pa_sos", task_name="sync_pa_elections", status=SyncLog.Status.COMPLETED, age_minutes=180)

    call_command("reconcile_stale_sync_logs", stdout=StringIO())

    completed.refresh_from_db()
    assert completed.status == SyncLog.Status.COMPLETED


@pytest.mark.django_db
def test_dry_run_does_not_write():
    stale = _make_log(source="pa_sos", task_name="sync_pa_elections", status=SyncLog.Status.STARTED, age_minutes=180)

    call_command("reconcile_stale_sync_logs", "--dry-run", stdout=StringIO())

    stale.refresh_from_db()
    assert stale.status == SyncLog.Status.STARTED


@pytest.mark.django_db
def test_source_and_task_name_filters_narrow_scope():
    pa_stale = _make_log(source="pa_sos", task_name="sync_pa_elections", status=SyncLog.Status.STARTED, age_minutes=180)
    other_stale = _make_log(source="ga_sos", task_name="sync_ga_races", status=SyncLog.Status.STARTED, age_minutes=180)

    call_command("reconcile_stale_sync_logs", "--source=pa_sos", "--task-name=sync_pa_elections", stdout=StringIO())

    pa_stale.refresh_from_db()
    other_stale.refresh_from_db()
    assert pa_stale.status == SyncLog.Status.FAILED
    assert other_stale.status == SyncLog.Status.STARTED
