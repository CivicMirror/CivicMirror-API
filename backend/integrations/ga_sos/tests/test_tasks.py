import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from integrations.ga_sos.tasks import sync_ga_elections, sync_ga_races

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text())


def _mock_sync_log(mock_log_cls):
    mock_log = MagicMock()
    mock_log_cls.objects.create.return_value = mock_log
    mock_log_cls.Status.STARTED = "started"
    mock_log_cls.Status.COMPLETED = "completed"
    mock_log_cls.Status.COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    mock_log_cls.Status.FAILED = "failed"
    return mock_log


def test_sync_ga_elections_discovers_elections_and_queues_race_sync():
    jurisdiction = _fixture("jurisdiction_georgia.json")
    election_row = next(
        e for e in jurisdiction["elections"]
        if e["publicElectionId"] == "06162026GeneralPrimaryRunoff"
    )
    mock_election = MagicMock()
    mock_election.pk = 42
    mock_election.source_metadata = {}

    with patch("integrations.ga_sos.tasks.GaSosClient") as mock_client_cls, \
         patch("integrations.ga_sos.tasks.SyncLog") as mock_log_cls, \
         patch("integrations.ga_sos.tasks.sync_ga_races") as mock_races_task, \
         patch("aggregation.ingest.ingest_election", return_value=(mock_election, True)) as mock_ingest:
        _mock_sync_log(mock_log_cls)
        mock_client_cls.return_value.list_elections.return_value = [election_row]

        result = sync_ga_elections()

    mock_ingest.assert_called_once()
    kwargs = mock_ingest.call_args.kwargs
    assert kwargs["source"] == "ga_sos"
    assert kwargs["source_id"] == "ga_sos:06162026GeneralPrimaryRunoff"
    assert kwargs["identity"]["state"] == "GA"
    assert mock_election.source_metadata["enr_slug"] == "06162026GeneralPrimaryRunoff"
    assert mock_election.source_metadata["ga_public_election_id"] == "06162026GeneralPrimaryRunoff"
    mock_election.save.assert_called_once_with(update_fields=["source_metadata"])
    mock_races_task.apply_async.assert_called_once_with(args=[42, "06162026GeneralPrimaryRunoff"], countdown=0)
    assert result == {"created": 1, "updated": 0, "skipped": 0, "queued": 1}


def test_sync_ga_elections_skips_rows_without_public_id():
    row = {
        "publicElectionId": "",
        "electionDate": "2026-06-16",
        "name": [{"languageId": "en", "text": "Broken Election"}],
    }

    with patch("integrations.ga_sos.tasks.GaSosClient") as mock_client_cls, \
         patch("integrations.ga_sos.tasks.SyncLog") as mock_log_cls, \
         patch("aggregation.ingest.ingest_election") as mock_ingest:
        _mock_sync_log(mock_log_cls)
        mock_client_cls.return_value.list_elections.return_value = [row]

        result = sync_ga_elections()

    mock_ingest.assert_not_called()
    assert result["skipped"] == 1
    assert result["queued"] == 0


def test_sync_ga_races_candidate_item_ingests_candidates():
    data = _fixture("election_data_06162026.json")
    ballot_item = next(b for b in data["ballotItems"] if b["name"][0]["text"] == "US Senate - Rep")
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.source_id = "ga_sos:06162026GeneralPrimaryRunoff"
    mock_election.status = "results_pending"
    mock_election.source_metadata = {
        "enr_slug": "06162026GeneralPrimaryRunoff",
        "ga_public_election_id": "06162026GeneralPrimaryRunoff",
    }
    mock_race = MagicMock()
    mock_candidate = MagicMock()

    with patch("integrations.ga_sos.tasks.Election") as mock_election_cls, \
         patch("integrations.ga_sos.tasks.GaSosClient") as mock_client_cls, \
         patch("integrations.ga_sos.tasks.SyncLog") as mock_log_cls, \
         patch("aggregation.ingest.ingest_race", return_value=(mock_race, True)) as mock_ingest_race, \
         patch("aggregation.ingest.ingest_candidate", return_value=(mock_candidate, True)) as mock_ingest_candidate:
        _mock_sync_log(mock_log_cls)
        mock_election_cls.objects.get.return_value = mock_election
        mock_election_cls.DoesNotExist = Exception
        mock_client_cls.return_value.get_election_data.return_value = {"ballotItems": [ballot_item]}

        result = sync_ga_races(1, "06162026GeneralPrimaryRunoff")

    race_kwargs = mock_ingest_race.call_args.kwargs
    assert race_kwargs["source"] == "ga_sos"
    assert race_kwargs["identity"]["office_title"] == "US Senate - Rep"
    assert race_kwargs["identity"]["race_type"] == "candidate"
    assert mock_ingest_candidate.call_count == 2
    first_candidate = mock_ingest_candidate.call_args_list[0].kwargs
    assert first_candidate["source"] == "ga_sos"
    assert first_candidate["name"] == "Mike Collins"
    assert first_candidate["party"] == "REP"
    mock_election.save.assert_called_once_with(update_fields=["last_synced_at"])
    assert result["races"]["created"] == 1
    assert result["candidates"]["created"] == 2


