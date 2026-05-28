from django.db import models


class SourcePrecedence(models.Model):
    """
    Admin-editable, per-(state, field_group) ranking of sources.
    Lower rank = higher precedence. `*` is a wildcard for state or field_group.
    """
    state = models.CharField(max_length=2, default="*", help_text="2-letter state or '*' for all")
    field_group = models.CharField(max_length=40, default="*", help_text="field group or '*' for all")
    source = models.CharField(max_length=40)
    rank = models.IntegerField(default=0, help_text="lower = higher precedence")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["state", "field_group", "source"],
                name="unique_precedence_state_group_source",
            )
        ]
        ordering = ["state", "field_group", "rank"]

    def __str__(self) -> str:
        return f"{self.state}/{self.field_group}: {self.source}={self.rank}"
