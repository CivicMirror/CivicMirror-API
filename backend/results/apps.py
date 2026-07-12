from django.apps import AppConfig


class ResultsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'results'

    def ready(self):
        # Import concrete adapters so @register runs at Django startup.
        from results.adapters import (  # noqa: F401
            ar,
            az,
            ca,
            co,
            ct,
            fl,
            ga,
            ia,
            il,
            ma,
            me,
            nc,
            ny,
            oh,
            sc,
            tx,
            va,
            wa,
            wv,
        )
