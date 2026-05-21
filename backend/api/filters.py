import django_filters
from django_filters import BooleanFilter, CharFilter, DateFilter, NumberFilter

from elections.models import Candidate, DistrictRecord, Election, Race


class ElectionFilterSet(django_filters.FilterSet):
    state = CharFilter(lookup_expr='iexact')
    status = CharFilter()
    jurisdiction_level = CharFilter()
    election_date__gte = DateFilter(field_name='election_date', lookup_expr='gte')
    election_date__lte = DateFilter(field_name='election_date', lookup_expr='lte')

    class Meta:
        model = Election
        fields = ['state', 'status', 'jurisdiction_level']


class RaceFilterSet(django_filters.FilterSet):
    election = NumberFilter()
    race_type = CharFilter()
    race_status = CharFilter()
    certification_status = CharFilter()
    state = CharFilter(field_name='election__state', lookup_expr='iexact')
    geography_scope = CharFilter(lookup_expr='iexact')
    source = CharFilter()

    class Meta:
        model = Race
        fields = ['election', 'race_type', 'race_status', 'certification_status', 'geography_scope', 'source']


class CandidateFilterSet(django_filters.FilterSet):
    race = NumberFilter()
    party = CharFilter(lookup_expr='icontains')
    incumbent = BooleanFilter()
    candidate_status = CharFilter()

    class Meta:
        model = Candidate
        fields = ['race', 'party', 'incumbent', 'candidate_status']


class DistrictFilterSet(django_filters.FilterSet):
    state = CharFilter(lookup_expr='iexact')
    district_type = CharFilter()

    class Meta:
        model = DistrictRecord
        fields = ['state', 'district_type']
