import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('elections', '0003_race_community'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uid', models.CharField(max_length=128, unique=True)),
                ('display_name', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='MockVote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uid', models.CharField(db_index=True, max_length=128)),
                ('race', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mock_votes', to='elections.race')),
                ('candidate_ids', models.JSONField(blank=True, null=True)),
                ('measure_option_id', models.IntegerField(blank=True, null=True)),
                ('ranked_selections', models.JSONField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'unique_together': {('uid', 'race')},
            },
        ),
    ]
