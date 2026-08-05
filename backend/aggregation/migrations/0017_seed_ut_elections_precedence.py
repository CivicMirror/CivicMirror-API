from django.db import migrations

_UT_ROWS = [
    ("UT", "date",     "ut_elections", 0),
    ("UT", "date",     "civic_api",    1),
    ("UT", "contacts", "civic_api",    0),
    ("UT", "contacts", "ut_elections", 1),
    ("UT", "identity",  "ut_elections", 0),
    ("UT", "identity",  "civic_api",    1),
    ("UT", "results",  "ut_elections", 0),
    ("UT", "results",  "civic_api",    1),
]


def seed_ut_elections_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _UT_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_ut_elections_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="UT").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0016_seed_md_sbe_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_ut_elections_precedence, remove_ut_elections_precedence),
    ]
