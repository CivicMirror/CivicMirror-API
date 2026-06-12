import importlib.util
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

try:
    import environ
except ModuleNotFoundError:
    class _FallbackEnv:
        def __init__(self, **schema):
            self.schema = schema

        @staticmethod
        def read_env(path):
            env_path = Path(path)
            if not env_path.exists():
                return
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

        def __call__(self, name, default=None):
            return os.environ.get(name, default)

        def bool(self, name, default=False):
            value = os.environ.get(name)
            if value is None:
                return default
            return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}

        def int(self, name, default=0):
            value = os.environ.get(name)
            return int(value) if value is not None else default

        def float(self, name, default=0.0):
            value = os.environ.get(name)
            return float(value) if value is not None else default

        def db(self, name, default=None):
            value = os.environ.get(name, default)
            if isinstance(value, dict):
                return value
            if not value:
                return {}
            if str(value).startswith('sqlite:///'):
                return {
                    'ENGINE': 'django.db.backends.sqlite3',
                    'NAME': str(value).replace('sqlite:///', '', 1),
                }
            parsed = urlparse(str(value))
            engine_map = {
                'postgres': 'django.db.backends.postgresql',
                'postgresql': 'django.db.backends.postgresql',
            }
            return {
                'ENGINE': engine_map.get(parsed.scheme, 'django.db.backends.sqlite3'),
                'NAME': parsed.path.lstrip('/'),
                'USER': parsed.username or '',
                'PASSWORD': parsed.password or '',
                'HOST': parsed.hostname or '',
                'PORT': parsed.port or '',
            }

    class environ:  # type: ignore[no-redef]
        Env = _FallbackEnv


BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    CIVIC_HTTP_TIMEOUT_SECONDS=(int, 10),
    CIVIC_MAX_RETRIES=(int, 3),
    CIVIC_RETRY_BACKOFF_SECONDS=(float, 1.0),
)
environ.Env.read_env(BASE_DIR / '.env')


HAS_DRF_SPECTACULAR = importlib.util.find_spec('drf_spectacular') is not None
HAS_DJANGO_FILTERS = importlib.util.find_spec('django_filters') is not None
HAS_WHITENOISE = importlib.util.find_spec('whitenoise') is not None
HAS_CORSHEADERS = importlib.util.find_spec('corsheaders') is not None


def _csv_env(name: str, default: Optional[list[str]] = None) -> list[str]:
    value = env(name, default='')
    if isinstance(value, list):
        return value
    if not value:
        return default or []
    return [item.strip() for item in str(value).split(',') if item.strip()]


SECRET_KEY = env('DJANGO_SECRET_KEY', default='django-insecure-change-me-in-production')
DEBUG = env.bool('DJANGO_DEBUG', default=False)
ALLOWED_HOSTS = _csv_env('DJANGO_ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

# CORS — allow the frontend origin(s) to call this API directly.
# In production, set CORS_ALLOWED_ORIGINS env var to a comma-separated list of
# origins, e.g. "https://civicmirror.welshrd.com,https://www.civicmirror.welshrd.com".
# Defaults allow local development only.
CORS_ALLOWED_ORIGINS: list[str] = _csv_env(
    'CORS_ALLOWED_ORIGINS',
    default=['http://localhost:5173', 'http://localhost:4173'],
)
# Allow X-Api-Key header in preflight responses.
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'x-api-key',
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
]
if HAS_DRF_SPECTACULAR:
    INSTALLED_APPS.append('drf_spectacular')
if HAS_DJANGO_FILTERS:
    INSTALLED_APPS.append('django_filters')
if HAS_CORSHEADERS:
    INSTALLED_APPS.append('corsheaders')
INSTALLED_APPS += [
    'elections',
    'aggregation',
    'results',
    'ops',
    'community',
    'integrations.civic',
    'integrations.openstates',
    'integrations.fec',
    'integrations.sc_vrems',
    'integrations.sc_enr',
    'integrations.ia_sos',
    'integrations.co_sos',
    'integrations.va_elect',
    'integrations.ma_sos',
    'integrations.ca_sos',
    'integrations.az_sos',
    'integrations.pa_sos',
    'integrations.nc_sbe',
    'integrations.election_calendar',
    'integrations.wa_pdc',
    'internal',
    'api',
    'accounts',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
]
if HAS_WHITENOISE:
    MIDDLEWARE.append('whitenoise.middleware.WhiteNoiseMiddleware')
if HAS_CORSHEADERS:
    MIDDLEWARE.append('corsheaders.middleware.CorsMiddleware')
MIDDLEWARE += [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    'default': env.db('DATABASE_URL', default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}
DATABASES['default']['ATOMIC_REQUESTS'] = False
DATABASES['default']['CONN_MAX_AGE'] = env.int('DJANGO_CONN_MAX_AGE', default=0)

REDIS_URL = env('REDIS_URL', default='')
if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'civicmirror-api-local',
        }
    }

