"""
Unit tests for the va_elect Celery tasks.
Django ORM + Celery are mocked — no DB required.
"""
from datetime import date as _date
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from integrations.va_elect.tasks import sync_va_elections, sync_va_races


def _make_election_dict(slug="2025-November-General", idx=0):
    """Return a fresh map_election-shaped dict for each call."""
    return {
        "source_id": f"va_elect_{slug}",
        "name": f"{slug} Election",
        "state": "VA",
        "election_date": _date(2025, 11, 4),
        "election_type": "general",
        "jurisdiction_level": "state",
        "status": "results_pending",
        "source_metadata": {"enr_slug": slug},
    }


# ---------------------------------------------------------------------------
# sync_va_elections
# ---------------------------------------------------------------------------

def test_sync_va_elections_no_slugs(db=None):
    """When the client returns no election slugs, the task succeeds with nothing queued."""
    with patch("integrations.va_elect.tasks.VaElectClient") as MockClient, \
         patch("integrations.va_elect.tasks.SyncLog") as MockLog, \
         patch("integrations.va_elect.tasks.sync_va_races") as mock_subtask:

        client = MockClient.return_value
        client.get_election_slugs.return_value = []

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log

        sync_va_elections()

        mock_subtask.apply_async.assert_not_called()
        mock_log.save.assert_called()


def test_sync_va_elections_dispatches_subtasks(db=None):
    """sync_va_elections routes through ingest_election; queues one subtask per valid slug."""
    mock_election_obj = MagicMock()
    mock_election_obj.pk = 42

    with patch("integrations.va_elect.tasks.VaElectClient") as MockClient, \
         patch("integrations.va_elect.tasks.SyncLog") as MockLog, \
         patch("integrations.va_elect.tasks.sync_va_races") as mock_subtask, \
         patch("aggregation.ingest.ingest_election", return_value=(mock_election_obj, True)) as mock_ingest:

        client = MockClient.return_value
        client.get_election_slugs.return_value = [
            "2025-November-General",
            "2025-June-Republican-Primary",
        ]
        client.get_election_metadata.return_value = {
            "electionDate": "2025-11-04",
            "electionName": "2025 November General",
        }

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log
        MockLog.Status.STARTED = "started"
        MockLog.Status.COMPLETED = "completed"

        sync_va_elections()

    assert mock_ingest.call_count == 2
    assert mock_subtask.apply_async.call_count == 2


def test_sync_va_elections_records_error(db=None):
    """Client exceptions are caught and written to SyncLog, then re-raised."""
    with patch("integrations.va_elect.tasks.VaElectClient") as MockClient, \
         patch("integrations.va_elect.tasks.SyncLog") as MockLog:

        MockClient.return_value.get_election_slugs.side_effect = Exception("Network error")

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log

        with pytest.raises(Exception, match="Network error"):
            sync_va_elections()

        mock_log.save.assert_called()


# ---------------------------------------------------------------------------
# sync_va_races
# ---------------------------------------------------------------------------

_DATA_PAYLOAD = {
    "jurisdiction": {
        "bannerUrl": "d2c804ee/banner.png",
    },
    "ballotItems": [
        {
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
                    }
                ]
            },
        }
    ],
    "publicReportCategories": [],
}


def test_sync_va_races_happy_path(db=None):
    """sync_va_races routes candidate ballot items through ingest_race + ingest_candidate."""
    data_payload = {
        "ballotItems": [
            {
                "id": "item-001",
                "contestType": "Candidate",
                "name": [{"languageId": "en", "text": "Governor"}],
                "summaryResults": {
                    "ballotOptions": [
                        {
                            "name": [{"languageId": "en", "text": "Jane Smith"}],
                            "nativeId": "cs1",
                            "party": {"abbreviation": "D", "name": "Democratic"},
                            "isWriteIn": False,
                        }
                    ]
                },
            }
        ],
    }

    mock_election = MagicMock()
    mock_election.pk = 42
    mock_election.state = "VA"
    mock_election.source_id = None
    mock_election.canonical_key = "VA:general:2025-11-04:state"
    mock_election.source_metadata = {"enr_slug": "2025-November-General"}
    mock_election.status = "upcoming"

    mock_race_obj = MagicMock()

    with patch("integrations.va_elect.tasks.VaElectClient") as MockClient, \
         patch("integrations.va_elect.tasks.SyncLog") as MockLog, \
         patch("integrations.va_elect.tasks.Election") as MockElection, \
         patch("aggregation.ingest.ingest_race", return_value=(mock_race_obj, True)) as mock_ingest_race, \
         patch("aggregation.ingest.ingest_candidate", return_value=(MagicMock(), True)) as mock_ingest_cand:

        MockClient.return_value.get_election_data.return_value = data_payload
        MockElection.objects.get.return_value = mock_election
        MockLog.objects.create.return_value = MagicMock()
        MockLog.Status.STARTED = "started"
        MockLog.Status.COMPLETED = "completed"

        sync_va_races(42, "2025-November-General")

    mock_ingest_race.assert_called_once()
    call_kw = mock_ingest_race.call_args.kwargs
    assert call_kw["source"] == "va_elect"
    assert call_kw["identity"]["office_title"] == "Governor"

    mock_ingest_cand.assert_called_once()
    cand_kw = mock_ingest_cand.call_args.kwargs
    assert cand_kw["name"] == "Jane Smith"
    assert cand_kw["party"] == "Democratic"


