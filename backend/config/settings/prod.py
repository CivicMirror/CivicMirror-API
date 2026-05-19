from .base import *  # noqa: F401,F403

DEBUG = False
DATABASES['default']['CONN_MAX_AGE'] = 600
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env.bool('DJANGO_SECURE_SSL_REDIRECT', default=False)
