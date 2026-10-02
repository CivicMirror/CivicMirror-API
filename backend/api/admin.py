from django.contrib import admin, messages

from .models import ApiKey


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ['name', 'prefix', 'access_level', 'is_active', 'expires_at', 'last_used_at', 'created_at']
    list_filter = ['access_level', 'is_active']
    search_fields = ['name', 'owner', 'prefix']
    readonly_fields = ['prefix', 'created_at', 'last_used_at']
    fields = [
        'name', 'owner', 'access_level', 'is_active', 'expires_at', 'throttle_rate', 'notes',
        'prefix', 'created_at', 'last_used_at',
    ]
    actions = ['deactivate_keys']

    def save_model(self, request, obj, form, change):
        # The key is always generated server-side; it is shown once and never stored in plaintext.
        if not change:
            raw_key = obj.assign_new_secret()
            super().save_model(request, obj, form, change)
            messages.warning(
                request,
                f'API key for "{obj.name}": {raw_key} — copy it now; it will not be shown again.',
            )
            return
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        # Deactivate instead of deleting, so attribution history stays intact.
        return False

    @admin.action(description='Deactivate selected API keys')
    def deactivate_keys(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'Deactivated {updated} API key(s).')
