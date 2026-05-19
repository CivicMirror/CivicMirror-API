from django.contrib import admin

from .models import SourceRecord, SyncLog


@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = ('task_name', 'source', 'status', 'started_at', 'completed_at', 'records_created', 'records_updated', 'error_count')
    list_filter = ('status', 'source')
    search_fields = ('task_name', 'source')
    readonly_fields = ('started_at',)
    ordering = ('-started_at',)


@admin.register(SourceRecord)
class SourceRecordAdmin(admin.ModelAdmin):
    list_display = ('source', 'external_id', 'first_seen_at', 'last_seen_at')
    list_filter = ('source',)
    search_fields = ('external_id',)
    raw_id_fields = ('linked_race', 'linked_candidate')
