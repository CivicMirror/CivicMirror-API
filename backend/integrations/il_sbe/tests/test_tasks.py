from unittest.mock import patch

import pytest

from elections.models import Election, Race
from integrations.il_sbe.tasks import sync_il_elections, sync_il_races


@pytest.mark.django_db
def test_sync_il_elections_creates_general_and_primary_skips_specials():
    options_html = "<html>fake search page</html>"
    fake_options = [
        {"value": "69", "label": "2026 GENERAL PRIMARY"},
        {"value": "68", "label": "2025 CONSOLIDATED ELECTION"},
        {"value": "13", "label": "2015 SPECIAL GENERAL ELECTION"},
    ]

    with patch(
        "integrations.il_sbe.tasks.IllinoisSbeClient.fetch_search_page",
        return_value=options_html,
    ), patch(
        "integrations.il_sbe.tasks.parse_election_options",
        return_value=fake_options,
    ), patch(
        "integrations.il_sbe.tasks.sync_il_races.delay"
    ) as mock_delay:
        result = sync_il_elections()

    assert result["created"] == 2
    assert Election.objects.filter(state="IL").count() == 2
    assert not Election.objects.filter(source_id="il_sbe_13").exists()
    assert mock_delay.call_count == 2


@pytest.mark.django_db
def test_sync_il_races_creates_federal_and_state_races_only():
    election = Election.objects.create(
        name="2026 Illinois General Primary",
        election_date="2026-03-17",
        election_type="primary",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="IL",
        source_id="il_sbe_69",
        status=Election.Status.RESULTS_PENDING,
        source_metadata={"il_sbe_election_value": "69"},
    )

    fake_offices = [
        {"office_name": "UNITED STATES SENATOR", "csv_url": "https://example.com/senate.csv"},
        {"office_name": "1ST STATE CENTRAL COMMITTEEPERSON", "csv_url": "https://example.com/scc.csv"},
        {"office_name": "GOVERNOR AND LIEUTENANT GOVERNOR", "csv_url": "https://example.com/gov.csv"},
    ]

    with patch(
        "integrations.il_sbe.tasks.IllinoisSbeClient.fetch_election_page",
        return_value="<html>fake election page</html>",
    ), patch(
        "integrations.il_sbe.tasks.parse_election_id_token",
        return_value="Z2J/vYpKX8w=",
    ), patch(
        "integrations.il_sbe.tasks.IllinoisSbeClient.fetch_category_page",
        return_value="<html>fake category page</html>",
    ), patch(
        "integrations.il_sbe.tasks.parse_category_offices",
        return_value=fake_offices,
    ):
        result = sync_il_races(election.pk)

    assert result["created"] == 2
    races = Race.objects.filter(election=election)
    assert races.count() == 2
    assert set(races.values_list("office_title", flat=True)) == {
        "UNITED STATES SENATOR", "GOVERNOR AND LIEUTENANT GOVERNOR",
    }
    election.refresh_from_db()
    assert election.source_metadata["il_sbe_election_id_token"] == "Z2J/vYpKX8w="


@pytest.mark.django_db
def test_sync_il_races_noop_when_election_missing():
    result = sync_il_races(999999)
    assert result is None
