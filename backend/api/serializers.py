from rest_framework import serializers

from elections.models import Candidate, DistrictRecord, Election, ElectionCycle, MeasureOption, Race
from results.models import OfficialResult


class ElectionCycleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ElectionCycle
        fields = ['id', 'cycle_year', 'description', 'cycle_start', 'cycle_end']


class ElectionSerializer(serializers.ModelSerializer):
    race_count = serializers.IntegerField(read_only=True)
    election_cycle = ElectionCycleSerializer(read_only=True)

    class Meta:
        model = Election
        fields = [
            'id', 'source_id', 'name', 'election_date', 'jurisdiction_level',
            'state', 'status', 'last_synced_at', 'election_cycle', 'race_count',
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
        ]


class OfficialResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = OfficialResult
        fields = [
            'id', 'race', 'candidate', 'measure_option',
            'vote_count', 'vote_pct', 'result_type', 'is_winner',
            'round_number', 'jurisdiction_fragment', 'is_write_in_aggregate',
            'certified_at', 'source_url',
        ]


class RaceListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Race
        fields = [
            'id', 'election', 'race_type', 'office_title', 'jurisdiction',
            'geography_scope', 'certification_status', 'race_status',
            'vote_method', 'ocd_division_id', 'last_synced_at',
        ]


class RaceDetailSerializer(serializers.ModelSerializer):
    candidates = CandidateSerializer(many=True, read_only=True)
    measure_options = MeasureOptionSerializer(many=True, read_only=True)

    class Meta:
        model = Race
        fields = [
            'id', 'election', 'race_type', 'office_title', 'jurisdiction',
            'geography_scope', 'certification_status', 'race_status',
            'vote_method', 'max_selections', 'ballot_type',
            'ocd_division_id', 'normalized_office_title',
            'yes_vote_details', 'no_vote_details', 'match_confidence',
            'last_synced_at', 'candidates', 'measure_options',
        ]


class DistrictRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DistrictRecord
        fields = [
            'id', 'state', 'district_type', 'district_number',
            'ocd_division_id', 'name', 'fips_code',
            'election_year_valid', 'approximate', 'last_updated',
        ]
