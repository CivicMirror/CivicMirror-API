from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import requests
from django.core.cache import cache

from results.adapters.ky import KentuckyXmlClient, parse_ky_xml_results, select_ky_election_id

FIXTURES = Path(__file__).parent / 'fixtures' / 'ky_live'


def feed(name):
    return (FIXTURES / f'{name}.xml').read_bytes()


def parse(results=None, **kwargs):
    return parse_ky_xml_results('current', feed('Contests'), feed('Candidates'),
                                results or feed('CurrentResults'), feed('GeopoliticalUnits'), **kwargs)


def test_observed_namespace_wrappers_and_fields():
    rows = parse()
    assert rows
    assert all(r.raw['contest_code'] and r.raw['candidate_id'] and r.raw['gpu_id'] for r in rows)
    assert all(r.result_type == 'unofficial' and r.is_winner is None for r in rows)
    assert any(r.raw['gpu_unit_type'] == 'State' for r in rows)
    assert any(r.raw['reporting_status'] == 'NotReporting' for r in rows)
    totals = [(r.raw['contest_code'], r.raw['candidate_id']) for r in rows if not r.jurisdiction_fragment]
    assert len(totals) == len(set(totals))
    assert any(r.raw['selectable_option'] == 4 for r in rows)
    assert any(r.option_label for r in rows)


def test_current_election_without_id_and_iso_timestamp():
    e = SimpleNamespace(election_date=date(2026, 11, 3), election_type='general', source_metadata={})
    assert select_ky_election_id(e, feed('Elections'))
    e.election_date = date(2026, 5, 19)
    e.source_metadata = {'ky_election_id': 'legacy'}
    assert not select_ky_election_id(e, feed('Elections'))
    e.election_date = date(2026, 11, 3)
    e.election_type = 'primary'
    assert not select_ky_election_id(e, feed('Elections'))


@pytest.mark.parametrize('field,value', [('TotalVotes', 'bad'), ('TotalVotes', '-1'),
                                        ('CandidateId', '999999'), ('ReportingUnitId', 'bad')])
def test_invalid_votes_ids_and_broken_joins_raise(field, value):
    from xml.etree import ElementTree as ET
    root = ET.fromstring(feed('CurrentResults'))
    el = next(x for x in root.iter() if x.tag.endswith('}' + field))
    el.text = value
    with pytest.raises(ValueError):
        parse(ET.tostring(root))


def response(content=b'<ArrayOfElection/>', status=200):
    r = requests.Response()
    r.status_code = status
    r._content = content
    return r


def solver():
    r = Mock()
    r.json.return_value = {'status': 'ok', 'solution': {'status': 200, 'userAgent': 'Browser',
                           'cookies': [{'name': 'session', 'value': 'secret', 'domain': 'vrsws.sos.ky.gov'}]}}
    return r


def test_transport_direct_success_does_not_solve(settings):
    settings.KY_FLARESOLVERR_URL = 'http://solver:8191'
    with patch('requests.Session.get', return_value=response()) as get, patch('requests.post') as post:
        assert KentuckyXmlClient().fetch_elections() == b'<ArrayOfElection/>'
    post.assert_not_called()
    assert get.call_args.kwargs['timeout'] == 60


def test_transport_solver_cookies_user_agent_and_original_xml(settings):
    cache.clear()
    settings.KY_FLARESOLVERR_URL = 'http://solver:8191'
    client = KentuckyXmlClient()
    with patch.object(client._session, 'get', side_effect=[response(b'<html>Policy</html>', 403), response()]), \
            patch('requests.post', return_value=solver()) as post:
        assert client.fetch_elections() == b'<ArrayOfElection/>'
    assert post.call_args.kwargs['json']['url'].endswith('/Elections')
    assert post.call_args.kwargs['json']['maxTimeout'] == 45000
    assert post.call_args.kwargs['timeout'] <= 45
    assert client._session.headers['User-Agent'] == 'Browser'
    assert client._session.cookies.get('session') == 'secret'


