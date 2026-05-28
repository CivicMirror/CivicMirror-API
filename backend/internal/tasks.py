"""Celery tasks supporting the internal scheduler-trigger machinery."""
import logging

from celery import shared_task
from django.core.cache import cache

logger = logging.getLogger(__name__)


@shared_task
def release_task_lock(lock_key: str):
    """
    Release an idempotency lock acquired by a scheduler-trigger view.

    Attached as both the ``link`` (success) and ``link_error`` (terminal
    failure) callback of a triggered task, so the lock is freed the moment the
    task finishes either way — but stays held during the run and across retries
    (``link_error`` does not fire on retry). The lock's TTL remains only as a
    backstop for hard kills where no callback can run.
    """
    cache.delete(lock_key)
    logger.info("scheduler.lock.released lock_key=%s", lock_key)
