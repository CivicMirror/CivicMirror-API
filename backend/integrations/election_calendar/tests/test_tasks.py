"""
Tests for the election calendar module.
Non-DB tests (mappers) run with SQLite; DB tests require PostgreSQL.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from integrations.election_calendar.mappers import (
    _GENERAL,
    _PRIMARY_DATES,
    _STATE_NAMES,
    build_2026_election_specs,
)


# ---------------------------------------------------------------------------
# mappers — no DB required
# ---------------------------------------------------------------------------

def test_build_2026_election_specs_covers_all_50_states():
    specs = build_2026_election_specs()
    states = {s.state for s in specs}
    assert len(states) == 50


def test_build_2026_election_specs_two_per_state():
    specs = build_2026_election_specs()
    # Each state gets exactly one primary + one general
    assert len(specs) == 100


def test_build_2026_election_specs_types():
    specs = build_2026_election_specs()
    primaries = [s for s in specs if s.election_type == "primary"]
    generals = [s for s in specs if s.election_type == "general"]
    assert len(primaries) == 50
    assert len(generals) == 50


def test_build_2026_general_date_is_nov_3():
    specs = build_2026_election_specs()
    for s in specs:
        if s.election_type == "general":
            assert s.election_date == date(2026, 11, 3)


def test_all_primary_dates_in_2026():
    for state, d in _PRIMARY_DATES.items():
        assert d.year == 2026, f"{state} primary not in 2026: {d}"


def test_no_dc_in_calendar():
    assert "DC" not in _PRIMARY_DATES
    assert "DC" not in _STATE_NAMES


def test_election_name_format():
    specs = build_2026_election_specs()
    tx_primary = next(s for s in specs if s.state == "TX" and s.election_type == "primary")
    assert tx_primary.name == "2026 Texas Primary Election"

    ca_general = next(s for s in specs if s.state == "CA" and s.election_type == "general")
    assert ca_general.name == "2026 California General Election"


def test_known_primary_dates():
    """Spot-check a handful of high-profile states against NCSL source."""
    assert _PRIMARY_DATES["TX"] == date(2026, 3, 3)
    assert _PRIMARY_DATES["NC"] == date(2026, 3, 3)
    assert _PRIMARY_DATES["FL"] == date(2026, 8, 18)
    assert _PRIMARY_DATES["MI"] == date(2026, 8, 4)
    assert _PRIMARY_DATES["WA"] == date(2026, 8, 4)
    assert _PRIMARY_DATES["CA"] == date(2026, 6, 2)
    assert _PRIMARY_DATES["NY"] == date(2026, 6, 23)
    assert _PRIMARY_DATES["PA"] == date(2026, 5, 19)
    assert _PRIMARY_DATES["AZ"] == date(2026, 7, 21)


# ---------------------------------------------------------------------------
# task — DB required (PostgreSQL); SQLite errors are pre-existing
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_seed_2026_elections_creates_records():
    from elections.models import Election
    from integrations.election_calendar.tasks import seed_2026_elections

    seed_2026_elections.apply()

    assert Election.objects.filter(state="TX", election_type="primary").exists()
    assert Election.objects.filter(state="CA", election_type="general").exists()
    assert Election.objects.count() >= 100


@pytest.mark.django_db
def test_seed_2026_elections_sets_correct_status():
    from elections.models import Election
    from integrations.election_calendar.tasks import seed_2026_elections

    seed_2026_elections.apply()

    # TX primary (Mar 3) is in the past → RESULTS_PENDING
    tx_primary = Election.objects.get(state="TX", election_type="primary", election_date=date(2026, 3, 3))
    assert tx_primary.status == "RESULTS_PENDING"

    # Nov 3 general is future → UPCOMING
    tx_general = Election.objects.get(state="TX", election_type="general", election_date=date(2026, 11, 3))
    assert tx_general.status == "UPCOMING"


@pytest.mark.django_db
def test_seed_2026_elections_is_idempotent():
    from elections.models import Election
    from integrations.election_calendar.tasks import seed_2026_elections

    seed_2026_elections.apply()
    count_after_first = Election.objects.count()

    seed_2026_elections.apply()
    count_after_second = Election.objects.count()

    assert count_after_first == count_after_second


@pytest.mark.django_db
def test_seed_2026_elections_does_not_overwrite_existing_election():
    """Calendar source has lowest precedence — should not clobber a dedicated SOS election."""
    from elections.models import Election
    from integrations.election_calendar.tasks import seed_2026_elections

    # Simulate an existing election seeded by a dedicated integration
    from aggregation import ingest
    ingest.ingest_election(
        source="co_sos",
        source_id="co_sos_2026_primary",
        identity={
            "state": "CO",
            "election_type": "primary",
            "election_date": date(2026, 6, 30),
            "jurisdiction_level": "STATE",
        },
        fields={"name": "2026 Colorado Primary from co_sos", "status": "UPCOMING"},
    )

    seed_2026_elections.apply()

    # Only one CO primary should exist
    assert Election.objects.filter(state="CO", election_type="primary").count() == 1
