from django.db import migrations

_SC_ROWS = [
    ("SC", "results",  "sc_vrems",  0),
    ("SC", "results",  "civic_api", 1),
    ("SC", "date",     "sc_vrems",  0),
    ("SC", "date",     "civic_api", 1),
    ("SC", "contacts", "civic_api", 0),
    ("SC", "contacts", "sc_vrems",  1),
    ("SC", "identity", "civic_api", 0),
    ("SC", "identity", "sc_vrems",  1),
]


def seed_sc_vrems_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _SC_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_sc_vrems_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="SC").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0002_seed_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_sc_vrems_precedence, remove_sc_vrems_precedence),
    ]
