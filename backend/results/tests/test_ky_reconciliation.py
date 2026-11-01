from dataclasses import replace
from datetime import date

import pytest
from django.core.cache import cache

from elections.models import Candidate, Election, Race
from results.adapters.ky import KentuckyAdapter, parse_ky_snapshot
from results.models import OfficialResult
from results.tests.test_ky_live import feed


@pytest.fixture
def election(db):
    return Election.objects.create(name='Kentucky General', election_date=date(2026, 11, 3),
                                   state='KY', election_type='general', jurisdiction_level='state')


@pytest.fixture
def snapshot():
    return parse_ky_snapshot('current', *[feed(n) for n in (
        'Contests', 'Candidates', 'CurrentResults', 'GeopoliticalUnits', 'PoliticalParties')])


def race(election, title='US Representative District 2nd', **kwargs):
    return Race.objects.create(election=election, office_title=title, jurisdiction='Kentucky District 2nd',
                               geography_scope='district', source='ky_sos', race_type='candidate', **kwargs)


def test_dry_run_is_read_only_and_holds_state_scoped_clerk(election, snapshot):
    from results.ky_reconciliation import reconcile
    with pytest.MonkeyPatch.context() as m:
        m.setattr(cache, 'set', lambda *a, **kw: pytest.fail('cache write'))
        report = reconcile(election, snapshot)
    assert Race.objects.count() == 0
    assert OfficialResult.objects.count() == 0
    assert report['source_rows'] == report['accepted_rows'] + report['held_rows']
    clerk = next(d for d in report['contests'] if d['contest_id'] == '966')
    assert clerk['status'] == 'held'
    assert 'jurisdiction' in clerk['reason']
    assert any(d['status'] == 'create' and d['evidence']['geography_scope'] == 'municipal'
               for d in report['contests'])


def test_matches_filings_with_normalized_office_district_and_candidate_names(election, snapshot):
    from results.ky_reconciliation import reconcile
    # Actual source fixture includes US Representative 2nd Congressional District.
    r = race(election)
    candidates = [c for (cid, _), c in snapshot.candidates.items()
                  if 'REPRESENTATIVE' in snapshot.contests[cid]['name']
                  and '2nd' in snapshot.contests[cid]['name']
                  and 'UNITED' in snapshot.contests[cid]['name'] and c['is_write_in'] != 'true']
    assert candidates
    for c in candidates:
        Candidate.objects.create(race=r, name=c['ballot_name'].title())
    report = reconcile(election, snapshot)
    match = next(d for d in report['contests'] if d['status'] == 'match')
    assert match['race_id'] == r.pk
    r.refresh_from_db()
    assert 'contest_code' not in r.source_metadata


def test_multiple_compatible_races_hold_instead_of_guess(election, snapshot):
    from results.ky_reconciliation import reconcile
    race(election)
    race(election)
    report = reconcile(election, snapshot)
    d = next(d for d in report['contests'] if len(d['competing_matches']) == 2)
    assert d['status'] == 'held'


def test_apply_creates_missing_local_contests_with_existing_races_and_is_idempotent(election, snapshot):
    from results.ky_reconciliation import ingest_snapshot
    race(election, title='unrelated')
    report = ingest_snapshot(election, snapshot)
    assert report['accepted_rows'] > 0
    assert OfficialResult.objects.count() == report['accepted_rows']
    assert Race.objects.filter(vote_method='multi_seat', max_selections=4).exists()
    assert Race.objects.filter(race_type='measure', jurisdiction='Fayette County').exists()
    assert not OfficialResult.objects.filter(is_winner__isnull=False).exists()
    assert not OfficialResult.objects.exclude(result_type='unofficial').exists()
    counts = (Race.objects.count(), Candidate.objects.count(), OfficialResult.objects.count())
    second = ingest_snapshot(election, snapshot)
    assert counts == (Race.objects.count(), Candidate.objects.count(), OfficialResult.objects.count())
    assert second['accepted_rows'] == report['accepted_rows']
    assert second['created_results'] == 0
    assert second['updated_results'] == 0
    totals = OfficialResult.objects.filter(jurisdiction_fragment='')
    assert totals.count()
    changed = replace(snapshot, rows=[replace(r, vote_count=7) for r in snapshot.rows])
    ingest_snapshot(election, changed)
    assert set(totals.values_list('vote_count', flat=True)) == {7}


