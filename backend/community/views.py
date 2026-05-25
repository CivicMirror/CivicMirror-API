import logging

from django.shortcuts import get_object_or_404
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from api.auth import FirebaseAuthentication
from api.permissions import HasAPIKey, IsFirebaseAuthenticated
from api.serializers import RaceDetailSerializer
from elections.models import Race

from .models import MockVote
from .serializers import MyVoteSummarySerializer, UserProfileSerializer
from .services import cast_vote, create_community_race, get_or_create_profile, get_tally

logger = logging.getLogger(__name__)


def _get_race_by_canonical_key(external_id: str) -> Race:
    return get_object_or_404(Race, canonical_key=external_id)


def _get_race_by_pk(pk) -> Race:
    return get_object_or_404(Race, pk=pk)


def _get_uid(request) -> str | None:
    """Return a stable uid string for either Firebase or Django Token auth."""
    if isinstance(request.auth, dict):
        return request.auth.get('uid')
    if request.user and request.user.is_authenticated:
        return f'user:{request.user.pk}'
    return None


def _is_authenticated(request) -> bool:
    return _get_uid(request) is not None


# ---------------------------------------------------------------------------
# PK-based vote/tally routes (POST /races/{pk}/vote/, GET /races/{pk}/tally/)
# ---------------------------------------------------------------------------

class PkVoteView(APIView):
    """POST /api/v1/races/{pk}/vote/"""
    authentication_classes = [FirebaseAuthentication, TokenAuthentication]
    permission_classes = [HasAPIKey]

    def post(self, request, pk):
        uid = _get_uid(request)
        if not uid:
            return Response({'detail': 'Authentication required.'}, status=401)
        race = _get_race_by_pk(pk)
        result, error, status_code = cast_vote(uid=uid, race=race, payload=request.data)
        if error:
            return Response(error, status=status_code)
        return Response(result, status=201)


class PkTallyView(APIView):
    """GET /api/v1/races/{pk}/tally/"""
    permission_classes = [HasAPIKey]

    def get(self, request, pk):
        race = _get_race_by_pk(pk)
        return Response(get_tally(race))


# ---------------------------------------------------------------------------
# ext/{external_id}/vote/ and ext/{external_id}/tally/
# ---------------------------------------------------------------------------

class ExtVoteView(APIView):
    """POST /api/v1/races/ext/{external_id}/vote/"""
    authentication_classes = [FirebaseAuthentication, TokenAuthentication]
    permission_classes = [HasAPIKey]

    def post(self, request, external_id):
        uid = _get_uid(request)
        if not uid:
            return Response({'detail': 'Authentication required.'}, status=401)
        race = _get_race_by_canonical_key(external_id)
        result, error, status_code = cast_vote(uid=uid, race=race, payload=request.data)
        if error:
            return Response(error, status=status_code)
        return Response(result, status=201)


class ExtTallyView(APIView):
    """GET /api/v1/races/ext/{external_id}/tally/"""
    permission_classes = [HasAPIKey]

    def get(self, request, external_id):
        race = _get_race_by_canonical_key(external_id)
        return Response(get_tally(race))


# ---------------------------------------------------------------------------
# Community race submission
# ---------------------------------------------------------------------------

class CommunityRaceListCreateView(APIView):
    """POST /api/v1/races/community/"""
    authentication_classes = [FirebaseAuthentication, TokenAuthentication]
    permission_classes = [HasAPIKey]

    def post(self, request):
        uid = _get_uid(request)
        if not uid:
            return Response({'detail': 'Authentication required.'}, status=401)
        race, error, status_code = create_community_race(uid=uid, payload=request.data)
        if error:
            return Response(error, status=status_code)
        return Response(
            RaceDetailSerializer(race, context={'request': request}).data,
            status=201,
        )


class CommunityRaceDetailView(APIView):
    """PATCH /DELETE /api/v1/races/community/{id}/"""
    authentication_classes = [FirebaseAuthentication, TokenAuthentication]
    permission_classes = [HasAPIKey]

    def _get_owned_race(self, request, pk):
        race = get_object_or_404(Race, pk=pk, source=Race.Source.COMMUNITY)
        uid = _get_uid(request)
        if not uid:
            return race, Response({'detail': 'Authentication required.'}, status=401)
        if race.submitted_by_uid != uid:
            return race, Response({'error': 'You do not have permission to modify this race.'}, status=403)
        return race, None

    def patch(self, request, pk):
        race, err = self._get_owned_race(request, pk)
        if err:
            return err

        allowed_fields = {'office_title', 'jurisdiction', 'source_url', 'candidates'}
        update_data = {k: v for k, v in request.data.items() if k in allowed_fields}

        if 'office_title' in update_data:
            race.office_title = update_data['office_title']
        if 'jurisdiction' in update_data:
            race.jurisdiction = update_data['jurisdiction']
        if 'source_url' in update_data:
            race.source_links = [update_data['source_url']] if update_data['source_url'] else []
        if 'candidates' in update_data:
            from elections.models import Candidate
            race.candidates.all().delete()
            for c in update_data['candidates']:
                if isinstance(c, dict) and c.get('name'):
                    Candidate.objects.create(
                        race=race,
                        name=c['name'],
                        party=c.get('party', ''),
                        website_url=c.get('website_url', ''),
                    )

        race.save()
        race.refresh_from_db()
        return Response(RaceDetailSerializer(race, context={'request': request}).data)

    def delete(self, request, pk):
        race, err = self._get_owned_race(request, pk)
        if err:
            return err
        if race.race_status != Race.RaceStatus.PENDING_REVIEW:
            return Response(
                {'error': 'Only pending-review races can be deleted.'},
                status=400,
            )
        race.delete()
        return Response(status=204)


# ---------------------------------------------------------------------------
# User profile and vote history
# ---------------------------------------------------------------------------

class UserProfileView(APIView):
    """GET /PATCH /api/v1/users/me/"""
    authentication_classes = [FirebaseAuthentication, TokenAuthentication]
    permission_classes = [HasAPIKey]

    def get(self, request):
        uid = _get_uid(request)
        if not uid:
            return Response({'detail': 'Authentication required.'}, status=401)
        profile = get_or_create_profile(uid)
        return Response(UserProfileSerializer(profile).data)

    def patch(self, request):
        uid = _get_uid(request)
        if not uid:
            return Response({'detail': 'Authentication required.'}, status=401)
        profile = get_or_create_profile(uid)
        if 'display_name' in request.data:
            display_name = str(request.data['display_name'])[:255]
            profile.display_name = display_name
            profile.save(update_fields=['display_name'])
        return Response(UserProfileSerializer(profile).data)


class UserVotesView(APIView):
    """GET /api/v1/users/votes/"""
    authentication_classes = [FirebaseAuthentication, TokenAuthentication]
    permission_classes = [HasAPIKey]

    def get(self, request):
        uid = _get_uid(request)
        if not uid:
            return Response({'detail': 'Authentication required.'}, status=401)
        votes = (
            MockVote.objects
            .filter(uid=uid)
            .select_related('race__election')
            .order_by('-created_at')
        )
        return Response(MyVoteSummarySerializer(votes, many=True).data)
