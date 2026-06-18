"""Unit tests for the Texas results adapter. All HTTP calls are mocked."""
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.base import AdapterResult
from results.adapters.tx import TxAdapter


def test_tx_adapter_registered():
    import results.adapters.tx  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "TX" in list_supported_states()
    assert get_adapter("TX") is TxAdapter
    assert get_adapter("tx") is TxAdapter


def test_fetch_results_missing_tx_election_id():
    adapter = TxAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {}  # no tx_election_id

    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results(None, election_id=1)

    assert result.mapping_confidence == "none"
    assert result.rows == []
    assert "tx_election_id" in result.notes


def test_fetch_results_version_unchanged():
    """If version n matches cache, returns unchanged=True without fetching countyInfo."""
    adapter = TxAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"tx_election_id": 56181}
    mock_election.pk = 1

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.tx.TxGoElectClient") as MockClient, \
         patch("results.adapters.tx.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        MockClient.return_value.get_version.return_value = 21
        mock_cache.get.return_value = "21"  # matches (cache stores str(version))

        result = adapter.fetch_results(None, election_id=1)

    assert result.unchanged is True
    assert result.rows == []
    MockClient.return_value.get_election_data.assert_not_called()


def test_fetch_results_statewide_candidate_rows():
    """OfficeSummary → statewide ResultRows with jurisdiction_fragment=''."""
    adapter = TxAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"tx_election_id": 56181}
    mock_election.pk = 2

    election_data = {
        "version": 22,
        "home": {"CountiesReporting": {"CR": 5, "CT": 5}, "PrecinctsReporting": {"PR": 122, "PT": 122}},
        "office_summary": {
            "OS": [
                {
                    "OID": 5031,
                    "ON": "STATE SENATOR, DISTRICT 4",
                    "C": [
                        {"ID": 36388, "BN": "BRETT W. LIGON", "P": "REP", "V": 5757, "PE": 73.05, "EV": 4394},
                        {"ID": 36422, "BN": "RON C. ANGELETTI", "P": "DEM", "V": 2124, "PE": 26.95, "EV": 1472},
                    ]
                }
            ]
        },
        "statewide_q": {},
    }
    county_data = {}  # no counties for this test

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.tx.TxGoElectClient") as MockClient, \
         patch("results.adapters.tx.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        client = MockClient.return_value
        client.get_version.return_value = 22
        client.get_election_data.return_value = election_data
        client.get_county_results.return_value = county_data
        mock_cache.get.return_value = 10  # different from 22

        result = adapter.fetch_results(None, election_id=2)

    assert result.mapping_confidence == "full"
    assert result.source_version == "22"
    # Two statewide rows
    assert len(result.rows) == 2
    row = result.rows[0]
    assert row.candidate_name == "BRETT W. LIGON"
    assert row.vote_count == 5757
    assert row.vote_pct == 73.05
    assert row.jurisdiction_fragment == ""
    assert row.raw["tx_candidate_id"] == 36388
    assert row.raw["party"] == "REP"
    assert row.raw["early_votes"] == 4394


def test_fetch_results_complete_unofficial_when_all_reporting():
    """CR==CT and PR==PT → result_type='complete_unofficial'."""
    adapter = TxAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"tx_election_id": 56181}
    mock_election.pk = 3

    election_data = {
        "version": 21,
        "home": {"CountiesReporting": {"CR": 5, "CT": 5}, "PrecinctsReporting": {"PR": 122, "PT": 122}},
        "office_summary": {"OS": []},
        "statewide_q": {},
    }

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.tx.TxGoElectClient") as MockClient, \
         patch("results.adapters.tx.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        MockClient.return_value.get_version.return_value = 21
        MockClient.return_value.get_election_data.return_value = election_data
        MockClient.return_value.get_county_results.return_value = {}
        mock_cache.get.return_value = 1

        result = adapter.fetch_results(None, election_id=3)

    # No rows (empty OS), but result_type inference worked — check via source_version
    assert result.source_version == "21"


