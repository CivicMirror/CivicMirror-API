"""
Unit tests for the va_elect Celery tasks.
Django ORM + Celery are mocked — no DB required.
"""
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from integrations.va_elect.tasks import sync_va_elections, sync_va_races


def _make_election_dict(slug="2025-November-General", idx=0):
    """Return a fresh map_election-shaped dict for each call."""
    return {
        "source_id": f"va_elect_{slug}",
        "name": f"{slug} Election",
        "state": "VA",
        "election_date": date(2025, 11, 4),
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
    """With 3 slugs, sync_va_elections dispatches 3 sync_va_races subtasks."""
    from datetime import date

    with patch("integrations.va_elect.tasks.VaElectClient") as MockClient, \
         patch("integrations.va_elect.tasks.SyncLog") as MockLog, \
         patch("integrations.va_elect.tasks.sync_va_races") as mock_subtask, \
         patch("integrations.va_elect.tasks.Election") as MockElection, \
         patch("integrations.va_elect.tasks.map_election") as mock_map_election:

        client = MockClient.return_value
        client.get_election_slugs.return_value = [
            "2025-November-General",
            "2025-June-Republican-Primary",
            "2025-September-9-Special",
        ]
        client.get_election_metadata.return_value = {
            "electionDate": "2025-11-04",
            "asOf": "2025-12-01T00:00:00Z",
            "isOfficialResults": True,
        }

        mock_map_election.side_effect = [
            _make_election_dict("2025-November-General"),
            _make_election_dict("2025-June-Republican-Primary"),
            _make_election_dict("2025-September-9-Special"),
        ]

        mock_election = MagicMock()
        mock_election.pk = 42
        mock_election.source_id = "va_elect_2025-November-General"
        # bulk_create returns the objects list; Elections.objects.filter returns iterable
        MockElection.objects.bulk_create.return_value = []
        MockElection.objects.filter.return_value.values_list.return_value = []
        mock_election2 = MagicMock()
        mock_election2.pk = 43
        mock_election2.source_id = "va_elect_2025-June-Republican-Primary"
        mock_election3 = MagicMock()
        mock_election3.pk = 44
        mock_election3.source_id = "va_elect_2025-September-9-Special"
        MockElection.objects.filter.return_value.__iter__ = lambda s: iter([mock_election, mock_election2, mock_election3])

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log

        sync_va_elections()

        # One apply_async per slug
        assert mock_subtask.apply_async.call_count == 3


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
    """sync_va_races fetches data, maps one candidate race, bulk-creates correctly."""
    with patch("integrations.va_elect.tasks.VaElectClient") as MockClient, \
         patch("integrations.va_elect.tasks.SyncLog") as MockLog, \
         patch("integrations.va_elect.tasks.Election") as MockElection, \
         patch("integrations.va_elect.tasks.Race") as MockRace, \
         patch("integrations.va_elect.tasks.Candidate") as MockCandidate, \
         patch("integrations.va_elect.tasks.MeasureOption"), \
         patch("integrations.va_elect.tasks.map_race") as mock_map_race, \
         patch("integrations.va_elect.tasks.map_candidate") as mock_map_candidate, \
         patch("integrations.va_elect.tasks.transaction") as mock_tx:

        mock_tx.atomic.return_value.__enter__ = MagicMock(return_value=None)
        mock_tx.atomic.return_value.__exit__ = MagicMock(return_value=False)

        client = MockClient.return_value
        client.get_election_data.return_value = _DATA_PAYLOAD

        mock_election = MagicMock()
        mock_election.pk = 42
        mock_election.source_metadata = {"enr_slug": "2025-November-General"}
        MockElection.objects.get.return_value = mock_election

        # Build a race mock whose race_type matches MockRace.RaceType.CANDIDATE
        canonical_key = "va_elect:va_elect_2025-November-General:governor:statewide:nonpartisan"
        mock_race_obj = MagicMock()
        mock_race_obj.canonical_key = canonical_key
        mock_race_obj.race_type = MockRace.RaceType.CANDIDATE  # same object = equality works

        MockRace.objects.filter.return_value.values_list.return_value = []
        MockRace.objects.filter.return_value.only.return_value = [mock_race_obj]
        MockRace.objects.bulk_create.return_value = []
        # Race(...) constructor call returns the mock race
        MockRace.return_value = mock_race_obj

        mock_map_race.return_value = {
            "office_title": "Governor",
            "race_type": MockRace.RaceType.CANDIDATE,
            "source": MockRace.Source.VA_ELECT,
            "canonical_key": canonical_key,
            "source_metadata": {},
            "geography_scope": "statewide",
            "normalized_office_title": "governor",
            "jurisdiction": "Virginia",
            "certification_status": MockRace.CertificationStatus.RESULTS_PENDING,
            "race_status": MockRace.RaceStatus.ACTIVE,
            "vote_method": MockRace.VoteMethod.SINGLE_CHOICE,
            "max_selections": 1,
            "ocd_division_id": "",
        }

        mock_map_candidate.return_value = {
            "party": "Democratic",
            "incumbent": False,
            "candidate_status": MagicMock(),
            "source_metadata": {"enr_native_id": "cs1", "is_write_in": False},
        }

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log

        sync_va_races(42, "2025-November-General")

        MockCandidate.objects.bulk_create.assert_called_once()
        mock_log.save.assert_called()


def test_sync_va_races_ballot_measure(db=None):
    """sync_va_races creates MeasureOption rows for BallotMeasure contest type."""
    measure_payload = {
        "jurisdiction": {"bannerUrl": "d2c804ee/banner.png"},
        "ballotItems": [
            {
                "id": "item-100",
                "contestType": "BallotMeasure",
                "name": [{"languageId": "en", "text": "Question 1"}],
                "summaryResults": {
                    "ballotOptions": [
                        {
                            "name": [{"languageId": "en", "text": "Yes"}],
                            "voteCount": 1_000_000,
                            "votePercent": 55.0,
                            "isWinner": None,
                            "isWriteIn": False,
                            "nativeId": "bms1",
                            "party": None,
                        }
                    ]
                },
            }
        ],
        "publicReportCategories": [],
    }

    with patch("integrations.va_elect.tasks.VaElectClient") as MockClient, \
         patch("integrations.va_elect.tasks.SyncLog") as MockLog, \
         patch("integrations.va_elect.tasks.Election") as MockElection, \
         patch("integrations.va_elect.tasks.Race") as MockRace, \
         patch("integrations.va_elect.tasks.Candidate") as MockCandidate, \
         patch("integrations.va_elect.tasks.MeasureOption") as MockOption, \
         patch("integrations.va_elect.tasks.map_race") as mock_map_race, \
         patch("integrations.va_elect.tasks.map_measure_option") as mock_map_option, \
         patch("integrations.va_elect.tasks.transaction") as mock_tx:

        mock_tx.atomic.return_value.__enter__ = MagicMock(return_value=None)
        mock_tx.atomic.return_value.__exit__ = MagicMock(return_value=False)

        client = MockClient.return_value
        client.get_election_data.return_value = measure_payload

        mock_election = MagicMock()
        mock_election.pk = 10
        mock_election.source_metadata = {"enr_slug": "2025-November-General"}
        MockElection.objects.get.return_value = mock_election

        canonical_key = "va_elect:va_elect_2025-November-General:question 1:statewide:nonpartisan"
        mock_race_obj = MagicMock()
        mock_race_obj.canonical_key = canonical_key
        mock_race_obj.race_type = MockRace.RaceType.MEASURE

        MockRace.objects.filter.return_value.values_list.return_value = []
        MockRace.objects.filter.return_value.only.return_value = [mock_race_obj]
        MockRace.objects.bulk_create.return_value = []
        MockRace.return_value = mock_race_obj

        mock_map_race.return_value = {
            "office_title": "Question 1",
            "race_type": MockRace.RaceType.MEASURE,
            "source": MockRace.Source.VA_ELECT,
            "canonical_key": canonical_key,
            "source_metadata": {},
            "geography_scope": "statewide",
            "normalized_office_title": "question 1",
            "jurisdiction": "Virginia",
            "certification_status": MockRace.CertificationStatus.RESULTS_PENDING,
            "race_status": MockRace.RaceStatus.ACTIVE,
            "vote_method": MockRace.VoteMethod.YES_NO,
            "max_selections": 1,
            "ocd_division_id": "",
        }

        mock_map_option.return_value = {"label": "Yes", "source_metadata": {"enr_native_id": "bms1"}}

        mock_log = MagicMock()
        MockLog.objects.create.return_value = mock_log

        sync_va_races(10, "2025-November-General")

        MockOption.objects.bulk_create.assert_called_once()
        # Candidate bulk_create should NOT be called for measure contests
        MockCandidate.objects.bulk_create.assert_not_called()
