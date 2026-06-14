from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('elections', '0016_candidate_contributing_sources'),
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
                    ('va_elect', 'Virginia ELECT'),
                    ('ma_sos', 'Massachusetts SOS'),
                    ('ca_sos', 'California SOS'),
                    ('wa_votewa', 'Washington VoteWA'),
                ],
                max_length=20,
            ),
        ),
    ]
