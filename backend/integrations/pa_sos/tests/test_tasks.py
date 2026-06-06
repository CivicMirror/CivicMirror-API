"""
Integration tests for pa_sos Celery tasks. All network and browser operations are mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from integrations.pa_sos.parsers import PaCandidateDetailData, PaCandidateListEntry


@pytest.fixture
def mock_entries():
    return [
        PaCandidateListEntry(
            candidate_id=161838,
            candidate_id_num="2026C0020",
            name="John Doe",
            party="Republican",
            status="Approved",
            type_val="Petition",
            office="REPRESENTATIVE IN THE GENERAL ASSEMBLY",
            district="55th Legislative District",
            election_name="2026 Primary Election",
            municipality="102 MAIN ST",
            county="YORK",
            primary_result=False,
            general_result=False,
            cf_online_url="https://campaignfinanceonline.beta.pa.gov/?Filer=2026C0020",
        ),
        PaCandidateListEntry(
            candidate_id=161839,
            candidate_id_num="2026C0021",
            name="Jane Smith",
            party="Democratic",
            status="Approved",
            type_val="Petition",
            office="REPRESENTATIVE IN THE GENERAL ASSEMBLY",
            district="55th Legislative District",
            election_name="2026 Primary Election",
            municipality="103 MAIN ST",
            county="YORK",
            primary_result=False,
            general_result=False,
            cf_online_url="https://campaignfinanceonline.beta.pa.gov/?Filer=2026C0021",
        ),
    ]


@pytest.mark.django_db
def test_sync_pa_elections_creates_elections(mock_entries):
    from elections.models import Election
    from integrations.pa_sos.tasks import sync_pa_elections

    with patch("integrations.pa_sos.tasks.PaSosClient") as MC, \
         patch("integrations.pa_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.pa_sos.tasks.cache") as mc, \
         patch("integrations.pa_sos.tasks.sync_pa_candidate_details"):
        # Mock client context manager
        mock_client = MC.return_value.__enter__.return_value
        mock_client.fetch_candidate_list.return_value = "[]"
        mc.get.return_value = None

        sync_pa_elections.apply()

    assert Election.objects.filter(state="PA", election_type="primary").exists()
    assert Election.objects.filter(state="PA", election_type="general").exists()


@pytest.mark.django_db
def test_sync_pa_elections_creates_races_and_candidates(mock_entries):
    from elections.models import Candidate, Race
    from integrations.pa_sos.tasks import sync_pa_elections

    with patch("integrations.pa_sos.tasks.PaSosClient") as MC, \
         patch("integrations.pa_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.pa_sos.tasks.cache") as mc, \
         patch("integrations.pa_sos.tasks.sync_pa_candidate_details"):
        mock_client = MC.return_value.__enter__.return_value
        mock_client.fetch_candidate_list.return_value = "[]"
        mc.get.return_value = None

        sync_pa_elections.apply()

    # Check race created with normalized office name
    assert Race.objects.filter(election__state="PA", office_title="State House - District 55").exists()

    # Check candidates created
    assert Candidate.objects.filter(name="John Doe", party="REP").exists()
    assert Candidate.objects.filter(name="Jane Smith", party="DEM").exists()


@pytest.mark.django_db
def test_sync_pa_elections_deduplication(mock_entries):
    from elections.models import Candidate
    from integrations.pa_sos.tasks import sync_pa_elections

    def run_sync():
        with patch("integrations.pa_sos.tasks.PaSosClient") as MC, \
             patch("integrations.pa_sos.tasks.parse_candidate_list", return_value=mock_entries), \
             patch("integrations.pa_sos.tasks.cache") as mc, \
             patch("integrations.pa_sos.tasks.sync_pa_candidate_details"):
            mock_client = MC.return_value.__enter__.return_value
            mock_client.fetch_candidate_list.return_value = "[]"
            mc.get.return_value = None
            sync_pa_elections.apply()

    run_sync()
    count1 = Candidate.objects.filter(name="John Doe", race__election__election_type="primary").count()
    run_sync()
    count2 = Candidate.objects.filter(name="John Doe", race__election__election_type="primary").count()

    assert count1 == count2 == 1


@pytest.mark.django_db
def test_sync_pa_candidate_details_enrichment(mock_entries):
    from elections.models import Candidate, Election
    from integrations.pa_sos.tasks import sync_pa_candidate_details, sync_pa_elections

    detail_data = PaCandidateDetailData(
        approved_date="02/10/2026 13:16:00",
        candidate_type="Petition",
        ballot_lottery="28",
        ballot_position="2",
        cross_filed="No",
        county="YORK",
        municipality="102 MAIN ST",
        cf_annual_totals_url="https://campaignfinanceonline.beta.pa.gov/?Filer=2026C0020",
    )

    # First run the list sync to populate candidates
    with patch("integrations.pa_sos.tasks.PaSosClient") as MC, \
         patch("integrations.pa_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.pa_sos.tasks.cache") as mc, \
         patch("integrations.pa_sos.tasks.sync_pa_candidate_details"):
        mock_client = MC.return_value.__enter__.return_value
        mock_client.fetch_candidate_list.return_value = "[]"
        mc.get.return_value = None
        sync_pa_elections.apply()

    primary_election = Election.objects.get(state="PA", election_type="primary")

    # Run the detail task
    with patch("integrations.pa_sos.tasks.PaSosClient") as MC, \
         patch("integrations.pa_sos.tasks.parse_candidate_detail", return_value=detail_data):
        mock_client = MC.return_value.__enter__.return_value
        mock_client.fetch_candidate_detail.return_value = "<html>mock</html>"
        sync_pa_candidate_details.apply(args=[primary_election.pk])

    doe = Candidate.objects.get(name="John Doe")
    assert doe.source_metadata.get("pa_approved_date") == "02/10/2026 13:16:00"
    assert doe.source_metadata.get("pa_ballot_lottery") == "28"
    assert doe.source_metadata.get("pa_ballot_position") == "2"
    assert doe.source_metadata.get("pa_cross_filed") == "No"
    assert doe.source_metadata.get("pa_details_enriched") is True
