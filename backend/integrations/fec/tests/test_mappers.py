from datetime import date
from unittest.mock import patch

from integrations.fec.mappers import current_cycle, fec_office_to_ocd_type, map_candidate


def test_map_candidate_happy_path():
    payload = {
        'candidate_id': 'H4MA07001',
        'name': 'Alex Rivera',
        'office': 'H',
        'office_full': 'U.S. House',
        'state': 'MA',
        'district': '07',
        'party_full': 'Democratic Party',
        'incumbent_challenge_full': 'Incumbent',
        'election_years': [2024],
        'candidate_status': 'C',
    }

    mapped = map_candidate(payload)

    assert mapped['fec_candidate_id'] == 'H4MA07001'
    assert mapped['office_type'] == 'H'
    assert mapped['state'] == 'MA'
    assert mapped['district'] == '07'
    assert mapped['party'] == 'Democratic Party'
    assert mapped['incumbent'] is True
    assert mapped['normalized_office_title'] == 'u.s. house'
    assert mapped['source_metadata']['fec']['candidate_id'] == 'H4MA07001'


def test_map_candidate_returns_none_for_inactive_status():
    payload = {'candidate_id': 'H4MA07001', 'candidate_status': 'N'}
    assert map_candidate(payload) is None


def test_fec_office_to_ocd_type_maps_known_codes():
    assert fec_office_to_ocd_type('H') == 'cd'
    assert fec_office_to_ocd_type('S') == 's'
    assert fec_office_to_ocd_type('P') == ''
    assert fec_office_to_ocd_type('X') == ''


def test_current_cycle_returns_even_year_when_current_year_even():
    with patch('integrations.fec.mappers.date') as mock_date:
        mock_date.today.return_value = date(2026, 5, 1)
        assert current_cycle() == 2026


def test_current_cycle_rounds_up_when_current_year_odd():
    with patch('integrations.fec.mappers.date') as mock_date:
        mock_date.today.return_value = date(2025, 5, 1)
        assert current_cycle() == 2026
