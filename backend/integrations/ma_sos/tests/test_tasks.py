"""
Tests for integrations.ma_sos.tasks — Celery task unit tests.
All DB and HTTP calls are mocked. No real DB or network required.
"""
from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# sync_ma_elections
# ---------------------------------------------------------------------------

@patch("integrations.ma_sos.tasks.SyncLog")
@patch("integrations.ma_sos.tasks.Election")
@patch("integrations.ma_sos.tasks.sync_ma_races")
@patch("integrations.ma_sos.tasks.sync_ma_ballot_question")
@patch("integrations.ma_sos.tasks.MaSosClient")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_elections_discovers_and_queues(
    mock_tz, mock_client_cls, mock_bq_task, mock_races_task,
    mock_election_cls, mock_synclog_cls,
):
    from integrations.ma_sos.tasks import sync_ma_elections

    # SyncLog setup
    mock_log = MagicMock()
    mock_synclog_cls.objects.create.return_value = mock_log
    mock_synclog_cls.Status.STARTED = "started"
    mock_synclog_cls.Status.COMPLETED = "completed"
    mock_synclog_cls.Status.COMPLETED_WITH_WARNINGS = "warnings"
    mock_synclog_cls.Status.FAILED = "failed"

    # Client returns 2 elections and 1 BQ
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.get_ocpf_schedule.return_value = {"generalElectionDate": "11/5/2024", "primaryElectionDate": "9/3/2024"}
    mock_client.get_election_ids.side_effect = [
        [{"election_id": 165300, "office": "President", "district": "", "stage": "General", "year": 2024}],
        [],  # Primaries current year
        [],  # General prior year
        [],  # Primaries prior year
    ]
    mock_client.get_ballot_question_ids.return_value = [11620]

    # Election model
    mock_qs = MagicMock()
    mock_qs.values_list.return_value = []
    mock_election_cls.objects.filter.return_value = mock_qs
    mock_election_cls.objects.bulk_create.return_value = []
    mock_saved_election = MagicMock()
    mock_saved_election.source_id = "ma_sos_165300"
    mock_saved_election.pk = 1
    mock_saved_election.source_metadata = {"electionstats_id": 165300}
    # Second call (reload after bulk_create) returns the list
    mock_election_cls.objects.filter.side_effect = [mock_qs, [mock_saved_election]]
    mock_election_cls.JurisdictionLevel.NATIONAL = "national"
    mock_election_cls.JurisdictionLevel.STATE = "state"
    mock_election_cls.JurisdictionLevel.LOCAL = "local"
    mock_election_cls.Status.UPCOMING = "upcoming"
    mock_election_cls.Status.ACTIVE = "active"
    mock_election_cls.Status.RESULTS_PENDING = "results_pending"

    mock_tz.now.return_value = MagicMock()
    mock_tz.localdate.return_value = date(2024, 12, 1)

    # Patch date.today()
    with patch("integrations.ma_sos.tasks.date") as mock_date:
        mock_date.today.return_value = date(2024, 12, 1)
        result = sync_ma_elections.run()

    # Task should have queued at least one races task and one BQ task
    mock_races_task.apply_async.assert_called()
    mock_bq_task.apply_async.assert_called()


@patch("integrations.ma_sos.tasks.SyncLog")
@patch("integrations.ma_sos.tasks.MaSosClient")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_elections_empty_returns_warning(mock_tz, mock_client_cls, mock_synclog_cls):
    from integrations.ma_sos.tasks import sync_ma_elections

    mock_log = MagicMock()
    mock_synclog_cls.objects.create.return_value = mock_log
    mock_synclog_cls.Status.STARTED = "started"
    mock_synclog_cls.Status.COMPLETED = "completed"
    mock_synclog_cls.Status.COMPLETED_WITH_WARNINGS = "warnings"

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.get_ocpf_schedule.return_value = {}
    mock_client.get_election_ids.return_value = []
    mock_client.get_ballot_question_ids.return_value = []

    mock_tz.now.return_value = MagicMock()

    with patch("integrations.ma_sos.tasks.date") as mock_date:
        mock_date.today.return_value = date(2024, 12, 1)
        result = sync_ma_elections.run()

    assert result["created"] == 0
    mock_log.save.assert_called()


# ---------------------------------------------------------------------------
# sync_ma_races
# ---------------------------------------------------------------------------

