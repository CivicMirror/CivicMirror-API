import datetime
import os
from datetime import date
from unittest.mock import patch

import pytest

from integrations.md_sbe.parsers import parse_county_results_csv
from results.adapters.md import MarylandAdapter
from results.adapters.md_aggregate import aggregate_county_rows

pytestmark = pytest.mark.django_db

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def _county_rows():
    county01 = parse_county_results_csv(_load_fixture("md_county01_us_senator.csv"))
    county02 = parse_county_results_csv(_load_fixture("md_county02_us_senator.csv"))
    return county01 + county02


def test_aggregate_county_rows_sums_total_votes_across_counties():
    rows = aggregate_county_rows(_county_rows(), office_allowlist=frozenset({"U.S. Senator"}))

    by_name = {r.candidate_name: r.vote_count for r in rows}
    # 7396 (county 01) + 137645 (county 02) = 145041
    assert by_name["Angela Alsobrooks"] == 145041
    # 21811 + 164698 = 186509
    assert by_name["Larry Hogan"] == 186509


def test_aggregate_county_rows_marks_winner_true_if_any_county_row_says_so():
    rows = aggregate_county_rows(_county_rows(), office_allowlist=frozenset({"U.S. Senator"}))
    alsobrooks = next(r for r in rows if r.candidate_name == "Angela Alsobrooks")
    hogan = next(r for r in rows if r.candidate_name == "Larry Hogan")

    assert alsobrooks.is_winner is True
    assert hogan.is_winner is False


def test_aggregate_county_rows_flags_write_in_aggregate():
    rows = aggregate_county_rows(_county_rows(), office_allowlist=frozenset({"U.S. Senator"}))
    write_in_rows = [r for r in rows if r.is_write_in_aggregate]

    # All six write-in-flagged candidate names (Patrick J. Burke, Billy Bridges,
    # Irwin William Gibbs, Christy Renee Helmondollar, Robin Rowe, Other
    # Write-Ins) must collapse into exactly ONE combined row per office —
    # otherwise they'd collide on the same (candidate=None) DB key downstream.
    assert len(write_in_rows) == 1

    write_ins = write_in_rows[0]
    assert write_ins.candidate_name == "Write-In"
    assert write_ins.is_write_in_aggregate is True
    # county01: 17 (Burke) + 1 (Bridges) + 0 (Gibbs) + 0 (Helmondollar) + 0 (Rowe) + 86 (Other Write-Ins) = 104
    # county02: 143 (Burke) + 6 (Bridges) + 0 (Gibbs) + 0 (Helmondollar) + 1 (Rowe) + 621 (Other Write-Ins) = 771
    # 104 + 771 = 875
    assert write_ins.vote_count == 875


def test_aggregate_county_rows_sets_office_title_and_result_type():
    rows = aggregate_county_rows(_county_rows(), office_allowlist=frozenset({"U.S. Senator"}))
    for row in rows:
        assert row.office_title == "U.S. Senator"
        assert row.result_type == "official"


def test_aggregate_county_rows_excludes_offices_not_in_allowlist():
    county_rows = parse_county_results_csv(_load_fixture("md_county01_us_senator.csv"))
    # Allowlist a different office than what's in the fixture.
    rows = aggregate_county_rows(county_rows, office_allowlist=frozenset({"Governor"}))
    assert rows == []


@pytest.mark.django_db
@patch("results.adapters.md.MdSbeClient")
def test_fetch_results_sums_across_all_24_counties(mock_client_cls, django_user_model):
    from elections.models import Election

    election = Election.objects.create(
        name="2024 Maryland General Election",
        election_date=date(2024, 11, 5),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MD",
        source_id="md-2024-general",
        status=Election.Status.RESULTS_CERTIFIED,
    )

    county01 = _load_fixture("md_county01_us_senator.csv")
    county02 = _load_fixture("md_county02_us_senator.csv")
    # Fixtures only cover 2 of the 24 counties; the other 22 return the same
    # county-02 text purely to exercise the full 24-file fetch loop.
    responses = [county01, county02] + [county02] * 22
    mock_client_cls.return_value.fetch_county_results.side_effect = responses

    result = MarylandAdapter().fetch_results(election_date=election.election_date, election_id=election.pk)

    assert result.mapping_confidence == "full"
    senator_rows = [r for r in result.rows if r.office_title == "U.S. Senator"]
    assert len(senator_rows) > 0
    assert mock_client_cls.return_value.fetch_county_results.call_count == 24


@pytest.mark.django_db
@patch("results.adapters.md.MdSbeClient")
def test_fetch_results_returns_unchanged_when_checksum_matches_cache(mock_client_cls):
    from django.core.cache import cache

    from elections.models import Election

    election = Election.objects.create(
        name="2024 Maryland General Election",
        election_date=date(2024, 11, 5),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MD",
        source_id="md-2024-general-2",
        status=Election.Status.RESULTS_CERTIFIED,
    )
    county02 = _load_fixture("md_county02_us_senator.csv")
    mock_client_cls.return_value.fetch_county_results.return_value = county02

    adapter = MarylandAdapter()
    first = adapter.fetch_results(election_date=election.election_date, election_id=election.pk)
    cache.set(adapter.version_cache_key(election.pk), first.source_version)

    second = adapter.fetch_results(election_date=election.election_date, election_id=election.pk)
    assert second.unchanged is True
    assert second.rows == []


