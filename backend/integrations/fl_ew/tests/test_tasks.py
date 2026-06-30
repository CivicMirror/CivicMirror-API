"""
Unit tests for fl_ew Celery tasks. DB and Celery are mocked — no network.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from integrations.fl_ew.tasks import sync_fl_elections, sync_fl_races

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _mock_sync_log():
    log = MagicMock()
    log.Status = MagicMock()
    log.Status.STARTED = "started"
    log.Status.COMPLETED = "completed"
    log.Status.FAILED = "failed"
    return log


def _make_election_obj(pk=1, status="upcoming", election_type="primary"):
    e = MagicMock()
    e.pk = pk
    e.status = status
    e.election_type = election_type
    e.source_id = "fl_ew:20260818"
    e.canonical_key = "fl:primary:2026-08-18:state"
    e.source_metadata = {"fl_ew_slug": "20260818"}
    return e


# ---------------------------------------------------------------------------
# sync_fl_elections
# ---------------------------------------------------------------------------

def test_sync_fl_elections_skips_404_slugs():
    """When file returns 404, no elections are created."""
    mock_log = _mock_sync_log()
    with patch("integrations.fl_ew.tasks.FlEwClient") as MockClient, \
         patch("integrations.fl_ew.tasks.SyncLog") as MockSyncLog:

        MockSyncLog.objects.create.return_value = mock_log
        MockSyncLog.Status.STARTED = "started"
        MockSyncLog.Status.COMPLETED = "completed"

        client = MockClient.return_value
        client.get_last_modified.return_value = ""  # 404 / file not found

        result = sync_fl_elections()

    assert result["created"] == 0
    assert result["skipped"] > 0


def test_sync_fl_elections_creates_election_and_queues_races():
    """Valid slug → election upserted, sync_fl_races queued."""
    mock_election = _make_election_obj()
    mock_log = _mock_sync_log()

    with patch("integrations.fl_ew.tasks.FlEwClient") as MockClient, \
         patch("integrations.fl_ew.tasks.SyncLog") as MockSyncLog, \
         patch("integrations.fl_ew.tasks.sync_fl_races") as mock_races, \
         patch("aggregation.ingest.ingest_election", return_value=(mock_election, True)):

        MockSyncLog.objects.create.return_value = mock_log
        MockSyncLog.Status.STARTED = "started"
        MockSyncLog.Status.COMPLETED = "completed"

        client = MockClient.return_value
        # First slug has a file, rest don't
        from integrations.fl_ew.client import KNOWN_ELECTION_SLUGS
        side_effects = ["Mon, 18 Aug 2026 01:00:00 GMT"] + [""] * (len(KNOWN_ELECTION_SLUGS) - 1)
        client.get_last_modified.side_effect = side_effects

        result = sync_fl_elections()

    mock_races.apply_async.assert_called_once()
    assert result["created"] == 1
    assert result["queued"] == 1


# ---------------------------------------------------------------------------
# sync_fl_races
# ---------------------------------------------------------------------------

_TSV = (
    "ElectionDate\tPartyCode\tPartyName\tRaceCode\tRaceName\tCountyCode\t"
    "CountyName\tJuris1num\tJuris2num\tPrecincts\tPrecinctsReporting\t"
    "CanNameLast\tCanNameFirst\tCanNameMiddle\tCanVotes\n"
    "08/18/2026\tREP\tRepublican Party\tSTS\tState Senator, District 14\t"
    "HIL\tHillsborough\t014\t\t152\t152\tSmith\tAlice\t\t39000\n"
    "08/18/2026\tDEM\tDemocratic Party\tSTS\tState Senator, District 14\t"
    "HIL\tHillsborough\t014\t\t152\t80\tJones\tBob\t\t41000\n"
)


def test_sync_fl_races_no_rows_returns_zero():
    """Empty file → task completes with zero races."""
    _EMPTY_TSV = "ElectionDate\tPartyCode\tPartyName\tRaceCode\tRaceName\tCountyCode\tCountyName\tJuris1num\tJuris2num\tPrecincts\tPrecinctsReporting\tCanNameLast\tCanNameFirst\tCanNameMiddle\tCanVotes\n"
    mock_election = _make_election_obj()
    mock_log = _mock_sync_log()

    with patch("integrations.fl_ew.tasks.Election") as MockElection, \
         patch("integrations.fl_ew.tasks.FlEwClient") as MockClient, \
         patch("integrations.fl_ew.tasks.SyncLog") as MockSyncLog:

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception
        MockSyncLog.objects.create.return_value = mock_log
        MockSyncLog.Status.STARTED = "started"
        MockSyncLog.Status.COMPLETED = "completed"

        client = MockClient.return_value
        client.fetch_results_file.return_value = _EMPTY_TSV

        result = sync_fl_races(1, "20260818")

    assert result == {"races": 0, "candidates": 0}


def test_sync_fl_races_general_election_creates_one_race_two_candidates():
    """General election: REP + DEM for same office → one race, two candidates."""
    mock_election = _make_election_obj(election_type="general")
    mock_race = MagicMock()
    mock_race.pk = 10
    mock_cand = MagicMock()
    mock_log = _mock_sync_log()

    with patch("integrations.fl_ew.tasks.Election") as MockElection, \
         patch("integrations.fl_ew.tasks.FlEwClient") as MockClient, \
         patch("integrations.fl_ew.tasks.SyncLog") as MockSyncLog, \
         patch("aggregation.ingest.ingest_race", return_value=(mock_race, True)) as mock_ir, \
         patch("aggregation.ingest.ingest_candidate", return_value=(mock_cand, True)) as mock_ic:

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception
        MockElection.Status.UPCOMING = "upcoming"
        MockElection.Status.ACTIVE = "active"
        MockSyncLog.objects.create.return_value = mock_log
        MockSyncLog.Status.STARTED = "started"
        MockSyncLog.Status.COMPLETED = "completed"

        client = MockClient.return_value
        client.fetch_results_file.return_value = _TSV

        result = sync_fl_races(1, "20260818")

    # One race (both parties merged in general), two candidates
    assert mock_ir.call_count == 1
    assert mock_ic.call_count == 2
    assert result["races"]["created"] == 1
    assert result["candidates"]["created"] == 2


def test_sync_fl_races_primary_creates_two_races():
    """Primary election: REP + DEM for same office → two separate races."""
    mock_election = _make_election_obj(election_type="primary")
    mock_race = MagicMock()
    mock_race.pk = 10
    mock_cand = MagicMock()
    mock_log = _mock_sync_log()

    with patch("integrations.fl_ew.tasks.Election") as MockElection, \
         patch("integrations.fl_ew.tasks.FlEwClient") as MockClient, \
         patch("integrations.fl_ew.tasks.SyncLog") as MockSyncLog, \
         patch("aggregation.ingest.ingest_race", return_value=(mock_race, True)) as mock_ir, \
         patch("aggregation.ingest.ingest_candidate", return_value=(mock_cand, True)) as mock_ic:

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception
        MockElection.Status.UPCOMING = "upcoming"
        MockElection.Status.ACTIVE = "active"
        MockSyncLog.objects.create.return_value = mock_log
        MockSyncLog.Status.STARTED = "started"
        MockSyncLog.Status.COMPLETED = "completed"

        client = MockClient.return_value
        client.fetch_results_file.return_value = _TSV

        result = sync_fl_races(1, "20260818")

    # Two races (one per party), one candidate each
    assert mock_ir.call_count == 2
    assert mock_ic.call_count == 2
    assert result["races"]["created"] == 2
