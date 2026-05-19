from unittest.mock import Mock, call, patch

import pytest

from integrations.fec.client import FECAPIForbidden, FECAPIRateLimitError, FECClient


@patch('integrations.fec.client.time.sleep', return_value=None)
def test_list_candidates_sends_expected_params(mock_sleep, settings):
    settings.FEC_API_KEY = 'test-fec-key'
    client = FECClient()
    response = Mock(status_code=200)
    response.json.return_value = {'results': [], 'pagination': {'pages': 1}}

    with patch.object(client.session, 'get', return_value=response) as mock_get:
        payload = client.list_candidates(office='H', state='MA', cycle=2024, page=2)

    assert payload == {'results': [], 'pagination': {'pages': 1}}
    mock_get.assert_called_once_with(
        'https://api.open.fec.gov/v1/candidates/',
        params={
            'office': 'H',
            'state': 'MA',
            'election_year': 2024,
            'per_page': 100,
            'page': 2,
            'api_key': 'test-fec-key',
        },
        timeout=10,
    )


@patch('integrations.fec.client.time.sleep', return_value=None)
def test_list_candidates_raises_forbidden_on_403(mock_sleep, settings):
    settings.FEC_API_KEY = 'test-fec-key'
    client = FECClient()
    with patch.object(client.session, 'get', return_value=Mock(status_code=403)):
        with pytest.raises(FECAPIForbidden):
            client.list_candidates(office='H', state='MA', cycle=2024)


@patch('integrations.fec.client.time.sleep', return_value=None)
def test_list_candidates_raises_rate_limit_on_429(mock_sleep, settings):
    settings.FEC_API_KEY = 'test-fec-key'
    client = FECClient()
    with patch.object(client.session, 'get', return_value=Mock(status_code=429)):
        with pytest.raises(FECAPIRateLimitError):
            client.list_candidates(office='H', state='MA', cycle=2024)


def test_list_candidates_all_pages_concatenates_results(settings):
    settings.FEC_API_KEY = 'test-fec-key'
    client = FECClient()

    with patch.object(
        client,
        'list_candidates',
        side_effect=[
            {'results': [{'candidate_id': 'C1'}], 'pagination': {'pages': 2}},
            {'results': [{'candidate_id': 'C2'}], 'pagination': {'pages': 2}},
        ],
    ) as mock_list_candidates:
        results = client.list_candidates_all_pages(office='S', state='MA', cycle=2024)

    assert results == [{'candidate_id': 'C1'}, {'candidate_id': 'C2'}]
    assert mock_list_candidates.call_args_list == [
        call(office='S', state='MA', cycle=2024, page=1),
        call(office='S', state='MA', cycle=2024, page=2),
    ]
