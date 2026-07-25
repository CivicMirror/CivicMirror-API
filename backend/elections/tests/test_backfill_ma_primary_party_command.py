"""
Fixture test for backfill_ma_primary_party — reproduces the Race 10000
scenario from issue #105 (a merged MA primary Race with blank-party
candidates) and verifies the command removes it in --apply mode and leaves
it untouched in --dry-run mode.
"""
from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command

from elections.models import Candidate, Election, Race


@pytest.fixture
def merged_primary_race(db):
    election = Election.objects.create(
        name="2026 MA State Representative 5th Essex Special Primary",
        election_date=date(2026, 9, 1),
        election_type=Election.ElectionType.PRIMARY,
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MA",
        canonical_key="MA:primary:2026-09-01:state",
        contributing_sources=["ma_sos"],
    )
    race = Race.objects.create(
        election=election,
        office_title="State Representative",
        jurisdiction="5th Essex",
        race_type=Race.RaceType.CANDIDATE,
        source=Race.Source.MA_SOS,
        canonical_key="MA:primary:2026-09-01:state|state representative|NO_OCD|candidate",
        contributing_sources=["ma_sos"],
    )
    for name in ["Andrew Tarr", "Christina Delisio", "Sam Meas", "Vanna Howard"]:
        Candidate.objects.create(race=race, name=name, party="")
    return election, race


@pytest.mark.django_db
def test_dry_run_does_not_delete(merged_primary_race):
    election, race = merged_primary_race
    stdout = StringIO()

    call_command("backfill_ma_primary_party", "--dry-run", stdout=stdout)

    assert Race.objects.filter(pk=race.pk).exists()
    assert "DRY RUN" in stdout.getvalue()
    assert str(race.pk) in stdout.getvalue()


@pytest.mark.django_db
def test_apply_deletes_merged_race(merged_primary_race):
    _election, race = merged_primary_race
    stdout = StringIO()

    call_command("backfill_ma_primary_party", stdout=stdout)

    assert not Race.objects.filter(pk=race.pk).exists()
    assert not Candidate.objects.filter(race_id=race.pk).exists()
    assert "deleted 1 race" in stdout.getvalue()


@pytest.mark.django_db
def test_general_election_races_untouched():
    election = Election.objects.create(
        name="2026 MA State Representative 5th Essex Special General",
        election_date=date(2026, 11, 3),
        election_type=Election.ElectionType.GENERAL,
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MA",
        canonical_key="MA:general:2026-11-03:state",
        contributing_sources=["ma_sos"],
    )
    race = Race.objects.create(
        election=election,
        office_title="State Representative",
        jurisdiction="5th Essex",
        race_type=Race.RaceType.CANDIDATE,
        source=Race.Source.MA_SOS,
        canonical_key="MA:general:2026-11-03:state|state representative|NO_OCD|candidate",
        contributing_sources=["ma_sos"],
    )
    Candidate.objects.create(race=race, name="Vanna Howard", party="Democratic")
    stdout = StringIO()

    call_command("backfill_ma_primary_party", stdout=stdout)

    assert Race.objects.filter(pk=race.pk).exists()
    assert "deleted 0 race" in stdout.getvalue()


@pytest.mark.django_db
def test_already_split_primary_races_untouched():
    """A primary Race where every candidate already has a party (post-fix,
    or a single-party primary the old code happened to get right) shouldn't
    be deleted."""
    election = Election.objects.create(
        name="2026 MA State Representative 5th Essex Special Primary",
        election_date=date(2026, 9, 1),
        election_type=Election.ElectionType.PRIMARY,
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MA",
        canonical_key="MA:primary:2026-09-01:state",
        contributing_sources=["ma_sos"],
    )
    race = Race.objects.create(
        election=election,
        office_title="State Representative",
        jurisdiction="5th Essex",
        race_type=Race.RaceType.CANDIDATE,
        source=Race.Source.MA_SOS,
        canonical_key="MA:primary:2026-09-01:state|state representative|NO_OCD|candidate|republican",
        contributing_sources=["ma_sos"],
    )
    Candidate.objects.create(race=race, name="Christina Delisio", party="Republican")
    Candidate.objects.create(race=race, name="Ashley Sullivan", party="Republican")
    stdout = StringIO()

    call_command("backfill_ma_primary_party", stdout=stdout)

    assert Race.objects.filter(pk=race.pk).exists()
    assert "deleted 0 race" in stdout.getvalue()
