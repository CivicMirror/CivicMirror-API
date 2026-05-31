from django.db import migrations

from ._seed_data import seed


def seed_co_sos_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    seed(SourcePrecedence)


def remove_co_sos_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="CO").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0005_seed_sc_vrems_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_co_sos_precedence, remove_co_sos_precedence),
    ]
