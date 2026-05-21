# Ensure the Celery app is always imported when Django starts so that
# @shared_task decorators bind to our configured app (not the default).
from .celery import app as celery_app  # noqa: F401

__all__ = ('celery_app',)
