from django.db import migrations

# Migration 0009 seeded a global ("*", "*", "openstates", 2) SourcePrecedence
# row, but nothing has ever passed source="openstates" to ingest_election/
# ingest_race/ingest_candidate -- integrations/openstates/ only writes
# through CandidateMatcher.enrich(), which uses its own separate
# candidate_matcher.FIELD_PRIORITY list and never consults SourcePrecedence.
# The row has been unreachable since it was added. See issue #125.


def remove_openstates_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.filter(source="openstates").delete()


def reseed_openstates_precedence(apps, schema_editor):
    SourcePrecedence = apps.get_model("aggregation", "SourcePrecedence")
    SourcePrecedence.objects.update_or_create(
        state="*", field_group="*", source="openstates",
        defaults={"rank": 2},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("aggregation", "0014_seed_ny_boe_precedence"),
    ]

    operations = [
        migrations.RunPython(remove_openstates_precedence, reseed_openstates_precedence),
    ]
