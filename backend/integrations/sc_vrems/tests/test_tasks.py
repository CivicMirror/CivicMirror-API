"""
Tests for SC VREMS Celery tasks.
"""
from unittest.mock import MagicMock, patch

import pytest

from elections.models import Candidate, Election, Race
from ops.models import SyncLog


# ------------------------------------------------------------------
# sync_sc_elections
# ------------------------------------------------------------------

@pytest.mark.django_db
@patch("integrations.sc_vrems.tasks.VremsClient")
def test_sync_sc_elections_creates_election(MockClient):
    MockClient.return_value.get_all_elections.return_value = [
        {
            "electionId": "22598",
            "electionName": "Statewide Primary",
            "displayName": "6/9/2026 Statewide Primary",
            "electionDate": "2026-06-09T00:00:00",
            "filingPeriodBeginDate": "2020-03-16T12:00:00",  # already open
            "electionType": "General",
        }
    ]
    with patch("integrations.sc_vrems.tasks.sync_sc_races") as mock_races:
        from integrations.sc_vrems.tasks import sync_sc_elections
        result = sync_sc_elections()

    assert Election.objects.filter(source_id="vrems_sc_22598").exists()
    assert result["created"] == 1
    mock_races.apply_async.assert_called_once()


@pytest.mark.django_db
@patch("integrations.sc_vrems.tasks.VremsClient")
def test_sync_sc_elections_skips_referendum(MockClient):
    MockClient.return_value.get_all_elections.return_value = [
        {
            "electionId": "22700",
            "electionName": "School Bond Referendum",
            "displayName": "11/3/2026 School Bond Referendum",
            "electionDate": "2026-11-03T00:00:00",
            "filingPeriodBeginDate": None,  # referendum
            "electionType": "Local",
        }
    ]
    with patch("integrations.sc_vrems.tasks.sync_sc_races") as mock_races:
        from integrations.sc_vrems.tasks import sync_sc_elections
        result = sync_sc_elections()

    # Election record is still created
    assert Election.objects.filter(source_id="vrems_sc_22700").exists()
    # But no race sync is queued
    mock_races.apply_async.assert_not_called()
    assert result["skipped"] == 1


@pytest.mark.django_db
@patch("integrations.sc_vrems.tasks.VremsClient")
def test_sync_sc_elections_skips_future_filing(MockClient):
    MockClient.return_value.get_all_elections.return_value = [
        {
            "electionId": "22741",
            "electionName": "City of Sumter Municipal Election",
            "displayName": "11/3/2026 City of Sumter Municipal Election",
            "electionDate": "2026-11-03T00:00:00",
            "filingPeriodBeginDate": "2099-07-15T00:00:00",  # far future
            "electionType": "Local",
        }
    ]
    with patch("integrations.sc_vrems.tasks.sync_sc_races") as mock_races:
        from integrations.sc_vrems.tasks import sync_sc_elections
        result = sync_sc_elections()

    assert Election.objects.filter(source_id="vrems_sc_22741").exists()
    mock_races.apply_async.assert_not_called()
    assert result["skipped"] == 1


@pytest.mark.django_db
@patch("integrations.sc_vrems.tasks.VremsClient")
def test_sync_sc_elections_creates_synclog(MockClient):
    MockClient.return_value.get_all_elections.return_value = []
    from integrations.sc_vrems.tasks import sync_sc_elections
    sync_sc_elections()
    assert SyncLog.objects.filter(
        task_name="sync_sc_elections",
        status=SyncLog.Status.COMPLETED,
    ).exists()


@pytest.mark.django_db
@patch("integrations.sc_vrems.tasks.VremsClient")
def test_sync_sc_elections_idempotent(MockClient):
    vrems_election = {
        "electionId": "22598",
        "electionName": "Statewide Primary",
        "displayName": "6/9/2026 Statewide Primary",
        "electionDate": "2026-06-09T00:00:00",
        "filingPeriodBeginDate": "2020-03-16T12:00:00",
        "electionType": "General",
    }
    MockClient.return_value.get_all_elections.return_value = [vrems_election]
    with patch("integrations.sc_vrems.tasks.sync_sc_races"):
        from integrations.sc_vrems.tasks import sync_sc_elections
        sync_sc_elections()
        result2 = sync_sc_elections()

    assert Election.objects.filter(source_id="vrems_sc_22598").count() == 1
    assert result2["created"] == 0
    assert result2["updated"] == 1


