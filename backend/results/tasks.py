import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def poll_pending_results(self):
    """Stub — implemented in Phase 4. Polls elections for pending results via state adapters."""
    logger.info("poll_pending_results: Phase 4 not yet implemented; no-op.")
    return {"status": "not_implemented"}