def test_sync_va_races_ballot_measure(db=None):
    """sync_va_races routes BallotMeasure items through ingest_race + MeasureOption.get_or_create."""
    measure_payload = {
        "ballotItems": [
            {
                "id": "item-100",
                "contestType": "BallotMeasure",
                "name": [{"languageId": "en", "text": "Question 1"}],
                "summaryResults": {
                    "ballotOptions": [
                        {
                            "name": [{"languageId": "en", "text": "Yes"}],
                            "nativeId": "bms1",
                            "party": None,
                            "isWriteIn": False,
                        }
                    ]
                },
            }
        ],
    }

    mock_election = MagicMock()
    mock_election.pk = 10
    mock_election.state = "VA"
    mock_election.source_id = None
    mock_election.canonical_key = "VA:general:2025-11-04:state"
    mock_election.source_metadata = {"enr_slug": "2025-November-General"}
    mock_election.status = "upcoming"

    mock_race_obj = MagicMock()

    with patch("integrations.va_elect.tasks.VaElectClient") as MockClient, \
         patch("integrations.va_elect.tasks.SyncLog") as MockLog, \
         patch("integrations.va_elect.tasks.Election") as MockElection, \
         patch("integrations.va_elect.tasks.MeasureOption") as MockOption, \
         patch("aggregation.ingest.ingest_race", return_value=(mock_race_obj, True)) as mock_ingest_race, \
         patch("aggregation.ingest.ingest_candidate") as mock_ingest_cand:

        MockClient.return_value.get_election_data.return_value = measure_payload
        MockElection.objects.get.return_value = mock_election
        MockLog.objects.create.return_value = MagicMock()
        MockLog.Status.STARTED = "started"
        MockLog.Status.COMPLETED = "completed"

        sync_va_races(10, "2025-November-General")

    mock_ingest_race.assert_called_once()
    assert mock_ingest_race.call_args.kwargs["identity"]["race_type"] == "measure"
    # MeasureOption.get_or_create called with option_label=, NOT label=
    MockOption.objects.get_or_create.assert_called_once_with(
        race=mock_race_obj, option_label="Yes"
    )
    # Candidate ingest must NOT be called for measure races
    mock_ingest_cand.assert_not_called()


# ---------------------------------------------------------------------------
# Integration tests — ingest service routing (real DB)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_sync_va_elections_routes_through_ingest_service():
    """Each discovered VA election lands as a canonical Election with contributing_sources=['va_elect']."""
    from aggregation.models import SourcePrecedence
    from elections.models import Election, ElectionSourceLink

    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)

    fake_meta = {"electionDate": "2025-11-04", "electionName": "2025 VA General"}

    with patch("integrations.va_elect.tasks.VaElectClient") as MockClient, \
         patch("integrations.va_elect.tasks.sync_va_races"):
        inst = MockClient.return_value
        inst.get_election_slugs.return_value = ["2025-November-General"]
        inst.get_election_metadata.return_value = fake_meta
        sync_va_elections.run()

    e = Election.objects.get(state="VA", election_date=_date(2025, 11, 4))
    assert "va_elect" in e.contributing_sources
    assert e.canonical_key.startswith("VA:")
    link = ElectionSourceLink.objects.get(election=e, source="va_elect")
    assert link.source_id == "va_elect_2025-November-General"


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_sync_va_races_routes_through_ingest_service():
    """sync_va_races writes canonical Race + Candidate via ingest (not bulk_create)."""
    from aggregation.models import SourcePrecedence
    from elections.models import Candidate, Election, Race

    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)

    e = Election.objects.create(
        name="2025 VA General",
        election_date=_date(2025, 11, 4),
        election_type="general",
        jurisdiction_level="state",
        state="VA",
        canonical_key="VA:general:2025-11-04:state",
        source_metadata={"enr_slug": "2025-November-General"},
        contributing_sources=["va_elect"],
    )

    fake_data = {
        "ballotItems": [
            {
                "id": "item-001",
                "contestType": "Candidate",
                "name": [{"languageId": "en", "text": "Governor"}],
                "summaryResults": {
                    "ballotOptions": [
                        {
                            "name": [{"languageId": "en", "text": "Alice Johnson"}],
                            "nativeId": "c1",
                            "party": {"abbreviation": "D", "name": "Democratic"},
                            "isWriteIn": False,
                        }
                    ]
                },
                "referendum": [],
                "reportingUnits": None,
            }
        ]
    }

    with patch("integrations.va_elect.tasks.VaElectClient") as MockClient:
        MockClient.return_value.get_election_data.return_value = fake_data
        sync_va_races.run(e.pk, "2025-November-General")

    race = Race.objects.filter(election=e).first()
    assert race is not None
    assert race.canonical_key.startswith("VA:general:2025-11-04:state|")
    assert "va_elect" in race.contributing_sources
    cands = list(Candidate.objects.filter(race=race))
    assert len(cands) == 1
    assert cands[0].name == "Alice Johnson"
