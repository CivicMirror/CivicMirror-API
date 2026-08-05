from django.apps import AppConfig


class UtahElectionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.ut_elections"
    label = "ut_elections"
    verbose_name = "Utah Elections Integration"
