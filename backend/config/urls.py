from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('internal/', include('internal.urls')),
    path('api/', include('accounts.urls')),
    path('api/', include('api.urls')),
    path('api/v1/', include('api.urls')),
    path('health/', health_check, name='health-check'),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    # Public, interactive API docs (Swagger UI). Scope is limited by api.schema.preprocess_public_endpoints.
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
