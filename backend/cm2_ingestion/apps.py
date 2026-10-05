from django.apps import AppConfig


class CivicMirrorIngestionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cm2_ingestion"
    label = "cm2_ingestion"
    verbose_name = "CivicMirror 2.0 Ingestion"
