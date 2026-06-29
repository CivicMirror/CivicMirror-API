"""
Unit tests for the Georgia results adapter.
Heavy parsing logic lives in EnhancedVotingAdapter and is tested via VA tests;
these tests cover GA-specific configuration and real-world data shapes.
"""
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.base import AdapterResult
from results.adapters.ga import GeorgiaAdapter
from results.adapters.enhanced_voting import _parse_ballot_items

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_ga_adapter_registered():
    import results.adapters.ga  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "GA" in list_supported_states()
    assert get_adapter("GA") is GeorgiaAdapter
    assert get_adapter("ga") is GeorgiaAdapter


def test_ga_adapter_base_url():
    assert GeorgiaAdapter.base_url == "https://results.sos.ga.gov/results/public/api"
    assert GeorgiaAdapter.state == "GA"
    assert GeorgiaAdapter.state_name == "Georgia"


# ---------------------------------------------------------------------------
# GA-specific race name format ("Governor - Rep" party suffix)
# ---------------------------------------------------------------------------

_GA_PRIMARY_BALLOT_ITEM = {
    "id": "01000000-76e9-acd3-495f-08dec5806d9e",
    "contestType": "Candidate",
    "name": [{"languageId": "en", "text": "Governor - Rep"}],
    "summaryResults": {
        "ballotOptions": [
            {
                "name": [{"languageId": "en", "text": "Rick Jackson"}],
                "voteCount": 373540,
                "votePercent": 52.6,
                "isWinner": None,
                "isWriteIn": False,
                "nativeId": "9",
                "party": {"abbreviation": "REP"},
            },
            {
                "name": [{"languageId": "en", "text": "Burt Jones"}],
                "voteCount": 336005,
                "votePercent": 47.4,
                "isWinner": None,
                "isWriteIn": False,
                "nativeId": "10",
                "party": {"abbreviation": "REP"},
            },
        ]
    },
}


def test_parse_ga_party_suffixed_race_name():
    rows = _parse_ballot_items([_GA_PRIMARY_BALLOT_ITEM], result_type="unofficial")
    assert len(rows) == 2
    # Office title preserved verbatim including party suffix
    assert rows[0].office_title == "Governor - Rep"
    assert rows[0].candidate_name == "Rick Jackson"
    assert rows[0].vote_count == 373540
    assert rows[0].raw["party"] == "REP"
    # isWinner is None for primaries (GA doesn't set it until certified)
    assert rows[0].is_winner is None


def test_parse_ga_us_senate_runoff():
    item = {
        "id": "uuid-senate",
        "contestType": "Candidate",
        "name": [{"languageId": "en", "text": "US Senate - Rep"}],
        "summaryResults": {
            "ballotOptions": [
                {
                    "name": [{"languageId": "en", "text": "Mike Collins"}],
                    "voteCount": 390167,
                    "votePercent": 55.5,
                    "isWinner": None,
                    "isWriteIn": False,
                    "nativeId": "2",
                    "party": {"abbreviation": "REP"},
                },
            ]
        },
    }
    rows = _parse_ballot_items([item], result_type="unofficial")
    assert rows[0].office_title == "US Senate - Rep"
    assert rows[0].candidate_name == "Mike Collins"
    assert rows[0].vote_count == 390167


# ---------------------------------------------------------------------------
# fetch_results integration (mocked HTTP)
# ---------------------------------------------------------------------------

def test_fetch_results_no_slug():
    adapter = GeorgiaAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {}

    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results(None, election_id=99)

    assert result.mapping_confidence == "none"
    assert "enr_slug" in result.notes


def test_fetch_results_uses_ga_base_url():
    adapter = GeorgiaAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "11032026General"}
    mock_election.pk = 1

    meta_payload = {"asOf": "2026-11-03T23:00:00Z", "isOfficialResults": False}
    data_payload = {"ballotItems": [_GA_PRIMARY_BALLOT_ITEM]}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.enhanced_voting.requests.get") as mock_get, \
         patch("results.adapters.enhanced_voting.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None

        meta_resp = MagicMock()
        meta_resp.json.return_value = meta_payload
        data_resp = MagicMock()
        data_resp.json.return_value = data_payload
        mock_get.side_effect = [meta_resp, data_resp]

        result = adapter.fetch_results(None, election_id=1)

    # Confirm requests hit results.sos.ga.gov, not app.enhancedvoting.com
    calls = [c.args[0] for c in mock_get.call_args_list]
    assert all("results.sos.ga.gov" in url for url in calls)
    assert any("11032026General/data" in url for url in calls)

    assert result.mapping_confidence == "full"
    assert len(result.rows) == 2
    assert result.rows[0].result_type == "unofficial"


def test_fetch_results_version_unchanged():
    adapter = GeorgiaAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "11032026General"}
    mock_election.pk = 1

    meta_payload = {"asOf": "2026-11-03T23:00:00Z", "isOfficialResults": False}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.enhanced_voting.requests.get") as mock_get, \
         patch("results.adapters.enhanced_voting.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = "2026-11-03T23:00:00Z"  # unchanged

        meta_resp = MagicMock()
        meta_resp.json.return_value = meta_payload
        mock_get.return_value = meta_resp

        result = adapter.fetch_results(None, election_id=1)

    assert result.unchanged is True
    assert mock_get.call_count == 1  # /data not fetched
