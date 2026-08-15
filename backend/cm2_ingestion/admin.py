from django.contrib import admin

from .models import ReconciliationReport, SyncLog


@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = ("state", "source_system", "capability", "status", "started_at", "completed_at")
    list_filter = ("state", "source_system", "capability", "status")
    search_fields = ("run_key",)
    raw_id_fields = ("source_artifact",)
    readonly_fields = (
        "id",
        "run_key",
        "state",
        "source_system",
        "capability",
        "status",
        "source_artifact",
        "started_at",
        "completed_at",
        "aggregate_counts",
        "error_summary",
        "created_at",
        "updated_at",
    )


@admin.register(ReconciliationReport)
class ReconciliationReportAdmin(admin.ModelAdmin):
    list_display = ("public_id", "sync_log", "source_artifact", "created_at")
    list_filter = ("sync_log__state", "sync_log__capability", "sync_log__status")
    search_fields = ("public_id", "sync_log__run_key")
    raw_id_fields = ("sync_log", "source_artifact")
    readonly_fields = ("id", "public_id", "sync_log", "source_artifact", "details", "created_at", "updated_at")
