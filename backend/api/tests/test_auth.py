import pytest
from django.test import Client, override_settings


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def api_key(settings):
    settings.CIVICMIRROR_API_KEY = 'test-api-key-phase3'
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
@override_settings(CIVICMIRROR_API_KEY='')
def test_empty_configured_key_returns_403(client):
    response = client.get('/api/v1/elections/', HTTP_X_API_KEY='anything')
    assert response.status_code == 403


@pytest.mark.django_db
def test_health_check_requires_no_auth(client):
    response = client.get('/health/')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'
