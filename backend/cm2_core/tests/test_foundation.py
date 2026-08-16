import sys

import pytest
from django.conf import settings
from django.db import connection
from django.test import Client

from config import celery_app

LEGACY_APPS = {
    "accounts",
    "aggregation",
    "api",
    "community",
    "elections",
    "internal",
    "ops",
    "results",
    "integrations.nc_sbe",
}


def test_runtime_uses_python_313():
    assert sys.version_info[:2] == (3, 13)


def test_v2_settings_exclude_legacy_apps():
    assert LEGACY_APPS.isdisjoint(settings.INSTALLED_APPS)
    assert "cm2_core" in settings.INSTALLED_APPS
    assert settings.CIVICMIRROR_V2_ENABLED_STATES == ("NC",)
    assert settings.REST_FRAMEWORK["DEFAULT_PAGINATION_CLASS"] is None
    assert settings.REST_FRAMEWORK["PAGE_SIZE"] is None
    assert settings.CELERY_TASK_DEFAULT_QUEUE == "civicmirror_2_0"
    assert celery_app.main == "civicmirror_2_0"


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/health/", "/api/v2/health/"])
def test_health_checks_database_and_reports_v2_runtime(path):
    response = Client().get(path)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "2.0",
        "enabled_states": ["NC"],
    }


@pytest.mark.django_db
def test_v2_database_has_no_legacy_domain_tables():
    tables = set(connection.introspection.table_names())
    expected_domain_tables = {
        "cm2_core_sourceartifact",
        "cm2_elections_jurisdiction",
        "cm2_elections_office",
        "cm2_elections_election",
        "cm2_elections_contest",
        "cm2_elections_person",
        "cm2_elections_personidentifier",
        "cm2_elections_personsourcerecord",
        "cm2_elections_candidacy",
        "cm2_elections_officeterm",
        "cm2_results_contestresult",
        "cm2_results_resultchoice",
        "cm2_review_identityreviewcase",
        "cm2_review_identityreviewsuggestion",
        "cm2_ingestion_synclog",
        "cm2_ingestion_reconciliationreport",
    }
    forbidden_prefixes = (
        "accounts_",
        "aggregation_",
        "community_",
        "elections_",
        "ops_",
        "results_",
    )

    assert expected_domain_tables <= tables
    assert not [table for table in tables if table.startswith(forbidden_prefixes)]
