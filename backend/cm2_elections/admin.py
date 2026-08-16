from django.contrib import admin, messages
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    Candidacy,
    Contest,
    Election,
    Jurisdiction,
    LifecycleAuditEvent,
    Office,
    OfficeTerm,
    Person,
    PersonIdentifier,
    PersonSourceRecord,
)
from .workflow import record_lifecycle_event, record_lifecycle_note


@admin.register(Jurisdiction)
class JurisdictionAdmin(ModelAdmin):
    list_display = ("name", "classification", "state", "record_status", "parent")
    list_filter = ("state", "classification", "record_status")
    search_fields = ("public_id", "name", "source_key")
    autocomplete_fields = ("parent", "source_artifact")


@admin.register(Office)
class OfficeAdmin(ModelAdmin):
    list_display = ("canonical_name", "jurisdiction", "role", "positions", "record_status")
    list_filter = ("record_status", "role", "jurisdiction__state")
    search_fields = ("public_id", "canonical_name", "jurisdiction__name", "source_key")
    autocomplete_fields = ("jurisdiction", "source_artifact")


class ElectionLifecycleAuditInline(TabularInline):
    model = LifecycleAuditEvent
    fk_name = "election"
    extra = 0
    can_delete = False
    fields = ("created_at", "event_type", "actor", "note", "metadata")
    readonly_fields = fields
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        return False


class ContestLifecycleAuditInline(TabularInline):
    model = LifecycleAuditEvent
    fk_name = "contest"
    extra = 0
    can_delete = False
    fields = ("created_at", "event_type", "actor", "note", "metadata")
    readonly_fields = fields
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        return False


class LifecycleAuditAdminMixin:
    """Auto-records a status_changed event on lifecycle_status edits and adds a note action."""

    def save_model(self, request, obj, form, change):
        old_status = None
        if change and "lifecycle_status" in form.changed_data:
            old_status = type(obj).objects.get(pk=obj.pk).lifecycle_status
        super().save_model(request, obj, form, change)
        if old_status is not None and old_status != obj.lifecycle_status:
            record_lifecycle_event(
                obj,
                LifecycleAuditEvent.EventType.STATUS_CHANGED,
                request.user,
                metadata={"old_status": old_status, "new_status": obj.lifecycle_status},
            )

    @admin.action(description="Add note to selected (enter note text below)")
    def add_lifecycle_note(self, request, queryset):
        note = request.POST.get("note", "").strip()
        if not note:
            self.message_user(request, "Provide note text to add a note.", messages.ERROR)
            return
        added = 0
        for obj in queryset:
            record_lifecycle_note(obj, actor=request.user, note=note)
            added += 1
        self.message_user(request, f"Added a note to {added} record(s).", messages.SUCCESS)


@admin.register(Election)
class ElectionAdmin(LifecycleAuditAdminMixin, ModelAdmin):
    list_display = ("name", "election_date", "election_type", "lifecycle_status")
    list_filter = ("election_type", "lifecycle_status", "election_date")
    search_fields = ("public_id", "name", "source_key")
    autocomplete_fields = ("source_artifact",)
    ordering = ("-election_date",)
    inlines = (ElectionLifecycleAuditInline,)
    actions = ("add_lifecycle_note",)


@admin.register(Contest)
class ContestAdmin(LifecycleAuditAdminMixin, ModelAdmin):
    list_display = ("office", "election", "party_contest", "lifecycle_status", "result_status")
    list_filter = ("lifecycle_status", "result_status", "is_partisan", "is_unexpired")
    search_fields = ("public_id", "office__canonical_name", "election__name", "party_contest", "source_key")
    autocomplete_fields = ("election", "office", "source_artifact")
    inlines = (ContestLifecycleAuditInline,)
    actions = ("add_lifecycle_note",)


@admin.register(Person)
class PersonAdmin(ModelAdmin):
    list_display = ("canonical_name", "identity_state", "family_name", "given_name", "merged_into")
    list_filter = ("identity_state",)
    search_fields = ("public_id", "canonical_name", "given_name", "family_name", "source_key")
    autocomplete_fields = ("merged_into", "source_artifact")


@admin.register(PersonIdentifier)
class PersonIdentifierAdmin(ModelAdmin):
    list_display = ("scheme", "identifier", "person", "verification_method", "verified_at")
    list_filter = ("scheme", "verification_method")
    search_fields = ("scheme", "identifier", "person__canonical_name", "person__public_id")
    autocomplete_fields = ("person", "verified_by")


@admin.register(PersonSourceRecord)
class PersonSourceRecordAdmin(ModelAdmin):
    list_display = ("reported_name", "ballot_name", "source_artifact", "source_row_key", "person")
    list_filter = ("source_artifact__source_system", "source_artifact__source_type")
    search_fields = ("reported_name", "ballot_name", "source_row_key", "person__public_id")
    autocomplete_fields = ("source_artifact", "person")
    readonly_fields = (
        "id",
        "source_artifact",
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
        "created_at",
        "updated_at",
    )


@admin.register(Candidacy)
class CandidacyAdmin(ModelAdmin):
    list_display = ("ballot_name", "contest", "person", "party_candidate", "status")
    list_filter = ("status", "party_candidate")
    search_fields = ("public_id", "ballot_name", "person__canonical_name", "contest__public_id")
    autocomplete_fields = ("person", "contest", "source_artifact", "source_records")


@admin.register(OfficeTerm)
class OfficeTermAdmin(ModelAdmin):
    list_display = ("person", "office", "role", "start_date", "end_date", "method_of_selection")
    list_filter = ("method_of_selection", "role")
    search_fields = ("public_id", "person__canonical_name", "office__canonical_name")
    autocomplete_fields = ("person", "office", "source_artifact")
