from django.db import migrations


class Migration(migrations.Migration):
    """
    Originally added Election.results_url when production had been migrated from
    an older schema that lacked it (the column was also declared by
    0001_initial). On a fresh database, 0001_initial already creates the column,
    so the original AddField raised DuplicateColumn in CI.

    Made idempotent: the column is added only if it does not already exist, and
    no state operations are emitted (0001_initial owns the model state).
    """

    dependencies = [
        ('elections', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE elections_election ADD COLUMN IF NOT EXISTS results_url varchar(200) NOT NULL DEFAULT '';",
                    reverse_sql="ALTER TABLE elections_election DROP COLUMN IF EXISTS results_url;",
                ),
            ],
            state_operations=[],
        ),
    ]
