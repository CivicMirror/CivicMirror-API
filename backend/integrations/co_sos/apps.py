from django.apps import AppConfig


class ColoradoSosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.co_sos"
    label = "co_sos"
    verbose_name = "Colorado SOS Integration"
