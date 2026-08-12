import datetime

import pytest
from django.core.management import call_command

from elections.models import Election, ElectionSourceLink, Race


@pytest.mark.django_db
def test_repair_splits_ma_6th_essex_3rd_bristol_collision():
    """Reproduces production Election id 2158 (issue #187): 6th Essex
    special general + 3rd Bristol special primary collapsed onto one
    Election because contest_group didn't exist yet."""
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="2025 MA State Representative 3rd Bristol Republican",
    )
    ElectionSourceLink.objects.create(election=collided, source="ma_sos", source_id="ma_sos:171341")
    essex = Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-essex",
    )
    bristol_d = Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-bristol-d",
    )
    bristol_r = Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-bristol-r",
    )

    call_command("repair_collided_elections", state="MA", group_by="jurisdiction", yes=True)

    essex.refresh_from_db()
    bristol_d.refresh_from_db()
    bristol_r.refresh_from_db()

    assert essex.election_id != bristol_d.election_id
    assert bristol_d.election_id == bristol_r.election_id
    assert not Election.objects.filter(pk=collided.pk).exists()
    assert Election.objects.filter(
        canonical_key="MA:special:2025-05-13:state|6th essex"
    ).exists()
    assert Election.objects.filter(
        canonical_key="MA:special:2025-05-13:state|3rd bristol"
    ).exists()


@pytest.mark.django_db
def test_repair_dry_run_makes_no_changes():
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="Collided",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-essex",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-bristol",
    )

    call_command("repair_collided_elections", state="MA", group_by="jurisdiction")  # no --yes

    assert Election.objects.filter(pk=collided.pk).exists()
    assert Election.objects.count() == 1


@pytest.mark.django_db
def test_repair_duplicates_source_link_to_every_matching_split_child():
    """Finding #1 (issue #187 follow-up): the original Election's
    ElectionSourceLink must not simply be deleted. When both split groups
    are built from races sharing the same source (as in MA's real 6th
    Essex / 3rd Bristol collision), the link is duplicated onto both split
    children rather than silently dropped, so neither loses provenance."""
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="2025 MA State Representative 3rd Bristol Republican",
    )
    ElectionSourceLink.objects.create(
        election=collided, source="ma_sos", source_id="ma_sos:171341",
        results_url="https://electionstats.state.ma.us/some/path",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-essex",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-bristol-d",
    )

    call_command("repair_collided_elections", state="MA", group_by="jurisdiction", yes=True)

    essex_election = Election.objects.get(canonical_key="MA:special:2025-05-13:state|6th essex")
    bristol_election = Election.objects.get(canonical_key="MA:special:2025-05-13:state|3rd bristol")

    assert ElectionSourceLink.objects.filter(election=essex_election, source="ma_sos").exists()
    assert ElectionSourceLink.objects.filter(election=bristol_election, source="ma_sos").exists()
    assert not ElectionSourceLink.objects.filter(election_id=collided.pk).exists()


@pytest.mark.django_db
def test_repair_derives_contributing_sources_per_split_group():
    """Finding #2 (issue #187 follow-up): contributing_sources on each split
    child must reflect only the sources actually backing that child's own
    races, not the full contributing_sources list of the original collided
    Election."""
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="Collided",
        contributing_sources=["ma_sos", "civic_api"],
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-essex",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.MA_SOS, canonical_key="race-bristol-d",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.CIVIC_API, canonical_key="race-bristol-r",
    )

    call_command("repair_collided_elections", state="MA", group_by="jurisdiction", yes=True)

    essex_election = Election.objects.get(canonical_key="MA:special:2025-05-13:state|6th essex")
    bristol_election = Election.objects.get(canonical_key="MA:special:2025-05-13:state|3rd bristol")

    assert essex_election.contributing_sources == ["ma_sos"]
    assert bristol_election.contributing_sources == ["civic_api", "ma_sos"]


@pytest.mark.django_db
def test_repair_is_idempotent():
    """A second run after a successful repair finds nothing left to split."""
    collided = Election.objects.create(
        state="MA", election_type="special",
        election_date=datetime.date(2025, 5, 13),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.RESULTS_PENDING,
        canonical_key="MA:special:2025-05-13:state",
        name="Collided",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="6th Essex",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-essex",
    )
    Race.objects.create(
        election=collided, race_type=Race.RaceType.CANDIDATE,
        office_title="State Representative", jurisdiction="3rd Bristol",
        geography_scope="district", certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        source=Race.Source.RESULTS_ADAPTER, canonical_key="race-bristol",
    )

    call_command("repair_collided_elections", state="MA", group_by="jurisdiction", yes=True)
    count_after_first_run = Election.objects.count()
    call_command("repair_collided_elections", state="MA", group_by="jurisdiction", yes=True)

    assert Election.objects.count() == count_after_first_run
