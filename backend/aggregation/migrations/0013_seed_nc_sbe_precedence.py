from django.db import migrations

_NC_ROWS = [
    ("NC", "date",     "nc_sbe",    0),
    ("NC", "date",     "civic_api", 1),
    ("NC", "contacts", "civic_api", 0),
    ("NC", "contacts", "nc_sbe",    1),
    ("NC", "identity", "nc_sbe",    0),
    ("NC", "identity", "civic_api", 1),
    ("NC", "results",  "nc_sbe",    0),
    ("NC", "results",  "civic_api", 1),
]


def seed_nc_sbe_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _NC_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_nc_sbe_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="NC").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0012_seed_vt_sos_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_nc_sbe_precedence, remove_nc_sbe_precedence),
    ]
