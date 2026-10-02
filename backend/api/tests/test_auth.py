import pytest
from django.test import Client


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def api_key(make_api_key):
    make_api_key('test-api-key-phase3')
    return 'test-api-key-phase3'


@pytest.mark.django_db
def test_missing_api_key_returns_403(client, api_key):
    response = client.get('/api/v1/elections/')
    assert response.status_code == 403


@pytest.mark.django_db
def test_wrong_api_key_returns_403(client, api_key):
    response = client.get('/api/v1/elections/', HTTP_X_API_KEY='wrong-key')
    assert response.status_code == 403


@pytest.mark.django_db
def test_valid_api_key_returns_200(client, api_key):
    response = client.get('/api/v1/elections/', HTTP_X_API_KEY=api_key)
    assert response.status_code == 200


@pytest.mark.django_db
def test_no_issued_keys_returns_403(client):
    response = client.get('/api/v1/elections/', HTTP_X_API_KEY='anything')
    assert response.status_code == 403


@pytest.mark.django_db
def test_retired_legacy_setting_is_ignored(client, settings):
    # The shared CIVICMIRROR_API_KEY was retired (#201); a leftover env value must not grant access.
    settings.CIVICMIRROR_API_KEY = 'leftover-legacy-key'
    response = client.get('/api/v1/elections/', HTTP_X_API_KEY='leftover-legacy-key')
    assert response.status_code == 403


@pytest.mark.django_db
def test_health_check_requires_no_auth(client):
    response = client.get('/health/')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'
