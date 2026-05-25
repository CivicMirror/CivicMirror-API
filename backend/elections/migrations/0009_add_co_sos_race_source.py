from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('elections', '0008_add_ia_sos_race_source'),
    ]

    operations = [
        migrations.AlterField(
            model_name='race',
            name='source',
            field=models.CharField(
                choices=[
                    ('civic_api', 'Civic API'),
                    ('openelections', 'OpenElections'),
                    ('medsl', 'MEDSL'),
                    ('community', 'Community'),
                    ('results_adapter', 'Results Adapter'),
                    ('sc_vrems', 'SC VREMS'),
                    ('ia_sos', 'Iowa SOS'),
                    ('co_sos', 'Colorado SOS'),
                ],
                max_length=20,
            ),
        ),
    ]
