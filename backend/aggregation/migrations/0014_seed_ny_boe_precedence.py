from django.db import migrations

_NY_ROWS = [
    ("NY", "identity", "ny_boe",    0),
    ("NY", "identity", "civic_api", 1),
    ("NY", "date",     "ny_boe",    0),
    ("NY", "date",     "civic_api", 1),
    ("NY", "status",   "ny_boe",    0),
    ("NY", "status",   "civic_api", 1),
    ("NY", "party",    "ny_boe",    0),
    ("NY", "party",    "civic_api", 1),
    ("NY", "district", "ny_boe",    0),
    ("NY", "district", "civic_api", 1),
    ("NY", "results",  "ny_boe",    0),
    ("NY", "results",  "civic_api", 1),
    ("NY", "contacts", "civic_api", 0),
    ("NY", "contacts", "ny_boe",    1),
]


def seed_ny_boe_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _NY_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_ny_boe_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="NY").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0013_seed_nc_sbe_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_ny_boe_precedence, remove_ny_boe_precedence),
    ]
