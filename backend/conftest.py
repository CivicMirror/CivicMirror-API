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
    if "aggregation" not in settings.INSTALLED_APPS:
        return

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


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Reset rate-limit counters between tests (the throttle cache is LocMem in dev/test settings)."""
    from django.core.cache import caches
    caches['throttle'].clear()


@pytest.fixture
def make_api_key(db):
    """
    Create (or reuse) a DB-backed service API key whose plaintext is ``raw``, for tests that need a
    known header value. Defaults to read_write with throttling disabled.
    """
    def _make(raw='test-key', access_level='read_write', throttle_rate='none'):
        import secrets

        from api.models import ApiKey, hash_api_key
        api_key, _ = ApiKey.objects.get_or_create(
            hashed_key=hash_api_key(raw),
            defaults={
                'name': f'test key {raw}',
                'prefix': f'cm_{secrets.token_hex(4)}',
                'access_level': access_level,
                'throttle_rate': throttle_rate,
            },
        )
        return api_key
    return _make
