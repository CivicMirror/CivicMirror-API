from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('elections', views.ElectionViewSet, basename='election')
router.register('races', views.RaceViewSet, basename='race')
router.register('candidates', views.CandidateViewSet, basename='candidate')
router.register('ballot-measures', views.BallotMeasureViewSet, basename='ballot-measure')
router.register('districts', views.DistrictViewSet, basename='district')

urlpatterns = router.urls + [
    path('lookup/', views.LookupView.as_view(), name='api-lookup'),
]
