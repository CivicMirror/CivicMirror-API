from rest_framework import serializers

from .models import Candidacy, Contest, Election, Jurisdiction, Office, OfficeTerm, Person, PersonIdentifier


class JurisdictionSerializer(serializers.ModelSerializer):
    parent_public_id = serializers.CharField(source="parent.public_id", read_only=True, allow_null=True)

    class Meta:
        model = Jurisdiction
        fields = [
            "public_id",
            "name",
            "classification",
            "state",
            "parent_public_id",
            "active_start",
            "active_end",
            "record_status",
        ]


class OfficeSerializer(serializers.ModelSerializer):
    jurisdiction_public_id = serializers.CharField(source="jurisdiction.public_id", read_only=True)

    class Meta:
        model = Office
        fields = [
            "public_id",
            "jurisdiction_public_id",
            "canonical_name",
            "role",
            "default_term_months",
            "positions",
            "record_status",
        ]


class ElectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Election
        fields = ["public_id", "name", "election_date", "election_type", "lifecycle_status"]


class ContestSerializer(serializers.ModelSerializer):
    election_public_id = serializers.CharField(source="election.public_id", read_only=True)
    office_public_id = serializers.CharField(source="office.public_id", read_only=True)

    class Meta:
        model = Contest
        fields = [
            "public_id",
            "election_public_id",
            "office_public_id",
            "party_contest",
            "vote_for",
            "is_partisan",
            "is_unexpired",
            "lifecycle_status",
            "result_status",
        ]


class PersonIdentifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = PersonIdentifier
        fields = ["scheme", "identifier", "verification_method", "verified_at"]


class PersonSerializer(serializers.ModelSerializer):
    merged_into_public_id = serializers.CharField(source="merged_into.public_id", read_only=True, allow_null=True)
    identifiers = PersonIdentifierSerializer(many=True, read_only=True)

    class Meta:
        model = Person
        fields = [
            "public_id",
            "canonical_name",
            "prefix",
            "given_name",
            "middle_name",
            "family_name",
            "suffix",
            "identity_state",
            "merged_into_public_id",
            "identifiers",
        ]


class CandidacySerializer(serializers.ModelSerializer):
    person_public_id = serializers.CharField(source="person.public_id", read_only=True)
    contest_public_id = serializers.CharField(source="contest.public_id", read_only=True)

    class Meta:
        model = Candidacy
        fields = [
            "public_id",
            "person_public_id",
            "contest_public_id",
            "ballot_name",
            "party_candidate",
            "filing_date",
            "status",
        ]


class OfficeTermSerializer(serializers.ModelSerializer):
    person_public_id = serializers.CharField(source="person.public_id", read_only=True)
    office_public_id = serializers.CharField(source="office.public_id", read_only=True)

    class Meta:
        model = OfficeTerm
        fields = [
            "public_id",
            "person_public_id",
            "office_public_id",
            "start_date",
            "end_date",
            "method_of_selection",
            "role",
        ]
