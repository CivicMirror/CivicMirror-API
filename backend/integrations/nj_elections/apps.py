from django.apps import AppConfig


class NewJerseyElectionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.nj_elections"
    label = "nj_elections"
    verbose_name = "New Jersey Elections Integration"
