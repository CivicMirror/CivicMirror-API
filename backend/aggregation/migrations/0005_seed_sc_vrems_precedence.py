from django.db import migrations

from ._seed_data import seed


def seed_sc_vrems_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    seed(SourcePrecedence)


def remove_sc_vrems_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="SC").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0004_seed_va_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_sc_vrems_precedence, remove_sc_vrems_precedence),
    ]
