from django.apps import AppConfig


class CivicIntegrationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'integrations.civic'
    label = 'civic_integration'
    verbose_name = 'Civic Integration'
