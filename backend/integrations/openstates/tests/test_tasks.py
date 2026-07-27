from datetime import date
from unittest.mock import Mock, patch

import pytest
from celery.exceptions import Retry

from elections.models import Candidate, Election, Race
from integrations.openstates.client import OpenStatesError, OpenStatesForbiddenError, OpenStatesRateLimitError
from integrations.openstates.tasks import US_STATES, sync_openstates_all_states, sync_openstates_legislators
from ops.models import SourceRecord, SyncLog


@pytest.mark.django_db
def test_sync_openstates_legislators_skips_unchanged_records():
    raw_person = {
        'id': 'os-1',
        'name': 'Alex Smith',
        'current_role': {
            'org_classification': 'upper',
            'district': '5',
            'jurisdiction': 'ocd-division/country:us/state:ca/sldu:5',
        },
    }

    with (
        patch('integrations.openstates.tasks.OpenStatesClient') as mock_client_cls,
        patch('integrations.openstates.tasks.SourceRecordStore') as mock_store_cls,
        patch('integrations.openstates.tasks.CandidateMatcher') as mock_matcher_cls,
    ):
        mock_client_cls.return_value.list_people_all_pages.return_value = [raw_person]
        mock_store_cls.return_value.upsert.return_value = (Mock(linked_candidate_id=99), False)

        result = sync_openstates_legislators('CA')

    sync_log = SyncLog.objects.get(task_name='sync_openstates_legislators', address_label='CA')
    assert result['updated'] == 0
    assert sync_log.records_updated == 0
    assert sync_log.records_skipped == 1
    mock_matcher_cls.return_value.enrich_or_create.assert_not_called()


@pytest.mark.django_db
def test_sync_openstates_legislators_retries_unchanged_but_unlinked_records():
    """An unchanged payload only proves it's safe to skip re-fetching — it
    doesn't prove the last attempt found a match (e.g. the candidate for this
    cycle may not have existed yet). Without a linked_candidate, keep trying."""
    raw_person = {
        'id': 'os-1',
        'name': 'Alex Smith',
        'current_role': {
            'org_classification': 'upper',
            'district': '5',
            'jurisdiction': 'ocd-division/country:us/state:ca/sldu:5',
        },
    }

    with (
        patch('integrations.openstates.tasks.OpenStatesClient') as mock_client_cls,
        patch('integrations.openstates.tasks.SourceRecordStore') as mock_store_cls,
        patch('integrations.openstates.tasks.CandidateMatcher') as mock_matcher_cls,
    ):
        mock_client_cls.return_value.list_people_all_pages.return_value = [raw_person]
        mock_store_cls.return_value.upsert.return_value = (Mock(linked_candidate_id=None), False)
        mock_matcher_cls.return_value.find_races_for_legislator.return_value = []
        mock_matcher_cls.return_value.enrich_or_create.return_value = (None, 'no_match')

        sync_openstates_legislators('CA')

    mock_matcher_cls.return_value.enrich_or_create.assert_called_once()


