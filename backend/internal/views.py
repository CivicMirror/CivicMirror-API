import logging

from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from integrations.az_sos.tasks import sync_az_elections
from integrations.election_calendar.tasks import seed_2026_elections
from integrations.nc_sbe.tasks import sync_nc_elections
from integrations.ca_sos.tasks import sync_ca_elections
from integrations.civic.tasks import sync_elections
from integrations.co_sos.tasks import sync_co_elections
from integrations.fec.tasks import sync_fec_candidates
from integrations.ia_sos.tasks import sync_ia_elections
from integrations.ma_sos.tasks import sync_ma_elections
from integrations.openstates.tasks import sync_openstates_all_states
from integrations.sc_enr.tasks import poll_sc_enr_elections, sync_sc_enr_results
from integrations.sc_vrems.tasks import sync_sc_elections
from integrations.va_elect.tasks import sync_va_elections
from results.tasks import poll_pending_results

from .auth import require_internal_task_token
from .task_locks import TASK_LOCKS, current_window, lock_key
from .tasks import release_task_lock

logger = logging.getLogger(__name__)


def _acquire_lock(task_name: str):
    """
    Try to claim this task's idempotency lock for the current schedule window.

    Returns ``(acquired: bool, key: str)``. The window granularity and TTL come
    from the shared ``TASK_LOCKS`` registry so trigger and clearer stay in sync.
    """
    window_type, ttl = TASK_LOCKS[task_name]
    window = current_window(window_type)
    key = lock_key(task_name, window)
    acquired = cache.add(key, 1, ttl)
    return acquired, key


def _trigger(task_name, celery_task, request):
    """
    Shared trigger body: acquire the lock, enqueue, and arrange for the lock to
    be released when the task terminally finishes (success or failure) via
    Celery link/link_error callbacks. The lock stays held during retries.
    """
    acquired, key = _acquire_lock(task_name)
    if not acquired:
        logger.info("scheduler.trigger.skipped task=%s key=%s", task_name, key)
        return JsonResponse({"status": "already_running"}, status=202)

    try:
        task = celery_task.apply_async(
            link=release_task_lock.si(key),
            link_error=release_task_lock.si(key),
        )
    except Exception:
        cache.delete(key)
        logger.exception(
            "scheduler.trigger.enqueue_failed task=%s key=%s",
            task_name, key,
        )
        return JsonResponse({"status": "enqueue_failed"}, status=503)

    logger.info(
        "scheduler.trigger.enqueued task=%s task_id=%s key=%s",
        task_name, task.id, key,
    )
    return JsonResponse({"task_id": task.id}, status=202)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_elections_trigger(request):
    return _trigger("sync_elections", sync_elections, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def poll_results_trigger(request):
    return _trigger("poll_pending_results", poll_pending_results, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_openstates_trigger(request):
    return _trigger("sync_openstates", sync_openstates_all_states, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_fec_trigger(request):
    return _trigger("sync_fec", sync_fec_candidates, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_sc_vrems_trigger(request):
    return _trigger("sync_sc_vrems", sync_sc_elections, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_ia_sos_trigger(request):
    return _trigger("sync_ia_sos", sync_ia_elections, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_co_sos_trigger(request):
    return _trigger("sync_co_sos", sync_co_elections, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_va_elect_trigger(request):
    return _trigger("sync_va_elect", sync_va_elections, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_ma_sos_trigger(request):
    return _trigger("sync_ma_sos", sync_ma_elections, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def poll_sc_enr_trigger(request):
    return _trigger("poll_sc_enr", poll_sc_enr_elections, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_sc_enr_results_trigger(request):
    return _trigger("sync_sc_enr_results", sync_sc_enr_results, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_ca_sos_trigger(request):
    return _trigger("sync_ca_sos", sync_ca_elections, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def seed_election_calendar_trigger(request):
    return _trigger("seed_2026_elections", seed_2026_elections, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_nc_sbe_trigger(request):
    return _trigger("sync_nc_sbe", sync_nc_elections, request)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_az_sos_trigger(request):
    return _trigger("sync_az_sos", sync_az_elections, request)
