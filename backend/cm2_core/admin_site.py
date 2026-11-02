from django.contrib import admin
from django.contrib.admin.apps import AdminConfig


class CivicMirrorAdminSite(admin.AdminSite):
    site_header = "CivicMirror 2.0 Administration"
    site_title = "CivicMirror 2.0"
    index_title = "North Carolina Pilot"

    APP_ORDER = (
        "cm2_elections",
        "cm2_results",
        "cm2_review",
        "cm2_ingestion",
        "cm2_core",
        "auth",
    )

    MODEL_ORDER = {
        "cm2_elections": (
            "Election",
            "Jurisdiction",
            "Office",
            "Contest",
            "Person",
            "Candidacy",
            "PersonIdentifier",
            "PersonSourceRecord",
            "OfficeTerm",
        ),
        "cm2_results": ("ContestResult", "ResultChoice"),
        "cm2_review": ("IdentityReviewCase", "IdentityReviewSuggestion"),
        "cm2_ingestion": ("SyncLog", "ReconciliationReport"),
    }

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label=app_label)
        app_order = {label: index for index, label in enumerate(self.APP_ORDER)}
        app_list.sort(key=lambda app: app_order.get(app["app_label"], len(app_order)))
        for app in app_list:
            model_order = self.MODEL_ORDER.get(app["app_label"])
            if model_order:
                order_index = {name: index for index, name in enumerate(model_order)}
                app["models"].sort(key=lambda model: order_index.get(model["object_name"], len(order_index)))
        return app_list


class CivicMirrorAdminConfig(AdminConfig):
    default_site = "cm2_core.admin_site.CivicMirrorAdminSite"
