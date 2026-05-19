from django.apps import AppConfig


class OpenStatesIntegrationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'integrations.openstates'
    label = 'openstates_integration'
    verbose_name = 'OpenStates Integration'
