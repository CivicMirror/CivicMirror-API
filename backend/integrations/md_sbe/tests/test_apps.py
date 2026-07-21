from django.apps import apps


def test_md_sbe_app_is_installed():
    config = apps.get_app_config("md_sbe")

    assert config.name == "integrations.md_sbe"
