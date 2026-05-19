from django.urls import path

from . import views

urlpatterns = [
    path("tasks/sync-elections/", views.sync_elections_trigger, name="internal-sync-elections"),
    path("tasks/poll-results/", views.poll_results_trigger, name="internal-poll-results"),
]
