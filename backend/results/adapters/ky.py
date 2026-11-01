"""Kentucky SBE live WCF XML. Totals and reporting geography are kept separate."""
from __future__ import annotations

import datetime
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from xml.etree import ElementTree as ET

import requests
from django.conf import settings
from django.core.cache import cache

from results.models import OfficialResult

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)
_DATA_BASE = 'https://vrsws.sos.ky.gov/liveresults/Data'
_TIMEOUT = 60
_CACHE_TTL = 1200
PARSER_VERSION = 'ky-wcf-2026-11-01-v1'
_HEADERS = {'User-Agent': 'CivicMirror/1.0 (+https://civicmirror.app)', 'Accept': 'application/xml,text/xml'}
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class KentuckyPolicyBlockError(RuntimeError):
    """Persistent Kentucky policy block; keep the last stored results."""


class KentuckyXmlClient:
    def __init__(self, timeout=60, *, use_cache=True):
        self.timeout = min(timeout, _TIMEOUT)
        self.use_cache = use_cache
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        self.solver_url = getattr(settings, 'KY_FLARESOLVERR_URL', '').rstrip('/')
        self.credential_key = 'ky:browser:' + hashlib.sha256(self.solver_url.encode()).hexdigest()[:16]
        self.credentials = None

    def _apply(self, credentials):
        self._session.cookies.clear()
        self._session.headers['User-Agent'] = credentials['user_agent']
        for cookie in credentials['cookies']:
            self._session.cookies.set(cookie['name'], cookie['value'],
                                      domain=cookie.get('domain') or 'vrsws.sos.ky.gov',
                                      path=cookie.get('path') or '/')
        self.credentials = credentials

    def _solve(self):
        try:
            response = requests.post(self.solver_url + '/v1', json={
                'cmd': 'request.get', 'url': _DATA_BASE + '/Elections', 'maxTimeout': 45000,
            }, timeout=45)
            response.raise_for_status()
            payload = response.json()
            solution = payload.get('solution') or {}
            if payload.get('status') != 'ok' or solution.get('status') != 200 or not solution.get('userAgent'):
                raise RuntimeError('KY FlareSolverr did not establish a browser session')
            now = time.time()
            cookies = solution.get('cookies') or []
            expires = min([now + _CACHE_TTL] + [float(c['expiry']) for c in cookies if c.get('expiry', 0) > 0])
            if expires <= now:
                raise RuntimeError('KY FlareSolverr returned expired credentials')
            credentials = {'cookies': cookies, 'user_agent': solution['userAgent'], 'expires': expires}
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            # Do not include solver responses or exceptions containing cookie values.
            raise RuntimeError('KY FlareSolverr unavailable or invalid response') from exc
        self._apply(credentials)
        if self.use_cache:
            cache.set(self.credential_key, credentials, timeout=max(1, int(expires - now)))

    def _fetch(self, dataset):
        url = f'{_DATA_BASE}/{dataset}'
        if self.credentials and self.credentials['expires'] <= time.time():
            self._session.cookies.clear()
            self._session.headers.update(_HEADERS)
            self.credentials = None
        # Ordinary HTTP first. A blocked response may use cached browser credentials,
        # then at most one fresh solve (two solves if the first session is blocked).
        refreshed = 0
        tried_cached = False
        while True:
            try:
                response = self._session.get(url, timeout=self.timeout)
                if response.status_code in _RETRYABLE_STATUSES:
                    raise RuntimeError(f'KY XML returned {response.status_code} for {dataset}')
                blocked = response.status_code == 403 or _looks_like_policy_block(response.content)
                if not blocked:
                    response.raise_for_status()
                    return response.content
            except requests.RequestException as exc:
                raise RuntimeError(f'KY XML GET failed for {dataset}') from exc
            if not self.solver_url:
                raise KentuckyPolicyBlockError('Kentucky policy block; KY_FLARESOLVERR_URL is unset')
            if not tried_cached:
                tried_cached = True
                credentials = self.credentials or (cache.get(self.credential_key) if self.use_cache else None)
                if credentials and credentials.get('expires', 0) > time.time():
                    self._apply(credentials)
                    # A cached session gets exactly one refresh after a renewed block.
                    refreshed = 1
                    continue
            if refreshed >= 2:
                if self.use_cache:
                    cache.delete(self.credential_key)
                raise KentuckyPolicyBlockError('Kentucky policy block persisted after browser recovery')
            self._solve()
            refreshed += 1

    def fetch_elections(self):
        return self._fetch('Elections')

    def fetch_contests(self):
        return self._fetch('Contests')

    def fetch_candidates(self):
        return self._fetch('Candidates')

    def fetch_geopolitical_units(self):
        return self._fetch('GeopoliticalUnits')

    def fetch_political_parties(self):
        return self._fetch('PoliticalParties')

    def fetch_current_results(self, *, include_local=True):
        return self._fetch('CurrentResults' if include_local else 'CurrentResultsExcludeLocal')


