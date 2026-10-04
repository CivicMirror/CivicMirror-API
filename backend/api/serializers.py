from rest_framework import serializers

from elections.models import Candidate, DistrictRecord, Election, ElectionCycle, MeasureOption, Race
from results.models import OfficialResult

from .filters import GEOGRAPHY_SCOPE_HELP


class ElectionCycleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ElectionCycle
        fields = ['id', 'cycle_year', 'description', 'cycle_start', 'cycle_end']


class ElectionSerializer(serializers.ModelSerializer):
    race_count = serializers.IntegerField(read_only=True)
    election_cycle = ElectionCycleSerializer(read_only=True)
    sources = serializers.ListField(source="contributing_sources", read_only=True)

    class Meta:
        model = Election
        fields = [
            'id', 'source_id', 'name', 'election_date', 'election_type', 'jurisdiction_level',
            'state', 'status', 'last_synced_at', 'election_cycle', 'race_count',
            'sources', 'field_provenance',
        ]


class MeasureOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeasureOption
        fields = ['id', 'option_label', 'race']


class CandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Candidate
        fields = [
            'id', 'name', 'party', 'incumbent', 'candidate_status',
            'description', 'image_url', 'website_url',
            'fec_candidate_id', 'bioguide_id', 'openstates_person_id',
            'contact_phone', 'contact_office', 'race',
            'field_provenance',
        ]


class OfficialResultSerializer(serializers.ModelSerializer):
    candidate_name = serializers.SerializerMethodField(
        help_text='Candidate name. Null for write-in aggregate rows and ballot-measure rows.',
    )
    candidate_party = serializers.SerializerMethodField(help_text='Candidate party, if known.')
    option_label = serializers.SerializerMethodField(
        help_text='Ballot-measure option (e.g. Yes/No). Null for candidate rows.',
    )

    class Meta:
        model = OfficialResult
        fields = [
            'id', 'race', 'candidate', 'candidate_name', 'candidate_party', 'measure_option', 'option_label',
            'vote_count', 'vote_pct', 'result_type', 'is_winner',
            'round_number', 'jurisdiction_fragment', 'is_write_in_aggregate',
            'certified_at', 'source_url',
        ]
        extra_kwargs = {
            'jurisdiction_fragment': {
                'help_text': 'Sub-jurisdiction this row covers (county, town, precinct). Blank = the contest total.',
            },
            'is_winner': {
                'help_text': 'True/False when known (from the source, or derived from certified totals); '
                             'null when not determined (e.g. ties, measures, races without a total row).',
            },
        }

    def get_candidate_name(self, obj):
        return obj.candidate.name if obj.candidate_id else None

    def get_candidate_party(self, obj):
        return (obj.candidate.party or None) if obj.candidate_id else None

    def get_option_label(self, obj):
        return obj.measure_option.option_label if obj.measure_option_id else None


class RaceListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Race
        fields = [
            'id', 'election', 'race_type', 'office_title', 'jurisdiction',
            'geography_scope', 'certification_status', 'race_status',
            'vote_method', 'ocd_division_id', 'source', 'last_synced_at',
            'party', 'normalized_party',
        ]
        extra_kwargs = {'geography_scope': {'help_text': GEOGRAPHY_SCOPE_HELP}}


class RaceDetailSerializer(serializers.ModelSerializer):
    candidates = CandidateSerializer(many=True, read_only=True)
    measure_options = MeasureOptionSerializer(many=True, read_only=True)
    sources = serializers.ListField(source="contributing_sources", read_only=True)
    results_url = serializers.SerializerMethodField(
        help_text='Path to this race\'s official results: /api/v1/races/{id}/results/.',
    )
    winners = serializers.SerializerMethodField(
        help_text='Candidates marked winner in the official results (empty until determined).',
    )

    class Meta:
        model = Race
        fields = [
            'id', 'election', 'race_type', 'office_title', 'jurisdiction',
            'geography_scope', 'certification_status', 'race_status',
            'vote_method', 'max_selections', 'ballot_type',
            'party', 'normalized_party',
            'ocd_division_id', 'normalized_office_title',
            'yes_vote_details', 'no_vote_details', 'match_confidence',
            'source', 'last_synced_at', 'candidates', 'measure_options',
            'sources', 'field_provenance', 'results_url', 'winners',
        ]
        extra_kwargs = {'geography_scope': {'help_text': GEOGRAPHY_SCOPE_HELP}}


    def get_results_url(self, obj):
        # Relative: behind Cloudflare -> tunnel -> nginx the request scheme reads as http.
        return f'/api/v1/races/{obj.pk}/results/'

    def get_winners(self, obj):
        rows = getattr(obj, 'winner_rows', None)
        if rows is None:  # not prefetched (single-object views)
            rows = obj.official_results.filter(is_winner=True, candidate__isnull=False).select_related('candidate')
        seen, winners = set(), []
        for row in rows:
            if row.candidate_id not in seen:
                seen.add(row.candidate_id)
                winners.append({'candidate_id': row.candidate_id, 'name': row.candidate.name})
        return winners

class DistrictRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DistrictRecord
        fields = [
            'id', 'state', 'district_type', 'district_number',
            'ocd_division_id', 'name', 'fips_code',
            'election_year_valid', 'approximate', 'last_updated',
        ]
