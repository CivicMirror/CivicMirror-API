from django.apps import AppConfig


class MichiganSosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.mi_sos"
    label = "mi_sos"
    verbose_name = "Michigan SOS Integration"
