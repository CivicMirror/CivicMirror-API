import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.v2")

app = Celery("civicmirror_2_0")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
