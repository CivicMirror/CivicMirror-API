"""
Unit tests for wa_votewa Celery tasks.
Django ORM + Celery are mocked — no DB required.
"""
from datetime import date as _date
from unittest.mock import MagicMock, patch

import pytest

from integrations.wa_votewa.tasks import sync_wa_elections, sync_wa_races


# ---------------------------------------------------------------------------
# sync_wa_elections
# ---------------------------------------------------------------------------

def test_sync_wa_elections_skips_on_404():
    """When every slug returns a 404 (WaVoteWaError), no elections are created."""
    from integrations.wa_votewa.exceptions import WaVoteWaError

    with patch("integrations.wa_votewa.tasks.WaVoteWaClient") as MockClient, \
         patch("integrations.wa_votewa.tasks.SyncLog") as MockLog:

        client = MockClient.return_value
        client.get_election_metadata.side_effect = WaVoteWaError("404")

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log
        MockLog.Status.STARTED = "started"
        MockLog.Status.COMPLETED = "completed"
        MockLog.Status.FAILED = "failed"

        result = sync_wa_elections()

    assert result["created"] == 0
    assert result["skipped"] > 0


def test_sync_wa_elections_dispatches_subtasks():
    """Valid slug → ingest_election called, subtask queued."""
    mock_election_obj = MagicMock()
    mock_election_obj.pk = 42
    mock_election_obj.source_metadata = {}

    with patch("integrations.wa_votewa.tasks.WaVoteWaClient") as MockClient, \
         patch("integrations.wa_votewa.tasks.SyncLog") as MockLog, \
         patch("integrations.wa_votewa.tasks.sync_wa_races") as mock_subtask, \
         patch("aggregation.ingest.ingest_election", return_value=(mock_election_obj, True)):

        client = MockClient.return_value
        from integrations.wa_votewa.exceptions import WaVoteWaError
        client.get_election_metadata.side_effect = [
            {"electionDate": "2026-04-28", "isOfficialResults": True},
            WaVoteWaError("404"),
            WaVoteWaError("404"),
            WaVoteWaError("404"),
        ]

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log
        MockLog.Status.STARTED = "started"
        MockLog.Status.COMPLETED = "completed"
        MockLog.Status.FAILED = "failed"

        result = sync_wa_elections()

    mock_subtask.apply_async.assert_called_once()
    assert result["created"] == 1
    assert result["skipped"] == 3


# ---------------------------------------------------------------------------
# sync_wa_races
# ---------------------------------------------------------------------------

def _make_ballot_item(contest_type="BallotMeasure", name_text="Prop 1", item_id="bi-001"):
    return {
        "id": item_id,
        "contestType": contest_type,
        "name": [{"languageId": "en", "text": name_text}],
        "summaryResults": {
            "ballotOptions": [
                {
                    "name": [{"languageId": "en", "text": "Yes"}],
                    "nativeId": "opt-yes",
                    "voteCount": 100,
                    "votePercent": 60.0,
                }
            ]
        },
    }


def test_sync_wa_races_no_ballot_items():
    """Empty ballotItems → task completes with zero races."""
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.source_id = "wa_votewa:20260428"

    with patch("integrations.wa_votewa.tasks.Election") as MockElection, \
         patch("integrations.wa_votewa.tasks.WaVoteWaClient") as MockClient, \
         patch("integrations.wa_votewa.tasks.SyncLog") as MockLog:

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception

        client = MockClient.return_value
        client.get_election_data.return_value = {"ballotItems": []}

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log
        MockLog.Status.STARTED = "started"
        MockLog.Status.COMPLETED = "completed"
        MockLog.Status.FAILED = "failed"

        result = sync_wa_races(1, "20260428")

    assert result == {"races": 0, "candidates": 0}


def test_sync_wa_races_measure_item():
    """A BallotMeasure ballot item → ingest_race called with race_type=measure."""
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.source_id = "wa_votewa:20260428"
    mock_election.status = "results_pending"
    mock_election.source_metadata = {"enr_slug": "20260428"}

    mock_race = MagicMock()
    mock_race.pk = 10

    with patch("integrations.wa_votewa.tasks.Election") as MockElection, \
         patch("integrations.wa_votewa.tasks.WaVoteWaClient") as MockClient, \
         patch("integrations.wa_votewa.tasks.SyncLog") as MockLog, \
         patch("integrations.wa_votewa.tasks.MeasureOption") as MockMO, \
         patch("aggregation.ingest.ingest_race", return_value=(mock_race, True)) as mock_ir, \
         patch("integrations.wa_votewa.tasks._sync_pdc"):

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception
        MockElection.Status.UPCOMING = "upcoming"
        MockElection.Status.ACTIVE = "active"

        client = MockClient.return_value
        client.get_election_data.return_value = {
            "ballotItems": [_make_ballot_item("BallotMeasure", "Prop 1")]
        }

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log
        MockLog.Status.STARTED = "started"
        MockLog.Status.COMPLETED = "completed"
        MockLog.Status.FAILED = "failed"

        result = sync_wa_races(1, "20260428")

    mock_ir.assert_called_once()
    call_kwargs = mock_ir.call_args[1]
    assert call_kwargs["identity"]["race_type"] == "measure"
    assert result["races"]["created"] == 1


def test_sync_wa_races_candidate_item():
    """A Candidate ballot item → ingest_race + ingest_candidate called."""
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.source_id = "wa_votewa:20260428"
    mock_election.status = "results_pending"
    mock_election.source_metadata = {"enr_slug": "20260428"}

    mock_race = MagicMock()
    mock_cand = MagicMock()

    ballot_item = {
        "id": "bi-cand-001",
        "contestType": "Candidate",
        "name": [{"languageId": "en", "text": "State Senator"}],
        "summaryResults": {
            "ballotOptions": [
                {
                    "name": [{"languageId": "en", "text": "Alice Smith"}],
                    "nativeId": "opt-alice",
                    "isWriteIn": False,
                    "party": {"abbreviation": "D", "name": "Democratic"},
                }
            ]
        },
    }

    with patch("integrations.wa_votewa.tasks.Election") as MockElection, \
         patch("integrations.wa_votewa.tasks.WaVoteWaClient") as MockClient, \
         patch("integrations.wa_votewa.tasks.SyncLog") as MockLog, \
         patch("aggregation.ingest.ingest_race", return_value=(mock_race, True)), \
         patch("aggregation.ingest.ingest_candidate", return_value=(mock_cand, True)) as mock_ic, \
         patch("integrations.wa_votewa.tasks._sync_pdc"):

        MockElection.objects.get.return_value = mock_election
        MockElection.DoesNotExist = Exception
        MockElection.Status.UPCOMING = "upcoming"
        MockElection.Status.ACTIVE = "active"

        client = MockClient.return_value
        client.get_election_data.return_value = {"ballotItems": [ballot_item]}

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log
        MockLog.Status.STARTED = "started"
        MockLog.Status.COMPLETED = "completed"
        MockLog.Status.FAILED = "failed"

        result = sync_wa_races(1, "20260428")

    mock_ic.assert_called_once()
    call_kwargs = mock_ic.call_args[1]
    assert call_kwargs["name"] == "Alice Smith"
    assert result["candidates"]["created"] == 1
