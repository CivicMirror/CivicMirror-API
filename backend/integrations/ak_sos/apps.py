from django.apps import AppConfig


class AlaskaDivisionOfElectionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.ak_sos"
    label = "ak_sos"
    verbose_name = "Alaska Division of Elections Integration"
