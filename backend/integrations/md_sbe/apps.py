from django.apps import AppConfig


class MarylandSbeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.md_sbe"
    label = "md_sbe"
    verbose_name = "Maryland SBE Integration"
