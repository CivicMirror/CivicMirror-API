"""
Mark stuck ``SyncLog`` rows as FAILED.

WHY THIS EXISTS
---------------
Before the fix in issue #59, ``sync_pa_elections`` had a bug where retry
exhaustion on a ``PaSosRetryableError`` skipped the code path that gives
``SyncLog`` a terminal status: ``self.retry(exc=exc)`` re-raises the original
exception once ``max_retries`` is hit, and that exception was never caught by
the sibling ``except Exception`` block that marks the row FAILED (only one
except clause runs per try). Every exhausted PA run left its ``SyncLog`` row
stuck in STARTED forever, going back to at least 2026-07-16 (see #59).

The bug is fixed going forward, but past STARTED rows that are old enough to
know they'll never complete need a one-off reconciliation.

SCOPE
-----
Any SyncLog row still STARTED and older than ``--older-than-minutes``
(default 120 — no real sync run takes anywhere near that long) is marked
FAILED with an explanatory note. Defaults to all sources, since the same
retry-exhaustion bug pattern could in principle affect other tasks; pass
``--source``/``--task-name`` to narrow it.
"""

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from ops.models import SyncLog

logger = logging.getLogger(__name__)

_RECONCILE_NOTE = "Reconciled by reconcile_stale_sync_logs: row was stuck in STARTED past the expected run window (see #59)."


class Command(BaseCommand):
    help = (
        "Mark SyncLog rows stuck in STARTED (past a run's expected duration) "
        "as FAILED. One-off fix for the retry-exhaustion bug in #59."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-minutes", type=int, default=120,
            help="Only reconcile STARTED rows started at least this many minutes ago (default: 120).",
        )
        parser.add_argument(
            "--source", default=None,
            help="Restrict to a specific SyncLog.source (e.g. pa_sos). Default: all sources.",
        )
        parser.add_argument(
            "--task-name", default=None,
            help="Restrict to a specific SyncLog.task_name (e.g. sync_pa_elections). Default: all task names.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview what would be reconciled without writing any changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        cutoff = timezone.now() - timezone.timedelta(minutes=options["older_than_minutes"])

        logs = SyncLog.objects.filter(status=SyncLog.Status.STARTED, started_at__lt=cutoff)
        if options["source"]:
            logs = logs.filter(source=options["source"])
        if options["task_name"]:
            logs = logs.filter(task_name=options["task_name"])
        logs = logs.order_by("started_at")

        mode = "DRY RUN" if dry_run else "APPLY"
        self.stdout.write(f"[{mode}] scanning for SyncLog rows STARTED before {cutoff.isoformat()}...")

        count = 0
        for log in logs:
            self.stdout.write(
                f"  id={log.pk} source={log.source!r} task_name={log.task_name!r} "
                f"started_at={log.started_at.isoformat()}"
            )
            count += 1
            if not dry_run:
                log.status = SyncLog.Status.FAILED
                log.error_count = log.error_count or 1
                log.last_error = log.last_error or _RECONCILE_NOTE
                log.completed_at = timezone.now()
                log.save(update_fields=["status", "error_count", "last_error", "completed_at"])

        if dry_run:
            self.stdout.write(self.style.WARNING(f"[DRY RUN] would reconcile {count} row(s). Omit --dry-run to apply."))
        else:
            self.stdout.write(self.style.SUCCESS(f"[APPLY] reconciled {count} row(s)."))
