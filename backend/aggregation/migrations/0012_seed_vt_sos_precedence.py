from django.db import migrations

_VT_ROWS = [
    ("VT", "results",  "vt_sos",    0),
    ("VT", "results",  "civic_api", 1),
    ("VT", "date",     "vt_sos",    0),
    ("VT", "date",     "civic_api", 1),
    ("VT", "contacts", "civic_api", 0),
    ("VT", "contacts", "vt_sos",    1),
    ("VT", "identity", "civic_api", 0),
    ("VT", "identity", "vt_sos",    1),
]


def seed_vt_sos_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _VT_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_vt_sos_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="VT").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0011_seed_fl_ew_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_vt_sos_precedence, remove_vt_sos_precedence),
    ]
