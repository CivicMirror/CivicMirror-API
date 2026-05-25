from django.db import migrations


def delete_orphaned_users(apps, schema_editor):
    """Delete auth_user rows that have no accounts_userprofile (failed registrations)."""
    User = apps.get_model('auth', 'User')
    UserProfile = apps.get_model('accounts', 'UserProfile')
    profile_user_ids = set(UserProfile.objects.values_list('user_id', flat=True))
    deleted, _ = (
        User.objects
        .exclude(id__in=profile_user_ids)
        .exclude(is_staff=True)
        .exclude(is_superuser=True)
        .delete()
    )
    if deleted:
        print(f'  Removed {deleted} orphaned user(s).')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_drop_userprofile_username'),
    ]

    operations = [
        migrations.RunPython(delete_orphaned_users, reverse_code=migrations.RunPython.noop),
    ]
