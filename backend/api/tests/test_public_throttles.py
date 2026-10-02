"""
Tests for public-participation rate limits (#202).
"""
import logging

import pytest
from django.contrib.auth.models import User
from django.test import Client, RequestFactory
from rest_framework.authtoken.models import Token

from api.models import ApiKey
from api.throttling import get_client_ip
from elections.models import Election, Race

LEGACY_KEY = 'legacy-test-key'
IP_A = '203.0.113.10'
IP_B = '198.51.100.20'


@pytest.fixture(autouse=True)
def _settings(settings):
    settings.CIVICMIRROR_API_KEY = LEGACY_KEY
    settings.FIREBASE_AUTH_ENABLED = False
    settings.CIVICMIRROR_CLIENT_IP_HEADER = 'HTTP_CF_CONNECTING_IP'
    settings.CIVICMIRROR_CLIENT_IP_XFF_PROXIES = 0
    settings.CIVICMIRROR_THROTTLE_RATES = {
        'register_ip': '2/hour',
        'login_ip': '3/hour',
        'login_username': '2/hour',
        'vote_user': '2/hour',
        'vote_ip': '3/hour',
        'community_create_user': '1/day',
        'community_create_ip': '2/day',
    }


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def race(db):
    election = Election.objects.create(
        source_id='throttle-test-election',
        name='Throttle Test Election',
        election_date='2026-11-03',
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='WV',
        status=Election.Status.UPCOMING,
    )
    return Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Governor',
        jurisdiction='West Virginia',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='civic_api:throttle:governor',
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
    )


def _token(username):
    user = User.objects.create_user(username=username, password='pw-for-tests')
    return Token.objects.create(user=user).key


def _register(client, ip=None, **extra):
    headers = {'HTTP_CF_CONNECTING_IP': ip} if ip else {}
    return client.post('/api/auth/register/', data={'password': 'pw-for-tests-123'},
                       content_type='application/json', **headers, **extra)


def _login(client, username, ip=None):
    headers = {'HTTP_CF_CONNECTING_IP': ip} if ip else {}
    return client.post('/api/auth/login/', data={'username': username, 'password': 'wrong'},
                       content_type='application/json', **headers)


def _vote(client, race, token, ip=None, key=LEGACY_KEY):
    headers = {'HTTP_CF_CONNECTING_IP': ip} if ip else {}
    return client.post(f'/api/v1/races/{race.pk}/vote/', data={}, content_type='application/json',
                       HTTP_X_API_KEY=key, HTTP_AUTHORIZATION=f'Token {token}', **headers)


# ---------------------------------------------------------------------------
# Client IP resolution
# ---------------------------------------------------------------------------

def _request(**meta):
    return RequestFactory().get('/', **meta)


def test_client_ip_from_cloudflare_header():
    assert get_client_ip(_request(HTTP_CF_CONNECTING_IP=IP_A, REMOTE_ADDR='172.18.0.5')) == IP_A


def test_client_ip_ignores_remote_addr_and_unconfigured_xff():
    assert get_client_ip(_request(REMOTE_ADDR='172.18.0.5', HTTP_X_FORWARDED_FOR=IP_A)) is None


def test_client_ip_rejects_garbage_header():
    assert get_client_ip(_request(HTTP_CF_CONNECTING_IP='not-an-ip')) is None


def test_client_ip_normalizes_ipv6():
    assert get_client_ip(_request(HTTP_CF_CONNECTING_IP='2001:DB8::0001')) == '2001:db8::1'


def test_client_ip_xff_fallback_uses_nth_from_right(settings):
    settings.CIVICMIRROR_CLIENT_IP_XFF_PROXIES = 2
    # A spoofed left-most entry is ignored: the real client is 2nd from the right.
    xff = f'1.2.3.4, {IP_A}, 172.18.0.1'
    assert get_client_ip(_request(HTTP_X_FORWARDED_FOR=xff)) == IP_A
    assert get_client_ip(_request(HTTP_X_FORWARDED_FOR='172.18.0.1')) is None


def test_client_ip_header_disabled(settings):
    settings.CIVICMIRROR_CLIENT_IP_HEADER = ''
    assert get_client_ip(_request(HTTP_CF_CONNECTING_IP=IP_A)) is None


# ---------------------------------------------------------------------------
# Registration and login
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_register_throttled_per_ip(client):
    statuses = [_register(client, IP_A).status_code for _ in range(3)]
    assert statuses == [201, 201, 429]
    response = _register(client, IP_A)
    assert response.status_code == 429
    assert 'Retry-After' in response.headers
    # Another client IP has its own bucket.
    assert _register(client, IP_B).status_code == 201


