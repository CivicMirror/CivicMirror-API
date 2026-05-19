from datetime import date
from unittest.mock import Mock, patch

import pytest
from celery.exceptions import Retry

from elections.models import Candidate, Election, Race
from integrations.fec.client import FECAPIForbidden, FECAPIRateLimitError
from integrations.fec.tasks import sync_fec_candidates
from integrations.orchestrator.exceptions import NoRaceFoundError
from ops.models import SourceRecord, SyncLog


@pytest.fixture
def fec_candidate_payload():
    return {
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


@pytest.mark.django_db
def test_sync_fec_candidates_skips_unchanged_records(settings, fec_candidate_payload):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True

    with patch('integrations.fec.tasks.US_STATES', ['MA']), patch('integrations.fec.tasks.FECClient') as mock_client_cls, patch(
        'integrations.fec.tasks.SourceRecordStore'
    ) as mock_store_cls, patch('integrations.fec.tasks.RaceMatcher') as mock_race_matcher_cls:
        mock_client_cls.return_value.list_candidates_all_pages.side_effect = [[fec_candidate_payload], [], []]
        mock_store_cls.return_value.upsert.return_value = (Mock(), False)

        result = sync_fec_candidates.apply(kwargs={'cycle_year': 2024}).get()

    assert result == {'created': 0, 'updated': 0, 'skipped': 1}
    mock_race_matcher_cls.return_value.find_or_create.assert_not_called()
    sync_log = SyncLog.objects.latest('id')
    assert sync_log.records_skipped == 1
    assert sync_log.status == SyncLog.Status.COMPLETED


@pytest.mark.django_db
def test_sync_fec_candidates_skips_when_race_not_found(settings, fec_candidate_payload):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    source_record = Mock(linked_race_id=None, linked_candidate_id=None)

    with patch('integrations.fec.tasks.US_STATES', ['MA']), patch('integrations.fec.tasks.FECClient') as mock_client_cls, patch(
        'integrations.fec.tasks.SourceRecordStore'
    ) as mock_store_cls, patch('integrations.fec.tasks.RaceMatcher') as mock_race_matcher_cls, patch(
        'integrations.fec.tasks.resolve_ocd_id', return_value=None
    ):
        mock_client_cls.return_value.list_candidates_all_pages.side_effect = [[fec_candidate_payload], [], []]
        mock_store_cls.return_value.upsert.return_value = (source_record, True)
        mock_race_matcher_cls.return_value.find_or_create.side_effect = NoRaceFoundError('no race')

        result = sync_fec_candidates.apply(kwargs={'cycle_year': 2024}).get()

    assert result == {'created': 1, 'updated': 0, 'skipped': 1}
    sync_log = SyncLog.objects.latest('id')
    assert sync_log.records_skipped == 1
    source_record.save.assert_not_called()


@pytest.mark.django_db
def test_sync_fec_candidates_enriches_candidate_and_links_source_record(settings, fec_candidate_payload):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    election = Election.objects.create(
        name='US General Election',
        election_date=date(2024, 11, 5),
        jurisdiction_level=Election.JurisdictionLevel.NATIONAL,
        state='MA',
        source_id='us-2024-general',
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
    candidate = Candidate.objects.create(race=race, name='Alex Rivera')

    with patch('integrations.fec.tasks.US_STATES', ['MA']), patch('integrations.fec.tasks.FECClient') as mock_client_cls:
        mock_client_cls.return_value.list_candidates_all_pages.side_effect = [[fec_candidate_payload], [], []]
        result = sync_fec_candidates.apply(kwargs={'cycle_year': 2024}).get()

    candidate.refresh_from_db()
    source_record = SourceRecord.objects.get(source='fec', external_id='H4MA07001')
    assert result == {'created': 1, 'updated': 0, 'skipped': 0}
    assert candidate.fec_candidate_id == 'H4MA07001'
    assert source_record.linked_race == race
    assert source_record.linked_candidate == candidate


@pytest.mark.django_db
def test_sync_fec_candidates_skips_candidate_when_mapper_returns_none(settings, fec_candidate_payload):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    source_record = Mock(linked_race_id=None, linked_candidate_id=None)
    inactive_payload = dict(fec_candidate_payload, candidate_status='N')

    with patch('integrations.fec.tasks.US_STATES', ['MA']), patch('integrations.fec.tasks.FECClient') as mock_client_cls, patch(
        'integrations.fec.tasks.SourceRecordStore'
    ) as mock_store_cls:
        mock_client_cls.return_value.list_candidates_all_pages.side_effect = [[inactive_payload], [], []]
        mock_store_cls.return_value.upsert.return_value = (source_record, True)

        result = sync_fec_candidates.apply(kwargs={'cycle_year': 2024}).get()

    assert result == {'created': 1, 'updated': 0, 'skipped': 1}
    source_record.save.assert_not_called()


@pytest.mark.django_db
def test_sync_fec_candidates_marks_sync_log_failed_on_forbidden(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = False

    with patch('integrations.fec.tasks.US_STATES', ['MA']), patch('integrations.fec.tasks.FECClient') as mock_client_cls:
        mock_client_cls.return_value.list_candidates_all_pages.side_effect = FECAPIForbidden('forbidden')

        result = sync_fec_candidates.apply(kwargs={'cycle_year': 2024})

    assert result.failed()
    sync_log = SyncLog.objects.latest('id')
    assert sync_log.status == SyncLog.Status.FAILED
    assert sync_log.last_error == 'forbidden'


@pytest.mark.django_db
def test_sync_fec_candidates_retries_on_rate_limit(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True

    with patch('integrations.fec.tasks.US_STATES', ['MA']), patch('integrations.fec.tasks.FECClient') as mock_client_cls, patch.object(
        sync_fec_candidates, 'retry', side_effect=Retry()
    ) as mock_retry:
        mock_client_cls.return_value.list_candidates_all_pages.side_effect = FECAPIRateLimitError('rate limited')

        with pytest.raises(Retry):
            sync_fec_candidates(cycle_year=2024)

    sync_log = SyncLog.objects.latest('id')
    assert sync_log.status == SyncLog.Status.COMPLETED_WITH_WARNINGS
    assert mock_retry.call_args.kwargs['countdown'] == 300
