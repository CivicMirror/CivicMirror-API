from django.db import migrations

_VA_ROWS = [
    ("VA", "results",  "va_elect",  0),
    ("VA", "results",  "civic_api", 1),
    ("VA", "date",     "va_elect",  0),
    ("VA", "date",     "civic_api", 1),
    ("VA", "contacts", "civic_api", 0),
    ("VA", "contacts", "va_elect",  1),
    ("VA", "identity", "civic_api", 0),
    ("VA", "identity", "va_elect",  1),
]


def seed_va_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _VA_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_va_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="VA").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0003_seed_ma_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_va_precedence, remove_va_precedence),
    ]
