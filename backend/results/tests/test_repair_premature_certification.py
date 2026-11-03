"""
repair_premature_certification reverts certification applied to unheld elections.

Covers the two production cases from docs/2026-11-02-midterm-poll-triage.md:
Illinois (genuine rows, certified too early → keep rows, un-certify) and
Missouri (wrong-cycle 2024 rows under a 2026 record → delete rows).
"""
from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from elections.models import Candidate, Election, Race
from results.models import OfficialResult


def _days_from_today(offset):
    return timezone.localdate() + timedelta(days=offset)


def _election(state="IL", offset=1, status=Election.Status.RESULTS_CERTIFIED, key="a"):
    return Election.objects.create(
        name=f"2026 {state} General Election",
        election_date=_days_from_today(offset),
        election_type="general",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state=state,
        source_id=f"{state}-{key}",
        canonical_key=f"{state}:general:{key}",
        status=status,
    )


def _certified_race(election, n=1, derived=False):
    race = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title=f"U.S. Senator {n}",
        jurisdiction=election.state,
        geography_scope="statewide",
        source=Race.Source.CIVIC_API,
        canonical_key=f"{election.canonical_key}:{n}",
        certification_status=Race.CertificationStatus.RESULTS_CERTIFIED,
        race_status=Race.RaceStatus.ARCHIVED,
        source_metadata={"winners_derived": True} if derived else {},
    )
    candidate = Candidate.objects.create(race=race, name=f"Alice {n}", party="DEM")
    OfficialResult.objects.create(
        race=race,
        candidate=candidate,
        vote_count=1234,
        result_type=OfficialResult.ResultType.OFFICIAL,
        is_winner=True if derived else None,
        certified_at=timezone.now(),
    )
    return race


def _run(*args):
    out = StringIO()
    call_command("repair_premature_certification", *args, stdout=out)
    return json.loads(out.getvalue())


@pytest.mark.django_db
def test_dry_run_inventories_without_writing():
    election = _election()
    race = _certified_race(election)

    report = _run("--state", "il")

    assert report["mode"] == "dry_run"
    assert report["elections"] == 1
    assert report["races"] == 1
    assert report["result_rows"] == 1
    election.refresh_from_db()
    race.refresh_from_db()
    assert election.status == Election.Status.RESULTS_CERTIFIED
    assert race.certification_status == Race.CertificationStatus.RESULTS_CERTIFIED


@pytest.mark.django_db
def test_apply_reverts_status_and_keeps_rows_by_default():
    """Illinois: the candidates and votes are genuine 2026 data; only the claim was wrong."""
    election = _election()
    race = _certified_race(election)

    report = _run("--state", "IL", "--apply")

    assert report["mode"] == "applied"
    assert report["deleted_result_rows"] == 0
    election.refresh_from_db()
    race.refresh_from_db()
    assert election.status == Election.Status.UPCOMING
    assert race.certification_status == Race.CertificationStatus.RESULTS_PENDING
    assert race.race_status == Race.RaceStatus.ACTIVE
    row = OfficialResult.objects.get(race=race)
    assert row.vote_count == 1234
    assert row.certified_at is None


@pytest.mark.django_db
def test_delete_results_removes_wrong_cycle_rows():
    """Missouri: 2024 vote counts must not survive under a 2026 race."""
    election = _election(state="MO", key="mo")
    race = _certified_race(election)

    report = _run("--state", "MO", "--delete-results", "--apply")

    assert report["deleted_result_rows"] == 1
    assert not OfficialResult.objects.filter(race=race).exists()
    race.refresh_from_db()
    assert race.certification_status == Race.CertificationStatus.UPCOMING
    assert race.race_status == Race.RaceStatus.ACTIVE


@pytest.mark.django_db
def test_apply_clears_our_derived_winner_flags():
    election = _election(key="derived")
    race = _certified_race(election, derived=True)

    _run("--election-id", str(election.pk), "--apply")

    race.refresh_from_db()
    assert "winners_derived" not in (race.source_metadata or {})
    assert OfficialResult.objects.get(race=race).is_winner is None


@pytest.mark.django_db
def test_election_on_polling_day_reverts_to_results_pending():
    """results_pending, not active: poll_pending_results only queues RESULTS_PENDING."""
    election = _election(offset=0, key="today")
    _certified_race(election)

    _run("--election-id", str(election.pk), "--apply")

    election.refresh_from_db()
    assert election.status == Election.Status.RESULTS_PENDING


@pytest.mark.django_db
def test_elections_already_held_are_left_alone():
    election = _election(offset=-7, key="past")
    race = _certified_race(election)

    report = _run()

    assert report["elections"] == 0
    election.refresh_from_db()
    race.refresh_from_db()
    assert election.status == Election.Status.RESULTS_CERTIFIED
    assert race.certification_status == Race.CertificationStatus.RESULTS_CERTIFIED


@pytest.mark.django_db
def test_unheld_election_with_clean_races_is_not_listed():
    election = _election(status=Election.Status.UPCOMING, key="clean")
    Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title="Governor",
        jurisdiction="IL",
        geography_scope="statewide",
        source=Race.Source.CIVIC_API,
        canonical_key=f"{election.canonical_key}:clean",
        certification_status=Race.CertificationStatus.UPCOMING,
        race_status=Race.RaceStatus.ACTIVE,
    )

    assert _run()["elections"] == 0


@pytest.mark.django_db
def test_apply_with_nothing_to_repair_errors():
    with pytest.raises(CommandError):
        _run("--state", "IL", "--apply")


@pytest.mark.django_db
def test_state_must_be_two_letters():
    with pytest.raises(CommandError):
        _run("--state", "Illinois")


@pytest.mark.django_db
def test_delete_results_spares_unaffected_races_in_the_same_election():
    election = _election(key="mixed")
    bad = _certified_race(election, n=1)
    clean = Race.objects.create(
        election=election,
        race_type=Race.RaceType.CANDIDATE,
        office_title="Governor",
        jurisdiction="IL",
        geography_scope="statewide",
        source=Race.Source.CIVIC_API,
        canonical_key=f"{election.canonical_key}:clean",
        certification_status=Race.CertificationStatus.RESULTS_PENDING,
        race_status=Race.RaceStatus.ACTIVE,
    )
    keeper = Candidate.objects.create(race=clean, name="Bob", party="REP")
    OfficialResult.objects.create(
        race=clean,
        candidate=keeper,
        vote_count=99,
        result_type=OfficialResult.ResultType.UNOFFICIAL,
        certified_at=None,
    )

    report = _run("--election-id", str(election.pk), "--delete-results", "--apply")

    assert report["races"] == 1
    assert report["deleted_result_rows"] == 1
    assert not OfficialResult.objects.filter(race=bad).exists()
    assert OfficialResult.objects.filter(race=clean).count() == 1


@pytest.mark.django_db
def test_report_file_is_written(tmp_path):
    election = _election(key="report")
    _certified_race(election)
    path = tmp_path / "report.json"

    _run("--election-id", str(election.pk), "--report", str(path))

    payload = json.loads(path.read_text())
    assert payload["applied"] is False
    assert payload["elections"][0]["election_id"] == election.pk
    assert payload["elections"][0]["races"][0]["certified_at_stamps"] == 1
