"""Conservative KY source-contest reconciliation and atomic result persistence.

All decisions are made before writes. The same decision builder serves dry runs
and ingestion. Source geography and office/seat/term must agree; a candidate
name alone is never evidence for a contest's electorate.
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from functools import lru_cache

from django.core.cache import cache
from django.db import connection, transaction

from aggregation.identity import name_match_key
from elections.models import Candidate, Election, MeasureOption, Race
from results.adapters.ky import KentuckyAdapter, _bool_attr
from results.models import OfficialResult

logger = logging.getLogger(__name__)


@lru_cache(maxsize=8192)
def text_key(value):
    value = re.sub(r'\b([0-9]+)(st|nd|rd|th)\b', r'\1', str(value).lower())
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', value).split())


@lru_cache(maxsize=8192)
def legislative_identity(title):
    title = text_key(title)
    for prefix, family in (
        ('united states representative', 'us_representative'), ('us representative', 'us_representative'),
        ('u s representative', 'us_representative'), ('united states senator', 'us_senator'),
        ('us senator', 'us_senator'), ('u s senator', 'us_senator'),
        ('state representative', 'state_representative'), ('state senator', 'state_senator'),
    ):
        if title == prefix or title.startswith(prefix + ' '):
            numbers = re.findall(r'\b[0-9]+\b', title[len(prefix):])
            if family == 'us_senator' and not numbers and title == prefix:
                return family, ''
            if family != 'us_senator' and len(numbers) == 1 and int(numbers[0]) > 0:
                return family, str(int(numbers[0]))
    return None


def jurisdiction_evidence(contest, units, rows):
    uid = contest['scope_unit_id']
    scope = units.get(uid, {})
    title = contest['name']
    evidence = {
        'scope_unit_id': uid, 'scope_unit': scope,
        'reporting_unit_ids': sorted({r.raw['gpu_id'] for r in rows}, key=int),
        'office_key': text_key(title), 'is_unexpired_term': _bool_attr(contest['is_unexpired_term']),
        'selectable_option': contest['selectable_option'],
    }
    legislative = legislative_identity(title)
    if legislative and scope.get('type') == 'State':
        family, district = legislative
        evidence.update(office_family=family, district=district,
                        jurisdiction='Kentucky' + (f' District {district}' if district else ''),
                        geography_scope='district' if district else 'statewide')
        return evidence, ''
    # Judicial district/circuit numbers are explicit electorate evidence even
    # though Kentucky reports these contests using a State scope/rollup.
    judicial = re.search(r'\b([0-9]+)(?:st|nd|rd|th)? Judicial (Circuit|District)\b', title, re.I)
    appellate = re.search(r'\b([0-9]+)(?:st|nd|rd|th)? (?:Supreme Court|Appellate) District\b', title, re.I)
    if scope.get('type') == 'State' and any(word in title.upper() for word in ('JUDGE', 'JUSTICE', 'ATTORNEY')):
        if judicial:
            evidence.update(jurisdiction=f'Kentucky Judicial {judicial[2].title()} {int(judicial[1])}',
                            geography_scope='district')
            return evidence, ''
        if appellate:
            evidence.update(jurisdiction=f'Kentucky {appellate[0]}', geography_scope='district')
            return evidence, ''
    if scope.get('type') == 'State' and re.fullmatch(r'CONSTITUTIONAL AMENDMENT [0-9]+', title, re.I):
        evidence.update(jurisdiction='Kentucky', geography_scope='statewide')
        return evidence, ''
    if scope.get('type') in {'County', 'City', 'School'} and scope.get('name'):
        evidence.update(jurisdiction=scope['name'], geography_scope={
            'County': 'county', 'City': 'municipal', 'School': 'school',
        }[scope['type']])
        # A county office must not be qualified by rows belonging to a different
        # county. State rollups carry no additional jurisdiction evidence.
        counties = {r.raw['gpu_id'] for r in rows if r.raw['gpu_unit_type'] == 'County'}
        if scope['type'] == 'County' and counties - {uid}:
            return evidence, 'reporting geography conflicts with scope jurisdiction'
        return evidence, ''
    return evidence, 'unverified jurisdiction: source state rollup does not identify local electorate'


def _compatible(race, contest, evidence, is_measure):
    if race.race_type != ('measure' if is_measure else 'candidate'):
        return False
    metadata = race.source_metadata or {}
    if bool(metadata.get('is_unexpired_term', False)) != evidence['is_unexpired_term']:
        return False
    if evidence.get('office_family'):
        identity = legislative_identity(race.office_title)
        return (identity == (evidence['office_family'], evidence['district']) and
                text_key(race.jurisdiction) == text_key(evidence['jurisdiction']))
    if text_key(race.office_title) != evidence['office_key']:
        return False
    return (str(metadata.get('ky_scope_unit_id', '')) == evidence['scope_unit_id'] or
            text_key(race.jurisdiction) == text_key(evidence.get('jurisdiction', '')))


def _race_conflict(race, evidence, is_measure):
    metadata = race.source_metadata or {}
    scope_id = str(metadata.get('ky_scope_unit_id') or '')
    if scope_id and scope_id != evidence['scope_unit_id']:
        return 'conflicting existing scope unit identity'
    if text_key(race.jurisdiction) != text_key(evidence['jurisdiction']):
        return 'conflicting existing jurisdiction name'
    if race.geography_scope != evidence['geography_scope']:
        return 'conflicting existing geography scope'
    selections = evidence['selectable_option']
    if selections > 0:
        if race.max_selections != selections:
            return 'conflicting existing selectable seat count'
        allowed = {'multi_seat'} if selections > 1 else {'single_choice', 'yes_no'} if is_measure else {'single_choice'}
        if race.vote_method not in allowed:
            return 'conflicting existing vote method'
    return ''


def _office_index_key(title):
    legislative = legislative_identity(title)
    return ('legislative', legislative) if legislative else ('office', text_key(title))


def _choices_for(snapshot):
    choices = defaultdict(dict)
    for (cid, pid), choice in snapshot.candidates.items():
        choices[cid][pid] = choice
    return choices


def _build_plan(election, snapshot):
    by_contest = defaultdict(list)
    for row in snapshot.rows:
        by_contest[row.raw['contest_code']].append(row)
    races = list(Race.objects.filter(election=election).prefetch_related('candidates', 'measure_options'))
    choices = _choices_for(snapshot)
    by_identity, by_office = defaultdict(list), defaultdict(list)
    for race in races:
        code = str((race.source_metadata or {}).get('contest_code') or '')
        if code:
            by_identity[code].append(race)
        by_office[_office_index_key(race.office_title)].append(race)
    decisions = []
    signatures = defaultdict(list)
    for cid, contest in snapshot.contests.items():
        rows = by_contest[cid]
        evidence, reason = jurisdiction_evidence(contest, snapshot.units, rows)
        decision = {'contest_id': cid, 'title': contest['name'], 'source_rows': len(rows),
                    'status': 'held', 'reason': reason, 'evidence': evidence, 'race_id': None,
                    'competing_matches': [], 'candidate_ids': sorted(choices[cid]),
                    'candidate_names': [c['ballot_name'] for c in choices[cid].values()]}
        decisions.append(decision)
        if not rows:
            decision.update(status='no_results', reason='metadata contest has no result rows')
            continue
        if reason:
            continue
        expected = set(choices[cid])
        totals = [r.raw['candidate_id'] for r in rows if not r.jurisdiction_fragment]
        if set(totals) != expected or len(totals) != len(expected):
            decision['reason'] = 'incomplete contest: missing or duplicate choice totals'
            continue
        labels = [name_match_key(c['ballot_name']) for c in choices[cid].values()]
        if len(set(labels)) != len(labels):
            decision['reason'] = 'ambiguous duplicate choice names'
            continue
        signature = (evidence.get('office_family') or evidence['office_key'],
                     evidence.get('district'), evidence['jurisdiction'], evidence['is_unexpired_term'])
        signatures[signature].append(decision)
        is_measure = any(r.option_label is not None for r in rows)
        identified = by_identity[cid]
        compatible = [r for r in by_office[_office_index_key(contest['name'])]
                      if _compatible(r, contest, evidence, is_measure)]
        possible = {r.pk: r for r in identified + compatible}
        decision['competing_matches'] = [{'race_id': r.pk, 'office_title': r.office_title,
                                         'jurisdiction': r.jurisdiction,
                                         'contest_code': (r.source_metadata or {}).get('contest_code')}
                                        for r in possible.values()]
        if identified and (len(identified) != 1 or identified[0] not in compatible):
            decision['reason'] = 'existing source identity conflicts with office or jurisdiction'
            continue
        if len(possible) > 1:
            decision['reason'] = 'multiple compatible races'
            continue
        if possible:
            existing = next(iter(possible.values()))
            code = str((existing.source_metadata or {}).get('contest_code') or '')
            if code and code != cid:
                decision['reason'] = 'compatible race already has a different source contest identity'
                continue
            conflict = _race_conflict(existing, evidence, is_measure)
            if conflict:
                decision['reason'] = conflict
                continue
            existing_choices = list(existing.measure_options.all() if is_measure else existing.candidates.all())
            choice_keys = Counter(name_match_key(c.option_label if is_measure else c.name) for c in existing_choices)
            source_rows = {r.raw['candidate_id']: r for r in rows}
            required = [c for pid, c in choices[cid].items() if not source_rows[pid].is_write_in_aggregate]
            if any(choice_keys[name_match_key(c['ballot_name'])] != 1 for c in required):
                decision['reason'] = 'missing or ambiguous normalized candidate/option match'
                continue
            decision.update(status='match', reason='', race_id=existing.pk)
        else:
            decision.update(status='create', reason='')
    for group in signatures.values():
        if len(group) > 1:
            for d in group:
                d.update(status='held', reason='multiple source contests share office/jurisdiction/seat/term',
                         competing_contest_ids=[other['contest_id'] for other in group])
    # One existing race cannot receive two separate source identities.
    targets = Counter(d['race_id'] for d in decisions if d['status'] == 'match')
    for d in decisions:
        if d['status'] == 'match' and targets[d['race_id']] > 1:
            d.update(status='held', reason='multiple source contests target one existing race')
    accepted = [d for d in decisions if d['status'] in {'match', 'create'}]
    report = {
        'election_id': election.pk, 'source_url': snapshot.source_url, 'source_version': snapshot.source_version,
        'source_rows': len(snapshot.rows), 'metadata_contests': len(snapshot.contests),
        'reported_contests': sum(bool(d['source_rows']) for d in decisions),
        'no_result_contests': sum(d['status'] == 'no_results' for d in decisions),
        'accepted_rows': sum(d['source_rows'] for d in accepted),
        'held_rows': sum(d['source_rows'] for d in decisions if d['status'] == 'held'),
        'matched_contests': sum(d['status'] == 'match' for d in decisions),
        'proposed_creations': sum(d['status'] == 'create' for d in decisions),
        'held_contests': sum(d['status'] == 'held' for d in decisions),
        'contests': decisions,
    }
    assert report['source_rows'] == report['accepted_rows'] + report['held_rows']
    return report, by_contest


def reconcile(election, snapshot):
    """No DB/cache writes. Includes every metadata contest and every source row."""
    return _build_plan(election, snapshot)[0]


def _apply_contest(election, snapshot, decision, rows):
    evidence = decision['evidence']
    if decision['status'] == 'match':
        race = Race.objects.get(pk=decision['race_id'])
    else:
        race = Race(election=election, office_title=decision['title'],
                    jurisdiction=evidence['jurisdiction'], geography_scope=evidence['geography_scope'],
                    source=Race.Source.KY_SOS, race_type='measure' if any(r.option_label for r in rows) else 'candidate')
    metadata = {**(race.source_metadata or {}), 'contest_code': decision['contest_id'],
                'ky_scope_unit_id': evidence['scope_unit_id'], 'ky_identity_evidence': evidence,
                'is_unexpired_term': evidence['is_unexpired_term'],
                'selectable_option': evidence['selectable_option'], 'ky_results_source': snapshot.source_url}
    # Clear a prior derived flag; this feed is always unofficial and publishes no winners.
    metadata.pop('winners_derived', None)
    race.source_metadata = metadata
    selections = evidence['selectable_option']
    if selections > 0:
        race.max_selections = selections
        race.vote_method = ('yes_no' if race.race_type == 'measure' else
                            'multi_seat' if selections > 1 else 'single_choice')
    race.certification_status = Race.CertificationStatus.RESULTS_PENDING
    race.save()
    decision['race_id'] = race.pk
    sources = {r.raw['candidate_id']: r for r in rows}
    targets = {}
    existing = list(race.measure_options.all() if race.race_type == 'measure' else race.candidates.all())
    for pid, row in sources.items():
        if row.is_write_in_aggregate:
            targets[pid] = (None, None)
            continue
        key = name_match_key(row.option_label or row.candidate_name)
        choice = next((c for c in existing if name_match_key(
            c.option_label if race.race_type == 'measure' else c.name) == key), None)
        if race.race_type == 'measure':
            if choice is None:
                choice = MeasureOption.objects.create(race=race, option_label=row.option_label)
            targets[pid] = (None, choice.pk)
        else:
            if choice is None:
                choice = Candidate(race=race, name=row.candidate_name)
            choice.party = row.raw.get('party') or choice.party
            choice.incumbent = row.raw['is_incumbent']
            choice.candidate_status = 'withdrawn' if row.raw['is_withdrawn'] else 'running'
            choice.source_metadata = {**(choice.source_metadata or {}), 'ky_candidate_id': pid,
                                      'ky_contest_id': decision['contest_id'], 'ky_party_id': row.raw['party_id']}
            choice.save()
            targets[pid] = (choice.pk, None)
    existing_results = {(r.candidate_id, r.measure_option_id, r.round_number, r.jurisdiction_fragment): r
                        for r in OfficialResult.objects.filter(race=race)}
    create, update = [], []
    fields = ['vote_count', 'vote_pct', 'is_winner', 'result_type', 'is_write_in_aggregate',
              'source_url', 'raw_payload', 'certified_at']
    keys = set()
    for row in rows:
        candidate_id, option_id = targets[row.raw['candidate_id']]
        key = candidate_id, option_id, None, row.jurisdiction_fragment
        if key in keys:
            raise ValueError(f'KY duplicate persistence natural key: {race.pk}/{key}')
        keys.add(key)
        result = existing_results.get(key)
        values = dict(vote_count=row.vote_count, vote_pct=None, is_winner=None, result_type='unofficial',
                      is_write_in_aggregate=row.is_write_in_aggregate, source_url=snapshot.source_url,
                      raw_payload=row.raw, certified_at=None)
        if result is None:
            create.append(OfficialResult(race=race, candidate_id=candidate_id, measure_option_id=option_id,
                                         jurisdiction_fragment=row.jurisdiction_fragment, **values))
        elif any(getattr(result, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(result, k, v)
            update.append(result)
    if create:
        OfficialResult.objects.bulk_create(create, batch_size=1000)
    if update:
        OfficialResult.objects.bulk_update(update, fields, batch_size=500)
    # Old geography fragments/totals are retained until an explicit repair review;
    # a changed source unit set cannot silently leave obsolete public totals.
    stale = set(existing_results) - keys
    if stale:
        raise ValueError(f'KY stored result keys absent from current feed for race {race.pk}; review required')
    return len(create), len(update)


@transaction.atomic
def ingest_snapshot(election, snapshot, *, contest_ids=None):
    election = Election.objects.select_for_update().get(pk=election.pk, state='KY')
    report, by_contest = _build_plan(election, snapshot)
    report.update(created_results=0, updated_results=0, applied_contests=0)
    for decision in report['contests']:
        if decision['status'] not in {'create', 'match'}:
            continue
        if contest_ids and decision['contest_id'] not in contest_ids:
            continue
        created, updated = _apply_contest(election, snapshot, decision, by_contest[decision['contest_id']])
        report['created_results'] += created
        report['updated_results'] += updated
        report['applied_contests'] += 1
    election.source_metadata = {**(election.source_metadata or {}), 'ky_results_review': report}
    election.save(update_fields=['source_metadata'])
    if not report['held_contests'] and not contest_ids and snapshot.source_version:
        adapter = KentuckyAdapter()
        transaction.on_commit(lambda: cache.set(adapter.version_cache_key(election.pk), snapshot.source_version,
                                                adapter.VERSION_CACHE_TIMEOUT))
    logger.info('KY reconciliation election=%s rows=%s accepted=%s held=%s no_results=%s created=%s updated=%s',
                election.pk, report['source_rows'], report['accepted_rows'], report['held_rows'],
                report['no_result_contests'], report['created_results'], report['updated_results'])
    return report


def run_ky_ingestion(election_id, *, snapshot_dir=None, contest_ids=None, apply=True):
    """Serialize fetch, reconciliation, and writes per election (PostgreSQL)."""
    with transaction.atomic():
        if apply and connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_try_advisory_xact_lock(%s, %s)', [126414, election_id])
                if not cursor.fetchone()[0]:
                    return {'election_id': election_id, 'status': 'already_running'}
        election = Election.objects.get(pk=election_id, state='KY')
        snapshot = KentuckyAdapter().fetch_results(election.election_date, election.pk,
                                                   use_cache=apply, snapshot_dir=snapshot_dir)
        if not snapshot.rows:
            return {'election_id': election.pk, 'status': 'unavailable', 'reason': snapshot.notes}
        if apply:
            return ingest_snapshot(election, snapshot, contest_ids=contest_ids)
        return reconcile(election, snapshot)
