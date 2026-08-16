from django.conf import settings
from django.db import models

from cm2_core.models import SourceTrackedModel, UUIDModel, require_unchanged_fields


class RecordStatus(models.TextChoices):
    PROVISIONAL = "provisional", "Provisional"
    VERIFIED = "verified", "Verified"
    INACTIVE = "inactive", "Inactive"


class Jurisdiction(SourceTrackedModel):
    class Classification(models.TextChoices):
        STATE = "state", "State"
        CONGRESSIONAL_DISTRICT = "congressional_district", "Congressional district"
        STATE_LEGISLATIVE_DISTRICT = "state_legislative_district", "State legislative district"
        COUNTY = "county", "County"
        MUNICIPALITY = "municipality", "Municipality"
        JUDICIAL_DISTRICT = "judicial_district", "Judicial district"
        SCHOOL_DISTRICT = "school_district", "School district"
        OTHER = "other", "Other"

    RecordStatus = RecordStatus

    name = models.CharField(max_length=255)
    classification = models.CharField(max_length=32, choices=Classification.choices)
    state = models.CharField(max_length=2)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    active_start = models.DateField(null=True, blank=True)
    active_end = models.DateField(null=True, blank=True)
    record_status = models.CharField(
        max_length=16,
        choices=RecordStatus.choices,
        default=RecordStatus.PROVISIONAL,
    )

    class Meta:
        ordering = ["state", "classification", "name"]
        indexes = [models.Index(fields=["state", "classification", "record_status"])]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(id=models.F("parent")),
                name="cm2_juris_no_self_parent",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(active_start__isnull=True)
                    | models.Q(active_end__isnull=True)
                    | models.Q(active_end__gte=models.F("active_start"))
                ),
                name="cm2_juris_active_dates_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.state})"


