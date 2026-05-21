from django.urls import path

from . import views

urlpatterns = [
    # PK-based vote/tally (standalone views — DRF router action auth ordering issue)
    path('races/<int:pk>/vote/', views.PkVoteView.as_view(), name='race-pk-vote'),
    path('races/<int:pk>/tally/', views.PkTallyView.as_view(), name='race-pk-tally'),

    # ext/{external_id}/ routes (by canonical_key)
    path('races/ext/<str:external_id>/vote/', views.ExtVoteView.as_view(), name='race-ext-vote'),
    path('races/ext/<str:external_id>/tally/', views.ExtTallyView.as_view(), name='race-ext-tally'),

    # Community race submission
    path('races/community/', views.CommunityRaceListCreateView.as_view(), name='race-community-list'),
    path('races/community/<int:pk>/', views.CommunityRaceDetailView.as_view(), name='race-community-detail'),

    # User profile and vote history
    path('users/me/', views.UserProfileView.as_view(), name='user-me'),
    path('users/votes/', views.UserVotesView.as_view(), name='user-votes'),
]
