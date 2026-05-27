from django.contrib import admin

from .models import ENRElection


@admin.register(ENRElection)
class ENRElectionAdmin(admin.ModelAdmin):
    list_display = (
        "election_name",
        "election_date",
        "scope",
        "county",
        "eid",
        "is_active",
        "link_confidence",
        "election",
        "enr_resolved_url",
        "last_seen_at",
    )
    list_filter = ("scope", "is_active", "link_confidence", "election_date")
    search_fields = ("election_name", "county", "eid")
    raw_id_fields = ("election",)
    readonly_fields = ("discovered_at", "last_seen_at", "enr_base_url")
    ordering = ("-election_date", "scope", "county")

    fieldsets = (
        (None, {
            "fields": (
                "election_name", "election_date", "scope", "county", "eid", "is_active",
            ),
        }),
        ("URLs", {
            "fields": ("enr_base_url", "enr_resolved_url"),
        }),
        ("Election Link", {
            "fields": ("election", "link_confidence"),
            "description": (
                "State-level entries are linked automatically when exactly one SC Election "
                "matches the date. Set link_confidence to 'manual' to prevent auto-overwrite."
            ),
        }),
        ("Metadata", {
            "fields": ("discovered_at", "last_seen_at"),
            "classes": ("collapse",),
        }),
    )

    def save_model(self, request, obj, form, change):
        """Mark manually saved links as confidence=manual to prevent auto-overwrite."""
        if change and "election" in form.changed_data:
            obj.link_confidence = ENRElection.LinkConfidence.MANUAL
        super().save_model(request, obj, form, change)
