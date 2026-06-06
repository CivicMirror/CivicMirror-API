"""
Tests for results/adapters/ny.py — NewYorkAdapter unit tests.
All HTTP, Playwright, and DB calls are mocked. No real network or DB required.
"""
from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Adapter registration
# ---------------------------------------------------------------------------


def test_new_york_adapter_registered():
    from results.adapters.registry import get_adapter

    adapter = get_adapter("NY")
    assert adapter is not None
    assert adapter.state == "NY"


# ---------------------------------------------------------------------------
# fetch_results — missing election
# ---------------------------------------------------------------------------


@patch("results.adapters.ny.sync_playwright")
def test_fetch_results_missing_election(mock_sync_playwright):
    from elections.models import Election as RealElection
    from results.adapters.ny import NewYorkAdapter

    adapter = NewYorkAdapter()

    with patch("results.adapters.ny.Election") as mock_election_cls:
        mock_election_cls.DoesNotExist = RealElection.DoesNotExist
        mock_election_cls.objects.get.side_effect = RealElection.DoesNotExist()
        result = adapter.fetch_results(None, 99999)

    assert result.mapping_confidence == "none"
    assert result.rows == []


# ---------------------------------------------------------------------------
# fetch_results — no election_name in metadata
# ---------------------------------------------------------------------------


@patch("results.adapters.ny.sync_playwright")
def test_fetch_results_no_election_name(mock_sync_playwright):
    from results.adapters.ny import NewYorkAdapter

    adapter = NewYorkAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "ny_sos_999"
    mock_election.source_metadata = {}

    with patch("results.adapters.ny.Election") as mock_election_cls:
        mock_election_cls.objects.get.return_value = mock_election
        result = adapter.fetch_results(None, 1)

    assert result.mapping_confidence == "none"
    mock_sync_playwright.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_results — success & cache miss
# ---------------------------------------------------------------------------


MOCK_FLATEAU_DATA = [
    {
        "candidateName": "John Doe",
        "candidateParty": "Democratic",
        "voteTotal": "1,234",
        "outcome": "Win",
        "contestJurisdiction": "Albany",
        "precinct": "Precinct 1",
        "office": "Governor",
    },
    {
        "candidateName": "Jane Smith",
        "candidateParty": "Republican",
        "voteTotal": "987",
        "outcome": "Lose",
        "contestJurisdiction": "Albany",
        "precinct": "Precinct 1",
        "office": "Governor",
    },
    {
        "candidateName": "Write-In",
        "candidateParty": "",
        "voteTotal": "12",
        "outcome": "Lose",
        "contestJurisdiction": "Albany",
        "precinct": "Precinct 1",
        "office": "Governor",
    },
    {
        "propositionBudgetName": "Prop 1",
        "shortDescription": "School Budget",
        "voteTotal": "500",
        "outcome": "Pass",
        "contestJurisdiction": "Albany",
        "precinct": "Precinct 1",
        "office": "Proposition",
    },
]


@patch("results.adapters.ny.cache")
@patch("results.adapters.ny.sync_playwright")
def test_fetch_results_success_on_cache_miss(mock_sync_playwright, mock_cache):
    from results.adapters.ny import NewYorkAdapter

    # Setup Playwright mocks
    mock_p = mock_sync_playwright.return_value.__enter__.return_value
    mock_browser = mock_p.chromium.launch.return_value
    mock_context = mock_browser.new_context.return_value
    mock_page = mock_context.new_page.return_value
    mock_page.evaluate.return_value = MOCK_FLATEAU_DATA

    mock_cache.get.return_value = None  # Cache miss

    adapter = NewYorkAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "ny_sos_2026"
    mock_election.source_metadata = {"election_name": "2026 Primary Election"}

    with patch("results.adapters.ny.Election") as mock_election_cls:
        mock_election_cls.objects.get.return_value = mock_election
        result = adapter.fetch_results(None, 1)

    assert result.unchanged is False
    assert result.mapping_confidence == "full"
    assert len(result.rows) == 4

    # Verify rows mapping
    doe_row = [r for r in result.rows if r.candidate_name == "John Doe"][0]
    assert doe_row.candidate_name == "John Doe"
    assert doe_row.vote_count == 1234
    assert doe_row.is_winner is True
    assert doe_row.jurisdiction_fragment == "Albany - Precinct 1"
    assert doe_row.office_title == "Governor"
    assert doe_row.is_write_in_aggregate is False

    writein_row = [r for r in result.rows if r.is_write_in_aggregate][0]
    assert writein_row.candidate_name is None
    assert writein_row.option_label == "Write-In"
    assert writein_row.vote_count == 12

    prop_row = [r for r in result.rows if r.option_label == "Prop 1"][0]
    assert prop_row.candidate_name is None
    assert prop_row.is_winner is True
    assert prop_row.vote_count == 500


# ---------------------------------------------------------------------------
# fetch_results — success & cache hit (unchanged)
# ---------------------------------------------------------------------------


@patch("results.adapters.ny.cache")
@patch("results.adapters.ny.sync_playwright")
def test_fetch_results_unchanged_on_cache_hit(mock_sync_playwright, mock_cache):
    from results.adapters.ny import NewYorkAdapter

    # Setup Playwright mocks
    mock_p = mock_sync_playwright.return_value.__enter__.return_value
    mock_browser = mock_p.chromium.launch.return_value
    mock_context = mock_browser.new_context.return_value
    mock_page = mock_context.new_page.return_value
    mock_page.evaluate.return_value = MOCK_FLATEAU_DATA

    expected_hash = hashlib.sha256(
        json.dumps(MOCK_FLATEAU_DATA, sort_keys=True).encode("utf-8")
    ).hexdigest()
    mock_cache.get.return_value = expected_hash  # Cache hit

    adapter = NewYorkAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "ny_sos_2026"
    mock_election.source_metadata = {"election_name": "2026 Primary Election"}

    with patch("results.adapters.ny.Election") as mock_election_cls:
        mock_election_cls.objects.get.return_value = mock_election
        result = adapter.fetch_results(None, 1)

    assert result.unchanged is True
    assert result.source_version == expected_hash
    assert result.rows == []


# ---------------------------------------------------------------------------
# fetch_results — failure
# ---------------------------------------------------------------------------


@patch("results.adapters.ny.sync_playwright")
def test_fetch_results_failure_exception(mock_sync_playwright):
    from results.adapters.ny import NewYorkAdapter

    mock_sync_playwright.side_effect = RuntimeError("Playwright crashed")

    adapter = NewYorkAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "ny_sos_2026"
    mock_election.source_metadata = {"election_name": "2026 Primary Election"}

    with patch("results.adapters.ny.Election") as mock_election_cls:
        mock_election_cls.objects.get.return_value = mock_election
        result = adapter.fetch_results(None, 1)

    assert result.mapping_confidence == "none"
    assert "Playwright crashed" in result.notes
    assert result.rows == []
