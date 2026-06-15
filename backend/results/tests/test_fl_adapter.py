"""
Unit tests for the Florida Election Watch results adapter.
HTTP calls are fully mocked — no network required.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.base import AdapterResult, ResultRow
from results.adapters.fl import FloridaAdapter


def test_fl_adapter_registered():
    import results.adapters.fl  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "FL" in list_supported_states()
    assert get_adapter("FL") is FloridaAdapter
    assert get_adapter("fl") is FloridaAdapter


_MOCK_ELECTION = MagicMock()
_MOCK_ELECTION.source_metadata = {"fl_ew_slug": "20260324"}
_MOCK_ELECTION.pk = 1


_TSV = (
    "ElectionDate\tPartyCode\tPartyName\tRaceCode\tRaceName\tCountyCode\t"
    "CountyName\tJuris1num\tJuris2num\tPrecincts\tPrecinctsReporting\t"
    "CanNameLast\tCanNameFirst\tCanNameMiddle\tCanVotes\n"
    "03/24/2026\tREP\tRepublican Party\tSTS\tState Senator, District 14\t"
    "HIL\tHillsborough\t014\t\t152\t152\tTomkow\tJosie\t\t39836\n"
    "03/24/2026\tDEM\tDemocratic Party\tSTS\tState Senator, District 14\t"
    "HIL\tHillsborough\t014\t\t152\t152\tNathan\tBrian\t\t40245\n"
)


def test_fetch_results_no_slug():
    """Election with no fl_ew_slug in source_metadata → mapping_confidence=none."""
    adapter = FloridaAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {}

    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results(date(2026, 3, 24), election_id=1)

    assert isinstance(result, AdapterResult)
    assert result.mapping_confidence == "none"
    assert result.rows == []
    assert "fl_ew_slug" in result.notes


def test_fetch_results_unchanged_version():
    """Cached Last-Modified matches current → returns unchanged=True."""
    adapter = FloridaAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.fl.FlEwClient") as MockClient, \
         patch("results.adapters.fl.cache") as mock_cache:

        mock_mgr.get.return_value = _MOCK_ELECTION
        mock_cache.get.return_value = "Mon, 24 Mar 2026 22:00:00 GMT"

        client = MockClient.return_value
        client.get_last_modified.return_value = "Mon, 24 Mar 2026 22:00:00 GMT"
        client.file_url.return_value = "https://flelectionfiles.floridados.gov/enightfilespublic/20260324_ElecResultsFL.txt"

        result = adapter.fetch_results(date(2026, 3, 24), election_id=1)

    assert result.unchanged is True
    assert result.rows == []
    assert result.source_version == "Mon, 24 Mar 2026 22:00:00 GMT"


def test_fetch_results_returns_one_row_per_candidate_per_county():
    """Two candidates in one county → two ResultRows."""
    adapter = FloridaAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.fl.FlEwClient") as MockClient, \
         patch("results.adapters.fl.cache") as mock_cache:

        mock_mgr.get.return_value = _MOCK_ELECTION
        mock_cache.get.return_value = None

        client = MockClient.return_value
        client.get_last_modified.return_value = "Mon, 24 Mar 2026 22:00:00 GMT"
        client.file_url.return_value = (
            "https://flelectionfiles.floridados.gov/enightfilespublic/20260324_ElecResultsFL.txt"
        )
        client.fetch_results_file.return_value = _TSV

        result = adapter.fetch_results(date(2026, 3, 24), election_id=1)

    assert len(result.rows) == 2
    assert result.mapping_confidence == "full"
    assert result.unchanged is False


def test_result_row_fields():
    """Validate ResultRow field mapping from a known data row."""
    adapter = FloridaAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.fl.FlEwClient") as MockClient, \
         patch("results.adapters.fl.cache") as mock_cache:

        mock_mgr.get.return_value = _MOCK_ELECTION
        mock_cache.get.return_value = None

        client = MockClient.return_value
        client.get_last_modified.return_value = "v1"
        client.file_url.return_value = "https://flelectionfiles.floridados.gov/enightfilespublic/20260324_ElecResultsFL.txt"
        client.fetch_results_file.return_value = _TSV

        result = adapter.fetch_results(date(2026, 3, 24), election_id=1)

    tomkow_row = next(r for r in result.rows if r.candidate_name == "Josie Tomkow")
    assert tomkow_row.vote_count == 39836
    assert tomkow_row.vote_pct is None
    assert tomkow_row.result_type == "official"   # 152/152 precincts reporting
    assert tomkow_row.jurisdiction_fragment == "hil"
    assert tomkow_row.office_title == "State Senator, District 14"
    assert tomkow_row.raw["party_code"] == "REP"
    assert tomkow_row.raw["county_name"] == "Hillsborough"
    assert tomkow_row.raw["fl_ew_slug"] == "20260324"


def test_result_type_unofficial_when_precincts_incomplete():
    """PrecinctsReporting < Precincts → result_type='unofficial'."""
    adapter = FloridaAdapter()
    partial_tsv = (
        "ElectionDate\tPartyCode\tPartyName\tRaceCode\tRaceName\tCountyCode\t"
        "CountyName\tJuris1num\tJuris2num\tPrecincts\tPrecinctsReporting\t"
        "CanNameLast\tCanNameFirst\tCanNameMiddle\tCanVotes\n"
        "08/18/2026\tREP\tRepublican Party\tGOV\tGovernor\t"
        "ALA\tAlachua\t000\t\t100\t60\tSmith\tAlice\t\t5000\n"
    )
    mock_election = MagicMock()
    mock_election.source_metadata = {"fl_ew_slug": "20260818"}
    mock_election.pk = 2

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.fl.FlEwClient") as MockClient, \
         patch("results.adapters.fl.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None

        client = MockClient.return_value
        client.get_last_modified.return_value = "v2"
        client.file_url.return_value = "https://flelectionfiles.floridados.gov/enightfilespublic/20260818_ElecResultsFL.txt"
        client.fetch_results_file.return_value = partial_tsv

        result = adapter.fetch_results(date(2026, 8, 18), election_id=2)

    assert result.rows[0].result_type == "unofficial"


def test_fetch_results_election_not_found():
    adapter = FloridaAdapter()
    with patch("elections.models.Election.objects") as mock_mgr:
        from elections.models import Election
        mock_mgr.get.side_effect = Election.DoesNotExist
        result = adapter.fetch_results(date(2026, 3, 24), election_id=999)

    assert result.mapping_confidence == "none"
    assert result.rows == []


def test_source_version_written_to_result():
    adapter = FloridaAdapter()

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.fl.FlEwClient") as MockClient, \
         patch("results.adapters.fl.cache") as mock_cache:

        mock_mgr.get.return_value = _MOCK_ELECTION
        mock_cache.get.return_value = None

        client = MockClient.return_value
        client.get_last_modified.return_value = "Mon, 24 Mar 2026 22:00:00 GMT"
        client.file_url.return_value = "https://example.com/f.txt"
        client.fetch_results_file.return_value = _TSV

        result = adapter.fetch_results(date(2026, 3, 24), election_id=1)

    assert result.source_version == "Mon, 24 Mar 2026 22:00:00 GMT"
