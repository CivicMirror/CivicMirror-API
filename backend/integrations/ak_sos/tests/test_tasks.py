from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures"


def _make_ak_primary():
    from elections.models import Election

    return Election.objects.create(
        source_id="ak_2026_primary", name="2026 Alaska Primary Election", state="AK",
        election_type="primary", election_date=datetime.date(2026, 8, 18),
        status="results_pending", jurisdiction_level="state",
    )


def _mock_client_returning(html: str):
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.fetch_candidates_html.return_value = html
    return mock_client


def test_sync_ak_races_creates_races_and_candidates():
    from elections.models import Candidate, Race
    from integrations.ak_sos.tasks import sync_ak_races

    _make_ak_primary()
    html = (FIXTURES / "governor.html").read_text()

    with patch("integrations.ak_sos.tasks.AkSosClient", return_value=_mock_client_returning(html)):
        result = sync_ak_races()

    assert result["created"] == 53
    assert Race.objects.filter(office_title="Governor / Lieutenant Governor").exists()
    assert Race.objects.filter(office_title="State House - District 1").exists()
    race = Race.objects.get(office_title="Governor / Lieutenant Governor")
    assert Candidate.objects.filter(race=race, name="Bronson/Church").exists()
    assert race.source == "ak_sos"
    assert race.geography_scope == "statewide"


def test_sync_ak_races_is_idempotent_on_rerun():
    from elections.models import Candidate, Race
    from integrations.ak_sos.tasks import sync_ak_races

    _make_ak_primary()
    html = (FIXTURES / "governor.html").read_text()

    with patch("integrations.ak_sos.tasks.AkSosClient", return_value=_mock_client_returning(html)):
        sync_ak_races()
        result = sync_ak_races()

    assert result["created"] == 0
    assert result["updated"] == 53
    governor_race_count = Race.objects.filter(office_title="Governor / Lieutenant Governor").count()
    assert governor_race_count == 1
    assert Candidate.objects.filter(
        race__office_title="Governor / Lieutenant Governor",
    ).count() == 17


def test_sync_ak_races_skips_when_no_ak_primary_exists():
    from integrations.ak_sos.tasks import sync_ak_races

    result = sync_ak_races()

    assert result == {"created": 0, "updated": 0}


def test_sync_ak_races_skips_terminal_elections():
    from elections.models import Election
    from integrations.ak_sos.tasks import sync_ak_races

    Election.objects.create(
        source_id="ak_2024_primary", name="2024 Alaska Primary Election", state="AK",
        election_type="primary", election_date=datetime.date(2024, 8, 20),
        status="archived", jurisdiction_level="state",
    )

    result = sync_ak_races()

    assert result == {"created": 0, "updated": 0}


def test_sync_ak_races_only_targets_primary_not_general():
    from elections.models import Election
    from integrations.ak_sos.tasks import sync_ak_races

    Election.objects.create(
        source_id="ak_2026_general", name="2026 Alaska General Election", state="AK",
        election_type="general", election_date=datetime.date(2026, 11, 3),
        status="upcoming", jurisdiction_level="state",
    )

    result = sync_ak_races()

    assert result == {"created": 0, "updated": 0}
