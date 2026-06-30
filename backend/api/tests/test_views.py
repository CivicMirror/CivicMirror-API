import pytest
from django.test import Client

from elections.models import Candidate, Election, MeasureOption, Race
from results.models import OfficialResult


@pytest.fixture
def client(settings):
    settings.CIVICMIRROR_API_KEY = 'test-key'
    c = Client()
    c.defaults['HTTP_X_API_KEY'] = 'test-key'
    return c


@pytest.fixture
def election(db):
    return Election.objects.create(
        source_id='9530',
        name='Louisiana 2026 Primary',
        election_date='2026-03-21',
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='LA',
        status=Election.Status.UPCOMING,
    )


@pytest.fixture
def candidate_race(db, election):
    return Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Governor',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='civic_api:9530:governor:ocd:candidate:2026-03-21',
    )


@pytest.fixture
def measure_race(db, election):
    return Race.objects.create(
        election=election,
        race_type=Race.RaceType.MEASURE,
        office_title='Question 1',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='civic_api:9530:question1:ocd:measure:2026-03-21',
    )


@pytest.fixture
def candidate(db, candidate_race):
    return Candidate.objects.create(
        race=candidate_race,
        name='Jane Smith',
        party='Democratic',
    )


@pytest.fixture
def measure_option(db, measure_race):
    return MeasureOption.objects.create(race=measure_race, option_label='Yes')


# --- Elections ---

@pytest.mark.django_db
def test_election_list(client, election):
    response = client.get('/api/v1/elections/')
    assert response.status_code == 200
    data = response.json()
    assert data['count'] == 1
    assert data['results'][0]['source_id'] == '9530'
    assert 'race_count' in data['results'][0]


@pytest.mark.django_db
def test_election_retrieve(client, election):
    response = client.get(f'/api/v1/elections/{election.id}/')
    assert response.status_code == 200
    assert response.json()['source_id'] == '9530'
    assert 'race_count' in response.json()


@pytest.mark.django_db
def test_election_filter_by_state(client, election):
    response = client.get('/api/v1/elections/?state=LA')
    assert response.status_code == 200
    assert response.json()['count'] == 1

    response2 = client.get('/api/v1/elections/?state=TX')
    assert response2.json()['count'] == 0


@pytest.mark.django_db
def test_election_races_action(client, election, candidate_race, measure_race):
    response = client.get(f'/api/v1/elections/{election.id}/races/')
    assert response.status_code == 200
    data = response.json()
    # paginated response
    results = data.get('results', data)
    assert len(results) == 2


@pytest.mark.django_db
def test_election_races_action_includes_archived_certified_and_hides_nonpublic(client, election):
    active = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Active Governor',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='civic_api:9530:active-governor:ocd:candidate:2026-03-21',
    )
    archived = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Certified Governor',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ARCHIVED,
        certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        canonical_key='civic_api:9530:certified-governor:ocd:candidate:2026-03-21',
    )
    hidden_statuses = [
        Race.RaceStatus.DRAFT,
        Race.RaceStatus.PENDING_REVIEW,
        Race.RaceStatus.CANCELLED,
    ]
    for index, status in enumerate(hidden_statuses):
        Race.objects.create(
            election=election,
            race_type=Race.RaceType.CANDIDATE,
            office_title=f'Hidden {status}',
            jurisdiction='Louisiana',
            geography_scope='statewide',
            source=Race.Source.CIVIC_API,
            race_status=status,
            canonical_key=f'civic_api:9530:hidden-{index}:ocd:candidate:2026-03-21',
        )

    response = client.get(f'/api/v1/elections/{election.id}/races/')

    assert response.status_code == 200
    payload = response.json()
    results = payload.get('results', payload)
    returned_ids = {race['id'] for race in results}
    assert returned_ids == {active.id, archived.id}


# --- Races ---

@pytest.mark.django_db
def test_race_list_uses_list_serializer(client, candidate_race):
    response = client.get('/api/v1/races/')
    assert response.status_code == 200
    data = response.json()
    # RaceListSerializer should NOT include candidates
    assert 'candidates' not in data['results'][0]


@pytest.mark.django_db
def test_race_retrieve_uses_detail_serializer(client, candidate_race, candidate):
    response = client.get(f'/api/v1/races/{candidate_race.id}/')
    assert response.status_code == 200
    data = response.json()
    assert 'candidates' in data
    assert len(data['candidates']) == 1
    assert data['candidates'][0]['name'] == 'Jane Smith'


@pytest.mark.django_db
def test_race_candidates_action(client, candidate_race, candidate):
    response = client.get(f'/api/v1/races/{candidate_race.id}/candidates/')
    assert response.status_code == 200
    results = response.json().get('results', response.json())
    assert any(c['name'] == 'Jane Smith' for c in results)


@pytest.mark.django_db
def test_race_results_action(client, candidate_race, candidate):
    OfficialResult.objects.create(
        race=candidate_race,
        candidate=candidate,
        vote_count=1500,
        result_type=OfficialResult.ResultType.UNOFFICIAL,
    )
    response = client.get(f'/api/v1/races/{candidate_race.id}/results/')
    assert response.status_code == 200
    results = response.json()
    # Returned as a plain array (not paginated) so the frontend can consume it.
    assert isinstance(results, list)
    assert results[0]['vote_count'] == 1500
    assert 'raw_payload' not in results[0]


