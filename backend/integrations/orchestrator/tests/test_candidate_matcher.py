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
def test_enrich_matches_by_other_names_when_primary_name_differs(base_race):
    """OpenStates' primary `name` can be a display nickname (e.g. 'Dru Tarr')
    while the ballot/legal name ('Andrew Tarr') only appears in other_names."""
    candidate = Candidate.objects.create(race=base_race, name='Andrew Tarr')
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(
        base_race, 'openstates', 'os-1',
        {
            'name': 'Dru Tarr',
            'other_names': ['A. Tarr', 'Andrew Tarr'],
            'openstates_person_id': 'os-1',
        },
    )

    assert matched == candidate
    assert action == 'enriched'


@pytest.mark.django_db
def test_enrich_ignores_other_names_when_primary_name_already_matches(base_race):
    """Primary name is tried first; other_names shouldn't cause a second,
    unnecessary lookup when the first one already matched."""
    candidate = Candidate.objects.create(race=base_race, name='Alex Smith')
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(
        base_race, 'openstates', 'os-1',
        {'name': 'Alex Smith', 'other_names': ['Someone Else'], 'openstates_person_id': 'os-1'},
    )

    assert matched == candidate
    assert action == 'enriched'


@pytest.mark.django_db
def test_enrich_matches_by_last_name_when_full_name_and_other_names_fail(base_race):
    """Real case behind issue #26: OpenStates' name ('Dru Tarr') and every
    other_names variant ('A. Tarr', 'A.F.R. Tarr', 'D. Tarr') still don't
    exact-match the ballot name ('Andrew Francis Robert Tarr') — only the
    structured family_name field ('Tarr') does."""
    candidate = Candidate.objects.create(race=base_race, name='Andrew Francis Robert Tarr')
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(
        base_race, 'openstates', 'os-1',
        {
            'name': 'Dru Tarr',
            'other_names': ['A. Tarr', 'A.F.R. Tarr', 'D. Tarr'],
            'family_name': 'Tarr',
            'openstates_person_id': 'os-1',
        },
    )

    assert matched == candidate
    assert action == 'enriched'


@pytest.mark.django_db
def test_enrich_returns_ambiguous_when_last_name_collides_within_race(base_race):
    """Two candidates sharing a surname in the same race must not be guessed
    at — same safety net as the existing full-name ambiguity checks."""
    Candidate.objects.create(race=base_race, name='Andrew Tarr')
    Candidate.objects.create(race=base_race, name='Elizabeth Tarr')
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(
        base_race, 'openstates', 'os-1',
        {'name': 'Dru Tarr', 'family_name': 'Tarr', 'openstates_person_id': 'os-1'},
    )

    assert matched is None
    assert action == 'ambiguous'


@pytest.mark.django_db
def test_enrich_last_name_fallback_does_not_match_different_surname(base_race):
    Candidate.objects.create(race=base_race, name='Andrew Tarr')
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(
        base_race, 'openstates', 'os-2',
        {'name': 'Jamie Nobody', 'family_name': 'Nobody', 'openstates_person_id': 'os-2'},
    )

    assert matched is None
    assert action == 'no_match'


@pytest.mark.django_db
def test_enrich_matches_last_name_cross_race_from_payload_for_state_legislature():
    election = Election.objects.create(
        name='State Election',
        election_date=date(2026, 11, 3),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='MA',
        source_id='ma-2026',
        status=Election.Status.UPCOMING,
    )
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='State Representative 5th Essex',
        jurisdiction='5th Essex',
        geography_scope='district',
        source=Race.Source.CIVIC_API,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key='ma-house-5th-essex',
        normalized_office_title='state representative 5th essex',
    )
    candidate = Candidate.objects.create(race=race, name='Andrew Francis Robert Tarr')
    matcher = CandidateMatcher()

    matched, action = matcher.enrich(
        None, 'openstates', 'os-1',
        {
            'name': 'Dru Tarr',
            'other_names': ['A.F.R. Tarr'],
            'family_name': 'Tarr',
            'state': 'MA',
            'chamber': 'lower',
        },
    )

    assert matched == candidate
    assert action == 'enriched'


@pytest.mark.django_db
def test_enrich_backfills_blank_race_ocd_division_id(base_race):
    assert base_race.ocd_division_id == ''
    Candidate.objects.create(race=base_race, name='Alex Smith')
    matcher = CandidateMatcher()

    matcher.enrich(
        base_race, 'openstates', 'os-1',
        {
            'name': 'Alex Smith',
            'ocd_division_id': 'ocd-division/country:us/state:ca/sldu:5',
        },
    )

    base_race.refresh_from_db()
    assert base_race.ocd_division_id == 'ocd-division/country:us/state:ca/sldu:5'


@pytest.mark.django_db
def test_enrich_does_not_overwrite_existing_race_ocd_division_id(base_race):
    base_race.ocd_division_id = 'ocd-division/country:us/state:ca/sldu:5-original'
    base_race.save(update_fields=['ocd_division_id'])
    Candidate.objects.create(race=base_race, name='Alex Smith')
    matcher = CandidateMatcher()

    matcher.enrich(
        base_race, 'openstates', 'os-1',
        {'name': 'Alex Smith', 'ocd_division_id': 'ocd-division/country:us/state:ca/sldu:5-different'},
    )

    base_race.refresh_from_db()
    assert base_race.ocd_division_id == 'ocd-division/country:us/state:ca/sldu:5-original'


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