class Office(SourceTrackedModel):
    RecordStatus = RecordStatus

    jurisdiction = models.ForeignKey(Jurisdiction, on_delete=models.PROTECT, related_name="offices")
    canonical_name = models.CharField(max_length=255)
    role = models.CharField(max_length=64)
    default_term_months = models.PositiveSmallIntegerField(null=True, blank=True)
    positions = models.PositiveSmallIntegerField(default=1)
    record_status = models.CharField(
        max_length=16,
        choices=RecordStatus.choices,
        default=RecordStatus.PROVISIONAL,
    )

    class Meta:
        ordering = ["jurisdiction__state", "canonical_name"]
        indexes = [models.Index(fields=["jurisdiction", "record_status"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(positions__gt=0),
                name="cm2_office_positions_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(default_term_months__isnull=True) | models.Q(default_term_months__gt=0),
                name="cm2_office_term_months_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.canonical_name} — {self.jurisdiction.name}"


class Election(SourceTrackedModel):
    class ElectionType(models.TextChoices):
        GENERAL = "general", "General"
        PRIMARY = "primary", "Primary"
        PRIMARY_RUNOFF = "primary_runoff", "Primary runoff"
        GENERAL_RUNOFF = "general_runoff", "General runoff"
        SPECIAL = "special", "Special"
        MUNICIPAL = "municipal", "Municipal"
        OTHER = "other", "Other"

    class LifecycleStatus(models.TextChoices):
        PROVISIONAL = "provisional", "Provisional"
        UPCOMING = "upcoming", "Upcoming"
        ACTIVE = "active", "Active"
        RESULTS_PENDING = "results_pending", "Results pending"
        COMPLETE = "complete", "Complete"
        CANCELLED = "cancelled", "Cancelled"
        ARCHIVED = "archived", "Archived"

    name = models.CharField(max_length=255)
    election_date = models.DateField()
    election_type = models.CharField(max_length=24, choices=ElectionType.choices)
    lifecycle_status = models.CharField(
        max_length=24,
        choices=LifecycleStatus.choices,
        default=LifecycleStatus.PROVISIONAL,
    )

    class Meta:
        ordering = ["election_date", "name"]
        indexes = [models.Index(fields=["election_date", "election_type", "lifecycle_status"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.election_date})"


class Contest(SourceTrackedModel):
    class LifecycleStatus(models.TextChoices):
        PROVISIONAL = "provisional", "Provisional"
        UPCOMING = "upcoming", "Upcoming"
        ACTIVE = "active", "Active"
        COMPLETE = "complete", "Complete"
        CANCELLED = "cancelled", "Cancelled"
        ARCHIVED = "archived", "Archived"

    class ResultStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        UNOFFICIAL = "unofficial", "Unofficial"
        OFFICIAL = "official", "Official"
        CERTIFIED = "certified", "Certified"
        CORRECTED = "corrected", "Corrected"

    election = models.ForeignKey(Election, on_delete=models.PROTECT, related_name="contests")
    office = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="contests")
    party_contest = models.CharField(max_length=100, blank=True)
    vote_for = models.PositiveSmallIntegerField(default=1)
    is_partisan = models.BooleanField(default=False)
    is_unexpired = models.BooleanField(default=False)
    lifecycle_status = models.CharField(
        max_length=16,
        choices=LifecycleStatus.choices,
        default=LifecycleStatus.PROVISIONAL,
    )
    result_status = models.CharField(
        max_length=16,
        choices=ResultStatus.choices,
        default=ResultStatus.PENDING,
    )

    class Meta:
        ordering = ["election__election_date", "office__canonical_name", "party_contest"]
        indexes = [
            models.Index(fields=["election", "lifecycle_status", "result_status"]),
            models.Index(fields=["office", "party_contest"]),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(vote_for__gt=0), name="cm2_contest_vote_for_positive"),
            models.UniqueConstraint(
                fields=["election", "office", "party_contest", "is_unexpired"],
                name="cm2_contest_identity_uniq",
            ),
        ]

    def __str__(self) -> str:
        party = f" [{self.party_contest}]" if self.party_contest else ""
        return f"{self.office.canonical_name}{party} — {self.election.name}"


class Person(SourceTrackedModel):
    class IdentityState(models.TextChoices):
        PROVISIONAL = "provisional", "Provisional"
        RESOLVED = "resolved", "Resolved"
        DISPUTED = "disputed", "Disputed"
        MERGED = "merged", "Merged"

    canonical_name = models.CharField(max_length=255)
    prefix = models.CharField(max_length=32, blank=True)
    given_name = models.CharField(max_length=100, blank=True)
    middle_name = models.CharField(max_length=100, blank=True)
    family_name = models.CharField(max_length=100, blank=True)
    suffix = models.CharField(max_length=32, blank=True)
    identity_state = models.CharField(
        max_length=16,
        choices=IdentityState.choices,
        default=IdentityState.PROVISIONAL,
    )
    merged_into = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="merged_records",
    )

    class Meta:
        ordering = ["family_name", "given_name", "canonical_name"]
        indexes = [models.Index(fields=["identity_state", "family_name", "given_name"])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(identity_state="merged", merged_into__isnull=False)
                    | (~models.Q(identity_state="merged") & models.Q(merged_into__isnull=True))
                ),
                name="cm2_person_merge_target_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(id=models.F("merged_into")),
                name="cm2_person_no_self_merge",
            ),
        ]

    def __str__(self) -> str:
        return self.canonical_name


