from django.db import migrations


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
        migrations.RunSQL(
            sql='ALTER TABLE accounts_userprofile DROP COLUMN IF EXISTS username;',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
