from django.db import migrations


def drop_legacy_username_column(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('ALTER TABLE accounts_userprofile DROP COLUMN IF EXISTS username;')


class Migration(migrations.Migration):
    """
    Production DB has a 'username' NOT NULL column in accounts_userprofile
    that was created by an earlier version of the model but is not tracked in
    the current migration state. Drop it safely with IF EXISTS.
    """

    dependencies = [
        ('accounts', '0002_remove_userprofile_terms_accepted_at_and_more'),
    ]

    operations = [
        migrations.RunPython(drop_legacy_username_column, reverse_code=migrations.RunPython.noop),
    ]
