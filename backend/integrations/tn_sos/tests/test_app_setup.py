from django.apps import apps

from elections.models import Race


def test_tn_sos_app_is_registered():
    assert apps.get_app_config("tn_sos").name == "integrations.tn_sos"


def test_tn_sos_race_source_exists():
    assert Race.Source.TN_SOS == "tn_sos"
