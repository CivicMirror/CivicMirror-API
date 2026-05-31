from django.db import migrations

# SC ENR is a results-URL-only source: it links Clarity ENR elections to
# canonical Election records and writes results_url. Only the "results"
# field group is needed — sc_enr does not contribute identity, date, or
# contacts fields.
_SC_ENR_ROWS = [
    ("SC", "results", "sc_enr", 0),
]


def seed_sc_enr_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _SC_ENR_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_sc_enr_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(source="sc_enr").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0004_seed_va_precedence"),
        ("aggregation", "0005_seed_sc_vrems_precedence"),
        ("aggregation", "0006_seed_co_sos_precedence"),
    ]

    operations = [
        migrations.RunPython(seed_sc_enr_precedence, remove_sc_enr_precedence),
    ]