def _looks_like_policy_block(content):
    lowered = content[:4096].lower()
    return b'acceptable use policy' in lowered or b'<html' in lowered or b'<!doctype html' in lowered


def source_version_for(*datasets):
    digest = hashlib.sha256(PARSER_VERSION.encode())
    for content in datasets:
        digest.update(len(content).to_bytes(8, 'big'))
        digest.update(content)
    return digest.hexdigest()


def _local_name(tag):
    return tag.rsplit('}', 1)[-1]


@lru_cache(maxsize=256)
def _key(name):
    return re.sub('[^a-z0-9]', '', name.lower())


def _value(el, *names):
    wanted = {_key(n) for n in names}
    for child in el:
        if _key(_local_name(child.tag)) in wanted:
            return (child.text or '').strip()
    # Retain compatibility with archived v4 attribute fixtures.
    return next((v.strip() for k, v in el.attrib.items() if _key(k) in wanted), '')


def _elements(root, name):
    # WCF SummaryReport wrappers share their children's names. Never parse wrappers.
    return [el for el in root.iter() if _local_name(el.tag) == name
            and not any(_local_name(c.tag) == name for c in el)]


def _id(value, field):
    if not re.fullmatch(r'[1-9][0-9]*', value):
        raise ValueError(f'KY invalid required {field}: {value!r}')
    return value


def _integer(value, field, *, default=None):
    if value == '' and default is not None:
        return default
    if not re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)', value):
        raise ValueError(f'KY invalid nonnegative {field}: {value!r}')
    number = int(value.replace(',', ''))
    if number > 2147483647:
        raise ValueError(f'KY out-of-range {field}')
    return number


def _safe_date(value):
    try:
        return datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).date()
    except ValueError:
        try:
            return datetime.datetime.strptime(value, '%m/%d/%Y').date()
        except ValueError:
            return None


def _bool_attr(value):
    return value.lower() in {'true', '1', 'yes', 'y'}


def select_ky_election_id(election, elections_xml):
    records = _elements(ET.fromstring(elections_xml), 'Election')
    matches = [r for r in records if _safe_date(_value(r, 'ElectionDate')) == election.election_date
               and _value(r, 'ElectionType').replace('_', ' ').lower() ==
               election.election_type.replace('_', ' ').lower()]
    if len(matches) != 1 or (len(records) != 1 and any(not _value(r, 'ElectionId') for r in records)):
        return ''
    # A legacy configured ID never bypasses validation. The live feed has no ID.
    return _value(matches[0], 'ElectionId') or 'current'


def _insert(records, key, record, label):
    if key in records and records[key] != record:
        raise ValueError(f'KY conflicting duplicate {label}: {key}')
    records[key] = record


def _records(xml, tag, fields, election_id=None):
    records = {}
    for el in _elements(ET.fromstring(xml), tag):
        if election_id and _value(el, 'ElectionId') not in ('', election_id):
            continue
        record = {key: _value(el, *names) for key, names in fields.items()}
        identifier = _id(record['id'], f'{tag}Id')
        if tag == 'Candidate':
            identifier = (_id(record['contest_id'], 'ContestId'), identifier)
        _insert(records, identifier, record, tag)
    return records


def _parse_contests(xml, election_id):
    return _records(xml, 'Contest', {
        'id': ('ContestId',), 'name': ('ContestName',), 'scope_unit_id': ('ContestScopeUnitId',),
        'is_partisan': ('IsPartisan',), 'is_uncontested': ('IsUncontested',),
        'is_unexpired_term': ('IsUnexpiredTerm',), 'selectable_option': ('SelectableOption',),
        'party_id': ('PoliticalPartyId',), 'display_order': ('DisplayOrder',),
    }, election_id)


def _parse_candidates(xml, election_id):
    return _records(xml, 'Candidate', {
        'id': ('CandidateId',), 'contest_id': ('ContestId',), 'ballot_name': ('BallotName',),
        'party_id': ('PoliticalPartyId',), 'is_incumbent': ('IsIncumbent',),
        'is_write_in': ('IsWriteIn',), 'is_withdrawn': ('IsWithdrawn',),
    }, election_id)


def _parse_geopolitical_units(xml):
    if not xml:
        return {}
    return _records(xml, 'GeopoliticalUnit', {
        'id': ('UnitId',), 'name': ('UnitName',), 'type': ('UnitType',), 'parent': ('ParentId',),
    })


def statewide_unit_id(units):
    ids = [key for key, unit in units.items() if unit['type'] in {'State', '11'}]
    if len(ids) > 1:
        raise ValueError('KY multiple state units')
    return ids[0] if ids else '2'


