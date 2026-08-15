from django.contrib import admin

from .models import SourceArtifact


@admin.register(SourceArtifact)
class SourceArtifactAdmin(admin.ModelAdmin):
    list_display = (
        "source_system",
        "source_type",
        "retrieved_at",
        "election_date",
        "processing_status",
        "checksum_prefix",
    )
    list_filter = ("source_system", "source_type", "processing_status", "election_date")
    search_fields = ("public_id", "url", "content_sha256", "parser_version")
    readonly_fields = (
        "id",
        "public_id",
        "source_system",
        "source_type",
        "url",
        "retrieved_at",
        "source_timestamp",
        "content_sha256",
        "parser_version",
        "election_date",
        "supersedes",
        "created_at",
        "updated_at",
    )

    @admin.display(description="SHA-256")
    def checksum_prefix(self, artifact):
        return artifact.content_sha256[:12]
