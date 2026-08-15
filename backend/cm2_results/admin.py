from django.contrib import admin

from .models import ContestResult, ResultChoice


class ResultChoiceInline(admin.TabularInline):
    model = ResultChoice
    extra = 0
    raw_id_fields = ("candidacy", "source_artifact")
    readonly_fields = ("public_id", "created_at", "updated_at")


@admin.register(ContestResult)
class ContestResultAdmin(admin.ModelAdmin):
    list_display = ("contest", "status", "total_votes", "reported_at", "certified_at")
    list_filter = ("status",)
    search_fields = ("public_id", "contest__public_id", "contest__office__canonical_name")
    raw_id_fields = ("contest", "source_artifact")
    inlines = (ResultChoiceInline,)


@admin.register(ResultChoice)
class ResultChoiceAdmin(admin.ModelAdmin):
    list_display = (
        "source_label",
        "contest_result",
        "choice_type",
        "resolution_status",
        "vote_total",
        "is_winner",
    )
    list_filter = ("choice_type", "resolution_status", "is_winner")
    search_fields = ("public_id", "source_label", "normalized_label", "source_choice_key")
    raw_id_fields = ("contest_result", "candidacy", "source_artifact")
