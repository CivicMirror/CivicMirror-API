from django.contrib import admin

from .models import OfficialResult


@admin.register(OfficialResult)
class OfficialResultAdmin(admin.ModelAdmin):
    list_display = ('race', 'candidate', 'measure_option', 'vote_count', 'vote_pct', 'result_type', 'is_winner')
    list_filter = ('result_type', 'is_winner')
    search_fields = ('race__office_title',)
    raw_id_fields = ('race', 'candidate', 'measure_option')
