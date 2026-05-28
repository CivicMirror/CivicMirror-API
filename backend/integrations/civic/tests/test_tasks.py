from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from aggregation.models import SourcePrecedence
from elections.models import Candidate, Election, ElectionSourceLink, MeasureOption, Race
from integrations.civic.ingest_adapter import ingest_civic_election
from ops.models import SyncLog


@pytest.fixture
def civic_precedence(db):
    """Register civic_api as a known source so the ingest engine can rank it."""
    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)


@pytest.mark.django_db
@patch("integrations.civic.tasks.CivicAPIClient")
def test_sync_elections_creates_synclog(MockClient):
    MockClient.return_value.list_elections.return_value = []
    from integrations.civic.tasks import sync_elections
    result = sync_elections()
    assert SyncLog.objects.filter(task_name="sync_elections", status=SyncLog.Status.COMPLETED).exists()
    assert result == {"created": 0, "updated": 0, "queued": 0}


@pytest.mark.django_db
@patch("integrations.civic.tasks.CivicAPIClient")
@patch("integrations.civic.tasks.races_are_fresh", return_value=True)
def test_sync_elections_skips_vip_test(mock_fresh, MockClient, civic_precedence):
    # Updated: canonical elections don't set source_id on the Election row;
    # the source_id lives on ElectionSourceLink. Check that no link was created
    # for the VIP test election, which must be filtered out before ingest.
    MockClient.return_value.list_elections.return_value = [
        {"source_id": "2000", "name": "VIP Test Election", "election_date": "2024-01-01", "ocd_division_id": "ocd-division/country:us"}
    ]
    from integrations.civic.tasks import sync_elections
    sync_elections()
    assert ElectionSourceLink.objects.filter(source="civic_api", source_id="2000").count() == 0
    assert Election.objects.count() == 0


@pytest.mark.django_db
@patch("integrations.civic.tasks.CivicAPIClient")
@patch("integrations.civic.tasks.races_are_fresh", return_value=True)
def test_sync_elections_creates_election(mock_fresh, MockClient, civic_precedence):
    # Updated: the ingest service creates a canonical Election row (source_id=NULL)
    # and registers the civic source_id on ElectionSourceLink. Assert both.
    MockClient.return_value.list_elections.return_value = [
        {"source_id": "9530", "name": "Louisiana 2026 Primary", "election_date": "2026-03-21", "ocd_division_id": "ocd-division/country:us/state:la"}
    ]
    from integrations.civic.tasks import sync_elections
    sync_elections()
    assert Election.objects.filter(canonical_key="LA:primary:2026-03-21:state").exists()
    assert ElectionSourceLink.objects.filter(source="civic_api", source_id="9530").exists()
    election = Election.objects.get(canonical_key="LA:primary:2026-03-21:state")
    assert "civic_api" in election.contributing_sources


@pytest.mark.django_db
@patch("integrations.civic.tasks.CivicAPIClient")
def test_sync_elections_handles_forbidden(MockClient):
    from integrations.civic.exceptions import CivicAPIForbidden
    MockClient.return_value.list_elections.side_effect = CivicAPIForbidden("bad key")
    from integrations.civic.tasks import sync_elections
    with pytest.raises(CivicAPIForbidden):
        sync_elections()
    assert SyncLog.objects.filter(task_name="sync_elections", status=SyncLog.Status.FAILED).exists()


@pytest.mark.django_db
@patch("integrations.civic.tasks.get_cached_voter_info", return_value=None)
@patch("integrations.civic.tasks.set_cached_voter_info")
@patch("integrations.civic.tasks.CivicAPIClient")
def test_sync_election_races_candidate(MockClient, mock_set_cache, mock_get_cache):
    election = Election.objects.create(
        source_id="9530",
        name="Louisiana 2026 Primary",
        election_date="2026-03-21",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="LA",
    )
    MockClient.return_value.get_voter_info.return_value = {
        "contests": [
            {
                "type": "General",
                "office": "Governor",
                "district": {"name": "Louisiana", "scope": "statewide", "id": "ocd-division/country:us/state:la"},
                "candidates": [{"name": "Jane Smith", "party": "Democratic"}],
            }
        ]
    }
    from integrations.civic.tasks import sync_election_races
    result = sync_election_races(election.id, "900 N 3rd St, Baton Rouge, LA 70802", "LA-capital")
    assert Race.objects.filter(election=election).count() == 1
    assert Candidate.objects.filter(name="Jane Smith").count() == 1
    assert result["created"] >= 1


@pytest.mark.django_db
@patch("integrations.civic.tasks.get_cached_voter_info", return_value=None)
@patch("integrations.civic.tasks.set_cached_voter_info")
@patch("integrations.civic.tasks.CivicAPIClient")
def test_sync_election_races_measure(MockClient, mock_set_cache, mock_get_cache):
    election = Election.objects.create(
        source_id="9531",
        name="Louisiana 2026 Measure",
        election_date="2026-03-21",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="LA",
    )
    MockClient.return_value.get_voter_info.return_value = {
        "contests": [
            {
                "type": "Referendum",
                "referendumTitle": "Question 1",
                "district": {"name": "Louisiana", "scope": "statewide", "id": "ocd-division/country:us/state:la"},
            }
        ]
    }
    from integrations.civic.tasks import sync_election_races
    sync_election_races(election.id, "900 N 3rd St, Baton Rouge, LA 70802", "LA-capital")
    race = Race.objects.get(election=election)
    assert race.race_type == Race.RaceType.MEASURE
    assert MeasureOption.objects.filter(race=race).count() == 3  # Yes, No, Abstain


@pytest.mark.django_db
def test_ingest_civic_election_lands_on_canonical_key(civic_precedence):
    payload = {
        "source_id": "11255",
        "name": "California Primary Election",
        "election_date": "2026-06-02",
        "ocd_division_id": "ocd-division/country:us/state:ca",
    }
    election, created = ingest_civic_election(payload)
    assert election.canonical_key == "CA:primary:2026-06-02:state"
    assert "civic_api" in election.contributing_sources
    assert created is True
