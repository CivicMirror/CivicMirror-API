"""
Unit tests for the Washington results adapter.
HTTP calls are fully mocked — no network required.
"""
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.base import AdapterResult
from results.adapters.wa import WashingtonAdapter


def test_wa_adapter_registered():
    import results.adapters.wa  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "WA" in list_supported_states()
    assert get_adapter("WA") is WashingtonAdapter
    assert get_adapter("wa") is WashingtonAdapter


def test_fetch_results_no_slug():
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "wa_elect_test"
    mock_election.source_metadata = {}  # no enr_slug

    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results(None, election_id=99)

    assert isinstance(result, AdapterResult)
    assert result.mapping_confidence == "none"
    assert result.rows == []
    assert "enr_slug" in result.notes


def test_fetch_results_version_unchanged():
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "2026-April-Special"}
    mock_election.pk = 2

    meta_payload = {"asOf": "2026-04-29T18:15:08Z", "isOfficialResults": True}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.enhanced_voting.requests.get") as mock_get, \
         patch("results.adapters.enhanced_voting.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = "2026-04-29T18:15:08Z"  # same as asOf → unchanged

        meta_resp = MagicMock()
        meta_resp.json.return_value = meta_payload
        mock_get.return_value = meta_resp

        result = adapter.fetch_results(None, election_id=2)

    assert result.unchanged is True
    assert result.source_version == "2026-04-29T18:15:08Z"
    assert result.rows == []
    assert mock_get.call_count == 1


def test_fetch_results_candidate_data():
    adapter = WashingtonAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "2026-April-Special"}
    mock_election.pk = 2

    meta_payload = {"asOf": "2026-04-29T18:15:08Z", "isOfficialResults": True}
    data_payload = {
        "ballotItems": [
            {
                "id": "wa-item-001",
                "contestType": "Candidate",
                "name": [{"languageId": "en", "text": "State Senator"}],
                "summaryResults": {
                    "ballotOptions": [
                        {
                            "name": [{"languageId": "en", "text": "Alice Smith"}],
                            "voteCount": 12000,
                            "votePercent": 55.0,
                            "isWinner": True,
                            "isWriteIn": False,
                            "nativeId": "wa-opt-1",
                            "party": {"abbreviation": "D", "name": "Democratic"},
                        },
                        {
                            "name": [{"languageId": "en", "text": "Bob Jones"}],
                            "voteCount": 9800,
                            "votePercent": 45.0,
                            "isWinner": False,
                            "isWriteIn": False,
                            "nativeId": "wa-opt-2",
                            "party": {"abbreviation": "R", "name": "Republican"},
                        },
                    ]
                },
            }
        ]
    }

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.enhanced_voting.requests.get") as mock_get, \
         patch("results.adapters.enhanced_voting.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = None  # version changed

        meta_resp = MagicMock()
        meta_resp.json.return_value = meta_payload
        data_resp = MagicMock()
        data_resp.json.return_value = data_payload
        mock_get.side_effect = [meta_resp, data_resp]

        result = adapter.fetch_results(None, election_id=2)

    assert result.mapping_confidence == "full"
    assert result.unchanged is False
    assert len(result.rows) == 2
    assert result.rows[0].candidate_name == "Alice Smith"
    assert result.rows[0].vote_count == 12000
    assert result.rows[0].is_winner is True
    assert result.rows[0].result_type == "official"
    assert result.source_version == "2026-04-29T18:15:08Z"
