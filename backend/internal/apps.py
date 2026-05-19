from django.apps import AppConfig


class InternalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'internal'
    verbose_name = 'Internal Task Endpoints'
