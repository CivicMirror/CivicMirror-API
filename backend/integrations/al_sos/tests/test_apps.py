from django.apps import apps


def test_al_sos_app_is_installed():
    config = apps.get_app_config("al_sos")

    assert config.name == "integrations.al_sos"
