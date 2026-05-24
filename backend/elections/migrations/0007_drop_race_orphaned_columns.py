from django.db import migrations


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
        migrations.RunSQL(
            sql="""
                ALTER TABLE elections_race DROP COLUMN IF EXISTS submitter_id;
                ALTER TABLE elections_race DROP COLUMN IF EXISTS community_status;
                ALTER TABLE elections_race DROP COLUMN IF EXISTS rejection_reason;
                ALTER TABLE elections_race DROP COLUMN IF EXISTS reviewed_at;
                ALTER TABLE elections_race DROP COLUMN IF EXISTS reviewed_by_id;
                ALTER TABLE elections_race DROP COLUMN IF EXISTS submitted_at;
                ALTER TABLE elections_race DROP COLUMN IF EXISTS external_race_id;
            """,
            reverse_sql="""
                ALTER TABLE elections_race ADD COLUMN IF NOT EXISTS submitter_id INTEGER;
                ALTER TABLE elections_race ADD COLUMN IF NOT EXISTS community_status VARCHAR(50) NOT NULL DEFAULT '';
                ALTER TABLE elections_race ADD COLUMN IF NOT EXISTS rejection_reason TEXT NOT NULL DEFAULT '';
                ALTER TABLE elections_race ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP WITH TIME ZONE;
                ALTER TABLE elections_race ADD COLUMN IF NOT EXISTS reviewed_by_id INTEGER;
                ALTER TABLE elections_race ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMP WITH TIME ZONE;
                ALTER TABLE elections_race ADD COLUMN IF NOT EXISTS external_race_id VARCHAR(255);
            """,
        ),
    ]
