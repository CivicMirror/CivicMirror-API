from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from cm2_core.models import PublicIdentityModel


class ContestResult(PublicIdentityModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        UNOFFICIAL = "unofficial", "Unofficial"
        OFFICIAL = "official", "Official"
        CERTIFIED = "certified", "Certified"
        CORRECTED = "corrected", "Corrected"

    contest = models.OneToOneField(
        "cm2_elections.Contest",
        on_delete=models.PROTECT,
        related_name="current_result",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    source_artifact = models.ForeignKey(
        "cm2_core.SourceArtifact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="contest_results",
    )
    total_votes = models.BigIntegerField(default=0)
    reported_at = models.DateTimeField(null=True, blank=True)
    certified_at = models.DateTimeField(null=True, blank=True)
    source_evidence = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["contest"]
        indexes = [models.Index(fields=["status", "reported_at"])]
        constraints = [
            models.CheckConstraint(condition=models.Q(total_votes__gte=0), name="cm2_result_total_nonnegative")
        ]

    def __str__(self) -> str:
        return f"{self.contest} — {self.status}"


class ResultChoice(PublicIdentityModel):
    class ChoiceType(models.TextChoices):
        CANDIDATE = "candidate", "Candidate"
        NAMED_WRITE_IN = "named_write_in", "Named write-in"
        WRITE_IN_AGGREGATE = "write_in_aggregate", "Aggregate write-in"

    class ResolutionStatus(models.TextChoices):
        MATCHED = "matched", "Matched"
        PROVISIONAL = "provisional", "Provisional"
        AMBIGUOUS = "ambiguous", "Ambiguous"
        UNRESOLVED = "unresolved", "Unresolved"
        NOT_APPLICABLE = "not_applicable", "Not applicable"

    contest_result = models.ForeignKey(ContestResult, on_delete=models.CASCADE, related_name="choices")
    source_label = models.CharField(max_length=512)
    normalized_label = models.CharField(max_length=512)
    choice_type = models.CharField(max_length=24, choices=ChoiceType.choices)
    resolution_status = models.CharField(max_length=20, choices=ResolutionStatus.choices)
    candidacy = models.ForeignKey(
        "cm2_elections.Candidacy",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="result_choices",
    )
    vote_total = models.BigIntegerField(default=0)
    percentage = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    is_winner = models.BooleanField(null=True, blank=True)
    source_artifact = models.ForeignKey(
        "cm2_core.SourceArtifact",
        on_delete=models.PROTECT,
        related_name="result_choices",
    )
    source_choice_key = models.CharField(max_length=512)
    observation_lineage = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["contest_result", "-vote_total", "source_label"]
        indexes = [
            models.Index(fields=["choice_type", "resolution_status"]),
            models.Index(fields=["candidacy"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["contest_result", "source_choice_key"],
                name="cm2_result_choice_source_key_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(vote_total__gte=0),
                name="cm2_result_choice_votes_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(percentage__isnull=True)
                    | (models.Q(percentage__gte=Decimal("0")) & models.Q(percentage__lte=Decimal("100")))
                ),
                name="cm2_result_choice_percentage_valid",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(resolution_status="matched")
                    | models.Q(candidacy__isnull=False)
                ),
                name="cm2_result_choice_matched_target",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(choice_type="write_in_aggregate")
                    | (
                        models.Q(candidacy__isnull=True)
                        & models.Q(resolution_status="not_applicable")
                    )
                ),
                name="cm2_result_choice_aggregate_valid",
            ),
        ]

    def clean(self):
        super().clean()
        if self.candidacy_id and self.contest_result_id:
            contest_id = self.contest_result.contest_id
            if self.candidacy.contest_id != contest_id:
                raise ValidationError({"candidacy": "Candidacy must belong to the same Contest as this result."})

    def __str__(self) -> str:
        return f"{self.source_label} — {self.vote_total}"
