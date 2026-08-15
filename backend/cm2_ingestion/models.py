from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from cm2_core.models import PublicIdentityModel, UUIDModel


class SyncLog(UUIDModel):
    class Capability(models.TextChoices):
        PRE_ELECTION = "pre_election", "Pre-election"
        RESULTS = "results", "Results"
        CERTIFICATION = "certification", "Certification"
        CIVIC_DATA = "civic_data", "Civic-Data comparison"

    class Status(models.TextChoices):
        STARTED = "started", "Started"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        PARTIAL = "partial", "Partial"
        UNCHANGED = "unchanged", "Unchanged"

    run_key = models.CharField(max_length=512, unique=True)
    state = models.CharField(max_length=2)
    source_system = models.CharField(max_length=64)
    capability = models.CharField(max_length=24, choices=Capability.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.STARTED)
    source_artifact = models.ForeignKey(
        "cm2_core.SourceArtifact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sync_logs",
    )
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    aggregate_counts = models.JSONField(default=dict, blank=True)
    error_summary = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["state", "capability", "status", "started_at"])]

    def clean(self):
        super().clean()
        if not isinstance(self.aggregate_counts, dict) or any(
            not isinstance(key, str) or type(value) is not int or value < 0
            for key, value in self.aggregate_counts.items()
        ):
            raise ValidationError({"aggregate_counts": "SyncLog counts must be nonnegative integer aggregates."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.state}:{self.capability}:{self.status}:{self.run_key}"


class ReconciliationReport(PublicIdentityModel):
    sync_log = models.OneToOneField(SyncLog, on_delete=models.PROTECT, related_name="report")
    source_artifact = models.ForeignKey(
        "cm2_core.SourceArtifact",
        on_delete=models.PROTECT,
        related_name="reconciliation_reports",
    )
    details = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.sync_log.state}:{self.sync_log.capability}:{self.public_id}"
