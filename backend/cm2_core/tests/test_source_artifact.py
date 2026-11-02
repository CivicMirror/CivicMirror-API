from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from cm2_core.models import SourceArtifact


@pytest.fixture
def artifact_values():
    return {
        "source_system": "nc_sbe",
        "source_type": SourceArtifact.SourceType.CANDIDATES,
        "url": "https://example.test/nc/candidates.csv",
        "retrieved_at": timezone.now(),
        "content_sha256": "a" * 64,
        "parser_version": "nc-candidates-v1",
        "election_date": date(2026, 11, 3),
        "processing_status": SourceArtifact.ProcessingStatus.VALIDATED,
        "metadata": {"content_type": "text/csv"},
    }


@pytest.mark.django_db
def test_source_artifact_has_separate_database_and_public_identifiers(artifact_values):
    artifact = SourceArtifact.objects.create(**artifact_values)

    assert str(artifact.id) != artifact.public_id
    assert artifact.source_system == "nc_sbe"
    assert artifact.election_date == date(2026, 11, 3)
    assert artifact.metadata == {"content_type": "text/csv"}


@pytest.mark.django_db
def test_unchanged_source_artifact_is_idempotent_across_parser_versions(artifact_values):
    SourceArtifact.objects.create(**artifact_values)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SourceArtifact.objects.create(
                **{
                    **artifact_values,
                    "parser_version": "nc-candidates-v2",
                }
            )


@pytest.mark.django_db
def test_changed_content_creates_a_successive_artifact_version(artifact_values):
    first = SourceArtifact.objects.create(**artifact_values)
    second = SourceArtifact.objects.create(
        **{
            **artifact_values,
            "content_sha256": "b" * 64,
            "supersedes": first,
        }
    )

    assert second.id != first.id
    assert second.supersedes == first


@pytest.mark.django_db
def test_checksum_must_be_lowercase_sha256(artifact_values):
    artifact = SourceArtifact(**{**artifact_values, "content_sha256": "not-a-checksum"})

    with pytest.raises(ValidationError, match="64 lowercase hexadecimal"):
        artifact.full_clean()


@pytest.mark.django_db
def test_artifact_content_identity_cannot_be_rewritten(artifact_values):
    artifact = SourceArtifact.objects.create(**artifact_values)
    artifact.content_sha256 = "b" * 64

    with pytest.raises(ValidationError, match="immutable source fields"):
        artifact.save()


@pytest.mark.django_db
def test_artifact_processing_state_can_advance(artifact_values):
    artifact = SourceArtifact.objects.create(**artifact_values)
    artifact.processing_status = SourceArtifact.ProcessingStatus.APPLIED
    artifact.metadata = {"rows_applied": 42}
    artifact.save()

    artifact.refresh_from_db()
    assert artifact.processing_status == SourceArtifact.ProcessingStatus.APPLIED
    assert artifact.metadata == {"rows_applied": 42}
