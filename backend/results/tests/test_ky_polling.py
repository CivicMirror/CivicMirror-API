from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from django.core.cache import cache

from elections.models import Election
from internal.task_locks import current_window, windows_for_date


def create(day, state='KY'):
    return Election.objects.create(name='poll', state=state, election_date=day, election_type='general',
                                   jurisdiction_level='state')


@pytest.mark.django_db
def test_poll_uses_new_york_today_yesterday_and_ky_only():
    from results.tasks import poll_ky_results
    yesterday = create(date(2026, 11, 2))
    today = create(date(2026, 11, 3))
    create(date(2026, 11, 1))
    create(date(2026, 11, 4))
    create(date(2026, 11, 3), state='NC')
    with patch('results.tasks.timezone.now', return_value=datetime(2026, 11, 4, 2, tzinfo=timezone.utc)), \
            patch('results.tasks.ingest_official_results.delay') as enqueue:
        poll_ky_results()
    assert {c.args for c in enqueue.call_args_list} == {('KY', yesterday.pk), ('KY', today.pk)}


@pytest.mark.django_db
def test_explicit_election_id_allows_pre_election_smoke():
    from results.tasks import poll_ky_results
    ky = create(date(2026, 11, 3))
    other = create(date(2026, 11, 3), 'NC')
    with patch('results.tasks.ingest_official_results.delay') as enqueue:
        poll_ky_results(ky.pk)
        poll_ky_results(other.pk)
    enqueue.assert_called_once_with('KY', ky.pk)


@pytest.mark.django_db
def test_trigger_requires_auth_and_accepts_explicit_id(client, settings):
    settings.INTERNAL_TASK_TOKEN = 'ky-test-token'
    cache.clear()
    ky = create(date(2026, 11, 3))
    url = '/internal/tasks/poll-ky-results/'
    assert client.post(url).status_code == 401
    with patch('internal.views.poll_ky_results.apply_async') as queue:
        queue.return_value.id = 'ky-task'
        response = client.post(url, {'election_id': ky.pk}, content_type='application/json',
                               HTTP_AUTHORIZATION='Bearer ky-test-token')
        assert response.status_code == 202
        assert queue.call_args.kwargs['kwargs'] == {'election_id': ky.pk}
        assert client.post(url, data='{}', content_type='application/json',
                           HTTP_AUTHORIZATION='Bearer ky-test-token').json()['status'] == 'already_running'


def test_two_minute_lock_windows():
    before = datetime(2026, 11, 3, 12, 1, 59, tzinfo=timezone.utc)
    after = datetime(2026, 11, 3, 12, 2, tzinfo=timezone.utc)
    assert current_window('two_minutes', before) != current_window('two_minutes', after)
    assert len(windows_for_date('two_minutes', '2026-11-03')) == 720