def breakdown_fragment_for(gpu_id, units):
    unit = units.get(gpu_id, {})
    slug = re.sub('[^a-z0-9]+', '-', unit.get('name', '').lower()).strip('-')
    parent = re.sub('[^a-z0-9]+', '-', units.get(unit.get('parent'), {}).get('name', '').lower()).strip('-')
    if not slug:
        return f'gpu-{gpu_id}'
    if parent and unit.get('type') not in {'State', 'County', '11', '12'}:
        slug = f'{parent}-{slug}'
    return f'{slug[:220]}-gpu-{gpu_id}'


def total_unit_for_contest(contest, reported_gpu_ids, state_unit_id):
    return next((x for x in (contest.get('scope_unit_id'), state_unit_id) if x in reported_gpu_ids), '')


@dataclass
class KentuckyResult(AdapterResult):
    contests: dict = field(default_factory=dict)
    candidates: dict = field(default_factory=dict)
    units: dict = field(default_factory=dict)
    review: dict = field(default_factory=dict)


def parse_ky_snapshot(election_id, contests_xml, candidates_xml, current_results_xml,
                      geopolitical_units_xml=None, political_parties_xml=None, *, source_url=''):
    contests = _parse_contests(contests_xml, election_id)
    candidates = _parse_candidates(candidates_xml, election_id)
    units = _parse_geopolitical_units(geopolitical_units_xml)
    parties = _records(political_parties_xml, 'PoliticalParty', {
        'id': ('PartyId',), 'name': ('PartyName',), 'abbreviation': ('Abbreviation',),
    }) if political_parties_xml else {}
    for (contest_id, _), candidate in candidates.items():
        if contest_id not in contests or not candidate['ballot_name']:
            raise ValueError(f'KY broken candidate/contest join or missing ballot name: {candidate["id"]}')
    for contest in contests.values():
        if not contest['name']:
            raise ValueError(f'KY missing contest title: {contest["id"]}')
        if contest['scope_unit_id']:
            _id(contest['scope_unit_id'], 'ContestScopeUnitId')
        contest['selectable_option'] = _integer(contest['selectable_option'], 'SelectableOption', default=0)
    root = ET.fromstring(current_results_xml)
    reports = {}
    for el in _elements(root, 'ReportData'):
        uid = _id(_value(el, 'ReportingUnitId', 'gpu_id', 'Gup_id'), 'ReportingUnitId')
        report = {'status': _value(el, 'ReportingStatus', 'status')}
        for key, names in {
            'precinct_participating': ('PrecinctsParticipating', 'precinct_participating'),
            'precinct_reporting': ('PrecinctsReporting', 'precinct_reporting'),
            'ballots_cast': ('BallotsCast',), 'registered_voters': ('RegisteredVoters',),
        }.items():
            report[key] = _integer(_value(el, *names), key, default=0)
        _insert(reports, uid, report, 'ReportData')
    records = {}
    reported = {}
    for el in _elements(root, 'CandidateData'):
        cid = _id(_value(el, 'ContestId'), 'ContestId')
        # Only archived, explicitly election-qualified data may contain other elections.
        if cid not in contests and election_id != 'current' and any(x.attrib for x in _elements(root, 'CandidateData')):
            continue
        pid = _id(_value(el, 'CandidateId'), 'CandidateId')
        uid = _id(_value(el, 'ReportingUnitId', 'gpu_id', 'Gup_id'), 'ReportingUnitId')
        if cid not in contests or (cid, pid) not in candidates:
            raise ValueError(f'KY missing contest/candidate join: contest={cid} candidate={pid} unit={uid}')
        votes = _integer(_value(el, 'TotalVotes'), 'TotalVotes')
        day = _integer(_value(el, 'ElectionDayVotes'), 'ElectionDayVotes')
        if day > votes:
            raise ValueError(f'KY ElectionDayVotes exceeds TotalVotes: {cid}/{pid}/{uid}')
        _insert(records, (cid, pid, uid), (votes, day), 'CandidateData')
        reported.setdefault(cid, set()).add(uid)
    totals = {cid: total_unit_for_contest(contests[cid], ids, statewide_unit_id(units))
              for cid, ids in reported.items()}
    labels = {}
    for (cid, _), candidate in candidates.items():
        labels.setdefault(cid, set()).add(candidate['ballot_name'].upper())
    from results.tasks import _is_measure_contest
    measures = {cid: _is_measure_contest(c['name'], labels.get(cid, set())) for cid, c in contests.items()}
    rows = []
    for (cid, pid, uid), (votes, day) in records.items():
        contest, candidate = contests[cid], candidates[cid, pid]
        write_in = _bool_attr(candidate['is_write_in']) or candidate['ballot_name'].lower() in {'write-in', 'write in'}
        measure = measures[cid]
        report, unit = reports.get(uid, {}), units.get(uid, {})
        is_total = uid == totals[cid]
        rows.append(ResultRow(
            candidate_name=None if write_in or measure else candidate['ballot_name'],
            option_label=candidate['ballot_name'] if measure else None,
            vote_count=votes, vote_pct=None, is_winner=None, result_type=OfficialResult.ResultType.UNOFFICIAL,
            office_title=contest['name'], is_write_in_aggregate=write_in and not measure,
            jurisdiction_fragment='' if is_total else breakdown_fragment_for(uid, units),
            raw={
                'source': 'ky_sbe_live_xml', 'source_url': source_url or _DATA_BASE + '/CurrentResults',
                'election_id': election_id, 'contest_code': cid, 'contest_id': cid, 'candidate_id': pid,
                'gpu_id': uid, 'gpu_name': unit.get('name', ''), 'gpu_unit_type': unit.get('type', ''),
                'is_contest_total': is_total, 'has_contest_total': bool(totals[cid]),
                'election_day_votes': day, 'absentee_votes': votes - day,
                'reporting_status': report.get('status', ''),
                **{k: report.get(k, 0) for k in ('precinct_participating', 'precinct_reporting',
                                               'ballots_cast', 'registered_voters')},
                'is_withdrawn': _bool_attr(candidate['is_withdrawn']),
                'is_incumbent': _bool_attr(candidate['is_incumbent']),
                'is_unexpired_term': _bool_attr(contest['is_unexpired_term']),
                'is_partisan': _bool_attr(contest['is_partisan']),
                'party_id': candidate['party_id'], 'party': parties.get(candidate['party_id'], {}).get('abbreviation', ''),
                'contest_scope_unit_id': contest['scope_unit_id'], 'selectable_option': contest['selectable_option'],
            },
        ))
    return KentuckyResult(rows=rows, source_url=source_url or _DATA_BASE + '/CurrentResults',
                          mapping_confidence='full' if rows else 'none', contests=contests,
                          candidates=candidates, units=units)