def test_failed_persistence_rolls_back_every_contest(election, snapshot, monkeypatch):
    from results.ky_reconciliation import ingest_snapshot
    def fail(*a, **kw):
        raise RuntimeError('database failure')
    monkeypatch.setattr(OfficialResult.objects, 'bulk_create', fail)
    with pytest.raises(RuntimeError, match='database failure'):
        ingest_snapshot(election, snapshot)
    assert Race.objects.count() == 0
    assert Candidate.objects.count() == 0


def test_no_total_holds_entire_contest(election, snapshot):
    from results.ky_reconciliation import reconcile
    incomplete = replace(snapshot, rows=[r for r in snapshot.rows if r.jurisdiction_fragment])
    report = reconcile(election, incomplete)
    assert report['accepted_rows'] == 0
    assert all(d['status'] in ('held', 'no_results') for d in report['contests'])


def test_shared_task_dispatches_ky_without_generic_title_matching(election, snapshot, monkeypatch):
    from results.tasks import ingest_official_results
    monkeypatch.setattr(KentuckyAdapter, 'fetch_results', lambda *a, **kw: snapshot)
    report = ingest_official_results('KY', election.pk)
    assert report['accepted_rows'] == OfficialResult.objects.count()
    assert report['held_rows'] > 0


def test_state_scope_constitutional_amendment_and_numbered_prosecutor_are_verified(snapshot):
    from results.ky_reconciliation import jurisdiction_evidence
    for title, expected in [('CONSTITUTIONAL AMENDMENT 1', 'statewide'),
                            ("COMMONWEALTH'S ATTORNEY 1st Judicial Circuit", 'district')]:
        contest = {**snapshot.contests['966'], 'name': title}
        evidence, reason = jurisdiction_evidence(contest, snapshot.units, [])
        assert not reason
        assert evidence['geography_scope'] == expected


def test_legislative_match_requires_compatible_jurisdiction_and_term(election, snapshot):
    from results.ky_reconciliation import _compatible, jurisdiction_evidence
    contest = next(c for c in snapshot.contests.values() if 'UNITED' in c['name'] and '2nd' in c['name'])
    evidence, _ = jurisdiction_evidence(contest, snapshot.units, [])
    r = race(election, source_metadata={'is_unexpired_term': True})
    assert not _compatible(r, contest, evidence, False)
    r.source_metadata = {}
    r.jurisdiction = 'Another state District 2'
    assert not _compatible(r, contest, evidence, False)


@pytest.mark.django_db(transaction=True)
def test_postgresql_advisory_lock_serializes_the_fetch(monkeypatch):
    from django.db import connection

    from results.ky_reconciliation import run_ky_ingestion
    if connection.vendor != 'postgresql':
        pytest.skip('requires PostgreSQL advisory locks')
    e = Election.objects.create(name='lock', election_date=date(2026, 11, 3), state='KY',
                                election_type='general', jurisdiction_level='state')
    def unexpected_fetch(*a, **kw):
        pytest.fail('overlapping ingestion fetched the feed')
    monkeypatch.setattr(KentuckyAdapter, 'fetch_results', unexpected_fetch)
    other = connection.Database.connect(**connection.get_connection_params())
    try:
        with other.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s, %s)', [126414, e.pk])
            report = run_ky_ingestion(e.pk)
        assert report['status'] == 'already_running'
    finally:
        other.rollback()
        other.close()


def test_natural_key_enforced_for_null_aggregate_targets(election, snapshot):
    from django.db import IntegrityError, transaction

    from results.ky_reconciliation import ingest_snapshot
    ingest_snapshot(election, snapshot)
    row = OfficialResult.objects.filter(is_write_in_aggregate=True).first()
    assert row
    with pytest.raises(IntegrityError), transaction.atomic():
        OfficialResult.objects.create(race=row.race, candidate=None, measure_option=None,
                                       jurisdiction_fragment=row.jurisdiction_fragment,
                                       is_write_in_aggregate=True)


def test_local_candidate_overlap_cannot_override_jurisdiction(election, snapshot):
    from results.ky_reconciliation import reconcile
    sheriff = next(c for c in snapshot.contests.values() if c['name'] == 'SHERIFF')
    r = Race.objects.create(election=election, office_title='SHERIFF', jurisdiction='Wrong County',
                            geography_scope='county', source='ky_sos', race_type='candidate')
    for (cid, _), c in snapshot.candidates.items():
        if cid == sheriff['id']:
            Candidate.objects.create(race=r, name=c['ballot_name'])
    report = reconcile(election, snapshot)
    d = next(d for d in report['contests'] if d['contest_id'] == sheriff['id'])
    assert d['status'] == 'create'
    assert d['race_id'] is None


