from importlib import import_module

from django.apps import AppConfig


class ResultsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'results'

    def ready(self):
        # Import concrete adapters so @register runs at Django startup.
        # Use importlib because `in` is a valid module name but a Python keyword.
        adapter_modules = [
            "ak", "ar", "az", "ca", "co", "ct", "de", "fl", "ga", "hi",
            "id", "ia", "il", "in", "ks", "la", "ma", "me", "mi", "mn",
            "ms", "mt", "nc", "nd", "ne", "nh", "nj", "nv", "ny", "oh",
            "ok", "oregon", "pa", "ri", "sc", "sd", "tn", "tx", "va",
            "vt", "wa", "wi", "wv", "wy",
        ]

        for module in adapter_modules:
            import_module(f"results.adapters.{module}")
