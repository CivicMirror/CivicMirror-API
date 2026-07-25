"""
Tests for results/adapters/ma.py — MassachusettsAdapter unit tests.
All HTTP and DB calls are mocked. No real network or DB required.
"""
import hashlib
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Adapter registration
# ---------------------------------------------------------------------------

def test_massachusetts_adapter_registered():
    from results.adapters.registry import get_adapter
    adapter = get_adapter("MA")
    assert adapter is not None
    assert adapter.state == "MA"


# ---------------------------------------------------------------------------
# fetch_results — missing election
# ---------------------------------------------------------------------------

@patch("results.adapters.ma.requests.get")
def test_fetch_results_missing_election(mock_get):
    from elections.models import Election as RealElection
    from results.adapters.ma import MassachusettsAdapter

    adapter = MassachusettsAdapter()

    with patch("results.adapters.ma.Election") as mock_election_cls:
        mock_election_cls.DoesNotExist = RealElection.DoesNotExist
        mock_election_cls.objects.get.side_effect = RealElection.DoesNotExist()
        result = adapter.fetch_results(None, 99999)

    assert result.mapping_confidence == "none"
    assert result.rows == []


# ---------------------------------------------------------------------------
# fetch_results — no electionstats_id in metadata
# ---------------------------------------------------------------------------

@patch("results.adapters.ma.Race")
@patch("results.adapters.ma.requests.get")
def test_fetch_results_no_electionstats_id(mock_get, mock_race_cls):
    from results.adapters.ma import MassachusettsAdapter

    mock_race_cls.objects.filter.return_value = []

    adapter = MassachusettsAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "ma_sos_999"
    mock_election.source_metadata = {}

    with patch("results.adapters.ma.Election") as mock_election_cls:
        mock_election_cls.objects.get.return_value = mock_election
        result = adapter.fetch_results(None, 1)

    assert result.mapping_confidence == "none"
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_results — cache hit (unchanged)
# ---------------------------------------------------------------------------

CSV_BYTES = (
    b'City/Town,,,"Candidate A","Candidate B","All Others","Blanks","Total Votes Cast"\r\n'
    b',,,Democratic,Republican,,,\r\n'
    b'Abington,,,"4,714","4,639",4,27,"9,499"\r\n'
    b'TOTALS,,,"4,714","4,639",4,27,"9,499"\r\n'
)


@patch("results.adapters.ma.Race")
@patch("results.adapters.ma.cache")
@patch("results.adapters.ma.requests.get")
def test_fetch_results_unchanged_on_cache_hit(mock_get, mock_cache, mock_race_cls):
    from results.adapters.ma import MassachusettsAdapter

    csv_hash = hashlib.sha256(CSV_BYTES).hexdigest()

    mock_resp = MagicMock()
    mock_resp.content = CSV_BYTES
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    mock_cache.get.return_value = csv_hash  # Cache hit
    mock_race_cls.objects.filter.return_value = []

    adapter = MassachusettsAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "ma_sos_165300"
    mock_election.source_metadata = {"electionstats_id": 165300}

    with patch("results.adapters.ma.Election") as mock_election_cls:
        mock_election_cls.objects.get.return_value = mock_election
        result = adapter.fetch_results(None, 1)

    assert result.unchanged is True
    assert result.source_version == csv_hash
    assert result.rows == []


# ---------------------------------------------------------------------------
# fetch_results — cache miss (returns rows)
# ---------------------------------------------------------------------------

@patch("results.adapters.ma.Race")
@patch("results.adapters.ma.cache")
@patch("results.adapters.ma.requests.get")
def test_fetch_results_parses_csv_on_cache_miss(mock_get, mock_cache, mock_race_cls):
    from results.adapters.ma import MassachusettsAdapter

    mock_resp = MagicMock()
    mock_resp.content = CSV_BYTES
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    mock_cache.get.return_value = None  # Cache miss
    mock_race_cls.objects.filter.return_value = []

    adapter = MassachusettsAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "ma_sos_165300"
    mock_election.source_metadata = {"electionstats_id": 165300}

    with patch("results.adapters.ma.Election") as mock_election_cls:
        mock_election_cls.objects.get.return_value = mock_election
        result = adapter.fetch_results(None, 1)

    assert result.unchanged is False
    assert len(result.rows) > 0
    assert result.mapping_confidence == "full"
    assert all(r.raw.get("contest_code") == "165300" for r in result.rows)
    # Cache should be set with new hash
    mock_cache.set.assert_called_once()


# ---------------------------------------------------------------------------
# fetch_results — HTTP error
# ---------------------------------------------------------------------------

@patch("results.adapters.ma.Race")
@patch("results.adapters.ma.requests.get")
def test_fetch_results_http_error(mock_get, mock_race_cls):
    import requests as req_lib

    from results.adapters.ma import MassachusettsAdapter

    mock_get.side_effect = req_lib.RequestException("network error")
    mock_race_cls.objects.filter.return_value = []

    adapter = MassachusettsAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "ma_sos_165300"
    mock_election.source_metadata = {"electionstats_id": 165300}

    with patch("results.adapters.ma.Election") as mock_election_cls:
        mock_election_cls.objects.get.return_value = mock_election
        result = adapter.fetch_results(None, 1)

    assert result.mapping_confidence == "none"
    assert "network error" in result.notes


# ---------------------------------------------------------------------------
# fetch_results — split primary (multiple Races, distinct electionstats_ids)
# ---------------------------------------------------------------------------

