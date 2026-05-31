from django.db import migrations

_CO_ROWS = [
    ("CO", "results",  "co_sos",    0),
    ("CO", "results",  "civic_api", 1),
    ("CO", "date",     "co_sos",    0),
    ("CO", "date",     "civic_api", 1),
    ("CO", "contacts", "civic_api", 0),
    ("CO", "contacts", "co_sos",    1),
    ("CO", "identity", "civic_api", 0),
    ("CO", "identity", "co_sos",    1),
]


def seed_co_sos_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _CO_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_co_sos_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="CO").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0002_seed_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_co_sos_precedence, remove_co_sos_precedence),
    ]
