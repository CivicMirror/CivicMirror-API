from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from integrations.mi_sos.tasks import sync_mi_elections
from integrations.mn_sos.tasks import sync_mn_races
from integrations.or_sos.tasks import sync_or_elections
from internal.task_locks import TASK_LOCKS, current_window, lock_key
from internal.tasks import release_task_lock

LOCAL_TASKS = {
    "sync_mi_sos": sync_mi_elections,
    "sync_mn_sos": sync_mn_races,
    "sync_or_sos": sync_or_elections,
}


class Command(BaseCommand):
    help = "Enqueue a registered internal task for local cron/systemd schedulers."

    def add_arguments(self, parser):
        parser.add_argument("task", choices=sorted(LOCAL_TASKS))

    def handle(self, *args, **options):
        task_name = options["task"]
        celery_task = LOCAL_TASKS[task_name]
        window_type, ttl = TASK_LOCKS[task_name]
        key = lock_key(task_name, current_window(window_type))

        if not cache.add(key, 1, ttl):
            self.stdout.write(f"already_running task={task_name} key={key}")
            return

        try:
            result = celery_task.apply_async(
                link=release_task_lock.si(key),
                link_error=release_task_lock.si(key),
            )
        except Exception as exc:
            cache.delete(key)
            raise CommandError(f"failed to enqueue {task_name}: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"enqueued task={task_name} task_id={result.id} key={key}"))
