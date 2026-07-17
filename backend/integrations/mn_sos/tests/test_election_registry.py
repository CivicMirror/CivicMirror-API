import datetime

from integrations.mn_sos import election_registry
from integrations.mn_sos.election_registry import MnElection


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
