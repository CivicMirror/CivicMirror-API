"""Tests for the merge_duplicate_races backfill command.

The command recomputes Race.canonical_key under the *current* normalization and
merges races that now collapse to the same key. These tests simulate the
pre-fix DB state by creating Race rows with stale stored keys, then assert the
command merges, recomputes, or leaves them alone as appropriate.
"""
from datetime import date

import pytest
from django.core.management import call_command

from aggregation.identity import election_canonical_key
from aggregation.migrations._seed_data import seed
from aggregation.models import SourcePrecedence
from elections.models import Candidate, Election, MeasureOption, Race
from results.models import OfficialResult


@pytest.fixture
def ca_election(db):
    seed(SourcePrecedence)
    return Election.objects.create(
        name="California Primary Election",
        election_date=date(2026, 6, 2),
        election_type="primary",
        jurisdiction_level="state",
        state="CA",
        canonical_key=election_canonical_key("CA", "primary", date(2026, 6, 2), "state"),
    )


def _make_race(election, *, office_title, ocd, source, canonical_key,
               race_type="candidate"):
    return Race.objects.create(
        election=election,
        race_type=race_type,
        office_title=office_title,
        ocd_division_id=ocd,
        jurisdiction="California",
        geography_scope="statewide",
        source=source,
        canonical_key=canonical_key,
        contributing_sources=[source],
        field_provenance={"office_title": source},
    )


def _civic_governor(election):
    """civic_api: all-caps title + bare state-code OCD (the old fallback)."""
    ek = election.canonical_key
    return _make_race(
        election, office_title="GOVERNOR", ocd="CA", source="civic_api",
        canonical_key=f"{ek}|governor|CA|candidate",
    )


def _ca_sos_governor(election):
    """ca_sos: geographic suffix + no OCD."""
    ek = election.canonical_key
    return _make_race(
        election, office_title="Governor - Statewide Results", ocd="", source="ca_sos",
        canonical_key=f"{ek}|governor - statewide results|NO_OCD|candidate",
    )


@pytest.mark.django_db
def test_merges_cross_source_duplicate_races(ca_election, tmp_path):
    civic = _civic_governor(ca_election)
    _ca_sos_governor(ca_election)

    call_command("merge_duplicate_races", audit_file=str(tmp_path / "a.jsonl"))

    races = Race.objects.filter(election=ca_election)
    assert races.count() == 1
    survivor = races.get()
    # Winner is the higher-precedence identity source (civic_api, CA rank 0).
    assert survivor.pk == civic.pk
    assert survivor.source == "civic_api"
    assert set(survivor.contributing_sources) == {"civic_api", "ca_sos"}
    # Key recomputed to the normalized, deduplicated form.
    assert survivor.canonical_key == f"{ca_election.canonical_key}|governor|NO_OCD|candidate"


@pytest.mark.django_db
def test_dry_run_changes_nothing_but_writes_audit(ca_election, tmp_path):
    _civic_governor(ca_election)
    _ca_sos_governor(ca_election)
    audit = tmp_path / "dry.jsonl"

    call_command("merge_duplicate_races", dry_run=True, audit_file=str(audit))

    # Both races untouched.
    assert Race.objects.filter(election=ca_election).count() == 2
    # Audit written even in dry-run, so collision groups can be inspected.
    assert audit.exists()
    assert audit.read_text().strip() != ""


@pytest.mark.django_db
def test_second_run_is_noop(ca_election, tmp_path):
    _civic_governor(ca_election)
    _ca_sos_governor(ca_election)

    call_command("merge_duplicate_races", audit_file=str(tmp_path / "1.jsonl"))
    assert Race.objects.filter(election=ca_election).count() == 1

    audit2 = tmp_path / "2.jsonl"
    call_command("merge_duplicate_races", audit_file=str(audit2))
    # Already merged + keys already normalized -> nothing to do.
    assert Race.objects.filter(election=ca_election).count() == 1
    assert audit2.read_text().strip() == ""