@pytest.mark.django_db
def test_fetch_results_returns_empty_for_missing_election():
    result = MarylandAdapter().fetch_results(election_date=date(2024, 11, 5), election_id=999999)
    assert result.rows == []
    assert result.mapping_confidence == "none"


def test_md_is_registered_via_app_ready():
    """MD must be in list_supported_states() so ingest_official_results picks it up
    (results/apps.py ResultsConfig.ready() must import results.adapters.md)."""
    from results.adapters.registry import get_adapter, list_supported_states

    assert "MD" in list_supported_states()
    assert get_adapter("MD") is MarylandAdapter


def test_fetch_results_uses_active_cycle_not_hardcoded_2024(db):
    from elections.models import Election
    from results.adapters.md import MarylandAdapter

    election = Election.objects.create(
        name="2026 Maryland General Election", state="MD",
        election_date=datetime.date(2026, 11, 3), election_type="general",
        jurisdiction_level="state",
    )

    with patch("results.adapters.md.get_active_cycle") as mock_cycle:
        from integrations.md_sbe.calendar import MdElectionCycle
        mock_cycle.return_value = MdElectionCycle(
            year=2026, primary_date=datetime.date(2026, 6, 23),
            general_date=datetime.date(2026, 11, 3), cycle_letter="G",
        )
        with patch("results.adapters.md.MdSbeClient.fetch_county_results", return_value=""):
            adapter = MarylandAdapter()
            result = adapter.fetch_results(election.election_date, election.pk)

    # No rows expected from an empty fixture, but the call must not raise
    # and must not silently fall back to the 2024/PG constants.
    assert result.source_url == "" or "2026" in result.source_url


def test_office_allowlist_includes_state_legislative_offices():
    from results.adapters.md import _OFFICE_ALLOWLIST
    assert "Governor / Lt. Governor" in _OFFICE_ALLOWLIST
    assert "State Senator" in _OFFICE_ALLOWLIST
    assert "House of Delegates" in _OFFICE_ALLOWLIST


# ---------------------------------------------------------------------------
# Office-name alias: the results CSVs say "U.S. Congress" where the candidate
# CSV (and therefore IN_SCOPE_OFFICES and every Stage 1 race) says
# "Representative in Congress".
# ---------------------------------------------------------------------------

def test_us_congress_results_rows_resolve_to_the_stage1_office():
    from integrations.md_sbe.mappers import IN_SCOPE_OFFICES, map_race_identity

    rows = aggregate_county_rows(
        parse_county_results_csv(_load_fixture("md_county01_us_congress.csv")),
        office_allowlist=IN_SCOPE_OFFICES,
    )

    assert rows, "'U.S. Congress' rows must survive the IN_SCOPE_OFFICES allowlist"

    # ...and land on exactly the Race Stage 1 built from the candidate CSV.
    identity, fields = map_race_identity("Representative in Congress", "Congressional District 6")
    delaney = next(r for r in rows if r.candidate_name == "April McClain Delaney")
    assert delaney.office_title == identity["office_title"]
    assert delaney.office_title == "Representative in Congress - Congressional District 6"
    assert delaney.raw["contest_code"] == fields["source_metadata"]["contest_code"]


def test_unaliased_us_congress_name_is_never_leaked_into_office_titles():
    from integrations.md_sbe.mappers import IN_SCOPE_OFFICES

    rows = aggregate_county_rows(
        parse_county_results_csv(_load_fixture("md_county01_us_congress.csv")),
        office_allowlist=IN_SCOPE_OFFICES,
    )
    assert not any("U.S. Congress" in r.office_title for r in rows)


# ---------------------------------------------------------------------------
# District must be part of the aggregation key.
# ---------------------------------------------------------------------------

def test_aggregate_keeps_districts_apart_and_titles_them_like_stage1():
    from integrations.md_sbe.mappers import IN_SCOPE_OFFICES

    rows = aggregate_county_rows(
        parse_county_results_csv(_load_fixture("md_gp26_county01_democratic.csv")),
        office_allowlist=IN_SCOPE_OFFICES,
    )
    delegate_titles = {r.office_title for r in rows if r.office_title.startswith("House of Delegates")}

    # Three separate delegate districts in this one county file — they must NOT
    # be summed into a single bogus "House of Delegates" row.
    assert delegate_titles == {
        "House of Delegates - Legislative District 1A",
        "House of Delegates - Legislative District 1B",
        "House of Delegates - Legislative District 1C",
    }
    jobe = next(r for r in rows if r.candidate_name == "Jason M. Jobe")
    assert jobe.vote_count == 481
    assert jobe.raw["contest_code"] == "md:House of Delegates:01A"