DEM_CSV_BYTES = (
    b'City/Town,,,"Andrew Tarr","All Others","Blanks","Total Votes Cast"\r\n'
    b',,,Democratic,,,\r\n'
    b'Boston,,,"2,194",30,23,"2,247"\r\n'
    b'TOTALS,,,"2,194",30,23,"2,247"\r\n'
)
REP_CSV_BYTES = (
    b'City/Town,,,"Christina Delisio","All Others","Blanks","Total Votes Cast"\r\n'
    b',,,Republican,,,\r\n'
    b'Boston,,,"568",37,6,"611"\r\n'
    b'TOTALS,,,"568",37,6,"611"\r\n'
)


@patch("results.adapters.ma.Race")
@patch("results.adapters.ma.cache")
@patch("results.adapters.ma.requests.get")
def test_fetch_results_split_primary_fetches_each_party_csv(mock_get, mock_cache, mock_race_cls):
    from results.adapters.ma import MassachusettsAdapter

    mock_cache.get.return_value = None

    dem_race = MagicMock()
    dem_race.source_metadata = {"electionstats_id": 171921}
    rep_race = MagicMock()
    rep_race.source_metadata = {"electionstats_id": 171922}
    mock_race_cls.objects.filter.return_value = [dem_race, rep_race]

    dem_resp = MagicMock(content=DEM_CSV_BYTES)
    dem_resp.raise_for_status = MagicMock()
    rep_resp = MagicMock(content=REP_CSV_BYTES)
    rep_resp.raise_for_status = MagicMock()
    mock_get.side_effect = [dem_resp, rep_resp]

    adapter = MassachusettsAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "ma_sos_171920"
    mock_election.source_metadata = {"electionstats_id": 171921}

    with patch("results.adapters.ma.Election") as mock_election_cls:
        mock_election_cls.objects.get.return_value = mock_election
        result = adapter.fetch_results(None, 1)

    assert mock_get.call_count == 2
    assert result.mapping_confidence == "full"

    dem_rows = [r for r in result.rows if r.raw.get("contest_code") == "171921"]
    rep_rows = [r for r in result.rows if r.raw.get("contest_code") == "171922"]
    assert dem_rows and rep_rows
    assert any(r.candidate_name == "Andrew Tarr" for r in dem_rows)
    assert any(r.candidate_name == "Christina Delisio" for r in rep_rows)
    assert not any(r.candidate_name == "Christina Delisio" for r in dem_rows)
    assert not any(r.candidate_name == "Andrew Tarr" for r in rep_rows)


@patch("results.adapters.ma.Race")
@patch("results.adapters.ma.cache")
@patch("results.adapters.ma.requests.get")
def test_fetch_results_split_primary_unchanged_on_cache_hit(mock_get, mock_cache, mock_race_cls):
    from results.adapters.ma import MassachusettsAdapter

    combined_hash = hashlib.sha256(DEM_CSV_BYTES + REP_CSV_BYTES).hexdigest()
    mock_cache.get.return_value = combined_hash

    dem_race = MagicMock()
    dem_race.source_metadata = {"electionstats_id": 171921}
    rep_race = MagicMock()
    rep_race.source_metadata = {"electionstats_id": 171922}
    mock_race_cls.objects.filter.return_value = [dem_race, rep_race]

    dem_resp = MagicMock(content=DEM_CSV_BYTES)
    dem_resp.raise_for_status = MagicMock()
    rep_resp = MagicMock(content=REP_CSV_BYTES)
    rep_resp.raise_for_status = MagicMock()
    mock_get.side_effect = [dem_resp, rep_resp]

    adapter = MassachusettsAdapter()
    mock_election = MagicMock()
    mock_election.source_id = "ma_sos_171920"
    mock_election.source_metadata = {"electionstats_id": 171921}

    with patch("results.adapters.ma.Election") as mock_election_cls:
        mock_election_cls.objects.get.return_value = mock_election
        result = adapter.fetch_results(None, 1)

    assert result.unchanged is True
    assert result.rows == []


# ---------------------------------------------------------------------------
# _parse_election_csv — ResultRow structure
# ---------------------------------------------------------------------------

def test_parse_election_csv_rows_structure():
    from results.adapters.ma import _parse_election_csv

    rows = _parse_election_csv(CSV_BYTES, "http://test.url/")

    # Should have rows for real candidates + tally labels per town + TOTALS
    candidate_rows = [r for r in rows if r.candidate_name is not None]
    assert len(candidate_rows) > 0

    # Verify a candidate row has expected fields
    sample = candidate_rows[0]
    assert sample.result_type == "official"
    assert sample.vote_count >= 0
    assert sample.jurisdiction_fragment is not None


def test_parse_election_csv_write_in_aggregate():
    from results.adapters.ma import _parse_election_csv

    rows = _parse_election_csv(CSV_BYTES, "http://test.url/")
    tally_rows = [r for r in rows if r.option_label == "All Others"]
    assert len(tally_rows) > 0
    assert all(r.is_write_in_aggregate for r in tally_rows)


def test_parse_election_csv_totals_jurisdiction():
    from results.adapters.ma import _parse_election_csv

    rows = _parse_election_csv(CSV_BYTES, "http://test.url/")
    totals_rows = [r for r in rows if r.jurisdiction_fragment == "STATEWIDE"]
    assert len(totals_rows) > 0


def test_parse_election_csv_empty():
    from results.adapters.ma import _parse_election_csv

    rows = _parse_election_csv(b"", "http://test.url/")
    assert rows == []
