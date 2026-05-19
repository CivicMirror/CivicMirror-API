from django.apps import AppConfig


class FECIntegrationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'integrations.fec'
    label = 'fec_integration'
    verbose_name = 'FEC Integration'
