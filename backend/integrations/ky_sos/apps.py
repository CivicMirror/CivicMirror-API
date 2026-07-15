from django.apps import AppConfig


class KentuckySosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.ky_sos"
    label = "ky_sos"
    verbose_name = "Kentucky SOS Integration"