@pytest.mark.django_db
@patch('integrations.openstates.tasks.OpenStatesClient')
def test_sync_openstates_legislators_updates_matching_candidate(mock_client_cls):
    election = Election.objects.create(
        name='California General Election',
        election_date=date(2026, 11, 3),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='CA',
        source_id='ca-2026-general',
        status=Election.Status.UPCOMING,
    )
    race = Race.objects.create(
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
    candidate = Candidate.objects.create(race=race, name='Alex Smith')
    mock_client_cls.return_value.list_people_all_pages.return_value = [
        {
            'id': 'os-1',
            'name': 'Alex Smith',
            'party': [{'name': 'Democratic', 'end_date': ''}],
            'current_role': {
                'title': 'Senator',
                'org_classification': 'upper',
                'district': '5',
                'jurisdiction': 'ocd-division/country:us/state:ca/sldu:5',
                'division_id': 'ocd-division/country:us/state:ca/sldu:5',
            },
            'image': 'https://example.com/alex.jpg',
            'links': [{'url': 'https://alex.example.com'}],
            'email': 'alex@example.com',
            'offices': [{'voice': '555-0100', 'address': '123 Capitol Ave'}],
        }
    ]

    result = sync_openstates_legislators('CA')

    candidate.refresh_from_db()
    race.refresh_from_db()
    sync_log = SyncLog.objects.get(task_name='sync_openstates_legislators', address_label='CA')
    source_record = SourceRecord.objects.get(source='openstates', external_id='os-1')
    assert result['updated'] == 1
    assert result['created'] == 0
    assert candidate.openstates_person_id == 'os-1'
    assert 'openstates' in candidate.contributing_sources
    assert candidate.party == 'Democratic'
    assert candidate.website_url == 'https://alex.example.com'
    assert candidate.source_metadata['openstates']['person_id'] == 'os-1'
    assert race.ocd_division_id == 'ocd-division/country:us/state:ca/sldu:5'
    assert source_record.linked_candidate_id == candidate.pk
    assert sync_log.records_updated == 1
    assert sync_log.records_skipped == 0


@pytest.mark.django_db
@patch('integrations.openstates.tasks.OpenStatesClient')
def test_sync_openstates_legislators_enriches_both_primary_and_general_rows(mock_client_cls):
    """
    Regression for issue #26: MA (and any state that splits a partisan
    primary into its own Race — see ma_sos mappers.contest_variant_key)
    gives the same real candidate two Candidate rows for the same
    office+district — a primary Race and a general Race. Cross-race
    matching by state+chamber+name alone can't tell those rows apart and
    used to always report "ambiguous", so a genuinely resolvable OpenStates
    match never enriched anyone and Race.ocd_division_id never backfilled.
    Resolving races explicitly by state+chamber+district first (this task's
    fix) lets both rows get enriched independently.
    """
    primary_election = Election.objects.create(
        name='MA Primary', election_date=date(2026, 9, 1),
        jurisdiction_level=Election.JurisdictionLevel.STATE, state='MA',
        source_id='ma-2026-primary', status=Election.Status.UPCOMING,
    )
    general_election = Election.objects.create(
        name='MA General', election_date=date(2026, 11, 3),
        jurisdiction_level=Election.JurisdictionLevel.STATE, state='MA',
        source_id='ma-2026-general', status=Election.Status.UPCOMING,
    )
    primary_race = Race.objects.create(
        election=primary_election, race_type=Race.RaceType.CANDIDATE,
        office_title='State Representative', jurisdiction='5th Essex',
        geography_scope='district', source=Race.Source.MA_SOS,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key='ma-house-5th-essex-primary',
        normalized_office_title='state representative',
    )
    general_race = Race.objects.create(
        election=general_election, race_type=Race.RaceType.CANDIDATE,
        office_title='State Representative', jurisdiction='5th Essex',
        geography_scope='district', source=Race.Source.MA_SOS,
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
        canonical_key='ma-house-5th-essex-general',
        normalized_office_title='state representative',
    )
    primary_candidate = Candidate.objects.create(race=primary_race, name='Andrew Francis Robert Tarr')
    general_candidate = Candidate.objects.create(race=general_race, name='Andrew Francis Robert Tarr')

    mock_client_cls.return_value.list_people_all_pages.return_value = [
        {
            'id': 'ocd-person/tarr',
            'name': 'Dru Tarr',
            'family_name': 'Tarr',
            'party': [{'name': 'Democratic', 'end_date': ''}],
            'jurisdiction': {'id': 'ocd-jurisdiction/country:us/state:ma/government', 'name': 'Massachusetts'},
            'current_role': {
                'title': 'Representative',
                'org_classification': 'lower',
                'district': '5th Essex',
                'division_id': 'ocd-division/country:us/state:ma/sldl:5th_essex',
            },
            'other_names': [{'name': 'A.F.R. Tarr'}],
        }
    ]

    result = sync_openstates_legislators('MA')

    primary_candidate.refresh_from_db()
    general_candidate.refresh_from_db()
    primary_race.refresh_from_db()
    general_race.refresh_from_db()

    assert result['updated'] == 2
    assert primary_candidate.party == 'Democratic'
    assert general_candidate.party == 'Democratic'
    assert primary_race.ocd_division_id == 'ocd-division/country:us/state:ma/sldl:5th_essex'
    assert general_race.ocd_division_id == 'ocd-division/country:us/state:ma/sldl:5th_essex'


@pytest.mark.django_db
def test_sync_openstates_legislators_skips_missing_person_id():
    with patch('integrations.openstates.tasks.OpenStatesClient') as mock_client_cls:
        mock_client_cls.return_value.list_people_all_pages.return_value = [{'name': 'No ID'}]

        result = sync_openstates_legislators('CA')

    assert result['skipped'] == 1
    sync_log = SyncLog.objects.get(task_name='sync_openstates_legislators', address_label='CA')
    assert sync_log.records_skipped == 1


@pytest.mark.django_db
def test_sync_openstates_legislators_skips_people_without_state_or_chamber():
    # A person with no current_role has no state/chamber data → enrich_or_create returns no_match → skipped
    with patch('integrations.openstates.tasks.OpenStatesClient') as mock_client_cls:
        mock_client_cls.return_value.list_people_all_pages.return_value = [{'id': 'os-2', 'name': 'Alex', 'current_role': None}]

        result = sync_openstates_legislators('CA')

    assert result['skipped'] == 1
    sync_log = SyncLog.objects.get(task_name='sync_openstates_legislators', address_label='CA')
    assert sync_log.records_skipped == 1


@pytest.mark.django_db
def test_sync_openstates_legislators_marks_failed_on_forbidden():
    with patch('integrations.openstates.tasks.OpenStatesClient') as mock_client_cls:
        mock_client_cls.return_value.list_people_all_pages.side_effect = OpenStatesForbiddenError('forbidden')

        with pytest.raises(OpenStatesForbiddenError):
            sync_openstates_legislators('CA')

    sync_log = SyncLog.objects.get(task_name='sync_openstates_legislators', address_label='CA')
    assert sync_log.status == SyncLog.Status.FAILED
    assert sync_log.last_error == 'forbidden'


@pytest.mark.django_db
def test_sync_openstates_legislators_retries_on_rate_limit():
    with (
        patch('integrations.openstates.tasks.OpenStatesClient') as mock_client_cls,
        patch.object(sync_openstates_legislators, 'retry', side_effect=Retry()) as mock_retry,
    ):
        mock_client_cls.return_value.list_people_all_pages.side_effect = OpenStatesRateLimitError('Too many requests')

        with pytest.raises(Retry):
            sync_openstates_legislators('CA')

    sync_log = SyncLog.objects.get(task_name='sync_openstates_legislators', address_label='CA')
    assert sync_log.status == SyncLog.Status.COMPLETED_WITH_WARNINGS
    assert sync_log.error_count == 1
    assert mock_retry.call_args.kwargs['countdown'] == 600


@pytest.mark.django_db
def test_sync_openstates_legislators_retries_on_connectivity_error():
    with (
        patch('integrations.openstates.tasks.OpenStatesClient') as mock_client_cls,
        patch.object(sync_openstates_legislators, 'retry', side_effect=Retry()) as mock_retry,
    ):
        mock_client_cls.return_value.list_people_all_pages.side_effect = OpenStatesError(
            'Unable to reach the Open States API.'
        )

        with pytest.raises(Retry):
            sync_openstates_legislators('CA')

    sync_log = SyncLog.objects.get(task_name='sync_openstates_legislators', address_label='CA')
    assert sync_log.status == SyncLog.Status.COMPLETED_WITH_WARNINGS
    assert sync_log.error_count == 1
    assert mock_retry.call_args.kwargs['countdown'] == 300


@patch('integrations.openstates.tasks.sync_openstates_legislators.apply_async')
def test_sync_openstates_all_states_queues_all_states_with_countdown(mock_apply_async):
    sync_openstates_all_states()

    assert mock_apply_async.call_count == len(US_STATES) == 50
    countdowns = [call.kwargs['countdown'] for call in mock_apply_async.call_args_list]
    assert countdowns[0] == 0
    assert countdowns[-1] == (len(US_STATES) - 1) * 60
    assert countdowns == [index * 60 for index in range(len(US_STATES))]
