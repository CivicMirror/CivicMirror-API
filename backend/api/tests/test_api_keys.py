"""
Tests for per-client service API keys and access levels (ADR-010, issue #201).
"""
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import Client
from django.utils import timezone
from rest_framework.authtoken.models import Token

from api.models import ApiKey, hash_api_key, prefix_from_raw_key
from elections.models import Election, Race

# Public-participation write endpoints: need any valid key plus an authenticated user.
PUBLIC_WRITE_ENDPOINTS = [
    ('post', '/api/v1/races/{pk}/vote/'),
    ('post', '/api/v1/races/ext/{ext}/vote/'),
    ('post', '/api/v1/races/community/'),
    ('patch', '/api/v1/races/community/{cpk}/'),
    ('delete', '/api/v1/races/community/{cpk}/'),
    ('patch', '/api/v1/users/me/'),
]

DATA_READ_ENDPOINTS = [
    '/api/v1/elections/',
    '/api/v1/races/',
    '/api/v1/ballot-measures/',
    '/api/v1/candidates/',
    '/api/v1/districts/',
]


@pytest.fixture(autouse=True)
def _settings(settings):
    settings.FIREBASE_AUTH_ENABLED = False
    settings.CIVICMIRROR_API_KEY_DEFAULT_RATE = '1000/hour'
    # No cache.clear(): throttle counters are keyed on each key's random prefix, and in CI the
    # default cache is Redis DB 0, shared with Celery.


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def read_key(db):
    return ApiKey.issue(name='Reader', access_level=ApiKey.AccessLevel.READ)


@pytest.fixture
def write_key(db):
    return ApiKey.issue(name='Maintainer', access_level=ApiKey.AccessLevel.READ_WRITE)


@pytest.fixture
def race(db):
    election = Election.objects.create(
        source_id='apikey-test-election',
        name='Key Test Election',
        election_date='2026-11-03',
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='WV',
        status=Election.Status.UPCOMING,
    )
    Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Community Mayor',
        jurisdiction='Charleston',
        geography_scope='local',
        source=Race.Source.COMMUNITY,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='community:apikey:mayor',
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        submitted_by_uid='someone-else',
    )
    return Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Governor',
        jurisdiction='West Virginia',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='civic_api:apikey:governor',
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
    )


@pytest.fixture
def user_token(db):
    user = User.objects.create_user(username='voter', password='pw-for-tests')
    return Token.objects.create(user=user).key


def _url(template, race):
    community = Race.objects.get(source=Race.Source.COMMUNITY, election=race.election)
    return template.format(pk=race.pk, ext=race.canonical_key, cpk=community.pk)


# ---------------------------------------------------------------------------
# Key model
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_issue_stores_only_hash_and_unique_prefix(read_key):
    api_key, raw = read_key
    assert raw.startswith(api_key.prefix + '_')
    assert prefix_from_raw_key(raw) == api_key.prefix
    assert api_key.hashed_key == hash_api_key(raw)
    assert raw not in api_key.hashed_key
    stored = ApiKey.objects.get(pk=api_key.pk)
    assert raw not in {stored.prefix, stored.hashed_key, stored.notes, stored.name}


@pytest.mark.django_db
def test_issued_keys_are_distinct():
    _, raw_a = ApiKey.issue(name='A')
    _, raw_b = ApiKey.issue(name='B')
    assert raw_a != raw_b
    assert len(raw_a.split('_', 2)[2]) >= 40


@pytest.mark.django_db
def test_invalid_throttle_rate_rejected():
    from django.core.exceptions import ValidationError
    with pytest.raises(ValidationError):
        ApiKey.issue(name='Bad', throttle_rate='lots')


# ---------------------------------------------------------------------------
# Data endpoints: access levels
# ---------------------------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize('path', DATA_READ_ENDPOINTS)
def test_read_key_can_read_data(client, read_key, path):
    _, raw = read_key
    assert client.get(path, HTTP_X_API_KEY=raw).status_code == 200


@pytest.mark.django_db
def test_read_key_can_use_lookup(client, read_key):
    _, raw = read_key
    response = client.get('/api/v1/lookup/', {'zip': '25301'}, HTTP_X_API_KEY=raw)
    assert response.status_code != 403


@pytest.mark.django_db
@pytest.mark.parametrize('method', ['post', 'put', 'patch', 'delete'])
def test_read_key_rejected_on_data_writes(client, read_key, race, method):
    _, raw = read_key
    response = getattr(client, method)(f'/api/v1/races/{race.pk}/', HTTP_X_API_KEY=raw)
    assert response.status_code == 403
    assert response.json()['detail'] == 'This API key has read-only access.'


@pytest.mark.django_db
@pytest.mark.parametrize('method', ['post', 'patch', 'delete'])
def test_write_key_passes_key_check_on_data_writes(client, write_key, race, method):
    # Data endpoints are read-only viewsets today, so a permitted write gets 405, not 403.
    _, raw = write_key
    response = getattr(client, method)(f'/api/v1/races/{race.pk}/', HTTP_X_API_KEY=raw)
    assert response.status_code == 405


