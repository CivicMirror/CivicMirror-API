from django.apps import AppConfig


class IowaSosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.ia_sos"
    label = "ia_sos"
    verbose_name = "Iowa SOS Integration"