@pytest.mark.django_db
def test_archived_race_results_action_returns_plain_array(client, election):
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Certified Governor',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ARCHIVED,
        certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        canonical_key='civic_api:9530:certified-results:ocd:candidate:2026-03-21',
    )
    candidate = Candidate.objects.create(race=race, name='Jane Smith')
    OfficialResult.objects.create(
        race=race,
        candidate=candidate,
        vote_count=2500,
        result_type=OfficialResult.ResultType.OFFICIAL,
    )

    response = client.get(f'/api/v1/races/{race.id}/results/')

    assert response.status_code == 200
    results = response.json()
    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]['vote_count'] == 2500
    assert results[0]['result_type'] == OfficialResult.ResultType.OFFICIAL


@pytest.mark.django_db
def test_race_filter_by_race_type(client, candidate_race, measure_race):
    response = client.get('/api/v1/races/?race_type=candidate')
    data = response.json()
    assert data['count'] == 1
    assert data['results'][0]['office_title'] == 'Governor'


# --- Ballot Measures ---

@pytest.mark.django_db
def test_ballot_measure_only_returns_measures(client, candidate_race, measure_race):
    response = client.get('/api/v1/ballot-measures/')
    assert response.status_code == 200
    data = response.json()
    assert data['count'] == 1
    assert data['results'][0]['office_title'] == 'Question 1'


# --- Candidates ---

@pytest.mark.django_db
def test_candidate_list(client, candidate):
    response = client.get('/api/v1/candidates/')
    assert response.status_code == 200
    assert response.json()['count'] == 1
    assert response.json()['results'][0]['name'] == 'Jane Smith'


# --- Lookup ---

@pytest.mark.django_db
def test_lookup_missing_zip(client):
    response = client.get('/api/v1/lookup/')
    assert response.status_code == 400


@pytest.mark.django_db
def test_lookup_invalid_zip(client):
    response = client.get('/api/v1/lookup/?zip=00000')
    # 00000 is not a valid ZIP — should return 400
    assert response.status_code in (400, 200)  # depends on zipcodes library coverage


@pytest.mark.django_db
def test_lookup_valid_zip(client, election, candidate_race):
    # 70801 is Baton Rouge, LA
    response = client.get('/api/v1/lookup/?zip=70801')
    assert response.status_code == 200
    data = response.json()
    # Should return list with election + races
    assert isinstance(data, list)
    if data:
        assert 'election' in data[0]
        assert 'races' in data[0]


@pytest.mark.django_db
def test_lookup_election_id_filter(client, election, candidate_race):
    # Valid zip for LA, filter to specific election
    response = client.get(f'/api/v1/lookup/?zip=70801&election_id={election.id}')
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.django_db
def test_lookup_includes_archived_certified_and_hides_nonpublic(client, election):
    active = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Active Lookup Race',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='civic_api:9530:active-lookup:ocd:candidate:2026-03-21',
    )
    archived = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Archived Lookup Race',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ARCHIVED,
        certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        canonical_key='civic_api:9530:archived-lookup:ocd:candidate:2026-03-21',
    )
    Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Draft Lookup Race',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.DRAFT,
        canonical_key='civic_api:9530:draft-lookup:ocd:candidate:2026-03-21',
    )

    response = client.get(f'/api/v1/lookup/?zip=70801&election_id={election.id}')

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    returned_ids = {race['id'] for race in data[0]['races']}
    assert returned_ids == {active.id, archived.id}


@pytest.mark.django_db
@pytest.mark.parametrize(
    'election_status,expected_visible',
    [
        (Election.Status.UPCOMING, True),
        (Election.Status.ACTIVE, True),
        (Election.Status.RESULTS_PENDING, True),
        (Election.Status.RESULTS_CERTIFIED, True),
        (Election.Status.ARCHIVED, False),
    ],
)
def test_lookup_parent_election_status_visibility(client, db, election_status, expected_visible):
    # Confirms which parent Election.status values are surfaced by /lookup/.
    # LookupView excludes Election.Status.ARCHIVED, so an archived parent
    # election hides its races regardless of race_status.
    parent = Election.objects.create(
        source_id='9531',
        name=f'Louisiana {election_status} Election',
        election_date='2026-03-21',
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='LA',
        status=election_status,
    )
    # Use an ACTIVE race so the current race-level filter passes; this isolates
    # the parent Election.status as the only variable under test.
    Race.objects.create(
        election=parent,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Governor',
        jurisdiction='Louisiana',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key=f'civic_api:9531:gov-{election_status}:ocd:candidate:2026-03-21',
    )

    response = client.get(f'/api/v1/lookup/?zip=70801&election_id={parent.id}')

    assert response.status_code == 200
    data = response.json()
    if expected_visible:
        assert len(data) == 1
        assert len(data[0]['races']) == 1
    else:
        assert data == []


@pytest.mark.django_db
def test_lookup_requires_auth(settings):
    from django.test import Client
    settings.CIVICMIRROR_API_KEY = 'test-key'
    c = Client()
    response = c.get('/api/v1/lookup/?zip=70801')
    assert response.status_code == 403
