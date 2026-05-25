from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('elections', '0011_add_election_type_source_metadata'),
    ]

    operations = [
        migrations.AlterField(
            model_name='race',
            name='source',
            field=models.CharField(choices=[('civic_api', 'Civic API'), ('openelections', 'OpenElections'), ('medsl', 'MEDSL'), ('community', 'Community'), ('results_adapter', 'Results Adapter'), ('sc_vrems', 'SC VREMS'), ('ia_sos', 'Iowa SOS'), ('co_sos', 'Colorado SOS'), ('va_elect', 'Virginia ELECT'), ('ma_sos', 'Massachusetts SOS')], max_length=20),
        ),
    ]