def parse_ky_xml_results(election_id, contests_xml, candidates_xml, current_results_xml,
                         geopolitical_units_xml=None, political_parties_xml=None):
    return parse_ky_snapshot(election_id, contests_xml, candidates_xml, current_results_xml,
                             geopolitical_units_xml, political_parties_xml).rows


@register
class KentuckyAdapter(StateResultsAdapter):
    state = 'KY'
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id):
        return f'ky_sbe_live_xml:sha256:{election_id}'

    def fetch_results(self, election_date, election_id, *, use_cache=True, snapshot_dir=None):
        from elections.models import Election
        election = Election.objects.get(pk=election_id, state='KY')
        feed = str((election.source_metadata or {}).get('ky_results_feed') or 'all').lower()
        if feed not in {'all', 'exclude_local'}:
            raise ValueError(f'KY invalid ky_results_feed: {feed}')
        dataset = 'CurrentResults' if feed == 'all' else 'CurrentResultsExcludeLocal'
        client = KentuckyXmlClient(use_cache=use_cache)
        def fetch(name):
            if snapshot_dir:
                from pathlib import Path
                return (Path(snapshot_dir) / (name + '.xml')).read_bytes()
            return {
                'Elections': client.fetch_elections, 'Contests': client.fetch_contests,
                'Candidates': client.fetch_candidates, 'GeopoliticalUnits': client.fetch_geopolitical_units,
                'PoliticalParties': client.fetch_political_parties,
                dataset: lambda: client.fetch_current_results(include_local=feed == 'all'),
            }[name]()
        try:
            # Validate before downloading the large datasets. IDs in old configuration
            # cannot redirect this implicitly current-election feed.
            elections = fetch('Elections')
            source_id = select_ky_election_id(election, elections)
            if not source_id:
                return KentuckyResult([], _DATA_BASE + '/' + dataset, 'none', notes='KY election date/type mismatch')
            datasets = [fetch(name) for name in ('Contests', 'Candidates', dataset,
                                                 'GeopoliticalUnits', 'PoliticalParties')]
        except KentuckyPolicyBlockError as exc:
            logger.warning('ky_sbe.policy_block election=%s', election_id)
            return KentuckyResult([], _DATA_BASE + '/' + dataset, 'none', notes=str(exc))
        result = parse_ky_snapshot(source_id, *datasets, source_url=_DATA_BASE + '/' + dataset)
        result.source_version = source_version_for(elections, *datasets)
        # Reconcile on every fetch. Held contests and changed mappings must always
        # be reconsidered, including when upstream bytes have not changed.
        return result
