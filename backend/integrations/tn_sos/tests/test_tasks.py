from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from elections.models import Candidate, Election, Race
from integrations.tn_sos.tasks import sync_tn_candidates, sync_tn_elections, sync_tn_result_index

FIXTURES = Path(__file__).parent / "fixtures"


def _make_tn_election(election_date=date(2026, 8, 6), **overrides):
    fields = {
        "name": "Thursday, August 6, 2026 - Primary and General Election",
        "election_date": election_date,
        "election_type": Election.ElectionType.PRIMARY,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "TN",
        "status": Election.Status.UPCOMING,
        "source_id": f"tn_sos:{election_date.isoformat()}:statewide",
    }
    fields.update(overrides)
    return Election.objects.create(**fields)


@pytest.mark.django_db
def test_sync_tn_elections_ingests_statewide_calendar_elections():
    calendar_html = (FIXTURES / "calendar_2026.html").read_text()

    with patch(
        "integrations.tn_sos.tasks.TnSosClient.get_calendar_html",
        return_value=calendar_html,
    ), patch("integrations.tn_sos.tasks.sync_tn_candidates") as candidates_task:
        result = sync_tn_elections()

    statewide = Election.objects.filter(state="TN")
    assert statewide.count() >= 2
    dates = {election.election_date for election in statewide}
    assert date(2026, 8, 6) in dates
    assert date(2026, 11, 3) in dates
    # County/municipal calendar rows are deferred — nothing local gets created.
    assert not Election.objects.filter(jurisdiction_level=Election.JurisdictionLevel.LOCAL).exists()
    assert candidates_task.delay.called
    assert result["created"] >= 2


@pytest.mark.django_db
def test_sync_tn_candidates_ingests_races_and_candidates():
    election = _make_tn_election()
    list_html = (FIXTURES / "candidate_lists_2026.html").read_text()
    workbook_bytes = (FIXTURES / "candidates_us_senate_2026.xlsx").read_bytes()

    with patch(
        "integrations.tn_sos.tasks.TnSosClient.get_candidate_list_html",
        return_value=list_html,
    ), patch(
        "integrations.tn_sos.tasks.TnSosClient.download_file",
        return_value=(workbook_bytes, "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/USSenate_2026.xlsx"),
    ):
        result = sync_tn_candidates(election_pk=election.pk)

    race = Race.objects.get(election=election, office_title="United States Senate")
    assert race.source == Race.Source.TN_SOS
    assert race.candidates.filter(name="Jane Candidate", party="Republican").exists()
    assert result["created"] > 0

    election.refresh_from_db()
    workbooks = election.source_metadata["tn_candidate_workbooks"]
    assert any(entry["filename"] == "USSenate_2026.xlsx" for entry in workbooks)
    assert all("checksum" in entry for entry in workbooks)


@pytest.mark.django_db
def test_sync_tn_candidates_deduplicates_candidates_on_rerun():
    election = _make_tn_election()
    list_html = (FIXTURES / "candidate_lists_2026.html").read_text()
    workbook_bytes = (FIXTURES / "candidates_us_senate_2026.xlsx").read_bytes()

    with patch(
        "integrations.tn_sos.tasks.TnSosClient.get_candidate_list_html",
        return_value=list_html,
    ), patch(
        "integrations.tn_sos.tasks.TnSosClient.download_file",
        return_value=(workbook_bytes, "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/USSenate_2026.xlsx"),
    ):
        sync_tn_candidates(election_pk=election.pk)
        first_count = Candidate.objects.count()
        second_result = sync_tn_candidates(election_pk=election.pk)

    assert Candidate.objects.count() == first_count
    assert second_result["created"] == 0


@pytest.mark.django_db
def test_sync_tn_result_index_stores_matching_result_links():
    election = _make_tn_election(
        election_date=date(2025, 12, 2),
        name="December 2, 2025 - Special Election",
        election_type=Election.ElectionType.SPECIAL,
        status=Election.Status.RESULTS_PENDING,
        source_id="tn_sos:2025-12-02:statewide",
    )
    index_html = (FIXTURES / "results_index_sample.html").read_text()

    with patch(
        "integrations.tn_sos.tasks.TnSosClient.get_results_index_html",
        return_value=index_html,
    ):
        sync_tn_result_index()

    election.refresh_from_db()
    links = election.source_metadata["tn_result_links"]
    assert any("20251202AllbyPrecinct.xlsx" in link["url"] for link in links)

    # Rerun must not duplicate stored links.
    with patch(
        "integrations.tn_sos.tasks.TnSosClient.get_results_index_html",
        return_value=index_html,
    ):
        sync_tn_result_index()

    election.refresh_from_db()
    urls = [link["url"] for link in election.source_metadata["tn_result_links"]]
    assert len(urls) == len(set(urls))