@pytest.mark.parametrize('failure', [requests.Timeout(), requests.ConnectionError()])
def test_solver_failures_are_retryable(settings, failure):
    cache.clear()
    settings.KY_FLARESOLVERR_URL = 'http://solver:8191'
    with patch('requests.Session.get', return_value=response(status=403)), \
            patch('requests.post', side_effect=failure):
        with pytest.raises(RuntimeError):
            KentuckyXmlClient().fetch_elections()


def test_persistent_policy_block_is_bounded(settings):
    from results.adapters.ky import KentuckyPolicyBlockError
    cache.clear()
    settings.KY_FLARESOLVERR_URL = 'http://solver:8191'
    with patch('requests.Session.get', return_value=response(status=403)) as get, \
            patch('requests.post', return_value=solver()) as post:
        with pytest.raises(KentuckyPolicyBlockError):
            KentuckyXmlClient().fetch_elections()
    assert post.call_count <= 2
    assert get.call_count <= 3


def test_duplicate_result_conflict_is_rejected():
    from xml.etree import ElementTree as ET
    root = ET.fromstring(feed('CurrentResults'))
    wrapper = next(iter(root))
    first = wrapper[0]
    duplicate = ET.fromstring(ET.tostring(first))
    next(c for c in duplicate if c.tag.endswith('}TotalVotes')).text = '10'
    wrapper.append(duplicate)
    with pytest.raises(ValueError, match='conflicting duplicate CandidateData'):
        parse(ET.tostring(root))


def test_expired_cached_credentials_refresh_with_paired_user_agent(settings):
    import time
    settings.KY_FLARESOLVERR_URL = 'http://solver:8191'
    client = KentuckyXmlClient()
    cache.set(client.credential_key, {'expires': time.time() - 1, 'cookies': [], 'user_agent': 'Expired'})
    with patch.object(client._session, 'get', side_effect=[response(status=403), response()]), \
            patch('requests.post', return_value=solver()) as post:
        client.fetch_elections()
    assert post.call_count == 1
    assert client._session.headers['User-Agent'] == 'Browser'


def test_cached_credentials_get_one_refresh_after_renewed_block(settings):
    import time
    settings.KY_FLARESOLVERR_URL = 'http://solver:8191'
    client = KentuckyXmlClient()
    cache.set(client.credential_key, {'expires': time.time() + 50, 'cookies': [], 'user_agent': 'Cached'})
    with patch.object(client._session, 'get', side_effect=[response(status=403), response(status=403), response()]), \
            patch('requests.post', return_value=solver()) as post:
        client.fetch_elections()
    assert post.call_count == 1
    assert client._session.headers['User-Agent'] == 'Browser'


def test_solver_credential_cache_lifetime_bounded_by_cookie_expiry(settings):
    import time
    settings.KY_FLARESOLVERR_URL = 'http://solver:8191'
    r = solver()
    r.json.return_value['solution']['cookies'][0]['expiry'] = time.time() + 30
    with patch('requests.post', return_value=r), patch('results.adapters.ky.cache.set') as put:
        KentuckyXmlClient()._solve()
    assert 1 <= put.call_args.kwargs['timeout'] <= 30


def test_dry_run_client_never_reads_or_writes_cache(settings):
    settings.KY_FLARESOLVERR_URL = 'http://solver:8191'
    with patch('results.adapters.ky.cache') as mocked, \
            patch('requests.Session.get', side_effect=[response(status=403), response()]), \
            patch('requests.post', return_value=solver()):
        KentuckyXmlClient(use_cache=False).fetch_elections()
    mocked.get.assert_not_called()
    mocked.set.assert_not_called()
    mocked.delete.assert_not_called()


def test_all_metadata_and_parser_version_affect_source_hash(monkeypatch):
    from results.adapters import ky
    datasets = [feed(n) for n in ('Elections', 'Contests', 'Candidates', 'CurrentResults',
                                  'GeopoliticalUnits', 'PoliticalParties')]
    initial = ky.source_version_for(*datasets)
    for index in range(len(datasets)):
        changed = list(datasets)
        changed[index] += b'\n'
        assert ky.source_version_for(*changed) != initial
    monkeypatch.setattr(ky, 'PARSER_VERSION', 'new-parser')
    assert ky.source_version_for(*datasets) != initial
