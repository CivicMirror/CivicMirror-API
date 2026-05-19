from datetime import date

import pytest

from elections.models import Candidate, Election, Race
from integrations.orchestrator.candidate_matcher import CandidateMatcher


@pytest.fixture
def base_race():
    election = Election.objects.create(
        name='General Election',
        election_date=date(2026, 11, 3),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='CA',
        source_id='ca-2026-general',
        status=Election.Status.UPCOMING,
    )
    return Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='State Senate District 5',
        jurisdiction='California',
        geography_scope='district',
        source=Race.Source.CIVIC_API,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key='ca-senate-5',
        normalized_office_title='state senate district 5',
    )


@pytest.mark.django_db
def test_enrich_matches_by_external_id(base_race):
    candidate = Candidate.objects.create(race=base_race, name='Alex Smith', fec_candidate_id='H1')
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(base_race, 'fec', 'H1', {'fec_candidate_id': 'H1', 'name': 'Alex Smith', 'party': 'Independent'})

    candidate.refresh_from_db()
    assert matched == candidate
    assert action == 'enriched'
    assert candidate.party == 'Independent'


@pytest.mark.django_db
def test_enrich_matches_by_name_within_race(base_race):
    candidate = Candidate.objects.create(race=base_race, name='Alex Smith')
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(base_race, 'openstates', 'os-1', {'openstates_person_id': 'os-1', 'name': 'Alex Smith'})

    candidate.refresh_from_db()
    assert matched == candidate
    assert action == 'enriched'
    assert candidate.openstates_person_id == 'os-1'


@pytest.mark.django_db
def test_enrich_returns_no_match_when_candidate_not_found(base_race):
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(base_race, 'openstates', 'os-1', {'openstates_person_id': 'os-1', 'name': 'Missing Person'})

    assert matched is None
    assert action == 'no_match'


@pytest.mark.django_db
def test_enrich_respects_field_priority(base_race):
    candidate = Candidate.objects.create(
        race=base_race,
        name='Alex Smith',
        party='Democratic',
        source_metadata={'_field_sources': {'party': 'civic_api'}},
    )
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(base_race, 'openstates', 'os-1', {'openstates_person_id': 'os-1', 'name': 'Alex Smith', 'party': 'Independent'})

    candidate.refresh_from_db()
    assert matched == candidate
    assert action == 'enriched'
    assert candidate.party == 'Democratic'
    assert candidate.openstates_person_id == 'os-1'


@pytest.mark.django_db
def test_enrich_updates_blank_fields(base_race):
    candidate = Candidate.objects.create(race=base_race, name='Alex Smith')
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(base_race, 'openstates', 'os-1', {'name': 'Alex Smith', 'contact_phone': '555-0100'})

    candidate.refresh_from_db()
    assert matched == candidate
    assert action == 'enriched'
    assert candidate.contact_phone == '555-0100'


@pytest.mark.django_db
def test_enrich_returns_skipped_when_nothing_changes(base_race):
    candidate = Candidate.objects.create(
        race=base_race,
        name='Alex Smith',
        openstates_person_id='os-1',
        source_metadata={'openstates': {'external_id': 'os-1'}},
    )
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(base_race, 'openstates', 'os-1', {'openstates_person_id': 'os-1', 'name': 'Alex Smith'})

    assert matched == candidate
    assert action == 'skipped'


@pytest.mark.django_db
def test_enrich_matches_cross_race_from_payload_for_house():
    election = Election.objects.create(
        name='Federal Election',
        election_date=date(2026, 11, 3),
        jurisdiction_level=Election.JurisdictionLevel.NATIONAL,
        state='MA',
        source_id='federal-2026',
        status=Election.Status.UPCOMING,
    )
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='U.S. House District 7',
        jurisdiction='Massachusetts Congressional District 7',
        geography_scope='district',
        source=Race.Source.CIVIC_API,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key='ma-house-7',
        normalized_office_title='u.s. house district 7',
        ocd_division_id='ocd-division/country:us/state:ma/cd:7',
    )
    candidate = Candidate.objects.create(race=race, name='Alex Rivera')
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(None, 'fec', 'H1', {'name': 'Alex Rivera', 'office_type': 'H', 'state': 'MA', 'district': '07'})

    assert matched == candidate
    assert action == 'enriched'


@pytest.mark.django_db
def test_enrich_matches_cross_race_from_payload_for_state_legislature():
    election = Election.objects.create(
        name='State Election',
        election_date=date(2026, 11, 3),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='WA',
        source_id='wa-2026',
        status=Election.Status.UPCOMING,
    )
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='State Senate District 4',
        jurisdiction='Washington',
        geography_scope='district',
        source=Race.Source.CIVIC_API,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key='wa-senate-4',
        normalized_office_title='state senate district 4',
    )
    candidate = Candidate.objects.create(race=race, name='Taylor Jones')
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(None, 'openstates', 'os-9', {'name': 'Taylor Jones', 'state': 'WA', 'chamber': 'upper'})

    assert matched == candidate
    assert action == 'enriched'


@pytest.mark.django_db
def test_enrich_returns_ambiguous_when_multiple_external_id_matches(base_race):
    Candidate.objects.create(race=base_race, name='Alex Smith', fec_candidate_id='H1')
    other_election = Election.objects.create(
        name='Other Election',
        election_date=date(2028, 11, 7),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='CA',
        source_id='ca-2028-general',
        status=Election.Status.UPCOMING,
    )
    other_race = Race.objects.create(
        election=other_election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='State Senate District 5',
        jurisdiction='California',
        geography_scope='district',
        source=Race.Source.CIVIC_API,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key='ca-senate-5-2028',
        normalized_office_title='state senate district 5',
    )
    Candidate.objects.create(race=other_race, name='Alex Smith', fec_candidate_id='H1')
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(base_race, 'fec', 'H1', {'fec_candidate_id': 'H1', 'name': 'Alex Smith'})

    assert matched is None
    assert action == 'ambiguous'
