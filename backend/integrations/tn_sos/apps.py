from django.apps import AppConfig


class TennesseeSosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.tn_sos"
    label = "tn_sos"
    verbose_name = "Tennessee SOS Integration"
