"""
Relabel MA aggregate result rows from jurisdiction_fragment="STATEWIDE" to "".

The MA adapter stored each contest's TOTALS row as "STATEWIDE" (even for district races), while
every other adapter uses "" for the aggregate row. /races/{id}/results/ only collapses to the
aggregate when a "" row exists, so MA races returned every town row plus the total, and the
FrontEnd listed each candidate several times. The adapter now writes "".

Rows whose (race, candidate, measure_option, round_number) already has a "" row are left alone,
since relabeling them would violate the natural-key constraint. None existed when this was written.
"""
from django.db import migrations


def relabel(apps, schema_editor):
    OfficialResult = apps.get_model("results", "OfficialResult")
    rows = OfficialResult.objects.filter(race__election__state="MA", jurisdiction_fragment="STATEWIDE")
    for row in rows.iterator():
        clash = OfficialResult.objects.filter(
            race_id=row.race_id,
            candidate_id=row.candidate_id,
            measure_option_id=row.measure_option_id,
            round_number=row.round_number,
            jurisdiction_fragment="",
        ).exists()
        if not clash:
            OfficialResult.objects.filter(pk=row.pk).update(jurisdiction_fragment="")


class Migration(migrations.Migration):

    dependencies = [
        ("results", "0002_officialresult_official_result_natural_key"),
        ("elections", "0035_add_ut_elections_race_source"),
    ]

    operations = [
        migrations.RunPython(relabel, reverse_code=migrations.RunPython.noop),
    ]
