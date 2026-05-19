from datetime import date, timedelta

import pytest

from elections.models import DistrictRecord, Election, Race
from integrations.orchestrator.exceptions import AmbiguousMatchError, NoRaceFoundError
from integrations.orchestrator.race_matcher import RaceMatcher


@pytest.mark.django_db
def test_find_or_create_matches_tier_one_by_canonical_key():
    election = Election.objects.create(
        name='General Election',
        election_date=date(2026, 11, 3),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='CA',
        source_id='ca-2026-general',
        status=Election.Status.UPCOMING,
    )
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Governor',
        jurisdiction='California',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key='ca-governor-2026',
        normalized_office_title='governor',
    )

    matched, created = RaceMatcher().find_or_create(
        'civic_api',
        'ext-1',
        {
            'canonical_key': 'ca-governor-2026',
            'office_title': 'Governor',
            'normalized_office_title': 'governor',
            'election_date': date(2026, 11, 3),
            'race_type': Race.RaceType.CANDIDATE,
        },
    )

    assert matched == race
    assert created is False
    assert matched.match_confidence == Race.MatchConfidence.VERIFIED


@pytest.mark.django_db
def test_find_or_create_matches_tier_two_by_ocd_and_date():
    election = Election.objects.create(
        name='Federal Election',
        election_date=date(2026, 11, 3),
        jurisdiction_level=Election.JurisdictionLevel.NATIONAL,
        state='MA',
        source_id='us-2026-general',
        status=Election.Status.UPCOMING,
    )
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='U.S. House',
        jurisdiction='Massachusetts Congressional District 7',
        geography_scope='district',
        source=Race.Source.CIVIC_API,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key='ma-house-7',
        normalized_office_title='u.s. house',
        ocd_division_id='ocd-division/country:us/state:ma/cd:7',
    )

    matched, created = RaceMatcher().find_or_create(
        'fec',
        'H4MA07001',
        {
            'office_title': 'U.S. House',
            'normalized_office_title': 'u.s. house',
            'ocd_division_id': 'ocd-division/country:us/state:ma/cd:7',
            'election_date': date(2026, 11, 3),
            'state': 'MA',
            'race_type': Race.RaceType.CANDIDATE,
        },
    )

    race.refresh_from_db()
    assert matched == race
    assert created is False
    assert race.match_confidence == Race.MatchConfidence.HIGH
    assert race.source_metadata['fec']['external_id'] == 'H4MA07001'


@pytest.mark.django_db
def test_find_or_create_matches_tier_three_using_district_record():
    election = Election.objects.create(
        name='General Election',
        election_date=date(2026, 11, 3),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='WA',
        source_id='wa-2026-general',
        status=Election.Status.UPCOMING,
    )
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='State Senate District 4',
        jurisdiction='District 4',
        geography_scope='district',
        source=Race.Source.CIVIC_API,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key='wa-senate-4',
        normalized_office_title='state senate district 4',
    )
    district = DistrictRecord.objects.create(
        state='WA',
        district_type='sldu',
        district_number='4',
        ocd_division_id='ocd-division/country:us/state:wa/sldu:4',
        name='District 4',
        approximate=False,
    )

    matched, created = RaceMatcher().find_or_create(
        'medsl',
        'race-1',
        {
            'office_title': 'State Senate District 4',
            'normalized_office_title': 'state senate district 4',
            'election_date': date(2026, 11, 3),
            'state': 'WA',
            'jurisdiction': 'District 4',
            'district_number': '4',
            'race_type': Race.RaceType.CANDIDATE,
        },
        district_records=[district],
    )

    assert matched == race
    assert created is False
    assert matched.match_confidence == Race.MatchConfidence.MEDIUM


@pytest.mark.django_db
def test_find_or_create_marks_low_confidence_matches_pending_review():
    election = Election.objects.create(
        name='General Election',
        election_date=date(2026, 11, 3),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='CA',
        source_id='ca-2026-general',
        status=Election.Status.UPCOMING,
    )
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Governor',
        jurisdiction='California',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key='ca-governor-2026',
        normalized_office_title='governor',
    )

    matched, created = RaceMatcher().find_or_create(
        'medsl',
        'ext-1',
        {
            'office_title': 'Governor',
            'normalized_office_title': 'governor',
            'election_date': date(2026, 11, 18),
            'state': 'CA',
            'race_type': Race.RaceType.CANDIDATE,
        },
    )

    race.refresh_from_db()
    assert matched == race
    assert created is False
    assert race.match_confidence == Race.MatchConfidence.LOW
    assert race.race_status == Race.RaceStatus.PENDING_REVIEW


@pytest.mark.django_db
def test_find_or_create_raises_for_enrichment_source_without_match():
    matcher = RaceMatcher()

    with pytest.raises(NoRaceFoundError):
        matcher.find_or_create(
            'openstates',
            'os-1',
            {
                'office_title': 'State Senate District 4',
                'normalized_office_title': 'state senate district 4',
                'election_date': date(2026, 11, 3),
                'state': 'WA',
                'race_type': Race.RaceType.CANDIDATE,
            },
        )


@pytest.mark.django_db
def test_find_or_create_creates_new_race_for_primary_source():
    matched, created = RaceMatcher().find_or_create(
        'medsl',
        'race-9',
        {
            'office_title': 'Secretary of State',
            'normalized_office_title': 'secretary of state',
            'election_date': date(2026, 11, 3),
            'state': 'CA',
            'jurisdiction': 'California',
            'geography_scope': 'statewide',
            'race_type': Race.RaceType.CANDIDATE,
            'canonical_key': 'ca-secretary-of-state-2026',
        },
    )

    assert created is True
    assert matched.office_title == 'Secretary of State'
    assert matched.election.status == Election.Status.UPCOMING


@pytest.mark.django_db
def test_find_or_create_raises_ambiguous_match_when_same_rank_candidates_exist():
    election = Election.objects.create(
        name='General Election',
        election_date=date(2026, 11, 3),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='CA',
        source_id='ca-2026-general',
        status=Election.Status.UPCOMING,
    )
    for index in range(2):
        Race.objects.create(
            election=election,
            race_type=Race.RaceType.CANDIDATE,
            office_title='Governor',
            jurisdiction='California',
            geography_scope='statewide',
            source=Race.Source.CIVIC_API,
            vote_method=Race.VoteMethod.SINGLE_CHOICE,
            canonical_key=f'ca-governor-2026-{index}',
            normalized_office_title='governor',
        )

    with pytest.raises(AmbiguousMatchError):
        RaceMatcher().find_or_create(
            'medsl',
            'ext-2',
            {
                'office_title': 'Governor',
                'normalized_office_title': 'governor',
                'election_date': date(2026, 11, 18),
                'state': 'CA',
                'race_type': Race.RaceType.CANDIDATE,
            },
        )


@pytest.mark.django_db
def test_find_or_create_sets_past_election_status_for_created_election():
    matched, created = RaceMatcher().find_or_create(
        'medsl',
        'race-past',
        {
            'office_title': 'Governor',
            'normalized_office_title': 'governor',
            'election_date': date.today() - timedelta(days=1),
            'state': 'CA',
            'jurisdiction': 'California',
            'geography_scope': 'statewide',
            'race_type': Race.RaceType.CANDIDATE,
            'canonical_key': 'ca-governor-past',
        },
    )

    assert created is True
    assert matched.election.status == Election.Status.RESULTS_PENDING
