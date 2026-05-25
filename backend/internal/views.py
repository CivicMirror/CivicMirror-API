import logging

from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from integrations.civic.tasks import sync_elections
from integrations.co_sos.tasks import sync_co_elections
from integrations.fec.tasks import sync_fec_candidates
from integrations.ia_sos.tasks import sync_ia_elections
from integrations.openstates.tasks import sync_openstates_all_states
from integrations.sc_vrems.tasks import sync_sc_elections
from results.tasks import poll_pending_results

from .auth import require_internal_task_token

logger = logging.getLogger(__name__)

_SYNC_ELECTIONS_LOCK_TTL = 55 * 60   # 55 minutes — just under the 1-hour schedule window
_POLL_RESULTS_LOCK_TTL = 23 * 60 * 60  # 23 hours — just under the daily window
_SYNC_OPENSTATES_LOCK_TTL = 23 * 60 * 60  # 23 hours — just under the daily window
_SYNC_FEC_LOCK_TTL = 6 * 60 * 60  # 6 hours — on-demand trigger dedupe window
_SYNC_SC_VREMS_LOCK_TTL = 23 * 60 * 60  # 23 hours — daily cadence
_SYNC_IA_SOS_LOCK_TTL = 23 * 60 * 60  # 23 hours — daily cadence
_SYNC_CO_SOS_LOCK_TTL = 23 * 60 * 60  # 23 hours — daily cadence


def _schedule_window_hourly() -> str:
    return timezone.now().strftime("%Y-%m-%dT%H")


def _schedule_window_daily() -> str:
    return timezone.now().strftime("%Y-%m-%d")


def _schedule_window_six_hourly() -> str:
    now = timezone.now()
    bucket = (now.hour // 6) * 6
    return f"{now.strftime('%Y-%m-%d')}T{bucket:02d}"


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


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_openstates_trigger(request):
    window = _schedule_window_daily()
    lock_key = f"task_lock:sync_openstates:{window}"

    acquired = cache.add(lock_key, 1, _SYNC_OPENSTATES_LOCK_TTL)
    if not acquired:
        logger.info("scheduler.trigger.skipped task=sync_openstates window=%s", window)
        return JsonResponse({"status": "already_running"}, status=202)

    task = sync_openstates_all_states.delay()
    logger.info("scheduler.trigger.enqueued task=sync_openstates task_id=%s window=%s", task.id, window)
    return JsonResponse({"task_id": task.id}, status=202)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_fec_trigger(request):
    window = _schedule_window_six_hourly()
    lock_key = f"task_lock:sync_fec:{window}"

    acquired = cache.add(lock_key, 1, _SYNC_FEC_LOCK_TTL)
    if not acquired:
        logger.info("scheduler.trigger.skipped task=sync_fec window=%s", window)
        return JsonResponse({"status": "already_running"}, status=202)

    task = sync_fec_candidates.delay()
    logger.info("scheduler.trigger.enqueued task=sync_fec task_id=%s window=%s", task.id, window)
    return JsonResponse({"task_id": task.id}, status=202)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_sc_vrems_trigger(request):
    window = _schedule_window_daily()
    lock_key = f"task_lock:sync_sc_vrems:{window}"

    acquired = cache.add(lock_key, 1, _SYNC_SC_VREMS_LOCK_TTL)
    if not acquired:
        logger.info("scheduler.trigger.skipped task=sync_sc_vrems window=%s", window)
        return JsonResponse({"status": "already_running"}, status=202)

    task = sync_sc_elections.delay()
    logger.info("scheduler.trigger.enqueued task=sync_sc_vrems task_id=%s window=%s", task.id, window)
    return JsonResponse({"task_id": task.id}, status=202)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_ia_sos_trigger(request):
    window = _schedule_window_daily()
    lock_key = f"task_lock:sync_ia_sos:{window}"

    acquired = cache.add(lock_key, 1, _SYNC_IA_SOS_LOCK_TTL)
    if not acquired:
        logger.info("scheduler.trigger.skipped task=sync_ia_sos window=%s", window)
        return JsonResponse({"status": "already_running"}, status=202)

    task = sync_ia_elections.delay()
    logger.info("scheduler.trigger.enqueued task=sync_ia_sos task_id=%s window=%s", task.id, window)
    return JsonResponse({"task_id": task.id}, status=202)


@csrf_exempt
@require_POST
@require_internal_task_token
def sync_co_sos_trigger(request):
    window = _schedule_window_daily()
    lock_key = f"task_lock:sync_co_sos:{window}"

    acquired = cache.add(lock_key, 1, _SYNC_CO_SOS_LOCK_TTL)
    if not acquired:
        logger.info("scheduler.trigger.skipped task=sync_co_sos window=%s", window)
        return JsonResponse({"status": "already_running"}, status=202)

    task = sync_co_elections.delay()
    logger.info("scheduler.trigger.enqueued task=sync_co_sos task_id=%s window=%s", task.id, window)
    return JsonResponse({"task_id": task.id}, status=202)
