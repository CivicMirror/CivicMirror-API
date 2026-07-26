import pytest

from api.serializers import ElectionSerializer, RaceDetailSerializer, RaceListSerializer
from elections.models import Candidate, Election, MeasureOption, Race


@pytest.mark.django_db
def test_election_serializer_includes_race_count():
    from django.db.models import Count
    election = Election.objects.create(
        source_id='99001',
        name='Test Election',
        election_date='2026-11-03',
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='CA',
    )
    Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Governor',
        jurisdiction='California',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='civic:99001:gov:ocd:candidate:2026-11-03',
    )
    election_annotated = Election.objects.annotate(race_count=Count('races')).get(pk=election.pk)
    data = ElectionSerializer(election_annotated).data
    assert data['race_count'] == 1


@pytest.mark.django_db
def test_race_detail_serializer_includes_candidates():
    election = Election.objects.create(
        source_id='99002',
        name='Test Election 2',
        election_date='2026-11-03',
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='CA',
    )
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Senator',
        jurisdiction='California',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='civic:99002:senator:ocd:candidate:2026-11-03',
    )
    Candidate.objects.create(race=race, name='Alice')
    Candidate.objects.create(race=race, name='Bob')

    race_prefetched = Race.objects.prefetch_related('candidates', 'measure_options').get(pk=race.pk)
    data = RaceDetailSerializer(race_prefetched).data
    assert len(data['candidates']) == 2
    names = {c['name'] for c in data['candidates']}
    assert names == {'Alice', 'Bob'}


@pytest.mark.django_db
def test_race_list_and_detail_serializers_expose_party_fields():
    """Split partisan primaries (e.g. MA 5th Essex, issue #121) need `party`
    and `normalized_party` on both the list and detail shapes, or the
    frontend's PartyPill works on detail pages but vanishes from list cards."""
    election = Election.objects.create(
        source_id='99003',
        name='Test Primary',
        election_date='2026-09-01',
        election_type=Election.ElectionType.PRIMARY,
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='MA',
    )
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='State Representative',
        jurisdiction='Massachusetts',
        geography_scope='district',
        source=Race.Source.MA_SOS,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='ma:99003:state representative:ocd:candidate:5th essex',
        party='Republican',
        normalized_party='REP',
    )

    list_data = RaceListSerializer(race).data
    detail_data = RaceDetailSerializer(race).data

    assert list_data['party'] == 'Republican'
    assert list_data['normalized_party'] == 'REP'
    assert detail_data['party'] == 'Republican'
    assert detail_data['normalized_party'] == 'REP'


@pytest.mark.django_db
def test_race_detail_serializer_includes_measure_options():
    election = Election.objects.create(
        source_id='99003',
        name='Test Election 3',
        election_date='2026-11-03',
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='CA',
    )
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.MEASURE,
        office_title='Measure A',
        jurisdiction='California',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='civic:99003:measureA:ocd:measure:2026-11-03',
    )
    MeasureOption.objects.create(race=race, option_label='Yes')
    MeasureOption.objects.create(race=race, option_label='No')

    race_prefetched = Race.objects.prefetch_related('candidates', 'measure_options').get(pk=race.pk)
    data = RaceDetailSerializer(race_prefetched).data
    assert len(data['measure_options']) == 2
