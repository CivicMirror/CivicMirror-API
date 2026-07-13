from django.db import migrations


def drop_legacy_moderator_notes(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("ALTER TABLE elections_race DROP COLUMN IF EXISTS moderator_notes;")


def restore_legacy_moderator_notes(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("ALTER TABLE elections_race ADD COLUMN moderator_notes TEXT NOT NULL DEFAULT '';")


class Migration(migrations.Migration):
    """
    Drop the moderator_notes column that exists in the production DB but was
    removed from the Race model without a corresponding DROP COLUMN migration.
    This column is NOT NULL with no default, causing Race inserts to fail.
    """

    dependencies = [
        ("elections", "0005_add_results_adapter_source"),
    ]

    operations = [
        migrations.RunPython(drop_legacy_moderator_notes, reverse_code=restore_legacy_moderator_notes),
    ]
