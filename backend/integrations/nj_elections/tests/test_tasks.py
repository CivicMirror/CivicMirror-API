from unittest.mock import patch

import pytest

from elections.models import Election
from integrations.nj_elections.tasks import sync_nj_county_urls


@pytest.mark.django_db
def test_sync_nj_county_urls_updates_active_nj_elections():
    election = Election.objects.create(
        name="2026 New Jersey General Election",
        election_date="2026-11-03",
        election_type="general",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NJ",
        source_id="civic_api_nj_2026_general",
        status=Election.Status.RESULTS_PENDING,
        source_metadata={"some_existing_key": "preserved"},
    )
    other_state_election = Election.objects.create(
        name="2026 Ohio General Election",
        election_date="2026-11-03",
        election_type="general",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="OH",
        source_id="civic_api_oh_2026_general",
        status=Election.Status.RESULTS_PENDING,
    )

    fake_clarity_counties = [
        {"county": "Atlantic", "url": "https://results.enr.clarityelections.com/NJ/Atlantic/126380/", "election_id": "126380"},
        {"county": "Cumberland", "url": "https://results.enr.clarityelections.com/NJ/Cumberland/", "election_id": None},
    ]

    with patch(
        "integrations.nj_elections.tasks.NewJerseyElectionsClient.fetch_enr_page",
        return_value="<html>fake page</html>",
    ), patch(
        "integrations.nj_elections.tasks.parse_county_urls",
        return_value=[{"county": "Atlantic", "url": "x"}, {"county": "Cumberland", "url": "y"}],
    ), patch(
        "integrations.nj_elections.tasks.classify_clarity_counties",
        return_value=fake_clarity_counties,
    ):
        result = sync_nj_county_urls()

    assert result["updated"] == 1
    election.refresh_from_db()
    assert election.source_metadata["some_existing_key"] == "preserved"
    assert election.source_metadata["nj_county_urls"] == fake_clarity_counties

    other_state_election.refresh_from_db()
    assert "nj_county_urls" not in other_state_election.source_metadata


@pytest.mark.django_db
def test_sync_nj_county_urls_noop_when_no_active_nj_elections():
    Election.objects.create(
        name="2024 New Jersey General Election",
        election_date="2024-11-05",
        election_type="general",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="NJ",
        source_id="civic_api_nj_2024_general",
        status=Election.Status.ARCHIVED,
    )

    with patch(
        "integrations.nj_elections.tasks.NewJerseyElectionsClient.fetch_enr_page",
        return_value="<html>fake page</html>",
    ):
        result = sync_nj_county_urls()

    assert result == {"updated": 0}