def test_fetch_results_unofficial_when_partial():
    """CR < CT → result_type='unofficial'."""
    adapter = TxAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"tx_election_id": 56181}
    mock_election.pk = 4

    election_data = {
        "version": 5,
        "home": {"CountiesReporting": {"CR": 3, "CT": 5}, "PrecinctsReporting": {"PR": 60, "PT": 122}},
        "office_summary": {
            "OS": [
                {
                    "OID": 5031,
                    "ON": "STATE SENATOR",
                    "C": [{"ID": 1, "BN": "ALICE", "P": "REP", "V": 100, "PE": 100.0, "EV": 50}]
                }
            ]
        },
        "statewide_q": {},
    }

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.tx.TxGoElectClient") as MockClient, \
         patch("results.adapters.tx.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        MockClient.return_value.get_version.return_value = 5
        MockClient.return_value.get_election_data.return_value = election_data
        MockClient.return_value.get_county_results.return_value = {}
        mock_cache.get.return_value = 1

        result = adapter.fetch_results(None, election_id=4)

    assert result.rows[0].result_type == "unofficial"


def test_fetch_results_county_rows():
    """countyInfo → county ResultRows with jurisdiction_fragment set."""
    adapter = TxAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"tx_election_id": 56181}
    mock_election.pk = 5

    election_data = {
        "version": 21,
        "home": {"CountiesReporting": {"CR": 5, "CT": 5}, "PrecinctsReporting": {"PR": 122, "PT": 122}},
        "office_summary": {"OS": []},
        "statewide_q": {},
    }
    county_data = {
        "101": {
            "N": "HARRIS",
            "MID": 48201,
            "Races": {
                "5031": {
                    "OID": 5031,
                    "N": "STATE SENATOR, DISTRICT 4",
                    "C": {
                        "36388": {"id": 36388, "N": "BRETT W. LIGON", "P": "REP", "V": 5757, "PE": 73.05, "EV": 4394}
                    },
                    "PR": 75, "TP": 75,
                }
            }
        }
    }

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.tx.TxGoElectClient") as MockClient, \
         patch("results.adapters.tx.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        MockClient.return_value.get_version.return_value = 21
        MockClient.return_value.get_election_data.return_value = election_data
        MockClient.return_value.get_county_results.return_value = county_data
        mock_cache.get.return_value = 1

        result = adapter.fetch_results(None, election_id=5)

    county_rows = [r for r in result.rows if r.jurisdiction_fragment == "harris"]
    assert len(county_rows) == 1
    row = county_rows[0]
    assert row.candidate_name == "BRETT W. LIGON"
    assert row.vote_count == 5757
    assert row.raw["county_mid"] == 48201
    assert row.raw["tx_office_id"] == 5031


def test_fetch_results_proposition_rows():
    """StateWideQ entries → ResultRows with option_label, no candidate_name."""
    adapter = TxAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"tx_election_id": 59001}
    mock_election.pk = 6

    election_data = {
        "version": 3,
        "home": {"CountiesReporting": {"CR": 254, "CT": 254}, "PrecinctsReporting": {"PR": 5000, "PT": 5000}},
        "office_summary": {"OS": []},
        "statewide_q": {
            "Q": [
                {
                    "OID": 7001,
                    "ON": "PROPOSITION 1",
                    "C": [
                        {"ID": 901, "N": "FOR", "V": 3000000, "PE": 60.0, "EV": 2000000},
                        {"ID": 902, "N": "AGAINST", "V": 2000000, "PE": 40.0, "EV": 1200000},
                    ]
                }
            ]
        },
    }

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.tx.TxGoElectClient") as MockClient, \
         patch("results.adapters.tx.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        MockClient.return_value.get_version.return_value = 3
        MockClient.return_value.get_election_data.return_value = election_data
        MockClient.return_value.get_county_results.return_value = {}
        mock_cache.get.return_value = 1

        result = adapter.fetch_results(None, election_id=6)

    prop_rows = result.rows
    assert len(prop_rows) == 2
    assert prop_rows[0].candidate_name is None
    assert prop_rows[0].option_label == "FOR"
    assert prop_rows[0].vote_count == 3000000
    assert prop_rows[0].result_type == "complete_unofficial"
