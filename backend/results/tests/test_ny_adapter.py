"""
Tests for results/adapters/ny.py — NewYorkAdapter unit tests.
All HTTP, Playwright, and DB calls are mocked. No real network or DB required.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
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

ALBANY_PRIMARY_ROWS = [
    {
        "candidateName": "ALEX RIVERA",
        "candidateParty": "Democratic",
        "voteTotal": "100",
        "contestJurisdiction": "Congressional District 19",
        "office": "Representative in Congress",
        "district": "19",
    }
]

COLUMBIA_PRIMARY_ROWS = [
    {
        "candidateName": "ALEX RIVERA",
        "candidateParty": "Democratic",
        "voteTotal": "40",
        "contestJurisdiction": "Congressional District 19",
        "office": "Representative in Congress",
        "district": "19",
    },
    {
        "candidateName": "CASEY LEE",
        "candidateParty": "Republican",
        "voteTotal": "25",
        "contestJurisdiction": "Congressional District 19",
        "office": "Representative in Congress",
        "district": "19",
    },
]


def test_resolve_flateau_names_prefers_manual_override():
    from results.adapters.ny import resolve_flateau_election_names

    election = MagicMock()
    election.source_metadata = {
        "flateau_election_names": ["County B Primary", "County A Primary"],
        "election_name": "Legacy Primary",
    }

    assert resolve_flateau_election_names(election) == ["County A Primary", "County B Primary"]


def test_resolve_flateau_names_accepts_legacy_name():
    from results.adapters.ny import resolve_flateau_election_names

    election = MagicMock()
    election.source_metadata = {"election_name": "Legacy Primary"}

    assert resolve_flateau_election_names(election) == ["Legacy Primary"]


@patch("results.adapters.ny.cache")
def test_fetch_results_multiple_names_emits_identity_and_authority(mock_cache):
    from results.adapters.ny import NewYorkAdapter

    mock_cache.get.return_value = None
    adapter = NewYorkAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "ny_sos_2026_primary"
    mock_election.source_metadata = {
        "flateau_election_names": ["Albany County Board Primary", "Columbia County Board Primary"]
    }

    outcomes = [
        MagicMock(url="albany", ok=True, data=ALBANY_PRIMARY_ROWS, error=None),
        MagicMock(url="columbia", ok=True, data=COLUMBIA_PRIMARY_ROWS, error=None),
    ]

    with patch("results.adapters.ny.Election") as mock_election_cls, \
         patch.object(adapter, "_fetch_json_many", return_value=outcomes):
        mock_election_cls.objects.get.return_value = mock_election
        result = adapter.fetch_results(date(2026, 6, 23), 1907)

    assert result.mapping_confidence == "full"
    assert result.source_version
    assert len(result.rows) == 3
    identities = {(row.raw["contest_code"], row.raw["party_code"]) for row in result.rows}
    assert identities == {
        ("representative in congress|19|", "DEM"),
        ("representative in congress|19|", "REP"),
    }
    fragments = {row.jurisdiction_fragment for row in result.rows}
    assert fragments == {
        "albany county board primary - Congressional District 19",
        "columbia county board primary - Congressional District 19",
    }
    assert {row.raw["_flateau_election_name"] for row in result.rows} == {
        "Albany County Board Primary",
        "Columbia County Board Primary",
    }


@patch("results.adapters.ny.cache")
def test_fetch_results_partial_returns_empty_source_version(mock_cache):
    from results.adapters.ny import NewYorkAdapter

    mock_cache.get.return_value = "complete-hash"
    adapter = NewYorkAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "ny_sos_2026_primary"
    mock_election.source_metadata = {
        "flateau_election_names": ["Albany County Board Primary", "Columbia County Board Primary"]
    }

    outcomes = [
        MagicMock(url="albany", ok=True, data=ALBANY_PRIMARY_ROWS, error=None),
        MagicMock(url="columbia", ok=False, data=None, error="timeout"),
    ]

    with patch("results.adapters.ny.Election") as mock_election_cls, \
         patch.object(adapter, "_fetch_json_many", return_value=outcomes):
        mock_election_cls.objects.get.return_value = mock_election
        result = adapter.fetch_results(date(2026, 6, 23), 1907)

    assert result.mapping_confidence == "partial"
    assert result.unchanged is False
    assert result.source_version == ""
    assert len(result.rows) == 1
    assert "failed=1" in result.notes


@patch("results.adapters.ny.cache")
def test_fetch_results_hash_is_independent_of_name_order(mock_cache):
    from results.adapters.ny import NewYorkAdapter

    mock_cache.get.return_value = None
    adapter = NewYorkAdapter()

    first = adapter._source_version_for_payloads([
        ("Columbia County Board Primary", COLUMBIA_PRIMARY_ROWS),
        ("Albany County Board Primary", ALBANY_PRIMARY_ROWS),
    ])
    second = adapter._source_version_for_payloads([
        ("Albany County Board Primary", ALBANY_PRIMARY_ROWS),
        ("Columbia County Board Primary", COLUMBIA_PRIMARY_ROWS),
    ])

    assert first == second


def test_flateau_identity_matches_ny_boe_mapper_identity():
    from integrations.ny_boe.mappers import build_ny_source_identity
    from results.adapters.ny import _enrich_row

    contest = {
        "office": "Representative in Congress",
        "district": "19",
        "district2": "",
        "party": "Democratic",
    }
    flateau_row = {
        "office": "Representative in Congress",
        "district": "19",
        "candidateParty": "Democratic",
        "candidateName": "ALEX RIVERA",
        "voteTotal": "100",
    }

    stage1_identity = build_ny_source_identity(contest)
    enriched = _enrich_row(flateau_row, "Albany County Board Primary")

    assert enriched["contest_code"] == stage1_identity["contest_code"]
    assert enriched["party_code"] == stage1_identity["party_code"]


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
    assert doe_row.jurisdiction_fragment == "2026 primary election - Albany - Precinct 1"
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

    enriched = []
    for row in MOCK_FLATEAU_DATA:
        raw = dict(row)
        raw["_flateau_election_name"] = "2026 Primary Election"
        raw["_flateau_authority"] = "2026 primary election"
        raw["contest_code"] = f"{raw['office'].lower()}||"
        raw["party_code"] = {"Democratic": "DEM", "Republican": "REP", "": ""}[raw.get("candidateParty", "")]
        enriched.append(raw)
    expected_hash = hashlib.sha256(
        json.dumps(
            [{"election_name": "2026 Primary Election", "data": enriched}],
            sort_keys=True,
        ).encode("utf-8")
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
