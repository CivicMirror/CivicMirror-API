"""
Tests for Cloudflare Turnstile verification on registration (#202).
"""
from unittest import mock

import pytest
import requests
from django.contrib.auth.models import User
from django.test import Client

from api import turnstile

IP = '203.0.113.10'


@pytest.fixture(autouse=True)
def _settings(settings):
    settings.TURNSTILE_SECRET_KEY = 'test-secret'
    settings.TURNSTILE_EXPECTED_ACTION = 'register'
    settings.CIVICMIRROR_CLIENT_IP_HEADER = 'HTTP_CF_CONNECTING_IP'
    settings.CIVICMIRROR_THROTTLE_RATES = {}


def _siteverify(result=None, exc=None):
    response = mock.Mock()
    response.json.return_value = result if result is not None else {}
    return mock.patch('api.turnstile.requests.post', side_effect=exc, return_value=response)


def _register(client, **data):
    body = {'password': 'pw-for-tests-123', **data}
    return client.post('/api/auth/register/', data=body, content_type='application/json', HTTP_CF_CONNECTING_IP=IP)


# ---------------------------------------------------------------------------
# verify_turnstile
# ---------------------------------------------------------------------------

def test_verify_success_sends_secret_token_and_ip():
    with _siteverify({'success': True, 'action': 'register'}) as post:
        assert turnstile.verify_turnstile('tok', IP) is True
    _, kwargs = post.call_args
    assert kwargs['data'] == {'secret': 'test-secret', 'response': 'tok', 'remoteip': IP}
    assert kwargs['timeout'] == turnstile.TIMEOUT_SECONDS


def test_verify_omits_unknown_ip():
    with _siteverify({'success': True, 'action': 'register'}) as post:
        assert turnstile.verify_turnstile('tok', None) is True
    assert 'remoteip' not in post.call_args.kwargs['data']


def test_verify_rejected_by_cloudflare():
    with _siteverify({'success': False, 'error-codes': ['invalid-input-response']}):
        assert turnstile.verify_turnstile('tok') is False


def test_verify_rejects_wrong_action():
    with _siteverify({'success': True, 'action': 'login'}):
        assert turnstile.verify_turnstile('tok') is False


def test_verify_action_check_can_be_disabled(settings):
    settings.TURNSTILE_EXPECTED_ACTION = ''
    with _siteverify({'success': True, 'action': 'anything'}):
        assert turnstile.verify_turnstile('tok') is True


@pytest.mark.parametrize('exc', [requests.Timeout(), requests.ConnectionError()])
def test_verify_fails_closed_when_cloudflare_unreachable(exc):
    with _siteverify(exc=exc):
        assert turnstile.verify_turnstile('tok') is False


def test_verify_fails_closed_on_bad_json():
    with _siteverify() as post:
        post.return_value.json.side_effect = ValueError('not json')
        assert turnstile.verify_turnstile('tok') is False


@pytest.mark.parametrize('token', ['', None, 123, ['tok'], 'x' * 2049])
def test_verify_rejects_malformed_tokens_without_calling_cloudflare(token):
    with _siteverify({'success': True}) as post:
        assert turnstile.verify_turnstile(token) is False
    post.assert_not_called()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_register_with_valid_token_succeeds():
    with _siteverify({'success': True, 'action': 'register'}) as post:
        response = _register(Client(), turnstile_token='tok')
    assert response.status_code == 201
    assert post.call_args.kwargs['data']['remoteip'] == IP


@pytest.mark.django_db
def test_register_without_token_rejected():
    with _siteverify({'success': True}) as post:
        response = _register(Client())
    assert response.status_code == 400
    assert 'turnstile' in response.json()
    post.assert_not_called()
    assert not User.objects.exists()


@pytest.mark.django_db
def test_register_with_rejected_token_creates_nothing():
    with _siteverify({'success': False, 'error-codes': ['timeout-or-duplicate']}):
        response = _register(Client(), turnstile_token='reused')
    assert response.status_code == 400
    assert not User.objects.exists()


@pytest.mark.django_db
def test_turnstile_checked_before_username_lookup():
    User.objects.create_user(username='taken', password='x')
    with _siteverify({'success': False}):
        response = _register(Client(), username='taken', turnstile_token='bad')
    # A bot without a valid token learns nothing about existing usernames.
    assert 'username' not in response.json()
    assert 'turnstile' in response.json()


@pytest.mark.django_db
def test_register_unaffected_when_turnstile_disabled(settings):
    settings.TURNSTILE_SECRET_KEY = ''
    with _siteverify({'success': False}) as post:
        response = _register(Client())
    assert response.status_code == 201
    post.assert_not_called()


@pytest.mark.django_db
def test_login_does_not_require_turnstile():
    User.objects.create_user(username='member', password='pw-for-tests')
    with _siteverify({'success': False}) as post:
        response = Client().post('/api/auth/login/', data={'username': 'member', 'password': 'pw-for-tests'},
                                 content_type='application/json')
    assert response.status_code == 200
    post.assert_not_called()
