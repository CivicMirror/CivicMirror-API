from django.db import migrations

_MA_ROWS = [
    ("MA", "results",  "ma_sos",    0),
    ("MA", "results",  "civic_api", 1),
    ("MA", "date",     "ma_sos",    0),
    ("MA", "date",     "civic_api", 1),
    ("MA", "contacts", "civic_api", 0),
    ("MA", "contacts", "ma_sos",    1),
    ("MA", "identity", "civic_api", 0),
    ("MA", "identity", "ma_sos",    1),
]


def forward(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _MA_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def backward(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="MA").delete()


class Migration(migrations.Migration):
    dependencies = [("aggregation", "0002_seed_precedence")]
    operations = [migrations.RunPython(forward, backward)]
