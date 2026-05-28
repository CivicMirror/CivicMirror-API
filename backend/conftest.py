import os

import django
import pytest
from django.conf import settings


def pytest_configure():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
    if not settings.configured:
        django.setup()


@pytest.fixture(autouse=True)
def _clear_seeded_source_precedence(request):
    """
    Migration ``aggregation.0002_seed_precedence`` populates a Civic-first
    baseline of SourcePrecedence rows in the test database. Many tests
    (precedence/ingest/end-to-end) then call ``SourcePrecedence.objects.create``
    with rows that overlap the seed, raising IntegrityError on Postgres CI.

    Wipe the table before each DB-bound test so each starts from a clean
    slate. Tests that need the seed re-apply it explicitly (the seed helper
    is idempotent via ``update_or_create``).
    """
    db_in_use = "django_db" in request.keywords or any(
        f in request.fixturenames for f in ("db", "transactional_db")
    )
    if not db_in_use:
        return
    # Ensure pytest-django has fully set up DB access before we touch the
    # connection (autouse fixtures otherwise run before django_db setup).
    request.getfixturevalue("db")
    from aggregation.models import SourcePrecedence
    SourcePrecedence.objects.all().delete()
