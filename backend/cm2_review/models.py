from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from cm2_core.models import PublicIdentityModel, UUIDModel


class IdentityReviewCase(PublicIdentityModel):
    class CaseType(models.TextChoices):
        PERSON_IDENTITY = "person_identity", "Person identity"
        FUZZY_PERSON_MATCH = "fuzzy_person_match", "Fuzzy person match"
        UNRESOLVED_RESULT_CHOICE = "unresolved_result_choice", "Unresolved result choice"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        DEFERRED = "deferred", "Deferred"
        SUPERSEDED = "superseded", "Superseded"

    class ResolutionAction(models.TextChoices):
        LINK_EXISTING = "link_existing", "Link existing"
        CONFIRM_NEW = "confirm_new", "Confirm new"
        MERGE_PEOPLE = "merge_people", "Merge people"
        LINK_CIVIC_DATA = "link_civic_data", "Link Civic-Data"
        DEFER = "defer", "Defer"
        REJECT = "reject", "Reject"

    case_type = models.CharField(max_length=32, choices=CaseType.choices)
    deduplication_key = models.CharField(max_length=512, unique=True)
    source_record = models.ForeignKey(
        "cm2_elections.PersonSourceRecord",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="identity_review_cases",
    )
    provisional_person = models.ForeignKey(
        "cm2_elections.Person",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="identity_review_cases",
    )
    result_choice = models.ForeignKey(
        "cm2_results.ResultChoice",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="identity_review_cases",
    )
    supporting_evidence = models.JSONField(default=dict, blank=True)
    conflicting_evidence = models.JSONField(default=dict, blank=True)
    has_private_evidence = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    resolution_action = models.CharField(max_length=24, choices=ResolutionAction.choices, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="cm2_identity_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    superseded_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_cases",
    )

    class Meta:
        ordering = ["status", "-created_at"]
        indexes = [models.Index(fields=["status", "case_type", "created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(source_record__isnull=False)
                    | models.Q(provisional_person__isnull=False)
                    | models.Q(result_choice__isnull=False)
                ),
                name="cm2_review_case_subject_required",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status__in=["approved", "rejected"])
                    | (
                        models.Q(reviewed_by__isnull=False)
                        & models.Q(reviewed_at__isnull=False)
                        & ~models.Q(resolution_action="")
                    )
                ),
                name="cm2_review_terminal_metadata",
            ),
            models.CheckConstraint(
                condition=~models.Q(id=models.F("superseded_by")),
                name="cm2_review_no_self_supersede",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.case_type}:{self.status}:{self.deduplication_key}"


class IdentityReviewSuggestion(UUIDModel):
    review_case = models.ForeignKey(
        IdentityReviewCase,
        on_delete=models.CASCADE,
        related_name="suggestions",
    )
    suggested_person = models.ForeignKey(
        "cm2_elections.Person",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="identity_review_suggestions",
    )
    external_scheme = models.CharField(max_length=64, blank=True)
    external_identifier = models.CharField(max_length=255, blank=True)
    rank = models.PositiveIntegerField()
    score = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    supporting_evidence = models.JSONField(default=dict, blank=True)
    conflicting_evidence = models.JSONField(default=dict, blank=True)
    uses_private_evidence = models.BooleanField(default=False)

    class Meta:
        ordering = ["review_case", "rank"]
        constraints = [
            models.UniqueConstraint(fields=["review_case", "rank"], name="cm2_review_suggestion_rank_uniq"),
            models.CheckConstraint(condition=models.Q(rank__gt=0), name="cm2_review_suggestion_rank_positive"),
            models.CheckConstraint(
                condition=(
                    models.Q(score__isnull=True)
                    | (models.Q(score__gte=Decimal("0")) & models.Q(score__lte=Decimal("1")))
                ),
                name="cm2_review_suggestion_score_valid",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(suggested_person__isnull=False)
                        & models.Q(external_scheme="")
                        & models.Q(external_identifier="")
                    )
                    | (
                        models.Q(suggested_person__isnull=True)
                        & ~models.Q(external_scheme="")
                        & ~models.Q(external_identifier="")
                    )
                ),
                name="cm2_review_suggestion_target_valid",
            ),
        ]

    def __str__(self) -> str:
        target = self.suggested_person or f"{self.external_scheme}:{self.external_identifier}"
        return f"{self.review_case_id}:{self.rank}:{target}"


class IdentityReviewAuditEvent(UUIDModel):
    class EventType(models.TextChoices):
        CREATED = "created", "Created"
        STATUS_CHANGED = "status_changed", "Status changed"
        RESOLVED = "resolved", "Resolved"
        DEFERRED = "deferred", "Deferred"
        SUPERSEDED = "superseded", "Superseded"
        NOTE_ADDED = "note_added", "Note added"

    review_case = models.ForeignKey(
        IdentityReviewCase,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="cm2_identity_review_events",
    )
    event_type = models.CharField(max_length=24, choices=EventType.choices)
    metadata = models.JSONField(default=dict, blank=True)
    has_private_evidence = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["review_case", "created_at"])]

    def __str__(self) -> str:
        return f"{self.review_case.public_id}:{self.event_type}:{self.created_at.isoformat()}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Identity review audit events are immutable.")
        return super().save(*args, **kwargs)
