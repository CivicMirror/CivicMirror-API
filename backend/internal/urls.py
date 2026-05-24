from django.urls import path

from . import views

urlpatterns = [
    path("tasks/sync-elections/", views.sync_elections_trigger, name="internal-sync-elections"),
    path("tasks/poll-results/", views.poll_results_trigger, name="internal-poll-results"),
    path("tasks/sync-openstates/", views.sync_openstates_trigger, name="internal-sync-openstates"),
    path("tasks/sync-fec/", views.sync_fec_trigger, name="internal-sync-fec"),
    path("tasks/sync-sc-vrems/", views.sync_sc_vrems_trigger, name="internal-sync-sc-vrems"),
]
