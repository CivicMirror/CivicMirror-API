from integrations.openstates.mappers import map_person


def test_map_person_extracts_active_legislator_fields():
    mapped = map_person(
        {
            'id': 'os-1',
            'name': 'Alex Smith',
            'party': [
                {'name': 'Retired Party', 'end_date': '2020-01-01'},
                {'name': 'Democratic', 'end_date': ''},
            ],
            'jurisdiction': {'id': 'ocd-jurisdiction/country:us/state:ca/government', 'name': 'California'},
            'current_role': {
                'title': 'Senator',
                'org_classification': 'upper',
                'district': '5',
            },
            'image': 'https://example.com/alex.jpg',
            'links': [{'url': 'https://alex.example.com'}],
            'email': 'alex@example.com',
            'offices': [{'voice': '555-0100', 'address': '123 Capitol Ave'}],
            'other_names': [{'name': 'A. Smith', 'note': ''}, {'name': 'Alexander Smith', 'note': ''}],
        },
        state='CA',
    )

    assert mapped['openstates_person_id'] == 'os-1'
    assert mapped['party'] == 'Democratic'
    assert mapped['image_url'] == 'https://example.com/alex.jpg'
    assert mapped['website_url'] == 'https://alex.example.com'
    assert mapped['contact_phone'] == '555-0100'
    assert mapped['contact_office'] == '123 Capitol Ave'
    assert mapped['state'] == 'CA'
    assert mapped['chamber'] == 'upper'
    assert mapped['district'] == '5'
    assert mapped['display_name'] == 'Alex Smith'
    assert mapped['other_names'] == ['A. Smith', 'Alexander Smith']
    assert mapped['ocd_division_id'] == ''
    assert mapped['source_metadata']['openstates']['person_id'] == 'os-1'
    assert mapped['source_metadata']['openstates']['jurisdiction'] == 'ocd-jurisdiction/country:us/state:ca/government'


def test_map_person_extracts_ocd_division_id():
    mapped = map_person(
        {
            'id': 'os-1',
            'name': 'Dru Tarr',
            'jurisdiction': {'id': 'ocd-jurisdiction/country:us/state:ma/government', 'name': 'Massachusetts'},
            'current_role': {
                'org_classification': 'lower',
                'district': '5th Essex',
                'division_id': 'ocd-division/country:us/state:ma/sldl:5th_essex',
            },
        },
        state='MA',
    )

    assert mapped['ocd_division_id'] == 'ocd-division/country:us/state:ma/sldl:5th_essex'


def test_map_person_other_names_defaults_to_empty_list():
    mapped = map_person({'id': 'os-1', 'name': 'Alex Smith', 'current_role': None}, state='CA')
    assert mapped['other_names'] == []


def test_map_person_extracts_family_name():
    mapped = map_person(
        {
            'id': 'os-1',
            'name': 'Dru Tarr',
            'given_name': 'Dru',
            'family_name': 'Tarr',
            'current_role': {'org_classification': 'lower', 'district': '5th Essex'},
        },
        state='MA',
    )
    assert mapped['family_name'] == 'Tarr'


def test_map_person_family_name_defaults_to_empty_string():
    mapped = map_person({'id': 'os-1', 'name': 'Alex Smith', 'current_role': None}, state='CA')
    assert mapped['family_name'] == ''


def test_map_person_sets_incumbent_false_without_current_role():
    mapped = map_person({'id': 'os-1', 'name': 'Alex Smith', 'current_role': None}, state='CA')
    assert isinstance(mapped, dict)
    assert mapped['incumbent'] is False
    assert mapped['display_name'] == 'Alex Smith'
    assert mapped['state'] == 'CA'
    assert mapped['chamber'] == ''
    assert mapped['district'] == ''


def test_map_person_uses_queried_state_regardless_of_payload():
    """
    Real OpenStates v3 payloads have no state code inside current_role
    (jurisdiction is a separate top-level dict) — the state the caller
    queried for is the only reliable source. See issue #26.
    """
    mapped = map_person(
        {
            'id': 'os-2',
            'name': 'Taylor Jones',
            'current_role': {
                'org_classification': 'lower',
                'district': '4',
            },
        },
        state='wa',
    )

    assert mapped['state'] == 'WA'
    assert mapped['party'] == ''
    assert mapped['image_url'] == ''
    assert mapped['website_url'] == ''
    assert mapped['contact_phone'] == ''
    assert mapped['contact_office'] == ''