@pytest.mark.django_db
def test_register_without_resolvable_ip_is_not_throttled_and_warns(client, caplog):
    access_logger = logging.getLogger('api.access')
    access_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level('INFO', logger='api.access'):
            statuses = {_register(client).status_code for _ in range(4)}
    finally:
        access_logger.removeHandler(caplog.handler)
    assert statuses == {201}
    assert 'client_ip=unresolved' in caplog.text


@pytest.mark.django_db
def test_register_rate_none_disables(client, settings):
    settings.CIVICMIRROR_THROTTLE_RATES = {**settings.CIVICMIRROR_THROTTLE_RATES, 'register_ip': 'none'}
    assert {_register(client, IP_A).status_code for _ in range(4)} == {201}


@pytest.mark.django_db
def test_login_throttled_per_ip(client):
    statuses = [_login(client, f'user{i}', IP_A).status_code for i in range(4)]
    assert statuses == [400, 400, 400, 429]


@pytest.mark.django_db
def test_login_throttled_per_username_across_ips(client):
    statuses = [_login(client, 'Victim', ip).status_code for ip in (IP_A, IP_B, '192.0.2.30')]
    assert statuses == [400, 400, 429]
    # Username matching is case-insensitive.
    assert _login(client, 'victim', '192.0.2.31').status_code == 429


@pytest.mark.django_db
def test_login_with_non_object_body_does_not_crash(client):
    response = client.post('/api/auth/login/', data='["x"]', content_type='application/json',
                           HTTP_CF_CONNECTING_IP=IP_A)
    assert response.status_code < 500


@pytest.mark.django_db
def test_auth_attempts_log_resolved_client_ip(client, caplog):
    access_logger = logging.getLogger('api.access')
    access_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level('INFO', logger='api.access'):
            _login(client, 'someone', IP_A)
    finally:
        access_logger.removeHandler(caplog.handler)
    assert f'scope=login_ip client_ip={IP_A}' in caplog.text


# ---------------------------------------------------------------------------
# Mock voting and community submissions
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_vote_throttled_per_user(client, race):
    token = _token('voter1')
    statuses = [_vote(client, race, token).status_code for _ in range(3)]
    assert statuses[-1] == 429
    assert 429 not in statuses[:2]


@pytest.mark.django_db
def test_vote_throttled_per_ip_across_users(client, race):
    tokens = [_token(f'voter{i}') for i in range(4)]
    statuses = [_vote(client, race, token, ip=IP_A).status_code for token in tokens]
    assert statuses[-1] == 429
    assert 429 not in statuses[:3]


@pytest.mark.django_db
def test_vote_without_user_is_401_not_throttled(client, race):
    for _ in range(4):
        response = client.post(f'/api/v1/races/{race.pk}/vote/', data={}, content_type='application/json',
                               HTTP_X_API_KEY=LEGACY_KEY, HTTP_CF_CONNECTING_IP=IP_A)
        assert response.status_code in (401, 429)
    # Anonymous attempts still count toward the IP backstop, but never toward a user bucket.
    token = _token('fresh')
    assert _vote(client, race, token).status_code != 429


@pytest.mark.django_db
def test_tally_reads_are_not_throttled(client, race):
    for _ in range(6):
        response = client.get(f'/api/v1/races/{race.pk}/tally/', HTTP_X_API_KEY=LEGACY_KEY,
                              HTTP_CF_CONNECTING_IP=IP_A)
        assert response.status_code == 200


@pytest.mark.django_db
def test_community_create_throttled_per_user(client):
    token = _token('submitter')
    statuses = [
        client.post('/api/v1/races/community/', data={}, content_type='application/json',
                    HTTP_X_API_KEY=LEGACY_KEY, HTTP_AUTHORIZATION=f'Token {token}').status_code
        for _ in range(2)
    ]
    assert statuses[0] != 429
    assert statuses[1] == 429


@pytest.mark.django_db
def test_api_key_throttle_still_applies_on_public_views(client, race):
    _, raw = ApiKey.issue(name='Tester', throttle_rate='1/minute')
    token = _token('keyed-voter')
    first = _vote(client, race, token, key=raw)
    second = client.get(f'/api/v1/races/{race.pk}/tally/', HTTP_X_API_KEY=raw)
    assert first.status_code != 429
    assert second.status_code == 429
