from django.apps import AppConfig


class IllinoisSbeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.il_sbe"
    label = "il_sbe"
    verbose_name = "Illinois SBE Integration"
