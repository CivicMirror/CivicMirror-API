from django.apps import AppConfig


class MinnesotaSosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.mn_sos"
    label = "mn_sos"
    verbose_name = "Minnesota SOS Integration"
