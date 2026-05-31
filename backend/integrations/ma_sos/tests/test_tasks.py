"""
Tests for integrations.ma_sos.tasks — Celery task unit tests.
All DB and HTTP calls are mocked. No real DB or network required.
"""
from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest
from django.test import override_settings

# ---------------------------------------------------------------------------
# sync_ma_elections
# ---------------------------------------------------------------------------

@patch("integrations.ma_sos.tasks.SyncLog")
@patch("integrations.ma_sos.tasks.sync_ma_races")
@patch("integrations.ma_sos.tasks.sync_ma_ballot_question")
@patch("integrations.ma_sos.tasks.MaSosClient")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_elections_discovers_and_queues(
    mock_tz, mock_client_cls, mock_bq_task, mock_races_task,
    mock_synclog_cls,
):
    """Routing through ingest_election: verify races + BQ tasks are queued when
    a valid election is discovered.  Election model calls now go through the
    aggregation ingest service, so we mock that instead of bulk_create."""
    from integrations.ma_sos.tasks import sync_ma_elections

    # SyncLog setup
    mock_log = MagicMock()
    mock_synclog_cls.objects.create.return_value = mock_log
    mock_synclog_cls.Status.STARTED = "started"
    mock_synclog_cls.Status.COMPLETED = "completed"
    mock_synclog_cls.Status.COMPLETED_WITH_WARNINGS = "warnings"
    mock_synclog_cls.Status.FAILED = "failed"

    # Client returns 1 election and 1 BQ
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

    # Mock the ingest service to return a fake election object
    mock_saved_election = MagicMock()
    mock_saved_election.pk = 1
    mock_saved_election.source_metadata = {"electionstats_id": 165300}

    mock_tz.now.return_value = MagicMock()
    mock_tz.localdate.return_value = date(2024, 12, 1)

    # Patch date.today() and the ingest service
    with patch("integrations.ma_sos.tasks.date") as mock_date, \
         patch("aggregation.ingest.ingest_election", return_value=(mock_saved_election, True)):
        mock_date.today.return_value = date(2024, 12, 1)
        sync_ma_elections.run()

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
@patch("integrations.ma_sos.tasks.MaSosClient")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_races_upserts_race_and_candidates(
    mock_tz, mock_client_cls, mock_election_cls, mock_synclog_cls,
):
    """sync_ma_races routes through ingest_race + ingest_candidate (not bulk_create).
    Adapted from OLD bulk_create pattern: now mocks the aggregation ingest service."""
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
    mock_election.state = "MA"
    mock_election.canonical_key = "MA:general:2024-11-05:state"
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

    mock_race_obj = MagicMock()
    mock_tz.now.return_value = MagicMock()

    with patch("aggregation.ingest.ingest_race", return_value=(mock_race_obj, True)) as mock_ingest_race, \
         patch("aggregation.ingest.ingest_candidate", return_value=(MagicMock(), True)) as mock_ingest_cand:
        sync_ma_races.run(1, 165323)

    # Verify ingest_race was called once (one race per election CSV)
    mock_ingest_race.assert_called_once()
    # Verify ingest_candidate was called twice (two real candidates)
    assert mock_ingest_cand.call_count == 2


@patch("integrations.ma_sos.tasks.SyncLog")
@patch("integrations.ma_sos.tasks.Election")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_races_missing_election_returns(mock_tz, mock_election_cls, mock_synclog_cls):
    from elections.models import Election as RealElection
    from integrations.ma_sos.tasks import sync_ma_races

    mock_election_cls.DoesNotExist = RealElection.DoesNotExist
    mock_election_cls.objects.get.side_effect = RealElection.DoesNotExist()
    mock_tz.now.return_value = MagicMock()

    result = sync_ma_races.run(99999, 12345)
    assert result is None


# ---------------------------------------------------------------------------
# sync_ma_ballot_question
# ---------------------------------------------------------------------------

@patch("integrations.ma_sos.tasks.SyncLog")
@patch("integrations.ma_sos.tasks.MeasureOption")
@patch("integrations.ma_sos.tasks.MaSosClient")
@patch("integrations.ma_sos.tasks._get_or_create_bq_election")
@patch("integrations.ma_sos.tasks.timezone")
def test_sync_ma_ballot_question_upserts(
    mock_tz, mock_get_election, mock_client_cls,
    mock_measure_cls, mock_synclog_cls,
):
    """sync_ma_ballot_question routes through ingest_race (not bulk_create).
    Adapted from OLD bulk_create pattern: now mocks aggregation.ingest.ingest_race."""
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
    mock_election.canonical_key = "MA:general:2024-11-05:state"
    mock_election.state = "MA"
    mock_get_election.return_value = mock_election

    mock_race_obj = MagicMock()
    mock_tz.now.return_value = MagicMock()

    with patch("aggregation.ingest.ingest_race", return_value=(mock_race_obj, True)) as mock_ingest_race:
        sync_ma_ballot_question.run(11620)

    # Verify ingest_race was called with source="ma_sos" and race_type="measure"
    mock_ingest_race.assert_called_once()
    call_kwargs = mock_ingest_race.call_args.kwargs
    assert call_kwargs["source"] == "ma_sos"
    assert call_kwargs["identity"]["race_type"] == "measure"
    # Yes/No MeasureOptions are still created outside the merge layer
    assert mock_measure_cls.objects.get_or_create.call_count == 2


