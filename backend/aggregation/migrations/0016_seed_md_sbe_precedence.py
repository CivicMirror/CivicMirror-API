from django.db import migrations

_MD_ROWS = [
    ("MD", "date",     "md_sbe",    0),
    ("MD", "date",     "civic_api", 1),
    ("MD", "contacts", "civic_api", 0),
    ("MD", "contacts", "md_sbe",    1),
    ("MD", "identity", "md_sbe",    0),
    ("MD", "identity", "civic_api", 1),
    ("MD", "results",  "md_sbe",    0),
    ("MD", "results",  "civic_api", 1),
]


def seed_md_sbe_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _MD_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_md_sbe_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="MD").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0015_remove_unreachable_openstates_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_md_sbe_precedence, remove_md_sbe_precedence),
    ]
