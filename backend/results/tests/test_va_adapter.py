"""
Unit tests for the Virginia results adapter.
HTTP calls are fully mocked — no network required.
"""
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.base import AdapterResult
from results.adapters.va import VirginiaAdapter, _get_text, _parse_ballot_items, _safe_float, _safe_int

# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

def test_safe_int_normal():
    assert _safe_int(1234) == 1234


def test_safe_int_none():
    assert _safe_int(None) == 0


def test_safe_int_invalid():
    assert _safe_int("abc") == 0


def test_safe_float_normal():
    assert _safe_float(52.3) == 52.3


def test_safe_float_none():
    assert _safe_float(None) is None


def test_safe_float_invalid():
    assert _safe_float("bad") is None


def test_get_text_english():
    names = [
        {"languageId": "en", "text": "Governor"},
        {"languageId": "1", "text": "Gobernador"},
    ]
    assert _get_text(names) == "Governor"


def test_get_text_fallback_first():
    names = [{"languageId": "es", "text": "Gobernador"}]
    assert _get_text(names) == "Gobernador"


def test_get_text_empty():
    assert _get_text([]) == ""


def test_get_text_missing_language():
    names = [{"languageId": "fr", "text": "Gouverneur"}]
    assert _get_text(names) == "Gouverneur"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_va_adapter_registered():
    import results.adapters.va  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "VA" in list_supported_states()
    assert get_adapter("VA") is VirginiaAdapter
    assert get_adapter("va") is VirginiaAdapter


# ---------------------------------------------------------------------------
# _parse_ballot_items
# ---------------------------------------------------------------------------

_CANDIDATE_BALLOT_ITEM = {
    "id": "item-001",
    "contestType": "Candidate",
    "name": [{"languageId": "en", "text": "Governor"}],
    "summaryResults": {
        "ballotOptions": [
            {
                "name": [{"languageId": "en", "text": "Jane Smith"}],
                "voteCount": 750000,
                "votePercent": 52.5,
                "isWinner": True,
                "isWriteIn": False,
                "nativeId": "cs1",
                "party": {"abbreviation": "D", "name": "Democratic"},
            },
            {
                "name": [{"languageId": "en", "text": "John Doe"}],
                "voteCount": 680000,
                "votePercent": 47.5,
                "isWinner": False,
                "isWriteIn": False,
                "nativeId": "cs2",
                "party": {"abbreviation": "R", "name": "Republican"},
            },
        ]
    },
}

_BALLOT_MEASURE_ITEM = {
    "id": "item-002",
    "contestType": "BallotMeasure",
    "name": [{"languageId": "en", "text": "Question 1: Redistricting Amendment"}],
    "summaryResults": {
        "ballotOptions": [
            {
                "name": [{"languageId": "en", "text": "Yes"}],
                "voteCount": 1604276,
                "votePercent": 51.7,
                "isWinner": None,
                "isWriteIn": False,
                "nativeId": "bms1",
                "party": None,
            },
            {
                "name": [{"languageId": "en", "text": "No"}],
                "voteCount": 1499393,
                "votePercent": 48.3,
                "isWinner": None,
                "isWriteIn": False,
                "nativeId": "bms2",
                "party": None,
            },
        ]
    },
}


def test_parse_candidate_contest():
    rows = _parse_ballot_items([_CANDIDATE_BALLOT_ITEM], result_type="unofficial")
    assert len(rows) == 2

    winner = rows[0]
    assert winner.candidate_name == "Jane Smith"
    assert winner.option_label is None
    assert winner.vote_count == 750000
    assert winner.vote_pct == 52.5
    assert winner.is_winner is True
    assert winner.result_type == "unofficial"
    assert winner.office_title == "Governor"
    assert winner.is_write_in_aggregate is False
    assert winner.raw["party"] == "D"
    assert winner.raw["native_id"] == "cs1"

    loser = rows[1]
    assert loser.candidate_name == "John Doe"
    assert loser.is_winner is False
    assert loser.raw["party"] == "R"


def test_parse_ballot_measure_contest():
    rows = _parse_ballot_items([_BALLOT_MEASURE_ITEM], result_type="official")
    assert len(rows) == 2

    yes_row = rows[0]
    assert yes_row.candidate_name is None
    assert yes_row.option_label == "Yes"
    assert yes_row.vote_count == 1604276
    assert yes_row.is_winner is None  # ballot measures have no winner flag
    assert yes_row.result_type == "official"
    assert yes_row.office_title == "Question 1: Redistricting Amendment"

    no_row = rows[1]
    assert no_row.option_label == "No"
    assert no_row.vote_count == 1499393


def test_parse_write_in_flagged():
    item = {
        "id": "item-003",
        "contestType": "Candidate",
        "name": [{"languageId": "en", "text": "Attorney General"}],
        "summaryResults": {
            "ballotOptions": [
                {
                    "name": [{"languageId": "en", "text": "Write-In"}],
                    "voteCount": 500,
                    "votePercent": 0.1,
                    "isWinner": False,
                    "isWriteIn": True,
                    "nativeId": "wi-cc1",
                    "party": None,
                }
            ]
        },
    }
    rows = _parse_ballot_items([item], result_type="unofficial")
    assert rows[0].is_write_in_aggregate is True


def test_parse_missing_summary_results():
    item = {
        "id": "item-004",
        "contestType": "Candidate",
        "name": [{"languageId": "en", "text": "Lt. Governor"}],
        "summaryResults": None,
    }
    rows = _parse_ballot_items([item], result_type="unofficial")
    assert rows == []


# ---------------------------------------------------------------------------
# VirginiaAdapter.fetch_results
# ---------------------------------------------------------------------------

def test_fetch_results_no_slug():
    adapter = VirginiaAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "va_elect_test"
    mock_election.source_metadata = {}  # no enr_slug

    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results(None, election_id=99)

    assert isinstance(result, AdapterResult)
    assert result.mapping_confidence == "none"
    assert result.rows == []
    assert "enr_slug" in result.notes


def test_fetch_results_version_unchanged():
    adapter = VirginiaAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "2025-November-General"}
    mock_election.pk = 1

    meta_payload = {"asOf": "2025-12-01T18:15:08Z", "isOfficialResults": True}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.enhanced_voting.requests.get") as mock_get, \
         patch("results.adapters.enhanced_voting.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = "2025-12-01T18:15:08Z"  # same as asOf → unchanged

        meta_resp = MagicMock()
        meta_resp.json.return_value = meta_payload
        mock_get.return_value = meta_resp

        result = adapter.fetch_results(None, election_id=1)

    assert result.unchanged is True
    assert result.source_version == "2025-12-01T18:15:08Z"
    assert result.rows == []
    # Full /data endpoint must NOT be called when unchanged
    assert mock_get.call_count == 1


def test_fetch_results_candidate_data():
    adapter = VirginiaAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "2025-November-General"}
    mock_election.pk = 1

    meta_payload = {"asOf": "2025-12-01T18:15:08Z", "isOfficialResults": True}
    data_payload = {"ballotItems": [_CANDIDATE_BALLOT_ITEM]}

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

        result = adapter.fetch_results(None, election_id=1)

    assert result.mapping_confidence == "full"
    assert result.unchanged is False
    assert len(result.rows) == 2
    assert result.rows[0].result_type == "official"
    assert result.source_version == "2025-12-01T18:15:08Z"
