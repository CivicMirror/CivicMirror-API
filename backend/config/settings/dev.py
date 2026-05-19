from .base import *  # noqa: F401,F403

DEBUG = env.bool('DJANGO_DEBUG', default=True)

if not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ['*']

CELERY_TASK_ALWAYS_EAGER = env.bool('CELERY_TASK_ALWAYS_EAGER', default=True)
CELERY_TASK_EAGER_PROPAGATES = True
