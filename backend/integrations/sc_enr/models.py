from django.db import models


class ENRElection(models.Model):
    """
    Represents a single election entry discovered from the SC ENR elections.json feed.

    The feed returns one entry per jurisdiction per election — one state-level entry
    (county=null) and one per participating county. Each has a unique EID.

    The enr_resolved_url field stores the fully resolved /web.XXXXXX/ path required
    by the ClarityAdapter (which constructs current_ver.txt and summary.json paths
    by string concatenation). Never store the unresolved base URL in Election.results_url.
    """

    class Scope(models.TextChoices):
        STATE = "state", "State"
        COUNTY = "county", "County"

    class LinkConfidence(models.TextChoices):
        AUTO = "auto", "Auto-linked"
        AMBIGUOUS = "ambiguous", "Ambiguous — manual review needed"
        MANUAL = "manual", "Manually linked"

    election_name = models.CharField(max_length=200)
    election_date = models.DateField()
    scope = models.CharField(max_length=10, choices=Scope.choices)
    # null for state-level entries; county name (e.g. "Charleston") for county entries.
    county = models.CharField(max_length=100, blank=True, null=True)
    eid = models.IntegerField()
    # Unresolved base URL: https://www.enr-scvotes.org/SC/{EID}/
    enr_base_url = models.URLField()
    # Fully resolved URL: https://www.enr-scvotes.org/SC/{EID}/web.XXXXXX/
    # Populated on first successful redirect resolution; never overwritten unless stale.
    enr_resolved_url = models.URLField(blank=True, default="")
    # False when the entry is no longer present in elections.json (off-season or removed).
    # Records are never deleted — only marked inactive.
    is_active = models.BooleanField(default=True, db_index=True)
    link_confidence = models.CharField(
        max_length=20,
        choices=LinkConfidence.choices,
        default=LinkConfidence.AUTO,
    )
    # FK to Election — populated for state-level entries when a date match is found.
    # Null for county-level entries (no county-scoped Election records in sc_vrems).
    election = models.ForeignKey(
        "elections.Election",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="enr_elections",
    )
    discovered_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField()

    class Meta:
        constraints = [
            # Uniqueness for county-level entries (county is not null).
            models.UniqueConstraint(
                fields=["eid", "county"],
                condition=models.Q(county__isnull=False),
                name="unique_enr_county_election",
            ),
            # Uniqueness for state-level entries (county is null).
            # Standard unique_together cannot enforce this because PostgreSQL
            # considers NULL != NULL in unique constraints.
            models.UniqueConstraint(
                fields=["eid"],
                condition=models.Q(county__isnull=True),
                name="unique_enr_state_election",
            ),
        ]
        ordering = ["-election_date", "scope", "county"]

    def __str__(self) -> str:
        loc = self.county or "Statewide"
        return f"{self.election_name} [{loc}] EID={self.eid}"