# ------------------------------------------------------------------
# sync_sc_races
# ------------------------------------------------------------------

@pytest.mark.django_db
@patch("integrations.sc_vrems.tasks.VremsClient")
def test_sync_sc_races_creates_race_and_candidates(MockClient):
    election = Election.objects.create(
        source_id="vrems_sc_22598",
        name="6/9/2026 Statewide Primary",
        election_date="2026-06-09",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="SC",
    )
    MockClient.return_value.get_candidates.return_value = [
        {
            "office": "Governor",
            "filing_location": "State",
            "associated_counties": "",
            "party": "Republican",
            "name_on_ballot": "Jane Smith",
            "status": "Active",
            "candidate_id": "1",
            "candidate_detail_id": "999",
            "candidate_detail_election_id": "22598",
            "running_mate": "",
        },
        {
            "office": "Governor",
            "filing_location": "State",
            "associated_counties": "",
            "party": "Democratic",
            "name_on_ballot": "John Doe",
            "status": "Active",
            "candidate_id": "2",
            "candidate_detail_id": "1000",
            "candidate_detail_election_id": "22598",
            "running_mate": "",
        },
    ]
    from integrations.sc_vrems.tasks import sync_sc_races
    result = sync_sc_races(election.pk, "22598")

    # Primary → two separate races (R and D)
    assert Race.objects.filter(election=election).count() == 2
    assert Candidate.objects.filter(race__election=election).count() == 2
    assert result["created"] >= 2


@pytest.mark.django_db
@patch("integrations.sc_vrems.tasks.VremsClient")
def test_sync_sc_races_empty_table_logged(MockClient):
    election = Election.objects.create(
        source_id="vrems_sc_22741",
        name="11/3/2026 City of Sumter Municipal Election",
        election_date="2026-11-03",
        jurisdiction_level=Election.JurisdictionLevel.LOCAL,
        state="SC",
    )
    MockClient.return_value.get_candidates.return_value = []
    from integrations.sc_vrems.tasks import sync_sc_races
    result = sync_sc_races(election.pk, "22741")

    assert Race.objects.filter(election=election).count() == 0
    assert result == {"created": 0, "updated": 0}
    assert SyncLog.objects.filter(
        election=election,
        task_name="sync_sc_races",
        status=SyncLog.Status.COMPLETED,
    ).exists()


@pytest.mark.django_db
@patch("integrations.sc_vrems.tasks.VremsClient")
def test_sync_sc_races_idempotent(MockClient):
    election = Election.objects.create(
        source_id="vrems_sc_22598",
        name="6/9/2026 Statewide Primary",
        election_date="2026-06-09",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="SC",
    )
    candidates = [
        {
            "office": "Governor", "filing_location": "State",
            "associated_counties": "", "party": "Republican",
            "name_on_ballot": "Jane Smith", "status": "Active",
            "candidate_id": "1", "candidate_detail_id": "999",
            "candidate_detail_election_id": None, "running_mate": "",
        }
    ]
    MockClient.return_value.get_candidates.return_value = candidates
    from integrations.sc_vrems.tasks import sync_sc_races
    sync_sc_races(election.pk, "22598")
    sync_sc_races(election.pk, "22598")

    assert Race.objects.filter(election=election).count() == 1
    assert Candidate.objects.filter(race__election=election).count() == 1


@pytest.mark.django_db
@patch("integrations.sc_vrems.tasks.VremsClient")
def test_sync_sc_races_vrems_status_in_metadata(MockClient):
    election = Election.objects.create(
        source_id="vrems_sc_22598",
        name="11/3/2024 Statewide General",
        election_date="2024-11-05",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="SC",
        status=Election.Status.ARCHIVED,
    )
    MockClient.return_value.get_candidates.return_value = [
        {
            "office": "Governor", "filing_location": "State",
            "associated_counties": "", "party": "Republican",
            "name_on_ballot": "Winner Candidate", "status": "Elected",
            "candidate_id": "10", "candidate_detail_id": "10",
            "candidate_detail_election_id": None, "running_mate": "",
        }
    ]
    from integrations.sc_vrems.tasks import sync_sc_races
    sync_sc_races(election.pk, "22598")

    candidate = Candidate.objects.get(name="Winner Candidate")
    assert candidate.source_metadata["vrems_status"] == "Elected"
    assert candidate.candidate_status == Candidate.CandidateStatus.RUNNING