def test_aggregate_out_of_scope_local_office_is_still_dropped():
    from integrations.md_sbe.mappers import IN_SCOPE_OFFICES

    rows = aggregate_county_rows(
        parse_county_results_csv(_load_fixture("md_gp26_county01_democratic.csv")),
        office_allowlist=IN_SCOPE_OFFICES,
    )
    assert not any("Commissioner" in r.office_title for r in rows)


# ---------------------------------------------------------------------------
# Party must be part of the aggregation key AND reach the race-matching path.
# ---------------------------------------------------------------------------

def test_aggregate_carries_party_code_matching_the_party_split_race():
    from integrations.md_sbe.mappers import IN_SCOPE_OFFICES, map_race_identity
    from results.tasks import _race_source_identity, _row_source_identity

    rows = aggregate_county_rows(
        parse_county_results_csv(_load_fixture("md_gp26_county01_democratic.csv")),
        office_allowlist=IN_SCOPE_OFFICES,
    )
    moore = next(r for r in rows if r.candidate_name == "Wes Moore and Aruna Miller")
    assert moore.raw["party_code"] == "DEM"

    class _FakeRace:
        def __init__(self, metadata):
            self.source_metadata = metadata

    _, dem_fields = map_race_identity("Governor / Lt. Governor", "State Of Maryland", "Democratic")
    _, rep_fields = map_race_identity("Governor / Lt. Governor", "State Of Maryland", "Republican")

    row_identity = _row_source_identity(moore)
    dem_identity = _race_source_identity(_FakeRace(dem_fields["source_metadata"]))
    rep_identity = _race_source_identity(_FakeRace(rep_fields["source_metadata"]))

    # results/tasks.py::_process_race_results filters rows with exactly this test.
    assert all(row_identity.get(k) == v for k, v in dem_identity.items())
    assert not all(row_identity.get(k) == v for k, v in rep_identity.items())


def test_general_election_race_identity_matches_every_party_row():
    from integrations.md_sbe.mappers import IN_SCOPE_OFFICES, map_race_identity
    from results.tasks import _race_source_identity, _row_source_identity

    rows = aggregate_county_rows(
        parse_county_results_csv(_load_fixture("md_county01_us_congress.csv")),
        office_allowlist=IN_SCOPE_OFFICES,
    )

    class _FakeRace:
        def __init__(self, metadata):
            self.source_metadata = metadata

    _, fields = map_race_identity("Representative in Congress", "Congressional District 6")
    race_identity = _race_source_identity(_FakeRace(fields["source_metadata"]))

    matched = [
        r for r in rows
        if all(_row_source_identity(r).get(k) == v for k, v in race_identity.items())
    ]
    # Both nominees plus the combined write-in row.
    assert {r.candidate_name for r in matched} == {
        "April McClain Delaney", "Neil C. Parrott", "Write-In",
    }


# ---------------------------------------------------------------------------
# Phase-aware fetching.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
@patch("results.adapters.md.MdSbeClient")
def test_fetch_results_uses_per_party_files_for_a_primary(mock_client_cls):
    from elections.models import Election

    election = Election.objects.create(
        name="2026 Maryland Primary Election", state="MD",
        election_date=datetime.date(2026, 6, 23), election_type="primary",
        jurisdiction_level="state", source_id="md-2026-primary",
    )
    mock_client_cls.return_value.fetch_county_party_results.return_value = _load_fixture(
        "md_gp26_county01_democratic.csv",
    )

    result = MarylandAdapter().fetch_results(election.election_date, election.pk)

    # 24 counties x 2 ballot parties, and never the general-only CountyResults shape.
    assert mock_client_cls.return_value.fetch_county_party_results.call_count == 48
    assert mock_client_cls.return_value.fetch_county_results.call_count == 0
    kwargs = mock_client_cls.return_value.fetch_county_party_results.call_args.kwargs
    assert kwargs["cycle_prefix"] == "GP"
    assert kwargs["archived"] is False
    assert any(r.raw.get("party_code") == "DEM" for r in result.rows)


@pytest.mark.django_db
@patch("results.adapters.md.MdSbeClient")
def test_fetch_results_uses_consolidated_file_for_a_general(mock_client_cls):
    from elections.models import Election

    election = Election.objects.create(
        name="2026 Maryland General Election", state="MD",
        election_date=datetime.date(2026, 11, 3), election_type="general",
        jurisdiction_level="state", source_id="md-2026-general",
    )
    mock_client_cls.return_value.fetch_county_results.return_value = _load_fixture(
        "md_county01_us_congress.csv",
    )

    MarylandAdapter().fetch_results(election.election_date, election.pk)

    assert mock_client_cls.return_value.fetch_county_results.call_count == 24
    assert mock_client_cls.return_value.fetch_county_party_results.call_count == 0
    kwargs = mock_client_cls.return_value.fetch_county_results.call_args.kwargs
    assert kwargs["cycle_prefix"] == "GG"
    assert kwargs["archived"] is False
