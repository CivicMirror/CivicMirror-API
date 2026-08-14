from rest_framework import serializers

from .models import IdentityReviewAuditEvent, IdentityReviewCase, IdentityReviewSuggestion


class IdentityReviewSuggestionSerializer(serializers.ModelSerializer):
    suggested_person_public_id = serializers.CharField(
        source="suggested_person.public_id",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = IdentityReviewSuggestion
        fields = [
            "public_id",
            "rank",
            "score",
            "suggested_person_public_id",
            "external_scheme",
            "external_identifier",
            "uses_private_evidence",
        ]


class IdentityReviewAuditEventSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source="actor.username", read_only=True, allow_null=True)

    class Meta:
        model = IdentityReviewAuditEvent
        fields = ["id", "event_type", "actor_username", "created_at", "metadata", "has_private_evidence"]


class IdentityReviewCaseSerializer(serializers.ModelSerializer):
    source_record_public_id = serializers.CharField(source="source_record.public_id", read_only=True, allow_null=True)
    provisional_person_public_id = serializers.CharField(
        source="provisional_person.public_id",
        read_only=True,
        allow_null=True,
    )
    result_choice_public_id = serializers.CharField(source="result_choice.public_id", read_only=True, allow_null=True)
    suggestions = IdentityReviewSuggestionSerializer(many=True, read_only=True)
    audit_events = IdentityReviewAuditEventSerializer(many=True, read_only=True)

    supporting_evidence = serializers.SerializerMethodField()
    conflicting_evidence = serializers.SerializerMethodField()

    class Meta:
        model = IdentityReviewCase
        fields = [
            "public_id",
            "case_type",
            "status",
            "resolution_action",
            "source_record_public_id",
            "provisional_person_public_id",
            "result_choice_public_id",
            "supporting_evidence",
            "conflicting_evidence",
            "has_private_evidence",
            "reviewed_at",
            "suggestions",
            "audit_events",
        ]

    def get_supporting_evidence(self, obj):
        return {"redacted": True} if obj.has_private_evidence else obj.supporting_evidence

    def get_conflicting_evidence(self, obj):
        return {"redacted": True} if obj.has_private_evidence else obj.conflicting_evidence
