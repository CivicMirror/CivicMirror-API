from django.db import migrations


def add_results_url_if_missing(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            "ALTER TABLE elections_election ADD COLUMN IF NOT EXISTS results_url varchar(200) NOT NULL DEFAULT '';"
        )


def drop_results_url_if_present(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("ALTER TABLE elections_election DROP COLUMN IF EXISTS results_url;")


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
                migrations.RunPython(add_results_url_if_missing, reverse_code=drop_results_url_if_present),
            ],
            state_operations=[],
        ),
    ]
