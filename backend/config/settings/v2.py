from cm2_core.isolation import require_database_name, require_task_queue

from .base import *  # noqa: F401,F403

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
]
if HAS_DRF_SPECTACULAR:
    INSTALLED_APPS.append("drf_spectacular")
if HAS_DJANGO_FILTERS:
    INSTALLED_APPS.append("django_filters")
if HAS_CORSHEADERS:
    INSTALLED_APPS.append("corsheaders")
INSTALLED_APPS.append("cm2_core")
INSTALLED_APPS.append("cm2_elections")
INSTALLED_APPS.append("cm2_results")
INSTALLED_APPS.append("cm2_review")
INSTALLED_APPS.append("cm2_ingestion")
INSTALLED_APPS.append("cm2_nc")

MIDDLEWARE = [
    middleware
    for middleware in MIDDLEWARE
    if middleware != "whitenoise.middleware.WhiteNoiseMiddleware"
]

ROOT_URLCONF = "config.urls_v2"
WSGI_APPLICATION = "config.wsgi_v2.application"
ASGI_APPLICATION = "config.asgi_v2.application"

CIVICMIRROR_V2_ENABLED_STATES = ("NC",)

_configured_database_name = str(DATABASES["default"]["NAME"])
_expected_database_name = env("CIVICMIRROR_V2_DATABASE_NAME", default="civicmirror_2_0")
require_database_name(_configured_database_name, _expected_database_name)

_test_database_name = env("CIVICMIRROR_V2_TEST_DATABASE_NAME", default="civicmirror_2_0_test")
DATABASES["default"].setdefault("TEST", {})["NAME"] = _test_database_name

CELERY_BROKER_URL = env(
    "CELERY_BROKER_URL",
    default=REDIS_URL or "redis://127.0.0.1:6379/2",
)
CELERY_RESULT_BACKEND = env(
    "CELERY_RESULT_BACKEND",
    default="redis://127.0.0.1:6379/3",
)
CELERY_TASK_DEFAULT_QUEUE = env("CIVICMIRROR_V2_TASK_QUEUE", default="civicmirror_2_0")
require_task_queue(CELERY_TASK_DEFAULT_QUEUE)

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_PAGINATION_CLASS": None,
    "PAGE_SIZE": None,
}

SPECTACULAR_SETTINGS = {
    **SPECTACULAR_SETTINGS,
    "TITLE": "CivicMirror API 2.0",
    "VERSION": "2.0.0",
    "SCHEMA_PATH_PREFIX": "/api/v2/",
}
