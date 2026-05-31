from django.db import migrations

_IA_ROWS = [
    ("IA", "results",  "ia_sos",    0),
    ("IA", "results",  "civic_api", 1),
    ("IA", "date",     "ia_sos",    0),
    ("IA", "date",     "civic_api", 1),
    ("IA", "contacts", "civic_api", 0),
    ("IA", "contacts", "ia_sos",    1),
    ("IA", "identity", "civic_api", 0),
    ("IA", "identity", "ia_sos",    1),
]


def seed_ia_sos_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _IA_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_ia_sos_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="IA").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0004_seed_va_precedence"),
        ("aggregation", "0005_seed_sc_vrems_precedence"),
        ("aggregation", "0006_seed_co_sos_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_ia_sos_precedence, remove_ia_sos_precedence),
    ]
