from django.db import migrations

# FEC already has ("*","*","fec",1) from 0002_seed_precedence.
# OpenStates contributes party, incumbent, and contacts — add it at rank 2
# (below FEC rank 1, above unranked sources) as a global wildcard so the
# ingest layer respects OpenStates precedence without state-specific rows.
_OPENSTATES_ROWS = [
    ("*", "*", "openstates", 2),
]


def seed_openstates_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _OPENSTATES_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_openstates_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(source="openstates").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0004_seed_va_precedence"),
        ("aggregation", "0005_seed_sc_vrems_precedence"),
        ("aggregation", "0006_seed_co_sos_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_openstates_precedence, remove_openstates_precedence),
    ]
