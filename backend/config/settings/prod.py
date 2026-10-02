import warnings

from .base import *  # noqa: F401,F403

DEBUG = False
DATABASES['default']['CONN_MAX_AGE'] = 600
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env.bool('DJANGO_SECURE_SSL_REDIRECT', default=False)

CSRF_TRUSTED_ORIGINS = env.list(
    'DJANGO_CSRF_TRUSTED_ORIGINS',
    default=[
        'https://civicmirror.app',
    ],
)

if not REDIS_URL:  # noqa: F405
    warnings.warn(
        'REDIS_URL is not set: caching and per-API-key rate limits fall back to per-process LocMemCache '
        'and are not shared across workers.',
        RuntimeWarning,
        stacklevel=1,
    )
