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
    path("tasks/seed-election-calendar/", views.seed_election_calendar_trigger, name="internal-seed-election-calendar"),
    path("tasks/sync-nc-sbe/", views.sync_nc_sbe_trigger, name="internal-sync-nc-sbe"),
    path("tasks/sync-nj-elections/", views.sync_nj_elections_trigger, name="internal-sync-nj-elections"),
    path("tasks/sync-az-sos/", views.sync_az_sos_trigger, name="internal-sync-az-sos"),
    path("tasks/sync-ga-sos/", views.sync_ga_sos_trigger, name="internal-sync-ga-sos"),
    path("tasks/poll-sc-enr/", views.poll_sc_enr_trigger, name="internal-poll-sc-enr"),
    path("tasks/sync-sc-enr-results/", views.sync_sc_enr_results_trigger, name="internal-sync-sc-enr-results"),
    path("tasks/sync-wa-votewa/", views.sync_wa_votewa_trigger, name="internal-sync-wa-votewa"),
    path("tasks/sync-fl-ew/", views.sync_fl_ew_trigger, name="internal-sync-fl-ew"),
    path("tasks/sync-tx-goelect/", views.sync_tx_goelect_trigger, name="internal-sync-tx-goelect"),
    path("tasks/sync-oh-sos/", views.sync_oh_sos_trigger, name="internal-sync-oh-sos"),
    path("tasks/sync-il-sbe/", views.sync_il_sbe_trigger, name="internal-sync-il-sbe"),
    path("tasks/sync-mn-sos/", views.sync_mn_sos_trigger, name="internal-sync-mn-sos"),
    path("tasks/sync-mi-sos/", views.sync_mi_sos_trigger, name="internal-sync-mi-sos"),
    path("tasks/sync-or-sos/", views.sync_or_sos_trigger, name="internal-sync-or-sos"),
    path("tasks/sync-ky-sos/", views.sync_ky_sos_trigger, name="internal-sync-ky-sos"),
    path("tasks/sync-pa-sos/", views.sync_pa_sos_trigger, name="internal-sync-pa-sos"),
]