@pytest.mark.django_db
def test_retired_legacy_setting_grants_nothing(client, settings, read_key):
    # The shared CIVICMIRROR_API_KEY was retired (#201): a leftover value is ignored, DB keys still work.
    settings.CIVICMIRROR_API_KEY = 'leftover-legacy-key'
    _, raw = read_key
    assert client.get('/api/v1/elections/', HTTP_X_API_KEY='leftover-legacy-key').status_code == 403
    assert client.get('/api/v1/elections/', HTTP_X_API_KEY=raw).status_code == 200
    assert client.get('/api/v1/elections/', HTTP_X_API_KEY='').status_code == 403


@pytest.mark.django_db
def test_revoked_key_rejected(client, read_key):
    api_key, raw = read_key
    api_key.is_active = False
    api_key.save()
    assert client.get('/api/v1/elections/', HTTP_X_API_KEY=raw).status_code == 403


@pytest.mark.django_db
def test_expired_key_rejected(client):
    api_key, raw = ApiKey.issue(name='Old', expires_at=timezone.now() + timedelta(days=1))
    ApiKey.objects.filter(pk=api_key.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert client.get('/api/v1/elections/', HTTP_X_API_KEY=raw).status_code == 403


@pytest.mark.django_db
def test_unknown_key_with_valid_shape_rejected(client, read_key):
    api_key, _ = read_key
    forged = f'{api_key.prefix}_not-the-real-secret'
    assert client.get('/api/v1/elections/', HTTP_X_API_KEY=forged).status_code == 403


# ---------------------------------------------------------------------------
# Public participation endpoints
# ---------------------------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize('method,template', PUBLIC_WRITE_ENDPOINTS)
def test_read_key_without_user_gets_401_on_public_writes(client, read_key, race, method, template):
    _, raw = read_key
    response = getattr(client, method)(_url(template, race), data={}, content_type='application/json',
                                       HTTP_X_API_KEY=raw)
    assert response.status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize('method,template', PUBLIC_WRITE_ENDPOINTS)
def test_write_key_without_user_gets_401_on_public_writes(client, write_key, race, method, template):
    _, raw = write_key
    response = getattr(client, method)(_url(template, race), data={}, content_type='application/json',
                                       HTTP_X_API_KEY=raw)
    assert response.status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize('method,template', PUBLIC_WRITE_ENDPOINTS)
def test_public_writes_still_require_a_key(client, user_token, race, method, template):
    response = getattr(client, method)(_url(template, race), data={}, content_type='application/json',
                                       HTTP_AUTHORIZATION=f'Token {user_token}')
    assert response.status_code == 403


@pytest.mark.django_db
def test_read_key_with_user_token_can_update_profile(client, read_key, user_token):
    _, raw = read_key
    response = client.patch('/api/v1/users/me/', data={'display_name': 'Voter'}, content_type='application/json',
                            HTTP_X_API_KEY=raw, HTTP_AUTHORIZATION=f'Token {user_token}')
    assert response.status_code == 200


@pytest.mark.django_db
def test_read_key_with_user_token_passes_key_check_on_vote(client, read_key, user_token, race):
    _, raw = read_key
    response = client.post(f'/api/v1/races/{race.pk}/vote/', data={}, content_type='application/json',
                           HTTP_X_API_KEY=raw, HTTP_AUTHORIZATION=f'Token {user_token}')
    # An empty ballot is a validation error from the voting service, not an auth failure.
    assert response.status_code not in (401, 403)


# ---------------------------------------------------------------------------
# Request attribution, last_used_at, throttling
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_last_used_at_updated_and_rate_limited(client, read_key):
    api_key, raw = read_key
    assert api_key.last_used_at is None
    client.get('/api/v1/elections/', HTTP_X_API_KEY=raw)
    first = ApiKey.objects.get(pk=api_key.pk).last_used_at
    assert first is not None
    client.get('/api/v1/elections/', HTTP_X_API_KEY=raw)
    assert ApiKey.objects.get(pk=api_key.pk).last_used_at == first


@pytest.mark.django_db
def test_access_log_uses_prefix_not_secret(client, read_key, caplog):
    import logging
    api_key, raw = read_key
    access_logger = logging.getLogger('api.access')  # propagate=False, so attach caplog directly
    access_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level('INFO', logger='api.access'):
            client.get('/api/v1/elections/', HTTP_X_API_KEY=raw)
            client.get('/api/v1/elections/', HTTP_X_API_KEY=f'{api_key.prefix}_wrong')
    finally:
        access_logger.removeHandler(caplog.handler)
    assert api_key.prefix in caplog.text
    assert raw not in caplog.text
    assert 'rejected' in caplog.text


@pytest.mark.django_db
def test_throttle_returns_429_per_key(client):
    _, limited = ApiKey.issue(name='Limited', throttle_rate='2/minute')
    _, other = ApiKey.issue(name='Other', throttle_rate='2/minute')
    statuses = [client.get('/api/v1/elections/', HTTP_X_API_KEY=limited).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]
    # Counters are per key.
    assert client.get('/api/v1/elections/', HTTP_X_API_KEY=other).status_code == 200


@pytest.mark.django_db
def test_default_rate_applies_when_key_has_none(client, settings):
    settings.CIVICMIRROR_API_KEY_DEFAULT_RATE = '1/minute'
    _, raw = ApiKey.issue(name='Default')
    assert client.get('/api/v1/elections/', HTTP_X_API_KEY=raw).status_code == 200
    assert client.get('/api/v1/elections/', HTTP_X_API_KEY=raw).status_code == 429


@pytest.mark.django_db
def test_rate_none_disables_throttle(client, settings):
    settings.CIVICMIRROR_API_KEY_DEFAULT_RATE = '1/minute'
    _, raw = ApiKey.issue(name='Unlimited', throttle_rate='none')
    statuses = {client.get('/api/v1/elections/', HTTP_X_API_KEY=raw).status_code for _ in range(3)}
    assert statuses == {200}


@pytest.mark.django_db
def test_shared_frontend_style_key_with_rate_none_is_not_throttled(client, settings):
    # Keys shared by every browser (the FrontEnd's) use throttle_rate='none' so the site isn't limited as a whole.
    settings.CIVICMIRROR_API_KEY_DEFAULT_RATE = '1/minute'
    _, raw = ApiKey.issue(name='frontend-web', throttle_rate='none')
    statuses = {client.get('/api/v1/elections/', HTTP_X_API_KEY=raw).status_code for _ in range(3)}
    assert statuses == {200}


@pytest.mark.django_db
def test_keyless_endpoints_unaffected(client, settings):
    settings.CIVICMIRROR_API_KEY_DEFAULT_RATE = '1/minute'
    for _ in range(3):
        assert client.get('/health/').status_code == 200
        assert client.get('/api/v1/coverage/sync-status/').status_code == 200


# ---------------------------------------------------------------------------
# Management commands and admin
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_list_revoke_commands(client):
    out = StringIO()
    call_command('create_api_key', '--name', 'CivicData', '--access', 'read', stdout=out)
    raw = out.getvalue().strip().splitlines()[-1]
    api_key = ApiKey.objects.get(name='CivicData')
    assert api_key.hashed_key == hash_api_key(raw)
    assert client.get('/api/v1/elections/', HTTP_X_API_KEY=raw).status_code == 200

    listing = StringIO()
    call_command('list_api_keys', stdout=listing)
    assert api_key.prefix in listing.getvalue()
    assert raw not in listing.getvalue()

    call_command('revoke_api_key', api_key.prefix, stdout=StringIO())
    assert client.get('/api/v1/elections/', HTTP_X_API_KEY=raw).status_code == 403
    all_listing = StringIO()
    call_command('list_api_keys', '--all', stdout=all_listing)
    assert 'revoked' in all_listing.getvalue()


@pytest.mark.django_db
def test_create_command_validates_input():
    with pytest.raises(CommandError):
        call_command('create_api_key', '--name', 'X', '--expires', '2000-01-01', stdout=StringIO())
    with pytest.raises(CommandError):
        call_command('create_api_key', '--name', 'X', '--rate', 'fast', stdout=StringIO())
    with pytest.raises(CommandError):
        call_command('revoke_api_key', 'cm_missing', stdout=StringIO())


@pytest.mark.django_db
def test_admin_generates_key_server_side_and_shows_it_once(client, settings):
    settings.STORAGES = {
        **settings.STORAGES,
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
    admin_user = User.objects.create_superuser('admin', 'admin@example.test', 'pw-for-tests')
    client.force_login(admin_user)
    response = client.post('/django-admin/api/apikey/add/', {
        'name': 'Tester', 'owner': '', 'access_level': 'read', 'is_active': 'on',
        'expires_at_0': '', 'expires_at_1': '', 'throttle_rate': '', 'notes': '',
        # Any client-supplied key material must be ignored.
        'prefix': 'cm_attacker', 'hashed_key': 'f' * 64,
    }, follow=True)
    assert response.status_code == 200
    api_key = ApiKey.objects.get(name='Tester')
    assert api_key.prefix != 'cm_attacker'
    assert api_key.hashed_key != 'f' * 64
    shown = [str(m) for m in response.context['messages']]
    assert any(api_key.prefix in m for m in shown)

    # Editing must not regenerate the key.
    original_hash = api_key.hashed_key
    client.post(f'/django-admin/api/apikey/{api_key.pk}/change/', {
        'name': 'Tester renamed', 'owner': '', 'access_level': 'read', 'is_active': 'on',
        'expires_at_0': '', 'expires_at_1': '', 'throttle_rate': '', 'notes': '',
    })
    api_key.refresh_from_db()
    assert api_key.name == 'Tester renamed'
    assert api_key.hashed_key == original_hash