class PersonIdentifier(UUIDModel):
    class VerificationMethod(models.TextChoices):
        SOURCE = "source", "Official source"
        HUMAN_REVIEW = "human_review", "Human review"
        EXISTING_LINK = "existing_link", "Existing approved link"

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="identifiers")
    scheme = models.CharField(max_length=64)
    identifier = models.CharField(max_length=255)
    verification_method = models.CharField(
        max_length=20,
        choices=VerificationMethod.choices,
        default=VerificationMethod.SOURCE,
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["scheme", "identifier"]
        constraints = [
            models.UniqueConstraint(fields=["scheme", "identifier"], name="cm2_person_identifier_global_uniq"),
            models.CheckConstraint(
                condition=(
                    ~models.Q(verification_method="human_review")
                    | (models.Q(verified_by__isnull=False) & models.Q(verified_at__isnull=False))
                ),
                name="cm2_identifier_review_metadata",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.scheme}:{self.identifier}"


class PersonSourceRecord(UUIDModel):
    IMMUTABLE_SOURCE_FIELDS = (
        "source_artifact_id",
        "source_row_key",
        "reported_name",
        "ballot_name",
        "prefix",
        "given_name",
        "middle_name",
        "family_name",
        "suffix",
        "filing_data",
        "protected_address",
        "protected_phone",
        "protected_email",
        "parser_version",
        "retrieval_context",
    )

    source_artifact = models.ForeignKey(
        "cm2_core.SourceArtifact",
        on_delete=models.PROTECT,
        related_name="person_source_records",
    )
    source_row_key = models.CharField(max_length=512)
    person = models.ForeignKey(
        Person,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="source_records",
    )
    reported_name = models.CharField(max_length=255)
    ballot_name = models.CharField(max_length=255, blank=True)
    prefix = models.CharField(max_length=32, blank=True)
    given_name = models.CharField(max_length=100, blank=True)
    middle_name = models.CharField(max_length=100, blank=True)
    family_name = models.CharField(max_length=100, blank=True)
    suffix = models.CharField(max_length=32, blank=True)
    filing_data = models.JSONField(default=dict, blank=True)
    protected_address = models.TextField(blank=True)
    protected_phone = models.CharField(max_length=64, blank=True)
    protected_email = models.EmailField(blank=True)
    parser_version = models.CharField(max_length=64)
    retrieval_context = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["source_artifact", "source_row_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_artifact", "source_row_key"],
                name="cm2_person_source_lineage_uniq",
            )
        ]

    def __str__(self) -> str:
        return f"{self.source_artifact.source_system}:{self.source_row_key}"

    def save(self, *args, **kwargs):
        require_unchanged_fields(self, self.IMMUTABLE_SOURCE_FIELDS)
        return super().save(*args, **kwargs)


class Candidacy(SourceTrackedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        WITHDRAWN = "withdrawn", "Withdrawn"
        DISQUALIFIED = "disqualified", "Disqualified"
        WRITE_IN = "write_in", "Write-in"
        PROVISIONAL = "provisional", "Provisional"

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="candidacies")
    contest = models.ForeignKey(Contest, on_delete=models.PROTECT, related_name="candidacies")
    ballot_name = models.CharField(max_length=255)
    party_candidate = models.CharField(max_length=100, blank=True)
    filing_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    source_records = models.ManyToManyField(PersonSourceRecord, blank=True, related_name="candidacies")

    class Meta:
        ordering = ["contest", "ballot_name"]
        constraints = [
            models.UniqueConstraint(fields=["person", "contest"], name="cm2_candidacy_person_contest_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.ballot_name} — {self.contest}"


class OfficeTerm(SourceTrackedModel):
    class SelectionMethod(models.TextChoices):
        ELECTION = "election", "Election"
        APPOINTMENT = "appointment", "Appointment"
        SUCCESSION = "succession", "Succession"
        OTHER = "other", "Other"

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="office_terms")
    office = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="terms")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    method_of_selection = models.CharField(max_length=16, choices=SelectionMethod.choices)
    role = models.CharField(max_length=64)

    class Meta:
        ordering = ["-start_date", "office"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True) | models.Q(end_date__gte=models.F("start_date")),
                name="cm2_office_term_dates_valid",
            ),
            models.UniqueConstraint(
                fields=["person", "office", "start_date", "role"],
                name="cm2_office_term_identity_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.person} — {self.office} ({self.start_date})"
