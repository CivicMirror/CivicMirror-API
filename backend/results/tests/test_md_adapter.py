import os

from integrations.md_sbe.parsers import parse_county_results_csv
from results.adapters.md_aggregate import aggregate_county_rows

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
    write_ins = next(r for r in rows if r.candidate_name == "Other Write-Ins")

    assert write_ins.is_write_in_aggregate is True
    # 86 (county 01) + 621 (county 02) = 707
    assert write_ins.vote_count == 707


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


from datetime import date
from unittest.mock import patch

import pytest

from results.adapters.md import MarylandAdapter


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
