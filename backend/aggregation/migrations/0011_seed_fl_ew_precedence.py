from django.db import migrations

_FL_ROWS = [
    ("FL", "results",  "fl_ew",    0),
    ("FL", "results",  "civic_api", 1),
    ("FL", "date",     "fl_ew",    0),
    ("FL", "date",     "civic_api", 1),
    ("FL", "contacts", "civic_api", 0),
    ("FL", "contacts", "fl_ew",    1),
    ("FL", "identity", "civic_api", 0),
    ("FL", "identity", "fl_ew",    1),
]


def seed_fl_ew_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    for state, field_group, source, rank in _FL_ROWS:
        SourcePrecedence.objects.update_or_create(
            state=state, field_group=field_group, source=source,
            defaults={"rank": rank},
        )


def remove_fl_ew_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(state="FL").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0010_merge_ia_sc_enr_fec_leaf_nodes"),
    ]

    operations = [
        migrations.RunPython(seed_fl_ew_precedence, remove_fl_ew_precedence),
    ]
