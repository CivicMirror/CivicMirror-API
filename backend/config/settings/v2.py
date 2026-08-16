from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from cm2_core.isolation import require_database_name, require_task_queue

from .base import *  # noqa: F401,F403

INSTALLED_APPS = [
    # cm2_core must precede both "unfold" and the admin config below: it ships
    # templates/admin/index.html, and Django's app-dirs template loader picks
    # the first installed app that defines a given path.
    "cm2_core",
    "unfold",
    "cm2_core.admin_site.CivicMirrorAdminConfig",
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
INSTALLED_APPS.append("cm2_elections")
INSTALLED_APPS.append("cm2_results")
INSTALLED_APPS.append("cm2_review")
INSTALLED_APPS.append("cm2_ingestion")
INSTALLED_APPS.append("cm2_nc")

UNFOLD = {
    "SITE_TITLE": "CivicMirror 2.0",
    "SITE_HEADER": "CivicMirror 2.0",
    "SITE_SUBHEADER": "North Carolina Pilot",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "DASHBOARD_CALLBACK": "cm2_core.dashboard.dashboard_callback",
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True,
        "navigation": [
            {
                "title": _("Review"),
                "collapsible": False,
                "items": [
                    {
                        "title": _("Identity Review Cases"),
                        "icon": "fact_check",
                        "link": reverse_lazy("admin:cm2_review_identityreviewcase_changelist"),
                        "badge": "cm2_core.badges.open_review_case_count",
                        "badge_variant": "danger",
                    },
                    {
                        "title": _("Suggestions"),
                        "icon": "lightbulb",
                        "link": reverse_lazy("admin:cm2_review_identityreviewsuggestion_changelist"),
                    },
                ],
            },
            {
                "title": _("Elections"),
                "collapsible": False,
                "items": [
                    {
                        "title": _("Elections"),
                        "icon": "event",
                        "link": reverse_lazy("admin:cm2_elections_election_changelist"),
                    },
                    {
                        "title": _("Contests"),
                        "icon": "how_to_vote",
                        "link": reverse_lazy("admin:cm2_elections_contest_changelist"),
                    },
                    {
                        "title": _("People"),
                        "icon": "person",
                        "link": reverse_lazy("admin:cm2_elections_person_changelist"),
                    },
                    {
                        "title": _("Candidacies"),
                        "icon": "badge",
                        "link": reverse_lazy("admin:cm2_elections_candidacy_changelist"),
                    },
                ],
            },
            {
                "title": _("Results"),
                "collapsible": False,
                "items": [
                    {
                        "title": _("Contest Results"),
                        "icon": "poll",
                        "link": reverse_lazy("admin:cm2_results_contestresult_changelist"),
                    },
                    {
                        "title": _("Result Choices"),
                        "icon": "checklist",
                        "link": reverse_lazy("admin:cm2_results_resultchoice_changelist"),
                    },
                ],
            },
            {
                "title": _("Reference Data"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Jurisdictions"),
                        "icon": "map",
                        "link": reverse_lazy("admin:cm2_elections_jurisdiction_changelist"),
                    },
                    {
                        "title": _("Offices"),
                        "icon": "work",
                        "link": reverse_lazy("admin:cm2_elections_office_changelist"),
                    },
                    {
                        "title": _("Office Terms"),
                        "icon": "schedule",
                        "link": reverse_lazy("admin:cm2_elections_officeterm_changelist"),
                    },
                    {
                        "title": _("Person Identifiers"),
                        "icon": "fingerprint",
                        "link": reverse_lazy("admin:cm2_elections_personidentifier_changelist"),
                    },
                    {
                        "title": _("Person Source Records"),
                        "icon": "description",
                        "link": reverse_lazy("admin:cm2_elections_personsourcerecord_changelist"),
                    },
                ],
            },
            {
                "title": _("Ingestion & Audit"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Sync Logs"),
                        "icon": "sync",
                        "link": reverse_lazy("admin:cm2_ingestion_synclog_changelist"),
                    },
                    {
                        "title": _("Reconciliation Reports"),
                        "icon": "summarize",
                        "link": reverse_lazy("admin:cm2_ingestion_reconciliationreport_changelist"),
                    },
                    {
                        "title": _("Source Artifacts"),
                        "icon": "source",
                        "link": reverse_lazy("admin:cm2_core_sourceartifact_changelist"),
                    },
                ],
            },
            {
                "title": _("Administration"),
                "collapsible": True,
                "items": [
                    {
                        "title": _("Users"),
                        "icon": "manage_accounts",
                        "link": reverse_lazy("admin:auth_user_changelist"),
                    },
                    {
                        "title": _("Groups"),
                        "icon": "group",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                    },
                ],
            },
        ],
    },
}

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
