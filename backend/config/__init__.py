import os

from .python_version import require_supported_python

require_supported_python()

if os.environ.get("DJANGO_SETTINGS_MODULE") == "config.settings.v2":
    from .celery_v2 import app as celery_app
else:
    # Ensure legacy @shared_task decorators bind to the existing configured app.
    from .celery import app as celery_app

__all__ = ("celery_app",)