def test_sync_ga_races_deduplicates_candidates_by_name_and_party():
    ballot_item = {
        "id": "race-1",
        "contestType": "Candidate",
        "name": [{"languageId": "en", "text": "State Representative"}],
        "summaryResults": {
            "ballotOptions": [
                {"name": [{"languageId": "en", "text": "Alex Smith"}], "party": {"abbreviation": "DEM"}},
                {"name": [{"languageId": "en", "text": "Alex Smith"}], "party": {"abbreviation": "DEM"}},
            ]
        },
    }
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.status = "results_pending"
    mock_election.source_id = "ga_sos:test"
    mock_election.source_metadata = {"enr_slug": "test"}

    with patch("integrations.ga_sos.tasks.Election") as mock_election_cls, \
         patch("integrations.ga_sos.tasks.GaSosClient") as mock_client_cls, \
         patch("integrations.ga_sos.tasks.SyncLog") as mock_log_cls, \
         patch("aggregation.ingest.ingest_race", return_value=(MagicMock(), True)), \
         patch("aggregation.ingest.ingest_candidate", return_value=(MagicMock(), True)) as mock_ingest_candidate:
        _mock_sync_log(mock_log_cls)
        mock_election_cls.objects.get.return_value = mock_election
        mock_election_cls.DoesNotExist = Exception
        mock_client_cls.return_value.get_election_data.return_value = {"ballotItems": [ballot_item]}

        sync_ga_races(1, "test")

    mock_ingest_candidate.assert_called_once()


def test_sync_ga_races_measure_item_creates_options():
    ballot_item = {
        "id": "measure-1",
        "contestType": "BallotMeasure",
        "name": [{"languageId": "en", "text": "Question 1"}],
        "summaryResults": {
            "ballotOptions": [
                {"name": [{"languageId": "en", "text": "Yes"}], "nativeId": "yes"},
                {"name": [{"languageId": "en", "text": "No"}], "nativeId": "no"},
            ]
        },
    }
    mock_election = MagicMock()
    mock_election.pk = 1
    mock_election.status = "results_pending"
    mock_election.source_id = "ga_sos:test"
    mock_election.source_metadata = {"enr_slug": "test"}
    mock_race = MagicMock()

    with patch("integrations.ga_sos.tasks.Election") as mock_election_cls, \
         patch("integrations.ga_sos.tasks.GaSosClient") as mock_client_cls, \
         patch("integrations.ga_sos.tasks.SyncLog") as mock_log_cls, \
         patch("integrations.ga_sos.tasks.MeasureOption") as mock_measure_option, \
         patch("aggregation.ingest.ingest_race", return_value=(mock_race, True)):
        _mock_sync_log(mock_log_cls)
        mock_election_cls.objects.get.return_value = mock_election
        mock_election_cls.DoesNotExist = Exception
        mock_client_cls.return_value.get_election_data.return_value = {"ballotItems": [ballot_item]}

        result = sync_ga_races(1, "test")

    assert mock_measure_option.objects.get_or_create.call_count == 2
    assert result["races"]["created"] == 1
