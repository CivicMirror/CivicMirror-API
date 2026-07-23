from django.apps import AppConfig


class NyBoeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.ny_boe"
    label = "ny_boe"
    verbose_name = "New York BOE"
