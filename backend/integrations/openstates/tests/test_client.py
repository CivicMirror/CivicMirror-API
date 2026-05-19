from unittest.mock import Mock, patch

import pytest

from integrations.openstates.client import OpenStatesClient, OpenStatesForbiddenError, OpenStatesRateLimitError


@patch('integrations.openstates.client.requests.Session.get')
def test_list_people_sends_expected_params(mock_get, settings):
    settings.OPENSTATES_API_KEY = 'test-key'
    response = Mock(status_code=200)
    response.json.return_value = {'results': [], 'pagination': {'page': 1, 'max_page': 1}}
    response.raise_for_status = Mock()
    mock_get.return_value = response

    payload = OpenStatesClient().list_people('CA')

    assert payload == {'results': [], 'pagination': {'page': 1, 'max_page': 1}}
    _, kwargs = mock_get.call_args
    assert kwargs['params']['jurisdiction'] == 'ocd-division/country:us/state:ca'
    assert kwargs['params']['apikey'] == 'test-key'
    assert kwargs['params']['api_key'] == 'test-key'
    assert kwargs['timeout'] == 10


def test_list_people_requires_api_key(settings):
    settings.OPENSTATES_API_KEY = ''
    with pytest.raises(OpenStatesForbiddenError):
        OpenStatesClient().list_people('CA')


@patch('integrations.openstates.client.requests.Session.get')
def test_list_people_raises_rate_limit_error_on_429(mock_get, settings):
    settings.OPENSTATES_API_KEY = 'test-key'
    mock_get.return_value = Mock(status_code=429)

    with pytest.raises(OpenStatesRateLimitError):
        OpenStatesClient().list_people('CA')


@patch.object(OpenStatesClient, 'list_people')
def test_list_people_all_pages_returns_flat_results(mock_list_people):
    mock_list_people.side_effect = [
        {'results': [{'id': 'one'}], 'pagination': {'page': 1, 'max_page': 2}},
        {'results': [{'id': 'two'}], 'pagination': {'page': 2, 'max_page': 2}},
    ]

    results = OpenStatesClient().list_people_all_pages('CA')

    assert results == [{'id': 'one'}, {'id': 'two'}]
    assert mock_list_people.call_count == 2
