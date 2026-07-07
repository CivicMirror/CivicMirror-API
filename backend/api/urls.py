from django.urls import include, path
from rest_framework.routers import DefaultRouter

from ops.views import CoverageSyncStatusView

from . import views

router = DefaultRouter()
router.register('elections', views.ElectionViewSet, basename='election')
router.register('races', views.RaceViewSet, basename='race')
router.register('candidates', views.CandidateViewSet, basename='candidate')
router.register('ballot-measures', views.BallotMeasureViewSet, basename='ballot-measure')
router.register('districts', views.DistrictViewSet, basename='district')

# Community/user routes come FIRST to prevent DRF router from swallowing
# "community" and "ext" as {pk} values.
urlpatterns = [
    path('', include('community.urls')),
    path('lookup/', views.LookupView.as_view(), name='api-lookup'),
    path('coverage/sync-status/', CoverageSyncStatusView.as_view(), name='coverage-sync-status'),
] + router.urls
