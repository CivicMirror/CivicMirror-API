from .base import *  # noqa: F401,F403

DEBUG = env.bool('DJANGO_DEBUG', default=True)

if not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ['*']

CELERY_TASK_ALWAYS_EAGER = env.bool('CELERY_TASK_ALWAYS_EAGER', default=True)
CELERY_TASK_EAGER_PROPAGATES = True

# Keep rate-limit counters in process memory in dev/test, even when REDIS_URL is set (CI), so tests can
# clear them without touching the Redis DB that Celery shares.
CACHES['throttle'] = {  # noqa: F405
    'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    'LOCATION': 'civicmirror-api-throttle',
}