@pytest.mark.django_db
def test_solo_race_key_is_recomputed(ca_election, tmp_path):
    race = _ca_sos_governor(ca_election)  # lone race with a stale key

    call_command("merge_duplicate_races", audit_file=str(tmp_path / "s.jsonl"))

    race.refresh_from_db()
    assert race.canonical_key == f"{ca_election.canonical_key}|governor|NO_OCD|candidate"
    assert Race.objects.filter(election=ca_election).count() == 1


@pytest.mark.django_db
def test_official_results_move_to_winner(ca_election, tmp_path):
    civic = _civic_governor(ca_election)
    civic_cand = Candidate.objects.create(
        race=civic, name="Xavier Becerra", party="DEM", normalized_party="DEM",
        contributing_sources=["civic_api"], field_provenance={"party": "civic_api"},
    )
    ca_sos = _ca_sos_governor(ca_election)
    ca_cand = Candidate.objects.create(
        race=ca_sos, name="Becerra, Xavier", party="Dem", normalized_party="DEM",
        contributing_sources=["ca_sos"], field_provenance={"party": "ca_sos"},
    )
    result = OfficialResult.objects.create(
        race=ca_sos, candidate=ca_cand, vote_count=89380, result_type="unofficial",
    )

    call_command("merge_duplicate_races", audit_file=str(tmp_path / "r.jsonl"))

    survivor = Race.objects.get(election=ca_election)
    assert survivor.pk == civic.pk
    # "Xavier Becerra" and "Becerra, Xavier" collapse to one candidate.
    assert survivor.candidates.count() == 1
    # Result followed its candidate onto the winner race.
    result.refresh_from_db()
    assert result.race_id == survivor.pk
    assert result.candidate_id == civic_cand.pk
    assert result.vote_count == 89380


@pytest.mark.django_db
def test_local_measures_are_not_merged(ca_election, tmp_path):
    ek = ca_election.canonical_key
    _make_race(
        ca_election, office_title="Measure A - Citywide", ocd="", source="civic_api",
        race_type="measure", canonical_key=f"{ek}|measure a - citywide|NO_OCD|measure",
    )
    _make_race(
        ca_election, office_title="Measure A - Countywide", ocd="", source="ca_sos",
        race_type="measure", canonical_key=f"{ek}|measure a - countywide|NO_OCD|measure",
    )

    call_command("merge_duplicate_races", audit_file=str(tmp_path / "m.jsonl"))

    # The measure guard keeps local qualifiers, so these stay distinct.
    assert Race.objects.filter(election=ca_election).count() == 2


@pytest.mark.django_db
def test_measure_options_move_to_winner(ca_election, tmp_path):
    ek = ca_election.canonical_key
    # Two sources for the same statewide proposition (statewide IS stripped).
    civic = _make_race(
        ca_election, office_title="PROPOSITION 1", ocd="CA", source="civic_api",
        race_type="measure", canonical_key=f"{ek}|proposition 1|CA|measure",
    )
    MeasureOption.objects.create(race=civic, option_label="Yes")
    ca_sos = _make_race(
        ca_election, office_title="Proposition 1 - Statewide Results", ocd="",
        source="ca_sos", race_type="measure",
        canonical_key=f"{ek}|proposition 1 - statewide results|NO_OCD|measure",
    )
    ca_opt = MeasureOption.objects.create(race=ca_sos, option_label="No")

    call_command("merge_duplicate_races", audit_file=str(tmp_path / "o.jsonl"))

    survivor = Race.objects.get(election=ca_election)
    assert survivor.pk == civic.pk
    labels = set(survivor.measure_options.values_list("option_label", flat=True))
    assert labels == {"Yes", "No"}  # "No" moved off the deleted loser race
    ca_opt.refresh_from_db()
    assert ca_opt.race_id == survivor.pk
