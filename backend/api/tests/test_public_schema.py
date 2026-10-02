"""
The public API docs (/api/docs/) and schema (/api/schema/) must publish only the versioned public API.
"""
import pytest
import yaml
from django.test import Client


@pytest.fixture
def schema_paths():
    response = Client().get('/api/schema/')
    assert response.status_code == 200
    return set(yaml.safe_load(response.content)['paths'])


@pytest.mark.django_db
def test_schema_excludes_auth_internal_alias_and_self(schema_paths):
    assert schema_paths, 'schema unexpectedly empty'
    assert all(path.startswith('/api/v1/') for path in schema_paths), sorted(schema_paths)
    for forbidden in ('/api/auth/login/', '/api/auth/register/', '/api/auth/logout/',
                      '/api/users/me/profile/', '/api/schema/', '/api/elections/'):
        assert forbidden not in schema_paths
    assert not any(path.startswith('/internal/') for path in schema_paths)


@pytest.mark.django_db
def test_schema_includes_public_data_endpoints(schema_paths):
    for expected in ('/api/v1/elections/', '/api/v1/races/{id}/results/', '/api/v1/candidates/',
                     '/api/v1/districts/', '/api/v1/lookup/', '/api/v1/coverage/sync-status/'):
        assert expected in schema_paths


@pytest.mark.django_db
def test_schema_documents_api_key_header():
    schema = yaml.safe_load(Client().get('/api/schema/').content)
    scheme = schema['components']['securitySchemes']['ApiKeyAuth']
    assert (scheme['type'], scheme['in'], scheme['name']) == ('apiKey', 'header', 'X-Api-Key')
    assert 'Internal' not in schema['info']['description']


@pytest.mark.django_db
def test_swagger_ui_is_public_without_debug(settings):
    settings.DEBUG = False
    response = Client().get('/api/docs/')
    assert response.status_code == 200
    assert b'swagger-ui' in response.content.lower()


def test_is_public_path():
    from api.schema import is_public_path
    assert is_public_path('/api/v1/races/')
    assert not is_public_path('/api/races/')
    assert not is_public_path('/api/auth/login/')
    assert not is_public_path('/internal/tasks/sync-elections/')


@pytest.mark.django_db
def test_schema_excludes_participation_endpoints(schema_paths):
    for hidden in ('/api/v1/races/{id}/vote/', '/api/v1/races/ext/{external_id}/vote/',
                   '/api/v1/races/{id}/tally/', '/api/v1/races/ext/{external_id}/tally/',
                   '/api/v1/races/community/', '/api/v1/races/community/{id}/',
                   '/api/v1/users/me/', '/api/v1/users/votes/'):
        assert hidden not in schema_paths
    assert not any('/vote/' in p or '/tally/' in p or '/users/' in p or '/community/' in p for p in schema_paths)
