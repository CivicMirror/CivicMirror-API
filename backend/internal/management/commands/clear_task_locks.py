"""
Management command to clear Celery idempotency locks from Redis cache.

Usage:
    python manage.py clear_task_locks                    # clear today's locks
    python manage.py clear_task_locks --date 2026-05-25  # clear specific date
    python manage.py clear_task_locks --all              # clear all task_lock:* keys
"""

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.utils import timezone

_LOCK_PREFIX = "task_lock:"

_DAILY_TASKS = [
    "sync_co_sos",
    "sync_ia_sos",
    "sync_ma_sos",
    "sync_va_elect",
    "sync_ca_sos",
    "poll_pending_results",
]

_SIX_HOURLY_TASKS = [
    "sync_elections",
    "sync_openstates",
    "sync_fec",
    "sync_sc_vrems",
]


class Command(BaseCommand):
    help = "Clear Celery idempotency lock keys from the cache"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            default=None,
            help="Date window to clear (YYYY-MM-DD). Defaults to today.",
        )
        parser.add_argument(
            "--task",
            default=None,
            help="Clear only this specific task name (e.g. sync_co_sos).",
        )

    def handle(self, *args, **options):
        date = options["date"] or timezone.now().strftime("%Y-%m-%d")
        task_filter = options["task"]

        tasks = _DAILY_TASKS + _SIX_HOURLY_TASKS
        if task_filter:
            tasks = [t for t in tasks if t == task_filter]
            if not tasks:
                self.stderr.write(f"Unknown task: {task_filter}")
                return

        cleared = 0
        for task in tasks:
            key = f"{_LOCK_PREFIX}{task}:{date}"
            deleted = cache.delete(key)
            status = "CLEARED" if deleted else "not found"
            self.stdout.write(f"  {key}: {status}")
            if deleted:
                cleared += 1

        self.stdout.write(self.style.SUCCESS(f"\nDone: {cleared}/{len(tasks)} locks cleared for {date}"))