# ---------------------------------------------------------------------------
# Integration test — ingest service routing
# ---------------------------------------------------------------------------

@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_sync_ma_elections_routes_through_ingest_service():
    """Verify each discovered MA election lands as a canonical Election via the
    aggregation ingest service with electionstats_id preserved on source_metadata."""
    from aggregation.models import SourcePrecedence
    from elections.models import Election, ElectionSourceLink
    from integrations.ma_sos.tasks import sync_ma_elections

    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)

    fake_rows = [
        {"election_id": 165300, "office": "President", "district": "Statewide",
         "stage": "General", "year": 2024},
    ]

    # The two task patches prevent .delay() side effects; their bindings
    # aren't asserted on.
    with patch("integrations.ma_sos.tasks.MaSosClient") as MockClient, \
         patch("integrations.ma_sos.tasks.sync_ma_races"), \
         patch("integrations.ma_sos.tasks.sync_ma_ballot_question"):
        inst = MockClient.return_value
        inst.get_ocpf_schedule.return_value = {"generalElectionDate": "11/5/2024", "primaryElectionDate": "9/3/2024"}
        inst.get_election_ids.return_value = fake_rows
        inst.get_ballot_question_ids.return_value = []
        sync_ma_elections.run()

    e = Election.objects.get(state="MA", election_date=date(2024, 11, 5))
    assert "ma_sos" in e.contributing_sources
    assert e.canonical_key.startswith("MA:")
    link = ElectionSourceLink.objects.get(election=e, source="ma_sos")
    assert link.source_id  # populated by ingest
    assert e.source_metadata.get("electionstats_id") == 165300


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_sync_ma_races_routes_through_ingest_service():
    """sync_ma_races writes a canonical Race + Candidates via the aggregation
    ingest service (not bulk_create)."""
    from aggregation.models import SourcePrecedence
    from elections.models import Candidate, Election, Race
    from integrations.ma_sos.tasks import sync_ma_races

    SourcePrecedence.objects.get_or_create(state="*", field_group="*", source="civic_api", defaults={"rank": 0})

    e = Election.objects.create(
        name="2024 MA U.S. House 1st Congressional General",
        election_date=date(2024, 11, 5),
        election_type="general",
        jurisdiction_level="state",
        state="MA",
        canonical_key="MA:general:2024-11-05:state",
        source_metadata={"electionstats_id": 165323, "office": "U.S. House", "district": "1", "stage": "General"},
        contributing_sources=["ma_sos"],
    )

    fake_csv = (
        b'City/Town,,,"Smith, John","Doe, Jane",All Others,Blanks,Total Votes Cast\n'
        b',,,Democratic,Republican,,,,\n'
        b'Boston,,,"1,000","800",5,10,"1,815"\n'
        b'TOTALS,,,"1,000","800",5,10,"1,815"\n'
    )

    with patch("integrations.ma_sos.tasks.MaSosClient") as MockClient:
        inst = MockClient.return_value
        inst.download_election_csv.return_value = fake_csv
        sync_ma_races.run(e.pk, 165323)

    race = Race.objects.filter(election=e).first()
    assert race is not None
    assert race.canonical_key is not None
    assert race.canonical_key.startswith("MA:general:2024-11-05:state|")
    assert "ma_sos" in race.contributing_sources
    assert Candidate.objects.filter(race=race).count() == 2


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_sync_ma_ballot_question_routes_through_ingest_service():
    """sync_ma_ballot_question writes a canonical measure Race (+ Yes/No options) via ingest."""
    from aggregation.models import SourcePrecedence
    from elections.models import Election, MeasureOption, Race
    from integrations.ma_sos.tasks import sync_ma_ballot_question

    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)

    # Pre-seed the BQ-parent Election so _get_or_create_bq_election finds it.
    e = Election.objects.create(
        name="2024 MA Ballot Questions",
        election_date=date(2024, 11, 5),
        election_type="general",
        jurisdiction_level="state",
        state="MA",
        canonical_key="MA:general:2024-11-05:state",
        contributing_sources=["ma_sos"],
    )

    fake_metadata = {
        "bq_id": 11620,
        "date": "2024-11-05",
        "year": 2024,
        "title": "Question 1 — State Auditor authority to audit Legislature",
        "summary": "Sample summary",
    }

    with patch("integrations.ma_sos.tasks.MaSosClient") as MockClient:
        inst = MockClient.return_value
        inst.get_ballot_question_metadata.return_value = fake_metadata
        sync_ma_ballot_question.run(11620)

    race = Race.objects.filter(election=e).first()
    assert race is not None
    assert race.race_type == "measure"
    assert race.canonical_key.startswith("MA:general:2024-11-05:state|")
    assert "ma_sos" in race.contributing_sources
    # Yes/No options are still created via get_or_create (outside the merge layer).
    labels = set(MeasureOption.objects.filter(race=race).values_list("option_label", flat=True))
    assert {"Yes", "No"}.issubset(labels)
