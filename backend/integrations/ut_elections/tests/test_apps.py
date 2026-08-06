from django.apps import apps


def test_ut_elections_app_is_installed():
    config = apps.get_app_config("ut_elections")
    assert config.name == "integrations.ut_elections"