def test_dry_run_command_does_not_issue_mutating_sql_or_cache_writes(election, monkeypatch):
    from io import StringIO

    from django.core.management import call_command
    from django.db import connection

    from results.tests.test_ky_live import FIXTURES
    def reject_write(execute, sql, params, many, context):
        assert not sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'ALTER', 'CREATE'))
        return execute(sql, params, many, context)
    def fail(*a, **kw):
        pytest.fail('cache write')
    monkeypatch.setattr(cache, 'set', fail)
    monkeypatch.setattr(cache, 'add', fail)
    monkeypatch.setattr(cache, 'delete', fail)
    with connection.execute_wrapper(reject_write):
        call_command('reconcile_ky_results', election_id=election.pk, snapshot_dir=str(FIXTURES), stdout=StringIO())
    assert Race.objects.count() == 0


def test_unavailable_fetch_preserves_prior_race_status_and_results(election, snapshot, monkeypatch):
    from results.adapters.ky import KentuckyResult
    from results.ky_reconciliation import ingest_snapshot, run_ky_ingestion
    ingest_snapshot(election, snapshot)
    before = list(OfficialResult.objects.values())
    statuses = list(Race.objects.values_list('pk', 'certification_status'))
    monkeypatch.setattr(KentuckyAdapter, 'fetch_results', lambda *a, **kw: KentuckyResult(
        [], '', 'none', notes='persistent policy block'))
    assert run_ky_ingestion(election.pk)['status'] == 'unavailable'
    assert list(OfficialResult.objects.values()) == before
    assert list(Race.objects.values_list('pk', 'certification_status')) == statuses


@pytest.mark.parametrize('conflict', ['scope_id', 'jurisdiction', 'geography_scope', 'selections'])
def test_conflicting_existing_local_evidence_is_held(election, snapshot, conflict):
    from results.ky_reconciliation import reconcile
    contest = snapshot.contests['1115']
    r = Race.objects.create(election=election, office_title=contest['name'], jurisdiction='City of Allen',
                            geography_scope='municipal', source='ky_sos', race_type='candidate',
                            max_selections=4, vote_method='multi_seat',
                            source_metadata={'ky_scope_unit_id': '126'})
    if conflict == 'scope_id':
        r.source_metadata['ky_scope_unit_id'] = '999999'
    elif conflict == 'jurisdiction':
        r.jurisdiction = 'Entirely Different Electorate'
    elif conflict == 'geography_scope':
        r.geography_scope = 'county'
    else:
        r.max_selections = 1
        r.vote_method = 'single_choice'
    r.save()
    for (cid, _), c in snapshot.candidates.items():
        if cid == '1115' and c['is_write_in'] != 'true':
            Candidate.objects.create(race=r, name=c['ballot_name'])
    d = next(d for d in reconcile(election, snapshot)['contests'] if d['contest_id'] == '1115')
    assert d['status'] == 'held'
    assert 'conflict' in d['reason']
    assert d['competing_matches'][0]['race_id'] == r.pk


def test_reconciliation_does_not_scan_unrelated_office_families(election, snapshot, monkeypatch):
    from results import ky_reconciliation as ky
    for i in range(50):
        race(election, title=f'Unrelated office {i}')
    calls = 0
    original = ky._compatible
    def count(*a, **kw):
        nonlocal calls
        calls += 1
        return original(*a, **kw)
    monkeypatch.setattr(ky, '_compatible', count)
    ky.reconcile(election, snapshot)
    assert calls < len(snapshot.contests)


@pytest.mark.parametrize('selection,include_local', [(None, True), ('all', True), ('exclude_local', False)])
def test_adapter_coverage_feed_selection(election, selection, include_local, monkeypatch):
    from unittest.mock import Mock

    from results.adapters import ky
    election.source_metadata = {'ky_results_feed': selection} if selection else {}
    election.save()
    client = Mock()
    for name in ('Elections', 'Contests', 'Candidates', 'GeopoliticalUnits', 'PoliticalParties'):
        method = {'Elections': 'elections', 'Contests': 'contests', 'Candidates': 'candidates',
                  'GeopoliticalUnits': 'geopolitical_units', 'PoliticalParties': 'political_parties'}[name]
        getattr(client, 'fetch_' + method).return_value = feed(name)
    client.fetch_current_results.return_value = feed('CurrentResults')
    monkeypatch.setattr(ky, 'KentuckyXmlClient', lambda **kw: client)
    result = KentuckyAdapter().fetch_results(election.election_date, election.pk)
    client.fetch_current_results.assert_called_once_with(include_local=include_local)
    assert result.source_url.endswith('/CurrentResults' if include_local else '/CurrentResultsExcludeLocal')
