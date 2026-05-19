from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Add results_url to Election — present in 0001_initial but missing from
    the production DB (the initial migration was applied against an older
    schema; this migration brings the column into sync).
    """

    dependencies = [
        ('elections', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='election',
            name='results_url',
            field=models.URLField(blank=True, default=''),
            preserve_default=False,
        ),
    ]
