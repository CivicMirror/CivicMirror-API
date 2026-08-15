from rest_framework import serializers

from .models import ContestResult, ResultChoice


class ResultChoiceSerializer(serializers.ModelSerializer):
    candidacy_public_id = serializers.CharField(source="candidacy.public_id", read_only=True, allow_null=True)

    class Meta:
        model = ResultChoice
        fields = [
            "public_id",
            "source_label",
            "normalized_label",
            "choice_type",
            "resolution_status",
            "candidacy_public_id",
            "vote_total",
            "percentage",
            "is_winner",
        ]


class ContestResultSerializer(serializers.ModelSerializer):
    contest_public_id = serializers.CharField(source="contest.public_id", read_only=True)
    choices = ResultChoiceSerializer(many=True, read_only=True)

    class Meta:
        model = ContestResult
        fields = [
            "public_id",
            "contest_public_id",
            "status",
            "total_votes",
            "reported_at",
            "certified_at",
            "choices",
        ]
