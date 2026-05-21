from django.contrib import admin

from .models import MockVote, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['uid', 'display_name', 'created_at']
    search_fields = ['uid', 'display_name']
    readonly_fields = ['uid', 'created_at']


@admin.register(MockVote)
class MockVoteAdmin(admin.ModelAdmin):
    list_display = ['uid', 'race', 'selection_type', 'created_at']
    list_filter = ['race__election']
    search_fields = ['uid']
    readonly_fields = ['uid', 'race', 'candidate_ids', 'measure_option_id', 'ranked_selections', 'created_at']
