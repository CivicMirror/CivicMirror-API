"""
Unit tests for the Utah results adapter.
Heavy parsing logic lives in EnhancedVotingAdapter and is tested via VA/GA
tests; these tests cover UT-specific configuration and real-world data shapes.
"""
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.enhanced_voting import _parse_ballot_items
from results.adapters.ut import UtahAdapter

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_ut_adapter_registered():
    import results.adapters.ut  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "UT" in list_supported_states()
    assert get_adapter("UT") is UtahAdapter
    assert get_adapter("ut") is UtahAdapter


def test_ut_adapter_base_url():
    assert UtahAdapter.base_url == "https://electionresults.utah.gov/results/public/api"
    assert UtahAdapter.state == "UT"
    assert UtahAdapter.state_name == "Utah"


# ---------------------------------------------------------------------------
# Real UT ballot item, captured live 2026-07-21 from Primary06232026
# (REP U.S. House District 2) — note no votePercent key: confirmed real,
# 0/27 ballot options across the live election had one.
# ---------------------------------------------------------------------------

_UT_BALLOT_ITEM = {
    "id": "01000000-b2af-048e-2bcd-08dec58ce469",
    "contestType": "Candidate",
    "name": [{"languageId": "en", "text": "REP U.S. House District 2"}],
    "summaryResults": {
        "ballotOptions": [
            {
                "name": [{"languageId": "en", "text": "BLAKE D. MOORE"}],
                "voteCount": 52673,
                "isWinner": None,
                "isWriteIn": False,
                "nativeId": "BLAKED.MOORE-1-Republican",
                "party": {"abbreviation": "REP"},
            },
            {
                "name": [{"languageId": "en", "text": "KARIANNE LISONBEE"}],
                "voteCount": 40271,
                "isWinner": None,
                "isWriteIn": False,
                "nativeId": "KARIANNELISONBEE-2-Republican",
                "party": {"abbreviation": "REP"},
            },
        ]
    },
}


def test_parse_ut_race_with_party_prefix_and_no_vote_percent():
    rows = _parse_ballot_items([_UT_BALLOT_ITEM], result_type="unofficial")

    assert len(rows) == 2
    # Office title preserved verbatim including party PREFIX (UT convention,
    # contrast with GA's party SUFFIX "Governor - Rep")
    assert rows[0].office_title == "REP U.S. House District 2"
    assert rows[0].candidate_name == "BLAKE D. MOORE"
    assert rows[0].vote_count == 52673
    assert rows[0].raw["party"] == "REP"
    assert rows[0].raw["native_id"] == "BLAKED.MOORE-1-Republican"
    # Utah never sends votePercent — must be None, not 0 or missing entirely
    assert rows[0].vote_pct is None
    assert rows[1].vote_pct is None
    # isWinner is None pre-certification, matching GA/VA/WA convention
    assert rows[0].is_winner is None


# ---------------------------------------------------------------------------
# fetch_results integration (mocked HTTP)
# ---------------------------------------------------------------------------


def test_fetch_results_no_slug():
    adapter = UtahAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {}

    with patch("elections.models.Election.objects") as mock_mgr:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results(None, election_id=99)

    assert result.mapping_confidence == "none"
    assert "enr_slug" in result.notes


def test_fetch_results_no_slug_does_not_guess_from_date():
    adapter = UtahAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.enhanced_voting.requests.get") as mock_get:
        mock_mgr.get.return_value = mock_election
        result = adapter.fetch_results("2026-06-23", election_id=99)

    assert result.mapping_confidence == "none"
    mock_get.assert_not_called()


def test_fetch_results_uses_ut_base_url():
    adapter = UtahAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "Primary06232026"}
    mock_election.pk = 1

    meta_payload = {"asOf": "2026-07-20T22:49:17.0406178Z", "isOfficialResults": False}
    data_payload = {"ballotItems": [_UT_BALLOT_ITEM]}

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

    # Confirm requests hit electionresults.utah.gov, not the shared
    # app.enhancedvoting.com domain or another state's self-hosted domain
    calls = [c.args[0] for c in mock_get.call_args_list]
    assert all("electionresults.utah.gov" in url for url in calls)
    assert any("Primary06232026/data" in url for url in calls)

    assert result.mapping_confidence == "full"
    assert len(result.rows) == 2
    assert result.rows[0].result_type == "unofficial"
    assert result.rows[0].vote_pct is None


def test_fetch_results_version_unchanged():
    adapter = UtahAdapter()
    mock_election = MagicMock()
    mock_election.source_metadata = {"enr_slug": "Primary06232026"}
    mock_election.pk = 1

    meta_payload = {"asOf": "2026-07-20T22:49:17.0406178Z", "isOfficialResults": False}

    with patch("elections.models.Election.objects") as mock_mgr, \
         patch("results.adapters.enhanced_voting.requests.get") as mock_get, \
         patch("results.adapters.enhanced_voting.cache") as mock_cache:

        mock_mgr.get.return_value = mock_election
        mock_cache.get.return_value = "2026-07-20T22:49:17.0406178Z"  # unchanged

        meta_resp = MagicMock()
        meta_resp.json.return_value = meta_payload
        mock_get.return_value = meta_resp

        result = adapter.fetch_results(None, election_id=1)

    assert result.unchanged is True
    assert mock_get.call_count == 1  # /data not fetched
