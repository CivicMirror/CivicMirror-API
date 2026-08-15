from django.urls import path

from cm2_core.views import health

urlpatterns = [
    path("health/", health, name="v2-health-check"),
    path("api/v2/health/", health, name="v2-api-health-check"),
]
