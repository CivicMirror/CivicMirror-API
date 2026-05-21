from rest_framework import serializers

from .models import MockVote, UserProfile


class UserProfileSerializer(serializers.ModelSerializer):
    vote_count = serializers.IntegerField(read_only=True)
    submission_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = UserProfile
        fields = ['uid', 'display_name', 'created_at', 'vote_count', 'submission_count']
        read_only_fields = ['uid', 'created_at', 'vote_count', 'submission_count']


class MyVoteSummarySerializer(serializers.ModelSerializer):
    race_title = serializers.SerializerMethodField()
    election_name = serializers.SerializerMethodField()
    selection_summary = serializers.SerializerMethodField()

    class Meta:
        model = MockVote
        fields = ['id', 'race', 'race_title', 'election_name', 'selection_summary', 'created_at']

    def get_race_title(self, obj):
        return f'{obj.race.office_title} — {obj.race.jurisdiction}'

    def get_election_name(self, obj):
        return obj.race.election.name

    def get_selection_summary(self, obj):
        if obj.measure_option_id is not None:
            from elections.models import MeasureOption
            try:
                return MeasureOption.objects.get(pk=obj.measure_option_id).option_label
            except MeasureOption.DoesNotExist:
                return str(obj.measure_option_id)
        if obj.ranked_selections:
            from elections.models import Candidate
            names = list(
                Candidate.objects.filter(pk__in=obj.ranked_selections)
                .values_list('name', flat=True)
            )
            return ', '.join(names)
        if obj.candidate_ids:
            from elections.models import Candidate
            names = list(
                Candidate.objects.filter(pk__in=obj.candidate_ids)
                .values_list('name', flat=True)
            )
            return ', '.join(names)
        return ''
