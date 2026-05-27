from django.urls import path

from . import views

urlpatterns = [
    path("tasks/sync-elections/", views.sync_elections_trigger, name="internal-sync-elections"),
    path("tasks/poll-results/", views.poll_results_trigger, name="internal-poll-results"),
    path("tasks/sync-openstates/", views.sync_openstates_trigger, name="internal-sync-openstates"),
    path("tasks/sync-fec/", views.sync_fec_trigger, name="internal-sync-fec"),
    path("tasks/sync-sc-vrems/", views.sync_sc_vrems_trigger, name="internal-sync-sc-vrems"),
    path("tasks/sync-ia-sos/", views.sync_ia_sos_trigger, name="internal-sync-ia-sos"),
    path("tasks/sync-co-sos/", views.sync_co_sos_trigger, name="internal-sync-co-sos"),
    path("tasks/sync-va-elect/", views.sync_va_elect_trigger, name="internal-sync-va-elect"),
    path("tasks/sync-va-elections/", views.sync_va_elect_trigger, name="internal-sync-va-elections"),
    path("tasks/sync-ma-sos/", views.sync_ma_sos_trigger, name="internal-sync-ma-sos"),
    path("tasks/sync-ca-sos/", views.sync_ca_sos_trigger, name="internal-sync-ca-sos"),
    path("tasks/poll-sc-enr/", views.poll_sc_enr_trigger, name="internal-poll-sc-enr"),
    path("tasks/sync-sc-enr-results/", views.sync_sc_enr_results_trigger, name="internal-sync-sc-enr-results"),
]
