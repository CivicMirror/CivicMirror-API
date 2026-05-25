from django.apps import AppConfig


class VaElectConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.va_elect"
    label = "va_elect"
    verbose_name = "Virginia ELECT Integration"
