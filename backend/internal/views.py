import logging

from django.core.cache import cache
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse

from integrations.civic.tasks import sync_elections
from results.tasks import poll_pending_results

from .auth import require_internal_task_token

logger = logging.getLogger(__name__)

_SYNC_ELECTIONS_LOCK_TTL = 55 * 60   # 55 minutes — just under the 1-hour schedule window
_POLL_RESULTS_LOCK_TTL = 23 * 60 * 60  # 23 hours — just under the daily window


def _schedule_window_hourly() -> str:
    return timezone.now().strftime("%Y-%m-%dT%H")


def _schedule_window_daily() -> str:
    return timezone.now().strftime("%Y-%m-%d")


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_elections_trigger(request):
    window = _schedule_window_hourly()
    lock_key = f"task_lock:sync_elections:{window}"

    acquired = cache.add(lock_key, 1, _SYNC_ELECTIONS_LOCK_TTL)
    if not acquired:
        logger.info("scheduler.trigger.skipped task=sync_elections window=%s", window)
        return JsonResponse({"status": "already_running"}, status=202)

    task = sync_elections.delay()
    logger.info("scheduler.trigger.enqueued task=sync_elections task_id=%s window=%s", task.id, window)
    return JsonResponse({"task_id": task.id}, status=202)


@csrf_exempt
@require_POST
@require_internal_task_token
def poll_results_trigger(request):
    window = _schedule_window_daily()
    lock_key = f"task_lock:poll_pending_results:{window}"

    acquired = cache.add(lock_key, 1, _POLL_RESULTS_LOCK_TTL)
    if not acquired:
        logger.info("scheduler.trigger.skipped task=poll_pending_results window=%s", window)
        return JsonResponse({"status": "already_running"}, status=202)

    task = poll_pending_results.delay()
    logger.info("scheduler.trigger.enqueued task=poll_pending_results task_id=%s window=%s", task.id, window)
    return JsonResponse({"task_id": task.id}, status=202)
