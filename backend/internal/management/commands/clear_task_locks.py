"""
Management command to clear Celery idempotency locks from the Redis cache.

Usage:
    python manage.py clear_task_locks                    # clear today's locks (all tasks)
    python manage.py clear_task_locks --date 2026-05-25  # clear a specific date
    python manage.py clear_task_locks --task sync_co_sos # clear one task only
    python manage.py clear_task_locks --all              # clear every task_lock:* key (any date)

Lock-window formats vary by task cadence (daily / six-hourly / hourly), so the
keys are built from the shared ``TASK_LOCKS`` registry rather than assuming a
plain date — otherwise six-hourly (``sync_fec``) and hourly (``sync_elections``)
locks would never match and could not be cleared.
"""

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.utils import timezone

from internal.task_locks import LOCK_PREFIX, TASK_LOCKS, lock_key, windows_for_date


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
            help="Clear only this task name (e.g. sync_co_sos).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Clear every task_lock:* key regardless of date (requires Redis backend).",
        )

    def handle(self, *args, **options):
        if options["all"]:
            self._clear_all()
            return

        date = options["date"] or timezone.now().strftime("%Y-%m-%d")
        task_filter = options["task"]

        if task_filter:
            if task_filter not in TASK_LOCKS:
                self.stderr.write(
                    f"Unknown task: {task_filter} "
                    f"(known: {', '.join(sorted(TASK_LOCKS))})"
                )
                return
            tasks = [task_filter]
        else:
            tasks = list(TASK_LOCKS)

        cleared = 0
        for task in tasks:
            window_type, _ = TASK_LOCKS[task]
            windows = windows_for_date(window_type, date)
            task_cleared = 0
            for window in windows:
                key = lock_key(task, window)
                if cache.delete(key):
                    self.stdout.write(f"  {key}: CLEARED")
                    cleared += 1
                    task_cleared += 1
            if task_cleared == 0:
                # Show a representative key so output is non-empty and greppable.
                self.stdout.write(f"  {lock_key(task, windows[0])}: not found")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone: {cleared} lock(s) cleared across {len(tasks)} task(s) for {date}"
            )
        )

    def _clear_all(self):
        """Scan-and-delete every ``task_lock:*`` key directly via the Redis client."""
        try:
            client = cache._cache.get_client(write=True)
        except AttributeError:
            # Non-Redis backend (e.g. LocMemCache in dev) has no scan support —
            # fall back to clearing today's registered locks.
            self.stderr.write(
                "--all requires the Redis cache backend; "
                "falling back to today's registered locks."
            )
            self.handle(date=None, task=None, all=False)
            return

        match = cache.make_key(f"{LOCK_PREFIX}*")
        cleared = 0
        for raw in client.scan_iter(match=match):
            client.delete(raw)
            key = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
            self.stdout.write(f"  {key}: CLEARED")
            cleared += 1

        self.stdout.write(
            self.style.SUCCESS(f"\nDone: {cleared} task_lock key(s) cleared (--all)")
        )
