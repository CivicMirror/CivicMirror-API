"""
Tests for mock voting, community race submission, and user profile endpoints.

Firebase authentication is mocked via the settings flag FIREBASE_AUTH_ENABLED=False
and a mock verify_id_token via monkeypatching api.auth.
"""
import pytest
from django.test import Client

from elections.models import Candidate, Election, MeasureOption, Race
from community.models import MockVote, UserProfile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_UID = 'firebase-uid-test-1'
OTHER_UID = 'firebase-uid-test-2'


@pytest.fixture
def client(settings):
    settings.CIVICMIRROR_API_KEY = 'test-key'
    settings.FIREBASE_AUTH_ENABLED = False
    c = Client()
    c.defaults['HTTP_X_API_KEY'] = 'test-key'
    return c


@pytest.fixture
def authed_client(settings):
    """Client with both API key and Firebase Bearer token."""
    settings.CIVICMIRROR_API_KEY = 'test-key'
    settings.FIREBASE_AUTH_ENABLED = True
    c = Client()
    c.defaults['HTTP_X_API_KEY'] = 'test-key'
    c.defaults['HTTP_AUTHORIZATION'] = 'Bearer fake-token'
    return c


@pytest.fixture
def other_authed_client(settings):
    """Client authenticated as a different user."""
    settings.CIVICMIRROR_API_KEY = 'test-key'
    settings.FIREBASE_AUTH_ENABLED = True
    c = Client()
    c.defaults['HTTP_X_API_KEY'] = 'test-key'
    c.defaults['HTTP_AUTHORIZATION'] = 'Bearer other-fake-token'
    return c


@pytest.fixture
def election(db):
    return Election.objects.create(
        source_id='test-election-1',
        name='Test Election 2026',
        election_date='2026-11-03',
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state='WV',
        status=Election.Status.UPCOMING,
    )


@pytest.fixture
def active_race(db, election):
    return Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title='Governor',
        jurisdiction='West Virginia',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='civic_api:test:governor',
        vote_method=Race.VoteMethod.SINGLE_CHOICE,
    )


@pytest.fixture
def measure_race(db, election):
    return Race.objects.create(
        election=election,
        race_type=Race.RaceType.MEASURE,
        office_title='Amendment 1',
        jurisdiction='West Virginia',
        geography_scope='statewide',
        source=Race.Source.CIVIC_API,
        race_status=Race.RaceStatus.ACTIVE,
        canonical_key='civic_api:test:measure',
    )


@pytest.fixture
def candidate(db, active_race):
    return Candidate.objects.create(race=active_race, name='Alice Smith', party='DEM')


@pytest.fixture
def measure_option(db, measure_race):
    return MeasureOption.objects.create(race=measure_race, option_label='Yes')


def _mock_verify(uid):
    """Return a patch context for api.auth that validates token → uid."""
    from unittest.mock import MagicMock, patch
    from contextlib import ExitStack

    mock_fb = MagicMock()
    mock_fb.get_app.return_value = MagicMock()

    mock_fb_auth = MagicMock()
    mock_fb_auth.verify_id_token.return_value = {'uid': uid}

    class _MultiPatch:
        def __enter__(self):
            self._p1 = patch('api.auth.firebase_admin', mock_fb)
            self._p2 = patch('api.auth.fb_auth', mock_fb_auth)
            self._p3 = patch('api.auth._FIREBASE_AVAILABLE', True)
            self._p1.__enter__()
            self._p2.__enter__()
            self._p3.__enter__()
            return self

        def __exit__(self, *args):
            self._p3.__exit__(*args)
            self._p2.__exit__(*args)
            self._p1.__exit__(*args)

    return _MultiPatch()


# ---------------------------------------------------------------------------
# Vote action on RaceViewSet (POST /api/v1/races/{pk}/vote/)
# ---------------------------------------------------------------------------

