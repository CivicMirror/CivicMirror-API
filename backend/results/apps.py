from django.apps import AppConfig


class ResultsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'results'

    def ready(self):
        # Import concrete adapters so @register runs at Django startup.
        from results.adapters import ca, co, ia, ma, sc, va, wv  # noqa: F401
