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
            'current_role': {
                'title': 'Senator',
                'org_classification': 'upper',
                'district': '5',
                'jurisdiction': 'ocd-division/country:us/state:ca/sldu:5',
            },
            'image': 'https://example.com/alex.jpg',
            'links': [{'url': 'https://alex.example.com'}],
            'email': 'alex@example.com',
            'offices': [{'voice': '555-0100', 'address': '123 Capitol Ave'}],
        }
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
    assert mapped['source_metadata']['openstates']['person_id'] == 'os-1'


def test_map_person_returns_none_without_current_role():
    assert map_person({'id': 'os-1', 'name': 'Alex Smith', 'current_role': None}) is None


def test_map_person_extracts_state_from_jurisdiction():
    mapped = map_person(
        {
            'id': 'os-1',
            'name': 'Alex Smith',
            'current_role': {
                'org_classification': 'lower',
                'district': '12',
                'jurisdiction': 'ocd-division/country:us/state:ny/sldl:12',
            },
        }
    )

    assert mapped['state'] == 'NY'


def test_map_person_uses_empty_defaults_when_fields_missing():
    mapped = map_person(
        {
            'id': 'os-2',
            'name': 'Taylor Jones',
            'current_role': {
                'org_classification': 'lower',
                'district': '4',
                'jurisdiction': 'ocd-division/country:us/state:wa/sldl:4',
            },
        }
    )

    assert mapped['party'] == ''
    assert mapped['image_url'] == ''
    assert mapped['website_url'] == ''
    assert mapped['contact_phone'] == ''
    assert mapped['contact_office'] == ''
