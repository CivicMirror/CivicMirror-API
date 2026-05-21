import logging

from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from elections.models import Candidate, DistrictRecord, Election, Race
from results.models import OfficialResult

from .filters import CandidateFilterSet, DistrictFilterSet, ElectionFilterSet, RaceFilterSet
from .permissions import HasAPIKey
from .serializers import (
    CandidateSerializer,
    DistrictRecordSerializer,
    ElectionSerializer,
    MeasureOptionSerializer,
    OfficialResultSerializer,
    RaceDetailSerializer,
    RaceListSerializer,
)

logger = logging.getLogger(__name__)


def resolve_state_from_zip(zip_code: str) -> str | None:
    try:
        import zipcodes
        results = zipcodes.matching(zip_code)
        if results:
            return results[0].get('state')
    except Exception:
        pass
    return None


class ElectionViewSet(ReadOnlyModelViewSet):
    serializer_class = ElectionSerializer
    permission_classes = [HasAPIKey]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = ElectionFilterSet
    search_fields = ['name', 'state']
    ordering_fields = ['election_date', 'name', 'state']
    ordering = ['election_date']

    def get_queryset(self):
        return Election.objects.select_related('election_cycle').annotate(
            race_count=Count('races')
        )

    @action(detail=True, url_path='races', url_name='races')
    def races(self, request, pk=None):
        election = self.get_object()
        qs = (
            election.races
            .filter(race_status=Race.RaceStatus.ACTIVE)
            .prefetch_related('candidates', 'measure_options')
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(RaceDetailSerializer(page, many=True, context={'request': request}).data)
        return Response(RaceDetailSerializer(qs, many=True, context={'request': request}).data)


class RaceViewSet(ReadOnlyModelViewSet):
    permission_classes = [HasAPIKey]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = RaceFilterSet
    search_fields = ['office_title', 'jurisdiction']
    ordering_fields = ['office_title', 'election__election_date']
    ordering = ['office_title']
    # Restrict pk routing to integers so static prefixes (community, ext) route correctly.
    lookup_value_regex = r'\d+'

    def get_queryset(self):
        qs = Race.objects.select_related('election')
        if self.action in ('retrieve', 'candidates', 'results'):
            qs = qs.prefetch_related('candidates', 'measure_options')
        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return RaceListSerializer
        return RaceDetailSerializer

    @action(detail=True, url_path='candidates', url_name='candidates')
    def candidates(self, request, pk=None):
        race = self.get_object()
        qs = race.candidates.all()
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(CandidateSerializer(page, many=True).data)
        return Response(CandidateSerializer(qs, many=True).data)

    @action(detail=True, url_path='results', url_name='results')
    def results(self, request, pk=None):
        race = self.get_object()
        qs = race.official_results.all()
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(OfficialResultSerializer(page, many=True).data)
        return Response(OfficialResultSerializer(qs, many=True).data)


class BallotMeasureViewSet(ReadOnlyModelViewSet):
    """Convenience endpoint: races filtered to race_type=MEASURE."""
    permission_classes = [HasAPIKey]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = RaceFilterSet
    search_fields = ['office_title', 'jurisdiction']
    ordering_fields = ['office_title', 'election__election_date']
    ordering = ['office_title']

    def get_queryset(self):
        qs = Race.objects.filter(race_type=Race.RaceType.MEASURE).select_related('election')
        if self.action == 'retrieve':
            qs = qs.prefetch_related('candidates', 'measure_options')
        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return RaceListSerializer
        return RaceDetailSerializer


class CandidateViewSet(ReadOnlyModelViewSet):
    serializer_class = CandidateSerializer
    permission_classes = [HasAPIKey]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = CandidateFilterSet
    search_fields = ['name', 'party']
    ordering_fields = ['name', 'party']
    ordering = ['name']

    def get_queryset(self):
        return Candidate.objects.select_related('race__election')


class DistrictViewSet(ReadOnlyModelViewSet):
    serializer_class = DistrictRecordSerializer
    permission_classes = [HasAPIKey]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = DistrictFilterSet
    search_fields = ['name', 'ocd_division_id']
    ordering_fields = ['name', 'state', 'district_type']
    ordering = ['state', 'name']

    def get_queryset(self):
        return DistrictRecord.objects.all()


@extend_schema(
    parameters=[
        OpenApiParameter('zip', str, OpenApiParameter.QUERY, required=True, description='5-digit US ZIP code'),
        OpenApiParameter('election_id', int, OpenApiParameter.QUERY, required=False, description='Filter by Election database ID'),
    ],
    responses={200: RaceDetailSerializer(many=True)},
    description=(
        'State-level ballot lookup. Returns all active elections and races '
        'for the state associated with the given ZIP code. '
        'Note: local district races may not match the specific voter address — '
        'use the election sync and detailed race endpoints for full coverage.'
    ),
)
class LookupView(APIView):
    permission_classes = [HasAPIKey]

    def get(self, request):
        zip_code = request.query_params.get('zip', '').strip()
        election_id = request.query_params.get('election_id', '').strip()

        if not zip_code:
            return Response({'error': 'zip parameter is required'}, status=400)

        state = resolve_state_from_zip(zip_code)
        if not state:
            return Response({'error': 'Invalid or unrecognized ZIP code'}, status=400)

        elections_qs = (
            Election.objects
            .filter(state=state)
            .exclude(status=Election.Status.ARCHIVED)
            .annotate(race_count=Count('races'))
        )

        if election_id:
            try:
                elections_qs = elections_qs.filter(pk=int(election_id))
            except ValueError:
                return Response({'error': 'election_id must be an integer'}, status=400)

        results = []
        for election in elections_qs:
            races = (
                election.races
                .filter(race_status=Race.RaceStatus.ACTIVE)
                .prefetch_related('candidates', 'measure_options')
            )
            results.append({
                'election': ElectionSerializer(election, context={'request': request}).data,
                'races': RaceDetailSerializer(races, many=True, context={'request': request}).data,
            })

        return Response(results)
