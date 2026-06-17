from django.apps import AppConfig


class TxGoElectConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.tx_goelect"
    label = "tx_goelect"
    verbose_name = "Texas GoElect Integration"
