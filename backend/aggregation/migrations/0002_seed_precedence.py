from django.db import migrations

from ._seed_data import seed


def forward(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    seed(SourcePrecedence)


def backward(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("aggregation", "0001_initial")]
    operations = [migrations.RunPython(forward, backward)]
