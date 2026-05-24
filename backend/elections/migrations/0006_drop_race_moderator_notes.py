from django.db import migrations


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
        migrations.RunSQL(
            sql="ALTER TABLE elections_race DROP COLUMN IF EXISTS moderator_notes;",
            reverse_sql="ALTER TABLE elections_race ADD COLUMN moderator_notes TEXT NOT NULL DEFAULT '';",
        ),
    ]
