from django.db import migrations

from ._seed_data import seed


def forward(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    seed(SourcePrecedence)


def backward(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="MA").delete()


class Migration(migrations.Migration):
    dependencies = [("aggregation", "0002_seed_precedence")]
    operations = [migrations.RunPython(forward, backward)]