@patch("integrations.ma_sos.tasks.SyncLog")
@patch("integrations.ma_sos.tasks.Election")
@patch("integrations.ma_sos.tasks.Race")
@patch("integrations.ma_sos.tasks.Candidate")
@patch("integrations.ma_sos.tasks.transaction")
@patch("integrations.ma_sos.tasks.MaSosClient")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_races_upserts_race_and_candidates(
    mock_tz, mock_client_cls, mock_tx, mock_cand_cls,
    mock_race_cls, mock_election_cls, mock_synclog_cls,
):
    from integrations.ma_sos.tasks import sync_ma_races

    mock_log = MagicMock()
    mock_synclog_cls.objects.create.return_value = mock_log
    mock_synclog_cls.Status.STARTED = "started"
    mock_synclog_cls.Status.COMPLETED = "completed"

    mock_election = MagicMock()
    mock_election.source_id = "ma_sos_165323"
    mock_election.source_metadata = {"electionstats_id": 165323, "office": "U.S. House", "district": "1st Congressional", "stage": "General"}
    mock_election.name = "2024 MA U.S. House 1st Congressional General"
    mock_election.status = "results_pending"
    mock_election_cls.objects.get.return_value = mock_election
    mock_election_cls.Status.UPCOMING = "upcoming"
    mock_election_cls.Status.ACTIVE = "active"
    mock_election_cls.Status.RESULTS_PENDING = "results_pending"

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    csv_bytes = (
        b'City/Town,,,"Richard E. Neal","Opponent","All Others","Blanks","Total Votes Cast"\r\n'
        b',,,Democratic,Republican,,,\r\n'
        b'Abington,,,"1000","500",5,10,"1515"\r\n'
        b'TOTALS,,,"1000","500",5,10,"1515"\r\n'
    )
    mock_client.download_election_csv.return_value = csv_bytes

    # Race mock
    mock_race_cls.objects.filter.return_value.values_list.return_value = []
    mock_race_cls.objects.bulk_create.return_value = []
    mock_race_cls.CertificationStatus.UPCOMING = "upcoming"
    mock_race_cls.CertificationStatus.RESULTS_CERTIFIED = "results_certified"
    mock_race_cls.RaceType.CANDIDATE = "candidate"
    mock_race_cls.RaceType.MEASURE = "measure"
    mock_race_cls.Source.MA_SOS = "ma_sos"
    mock_race_cls.RaceStatus.ACTIVE = "active"
    mock_race_cls.VoteMethod.SINGLE_CHOICE = "single_choice"
    mock_race_cls.VoteMethod.YES_NO = "yes_no"

    mock_race_obj = MagicMock()
    mock_race_cls.objects.get.return_value = mock_race_obj

    # Candidate mock
    mock_cand_cls.objects.filter.return_value.values_list.return_value = []
    mock_cand_cls.CandidateStatus.RUNNING = "running"

    # transaction mock
    mock_tx.atomic.return_value.__enter__ = MagicMock(return_value=None)
    mock_tx.atomic.return_value.__exit__ = MagicMock(return_value=False)

    mock_tz.now.return_value = MagicMock()

    result = sync_ma_races.run(1)

    mock_race_cls.objects.bulk_create.assert_called_once()
    mock_cand_cls.objects.bulk_create.assert_called_once()


@patch("integrations.ma_sos.tasks.SyncLog")
@patch("integrations.ma_sos.tasks.Election")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_races_missing_election_returns(mock_tz, mock_election_cls, mock_synclog_cls):
    from integrations.ma_sos.tasks import sync_ma_races
    from elections.models import Election as RealElection

    mock_election_cls.DoesNotExist = RealElection.DoesNotExist
    mock_election_cls.objects.get.side_effect = RealElection.DoesNotExist()
    mock_tz.now.return_value = MagicMock()

    result = sync_ma_races.run(99999)
    assert result is None


# ---------------------------------------------------------------------------
# sync_ma_ballot_question
# ---------------------------------------------------------------------------

@patch("integrations.ma_sos.tasks.SyncLog")
@patch("integrations.ma_sos.tasks.Race")
@patch("integrations.ma_sos.tasks.MeasureOption")
@patch("integrations.ma_sos.tasks.transaction")
@patch("integrations.ma_sos.tasks.MaSosClient")
@patch("integrations.ma_sos.tasks._get_or_create_bq_election")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_ballot_question_upserts(
    mock_tz, mock_get_election, mock_client_cls, mock_tx,
    mock_measure_cls, mock_race_cls, mock_synclog_cls,
):
    from integrations.ma_sos.tasks import sync_ma_ballot_question

    mock_log = MagicMock()
    mock_synclog_cls.objects.create.return_value = mock_log
    mock_synclog_cls.Status.STARTED = "started"
    mock_synclog_cls.Status.COMPLETED = "completed"

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.get_ballot_question_metadata.return_value = {
        "bq_id": 11620,
        "question_number": "1",
        "question": "Do you approve?",
        "question_alias": "Audit",
        "summary": "Short",
        "is_initiative_petition": True,
        "is_referendum": False,
        "is_local": False,
        "is_county": False,
        "date": "2024-11-05",
        "year": 2024,
    }

    mock_election = MagicMock()
    mock_election.status = "results_pending"
    mock_get_election.return_value = mock_election

    mock_race_cls.objects.filter.return_value.values_list.return_value = []
    mock_race_cls.objects.bulk_create.return_value = []
    mock_race_cls.CertificationStatus.UPCOMING = "upcoming"
    mock_race_cls.CertificationStatus.RESULTS_CERTIFIED = "results_certified"
    mock_race_cls.RaceType.MEASURE = "measure"
    mock_race_cls.RaceType.CANDIDATE = "candidate"
    mock_race_cls.Source.MA_SOS = "ma_sos"
    mock_race_cls.RaceStatus.ACTIVE = "active"
    mock_race_cls.VoteMethod.YES_NO = "yes_no"
    mock_race_cls.VoteMethod.SINGLE_CHOICE = "single_choice"

    mock_race_obj = MagicMock()
    mock_race_cls.objects.get.return_value = mock_race_obj

    mock_tx.atomic.return_value.__enter__ = MagicMock(return_value=None)
    mock_tx.atomic.return_value.__exit__ = MagicMock(return_value=False)
    mock_tz.now.return_value = MagicMock()

    result = sync_ma_ballot_question.run(11620)

    mock_race_cls.objects.bulk_create.assert_called_once()
    assert mock_measure_cls.objects.get_or_create.call_count == 2
