from django.db import migrations


def drop_legacy_race_columns(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for column in [
        "submitter_id",
        "community_status",
        "rejection_reason",
        "reviewed_at",
        "reviewed_by_id",
        "submitted_at",
        "external_race_id",
    ]:
        schema_editor.execute(f"ALTER TABLE elections_race DROP COLUMN IF EXISTS {column};")


def restore_legacy_race_columns(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("ALTER TABLE elections_race ADD COLUMN IF NOT EXISTS submitter_id INTEGER;")
    schema_editor.execute("ALTER TABLE elections_race ADD COLUMN IF NOT EXISTS community_status VARCHAR(50) NOT NULL DEFAULT '';")
    schema_editor.execute("ALTER TABLE elections_race ADD COLUMN IF NOT EXISTS rejection_reason TEXT NOT NULL DEFAULT '';")
    schema_editor.execute("ALTER TABLE elections_race ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP WITH TIME ZONE;")
    schema_editor.execute("ALTER TABLE elections_race ADD COLUMN IF NOT EXISTS reviewed_by_id INTEGER;")
    schema_editor.execute("ALTER TABLE elections_race ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMP WITH TIME ZONE;")
    schema_editor.execute("ALTER TABLE elections_race ADD COLUMN IF NOT EXISTS external_race_id VARCHAR(255);")


class Migration(migrations.Migration):
    """
    Drop columns that exist in the production DB but were removed from the Race
    model without corresponding DROP COLUMN migrations. Several are NOT NULL and
    block inserts from the SC VREMS integration.
    """

    dependencies = [
        ("elections", "0006_drop_race_moderator_notes"),
    ]

    operations = [
        migrations.RunPython(drop_legacy_race_columns, reverse_code=restore_legacy_race_columns),
    ]