class TestRaceVoteAction:
    def test_vote_success(self, authed_client, active_race, candidate):
        with _mock_verify(FAKE_UID):
            resp = authed_client.post(
                f'/api/v1/races/{active_race.pk}/vote/',
                data={'candidate_ids': [candidate.pk]},
                content_type='application/json',
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data['race'] == active_race.pk
        assert MockVote.objects.filter(uid=FAKE_UID, race=active_race).exists()

    def test_vote_duplicate_returns_409(self, authed_client, active_race, candidate):
        MockVote.objects.create(uid=FAKE_UID, race=active_race, candidate_ids=[candidate.pk])
        with _mock_verify(FAKE_UID):
            resp = authed_client.post(
                f'/api/v1/races/{active_race.pk}/vote/',
                data={'candidate_ids': [candidate.pk]},
                content_type='application/json',
            )
        assert resp.status_code == 409

    def test_vote_invalid_candidate_returns_400(self, authed_client, active_race):
        with _mock_verify(FAKE_UID):
            resp = authed_client.post(
                f'/api/v1/races/{active_race.pk}/vote/',
                data={'candidate_ids': [99999]},
                content_type='application/json',
            )
        assert resp.status_code == 400

    def test_vote_no_auth_returns_401(self, client, active_race, candidate):
        """API key only, no Firebase token → 401."""
        resp = client.post(
            f'/api/v1/races/{active_race.pk}/vote/',
            data={'candidate_ids': [candidate.pk]},
            content_type='application/json',
        )
        assert resp.status_code == 401

    def test_vote_inactive_race_returns_400(self, authed_client, election, candidate):
        draft_race = Race.objects.create(
            election=election,
            race_type=Race.RaceType.CANDIDATE,
            office_title='Closed Race',
            jurisdiction='WV',
            geography_scope='statewide',
            race_status=Race.RaceStatus.DRAFT,
            canonical_key='test:draft',
        )
        cand = Candidate.objects.create(race=draft_race, name='Bob')
        with _mock_verify(FAKE_UID):
            resp = authed_client.post(
                f'/api/v1/races/{draft_race.pk}/vote/',
                data={'candidate_ids': [cand.pk]},
                content_type='application/json',
            )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tally action (GET /api/v1/races/{pk}/tally/)
# ---------------------------------------------------------------------------

class TestRaceTallyAction:
    def test_tally_empty(self, client, active_race, candidate):
        resp = client.get(f'/api/v1/races/{active_race.pk}/tally/')
        assert resp.status_code == 200
        data = resp.json()
        assert data['total_votes'] == 0
        assert data['race_id'] == active_race.pk

    def test_tally_counts_correctly(self, client, active_race, candidate):
        another = Candidate.objects.create(race=active_race, name='Bob Jones', party='REP')
        MockVote.objects.create(uid='u1', race=active_race, candidate_ids=[candidate.pk])
        MockVote.objects.create(uid='u2', race=active_race, candidate_ids=[candidate.pk])
        MockVote.objects.create(uid='u3', race=active_race, candidate_ids=[another.pk])

        resp = client.get(f'/api/v1/races/{active_race.pk}/tally/')
        assert resp.status_code == 200
        data = resp.json()
        assert data['total_votes'] == 3
        by_id = {o['id']: o for o in data['options']}
        assert by_id[candidate.pk]['count'] == 2
        assert by_id[another.pk]['count'] == 1

    def test_tally_measure_race(self, client, measure_race, measure_option):
        no_opt = MeasureOption.objects.create(race=measure_race, option_label='No')
        MockVote.objects.create(uid='u1', race=measure_race, measure_option_id=measure_option.pk)
        MockVote.objects.create(uid='u2', race=measure_race, measure_option_id=measure_option.pk)
        MockVote.objects.create(uid='u3', race=measure_race, measure_option_id=no_opt.pk)

        resp = client.get(f'/api/v1/races/{measure_race.pk}/tally/')
        assert resp.status_code == 200
        data = resp.json()
        assert data['total_votes'] == 3
        by_label = {o['label']: o for o in data['options']}
        assert by_label['Yes']['count'] == 2
        assert by_label['No']['count'] == 1


# ---------------------------------------------------------------------------
# Ext vote/tally routes
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestExtVoteTallyRoutes:
    def test_ext_vote(self, authed_client, active_race, candidate):
        with _mock_verify(FAKE_UID):
            resp = authed_client.post(
                f'/api/v1/races/ext/{active_race.canonical_key}/vote/',
                data={'candidate_ids': [candidate.pk]},
                content_type='application/json',
            )
        assert resp.status_code == 201

    def test_ext_tally(self, client, active_race):
        resp = client.get(f'/api/v1/races/ext/{active_race.canonical_key}/tally/')
        assert resp.status_code == 200
        assert resp.json()['race_id'] == active_race.pk

    def test_ext_unknown_key_returns_404(self, client):
        resp = client.get('/api/v1/races/ext/nonexistent:key/tally/')
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Community race submission
# ---------------------------------------------------------------------------

class TestCommunityRaceSubmission:
    def _payload(self, election):
        return {
            'election_id': election.pk,
            'office_title': 'Mayor',
            'jurisdiction': 'Morgantown',
            'geography_scope': 'municipal',
            'race_type': Race.RaceType.CANDIDATE,
            'vote_method': Race.VoteMethod.SINGLE_CHOICE,
        }

    def test_create_community_race(self, authed_client, election):
        with _mock_verify(FAKE_UID):
            resp = authed_client.post(
                '/api/v1/races/community/',
                data=self._payload(election),
                content_type='application/json',
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data['source'] == Race.Source.COMMUNITY
        assert Race.objects.filter(source=Race.Source.COMMUNITY).exists()

    def test_create_sets_pending_review(self, authed_client, election):
        with _mock_verify(FAKE_UID):
            resp = authed_client.post(
                '/api/v1/races/community/',
                data=self._payload(election),
                content_type='application/json',
            )
        assert resp.status_code == 201
        race = Race.objects.get(pk=resp.json()['id'])
        assert race.race_status == Race.RaceStatus.PENDING_REVIEW
        assert race.submitted_by_uid == FAKE_UID

    def test_create_missing_required_field_returns_400(self, authed_client, election):
        payload = self._payload(election)
        del payload['office_title']
        with _mock_verify(FAKE_UID):
            resp = authed_client.post(
                '/api/v1/races/community/',
                data=payload,
                content_type='application/json',
            )
        assert resp.status_code == 400

    def test_delete_own_pending_race(self, authed_client, election):
        with _mock_verify(FAKE_UID):
            create_resp = authed_client.post(
                '/api/v1/races/community/',
                data=self._payload(election),
                content_type='application/json',
            )
        pk = create_resp.json()['id']
        with _mock_verify(FAKE_UID):
            del_resp = authed_client.delete(f'/api/v1/races/community/{pk}/')
        assert del_resp.status_code == 204
        assert not Race.objects.filter(pk=pk).exists()

    def test_delete_other_users_race_returns_403(self, authed_client, other_authed_client, election):
        with _mock_verify(FAKE_UID):
            create_resp = authed_client.post(
                '/api/v1/races/community/',
                data=self._payload(election),
                content_type='application/json',
            )
        pk = create_resp.json()['id']
        with _mock_verify(OTHER_UID):
            del_resp = other_authed_client.delete(f'/api/v1/races/community/{pk}/')
        assert del_resp.status_code == 403

    def test_no_auth_returns_401(self, client, election):
        resp = client.post(
            '/api/v1/races/community/',
            data=self._payload(election),
            content_type='application/json',
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# User profile and vote history
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestUserProfileAndVotes:
    def test_get_profile_auto_creates(self, authed_client):
        with _mock_verify(FAKE_UID):
            resp = authed_client.get('/api/v1/users/me/')
        assert resp.status_code == 200
        data = resp.json()
        assert data['uid'] == FAKE_UID
        assert UserProfile.objects.filter(uid=FAKE_UID).exists()

    def test_patch_display_name(self, authed_client):
        with _mock_verify(FAKE_UID):
            resp = authed_client.patch(
                '/api/v1/users/me/',
                data={'display_name': 'Alice Voter'},
                content_type='application/json',
            )
        assert resp.status_code == 200
        assert resp.json()['display_name'] == 'Alice Voter'

    def test_votes_returns_user_votes_only(self, authed_client, active_race, candidate):
        MockVote.objects.create(uid=FAKE_UID, race=active_race, candidate_ids=[candidate.pk])
        MockVote.objects.create(uid=OTHER_UID, race=active_race, candidate_ids=[candidate.pk])

        with _mock_verify(FAKE_UID):
            resp = authed_client.get('/api/v1/users/votes/')
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]['race'] == active_race.pk

    def test_no_auth_returns_401(self, client):
        resp = client.get('/api/v1/users/me/')
        assert resp.status_code == 401
