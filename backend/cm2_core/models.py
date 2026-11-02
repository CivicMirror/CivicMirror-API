import uuid

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models


def generate_public_id() -> str:
    return str(uuid.uuid4())


def require_unchanged_fields(instance: models.Model, field_names: tuple[str, ...]) -> None:
    if instance._state.adding or not instance.pk:
        return

    previous = type(instance)._default_manager.filter(pk=instance.pk).values(*field_names).first()
    if previous is None:
        return

    changed = [field_name for field_name in field_names if previous[field_name] != getattr(instance, field_name)]
    if changed:
        raise ValidationError(f"Cannot modify immutable source fields: {', '.join(changed)}.")


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PublicIdentityModel(UUIDModel):
    public_id = models.CharField(
        max_length=255,
        unique=True,
        default=generate_public_id,
        editable=False,
    )

    class Meta:
        abstract = True


class SourceTrackedModel(PublicIdentityModel):
    source_artifact = models.ForeignKey(
        "cm2_core.SourceArtifact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    source_key = models.CharField(max_length=512, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True


class SourceArtifact(PublicIdentityModel):
    IMMUTABLE_SOURCE_FIELDS = (
        "public_id",
        "source_system",
        "source_type",
        "url",
        "retrieved_at",
        "source_timestamp",
        "content_sha256",
        "parser_version",
        "election_date",
        "supersedes_id",
    )

    class SourceType(models.TextChoices):
        ELECTIONS = "elections", "Election discovery"
        CANDIDATES = "candidates", "Candidate filing"
        RESULTS = "results", "Election results"
        CERTIFICATION = "certification", "Certification evidence"
        CIVIC_DATA = "civic_data", "Civic-Data snapshot"
        OTHER = "other", "Other"

    class ProcessingStatus(models.TextChoices):
        RETRIEVED = "retrieved", "Retrieved"
        VALIDATED = "validated", "Validated"
        APPLIED = "applied", "Applied"
        UNCHANGED = "unchanged", "Unchanged"
        FAILED = "failed", "Failed"

    source_system = models.CharField(max_length=64)
    source_type = models.CharField(max_length=32, choices=SourceType.choices)
    url = models.URLField(max_length=2048)
    retrieved_at = models.DateTimeField()
    source_timestamp = models.DateTimeField(null=True, blank=True)
    content_sha256 = models.CharField(
        max_length=64,
        validators=[
            RegexValidator(
                regex=r"^[0-9a-f]{64}$",
                message="Checksum must contain exactly 64 lowercase hexadecimal characters.",
            )
        ],
    )
    parser_version = models.CharField(max_length=64)
    election_date = models.DateField(null=True, blank=True)
    processing_status = models.CharField(
        max_length=16,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.RETRIEVED,
    )
    error = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="successor_versions",
    )

    class Meta:
        ordering = ["-retrieved_at", "source_system"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_system", "url", "content_sha256"],
                name="cm2_artifact_source_url_checksum_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["source_system", "source_type", "election_date"]),
            models.Index(fields=["processing_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.source_system}:{self.source_type}:{self.content_sha256[:12]}"

    def save(self, *args, **kwargs):
        require_unchanged_fields(self, self.IMMUTABLE_SOURCE_FIELDS)
        return super().save(*args, **kwargs)