CELERY_BROKER_URL = env('CELERY_BROKER_URL', default=REDIS_URL or 'redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default=REDIS_URL or 'redis://127.0.0.1:6379/1')
CELERY_TASK_ALWAYS_EAGER = env.bool('CELERY_TASK_ALWAYS_EAGER', default=False)
CELERY_TASK_EAGER_PROPAGATES = env.bool('CELERY_TASK_EAGER_PROPAGATES', default=False)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
# Prefetch 1 task per worker slot — prevents long SC VREMS tasks from hogging the queue
# and avoids the "Restoring N unacknowledged messages" restart doom loop on Cloud Run.
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': (
            'whitenoise.storage.CompressedManifestStaticFilesStorage'
            if HAS_WHITENOISE
            else 'django.contrib.staticfiles.storage.StaticFilesStorage'
        )
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'DEFAULT_PAGINATION_CLASS': 'api.pagination.StandardPagination',
    'PAGE_SIZE': 25,
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PARSER_CLASSES': ['rest_framework.parsers.JSONParser'],
    'DEFAULT_SCHEMA_CLASS': (
        'drf_spectacular.openapi.AutoSchema'
        if HAS_DRF_SPECTACULAR
        else 'rest_framework.schemas.openapi.AutoSchema'
    ),
}
if HAS_DJANGO_FILTERS:
    REST_FRAMEWORK['DEFAULT_FILTER_BACKENDS'] = ['django_filters.rest_framework.DjangoFilterBackend']

SPECTACULAR_SETTINGS = {
    'TITLE': 'CivicMirror API',
    'DESCRIPTION': 'Internal election data aggregation API for CivicMirror.',
    'VERSION': '1.0.0',
    'SCHEMA_PATH_PREFIX': '/api/v1/',
    'SECURITY': [{'ApiKeyAuth': []}],
    'APPEND_COMPONENTS': {
        'securitySchemes': {
            'ApiKeyAuth': {
                'type': 'apiKey',
                'in': 'header',
                'name': 'X-Api-Key',
            }
        }
    },
}

CIVICMIRROR_API_KEY = env('CIVICMIRROR_API_KEY', default='')
INTERNAL_TASK_TOKEN = env('INTERNAL_TASK_TOKEN', default='')
SCHEDULER_OIDC_AUDIENCE = env('SCHEDULER_OIDC_AUDIENCE', default='')
SCHEDULER_SA_EMAIL = env('SCHEDULER_SA_EMAIL', default='')
CIVIC_API_KEY = env('CIVIC_API_KEY', default='')
FEC_API_KEY = env('FEC_API_KEY', default='')
OPENSTATES_API_KEY = env('OPENSTATES_API_KEY', default='')
GITHUB_TOKEN = env('GITHUB_TOKEN', default='')

# Universal Cloudflare Worker proxy (bypasses GCP datacenter IP blocks on
# Akamai/CloudFront-protected election data sites: Iowa SOS, SC ENR, etc.).
# Set CIVICMIRROR_PROXY_URL to the CF Worker URL to enable in production.
# Leave empty in local dev to hit upstream hosts directly.
CIVICMIRROR_PROXY_URL = env('CIVICMIRROR_PROXY_URL', default='')
CIVICMIRROR_PROXY_SECRET = env('CIVICMIRROR_PROXY_SECRET', default='')

# Deprecated — superseded by CIVICMIRROR_PROXY_URL / CIVICMIRROR_PROXY_SECRET.
# Kept until IA SOS adapter migration is verified in production; retire after.
IA_SOS_PROXY_URL = env('IA_SOS_PROXY_URL', default='')
IA_SOS_PROXY_SECRET = env('IA_SOS_PROXY_SECRET', default='')

# Firebase Authentication
FIREBASE_AUTH_ENABLED = env.bool('FIREBASE_AUTH_ENABLED', default=True)
FIREBASE_CREDENTIALS_FILE = env('FIREBASE_CREDENTIALS_FILE', default='')

CIVIC_API_BASE = env('CIVIC_API_BASE', default='https://www.googleapis.com/civicinfo/v2')
CIVIC_HTTP_TIMEOUT_SECONDS = env.int('CIVIC_HTTP_TIMEOUT_SECONDS', default=10)
CIVIC_MAX_RETRIES = env.int('CIVIC_MAX_RETRIES', default=3)
CIVIC_RETRY_BACKOFF_SECONDS = env.float('CIVIC_RETRY_BACKOFF_SECONDS', default=1.0)

_LOG_LEVEL = env('LOG_LEVEL', default='INFO')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
        'elections': {'handlers': ['console'], 'level': _LOG_LEVEL, 'propagate': False},
        'results': {'handlers': ['console'], 'level': _LOG_LEVEL, 'propagate': False},
        'ops': {'handlers': ['console'], 'level': _LOG_LEVEL, 'propagate': False},
        'integrations': {'handlers': ['console'], 'level': _LOG_LEVEL, 'propagate': False},
    },
}
