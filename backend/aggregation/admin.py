from django.contrib import admin

from .models import SourcePrecedence


@admin.register(SourcePrecedence)
class SourcePrecedenceAdmin(admin.ModelAdmin):
    list_display = ("state", "field_group", "source", "rank")
    list_filter = ("state", "field_group", "source")
    list_editable = ("rank",)
    ordering = ("state", "field_group", "rank")
