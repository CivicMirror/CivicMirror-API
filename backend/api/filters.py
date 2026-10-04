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


GEOGRAPHY_SCOPE_HELP = (
    'Where the race is elected. Canonical values: federal, statewide, district (state legislative, judicial or other sub-state district), countywide, local (municipal, township, school board, special district). Blank means unknown. Some sources still use their own values (e.g. citywide, state_legislative_district).'
)


class RaceFilterSet(django_filters.FilterSet):
    election = NumberFilter(help_text='Election ID.')
    race_type = CharFilter(help_text='candidate or measure.')
    race_status = CharFilter()
    certification_status = CharFilter()
    state = CharFilter(field_name='election__state', lookup_expr='iexact', help_text='Two-letter state code, e.g. NC.')
    geography_scope = CharFilter(lookup_expr='iexact', help_text=GEOGRAPHY_SCOPE_HELP)
    jurisdiction_level = CharFilter(field_name='election__jurisdiction_level')
    source = CharFilter()
    election_date__gte = DateFilter(field_name='election__election_date', lookup_expr='gte')
    election_date__lte = DateFilter(field_name='election__election_date', lookup_expr='lte')

    class Meta:
        model = Race
        fields = ['election', 'race_type', 'race_status', 'certification_status', 'geography_scope', 'jurisdiction_level', 'source']


class CandidateFilterSet(django_filters.FilterSet):
    race = NumberFilter(help_text='Race ID: candidates in one race.')
    election = NumberFilter(
        field_name='race__election',
        help_text=(
            'Election ID: every candidate in the election, in one paginated list. Use this '
            '(with page_size up to 500) instead of one request per race.'
        ),
    )
    state = CharFilter(
        field_name='race__election__state', lookup_expr='iexact', help_text='Two-letter state code, e.g. NC.',
    )
    geography_scope = CharFilter(
        field_name='race__geography_scope', lookup_expr='iexact',
        help_text='Filter by the race\'s geography_scope (see /races/).',
    )
    party = CharFilter(lookup_expr='icontains', help_text='Case-insensitive substring, e.g. democrat.')
    incumbent = BooleanFilter()
    candidate_status = CharFilter(help_text='running, withdrawn, disqualified, or write_in.')

    class Meta:
        model = Candidate
        fields = ['race', 'election', 'state', 'geography_scope', 'party', 'incumbent', 'candidate_status']


class DistrictFilterSet(django_filters.FilterSet):
    state = CharFilter(lookup_expr='iexact')
    district_type = CharFilter()

    class Meta:
        model = DistrictRecord
        fields = ['state', 'district_type']
