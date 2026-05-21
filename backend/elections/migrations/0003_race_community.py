from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('elections', '0002_add_results_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='race',
            name='submitted_by_uid',
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
    ]
