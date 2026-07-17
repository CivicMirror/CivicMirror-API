import datetime

import pytest

from elections.models import Election, ElectionSourceLink
from integrations.mn_sos import election_registry
from integrations.mn_sos.election_registry import MnElection


def _make_mn_election(date_path, election_date, election_type, name, source_id=None, ers=None):
    meta = {"mn_date_path": date_path}
    if ers is not None:
        meta["mn_ers_election_id"] = ers
    election = Election.objects.create(
        name=name, election_date=election_date, election_type=election_type,
        jurisdiction_level=Election.JurisdictionLevel.STATE, state="MN",
        source_metadata=meta,
    )
    ElectionSourceLink.objects.create(
        election=election, source="mn_sos", source_id=source_id or f"mn_sos_{date_path}",
    )
    return election


def test_load_elections_reads_bundled_registry():
    elections = election_registry.load_elections()
    ge = next(e for e in elections if e.source_id == "mn_sos_2024_general")
    assert ge.election_date == datetime.date(2024, 11, 5)
    assert ge.election_type == "general"
    assert ge.date_path == "20241105"
    assert ge.ers_election_id == 170
    assert ge.status == "results_certified"


def test_date_path_appends_suffix_for_same_day_special():
    e = MnElection(
        election_date=datetime.date(2025, 1, 28),
        election_type="special",
        name="State Senator District 60 Special",
        suffix="27",
    )
    assert e.date_path == "20250128_27"


def test_date_path_is_plain_date_without_suffix():
    e = MnElection(
        election_date=datetime.date(2026, 8, 11),
        election_type="primary",
        name="2026 Minnesota Primary",
    )
    assert e.date_path == "20260811"


def test_source_id_defaults_to_date_path_when_unpinned():
    e = MnElection(
        election_date=datetime.date(2026, 8, 11),
        election_type="primary",
        name="2026 Minnesota Primary",
    )
    assert e.source_id == "mn_sos_20260811"


def test_status_defaults_to_upcoming():
    e = MnElection(
        election_date=datetime.date(2026, 11, 3),
        election_type="general",
        name="2026 Minnesota General",
    )
    assert e.status == "upcoming"


@pytest.mark.django_db
def test_registered_elections_is_toml_seed_only_when_db_empty():
    got = election_registry.registered_elections()
    assert [e.source_id for e in got] == ["mn_sos_2024_general"]


@pytest.mark.django_db
def test_registered_elections_includes_db_discovered_election():
    _make_mn_election("20260811", datetime.date(2026, 8, 11), "primary", "2026 Minnesota Primary")
    by_date = {e.date_path: e for e in election_registry.registered_elections()}
    assert "20260811" in by_date
    assert by_date["20260811"].election_type == "primary"


@pytest.mark.django_db
def test_registered_elections_reconstructs_suffix_and_ers_from_db_row():
    _make_mn_election(
        "20250128_27", datetime.date(2025, 1, 28), "special",
        "State Senator District 60 Special", ers=189,
    )
    by_date = {e.date_path: e for e in election_registry.registered_elections()}
    desc = by_date["20250128_27"]
    assert desc.suffix == "27"
    assert desc.ers_election_id == 189


@pytest.mark.django_db
def test_registered_elections_dedups_toml_and_db_by_date_path():
    # A DB row on the same date as the TOML 2024 general must not duplicate it.
    _make_mn_election("20241105", datetime.date(2024, 11, 5), "general", "dup", "mn_sos_dup")
    matches = [e for e in election_registry.registered_elections() if e.date_path == "20241105"]
    assert len(matches) == 1
    assert matches[0].source_id == "mn_sos_2024_general"  # TOML wins
