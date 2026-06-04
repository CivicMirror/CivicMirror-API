"""Integration tests for az_sos tasks. HTTP calls are mocked."""
from unittest.mock import MagicMock, patch

import pytest

from integrations.az_sos.parsers import CandidateDetailData, CandidateListEntry


@pytest.fixture
def mock_entries():
    return [
        CandidateListEntry("STATE - EXECUTIVE", "Governor", 5577, "Katie Hobbs", "Democratic", False),
        CandidateListEntry("STATE - EXECUTIVE", "Governor", 5601, "Andy Biggs", "Republican", False),
        CandidateListEntry("FEDERAL - LEGISLATIVE", "U.S. House of Rep. - District 1", 5780, "Amish Shah", "Democratic", False),
    ]


@pytest.mark.django_db
def test_sync_elections_creates_election_records(mock_entries):
    from elections.models import Election
    from integrations.az_sos.tasks import sync_az_elections

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.az_sos.tasks.cache") as mc, \
         patch("integrations.az_sos.tasks.sync_az_candidate_details"):
        MC.return_value.fetch_candidate_list.return_value = b"<html>mock</html>"
        mc.get.return_value = None

        sync_az_elections.apply()

    assert Election.objects.filter(state="AZ", election_type="primary").exists()
    assert Election.objects.filter(state="AZ", election_type="general").exists()


@pytest.mark.django_db
def test_sync_elections_creates_races(mock_entries):
    from elections.models import Race
    from integrations.az_sos.tasks import sync_az_elections

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.az_sos.tasks.cache") as mc, \
         patch("integrations.az_sos.tasks.sync_az_candidate_details"):
        MC.return_value.fetch_candidate_list.return_value = b"<html>mock</html>"
        mc.get.return_value = None

        sync_az_elections.apply()

    # Race has no direct state field — use election__state
    assert Race.objects.filter(election__state="AZ", office_title="Governor").exists()
    assert Race.objects.filter(election__state="AZ", office_title="U.S. House - District 1").exists()


@pytest.mark.django_db
def test_sync_elections_creates_candidates(mock_entries):
    from elections.models import Candidate
    from integrations.az_sos.tasks import sync_az_elections

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.az_sos.tasks.cache") as mc, \
         patch("integrations.az_sos.tasks.sync_az_candidate_details"):
        MC.return_value.fetch_candidate_list.return_value = b"<html>mock</html>"
        mc.get.return_value = None

        sync_az_elections.apply()

    assert Candidate.objects.filter(name="Katie Hobbs").exists()
    assert Candidate.objects.filter(name="Amish Shah").exists()


@pytest.mark.django_db
def test_sync_elections_skips_candidate_parsing_on_unchanged_fingerprint(mock_entries):
    """Elections are always seeded; candidate parsing is skipped on unchanged fingerprint."""
    import hashlib

    from elections.models import Election
    from integrations.az_sos.tasks import sync_az_elections

    html = b"<html>mock</html>"
    fp = hashlib.md5(html).hexdigest()

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_list") as mock_parse, \
         patch("integrations.az_sos.tasks.cache") as mc, \
         patch("integrations.az_sos.tasks.sync_az_candidate_details"):
        MC.return_value.fetch_candidate_list.return_value = html
        mc.get.return_value = fp  # fingerprint matches → skip candidate parsing

        sync_az_elections.apply()

    # Elections ARE seeded even on fingerprint match
    assert Election.objects.filter(state="AZ", election_type="primary").exists()
    # Candidate parsing is NOT called
    mock_parse.assert_not_called()


@pytest.mark.django_db
def test_sync_elections_uses_stable_candidate_id_for_dedup(mock_entries):
    """Second sync with same candidates should not create duplicates."""
    from elections.models import Candidate
    from integrations.az_sos.tasks import sync_az_elections

    def run():
        with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
             patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries), \
             patch("integrations.az_sos.tasks.cache") as mc, \
             patch("integrations.az_sos.tasks.sync_az_candidate_details"):
            MC.return_value.fetch_candidate_list.return_value = b"<html>mock</html>"
            mc.get.return_value = None
            sync_az_elections.apply()

    run()
    count_after_first = Candidate.objects.filter(name="Katie Hobbs").count()
    run()
    count_after_second = Candidate.objects.filter(name="Katie Hobbs").count()
    assert count_after_first == count_after_second == 1


@pytest.mark.django_db
def test_sync_elections_queues_detail_task(mock_entries):
    from integrations.az_sos.tasks import sync_az_elections

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.az_sos.tasks.cache") as mc, \
         patch("integrations.az_sos.tasks.sync_az_candidate_details") as mock_detail:
        MC.return_value.fetch_candidate_list.return_value = b"<html>mock</html>"
        mc.get.return_value = None

        sync_az_elections.apply()

    mock_detail.delay.assert_called_once()


@pytest.mark.django_db
def test_sync_candidate_details_enriches_metadata(mock_entries):
    from elections.models import Candidate, Election
    from integrations.az_sos.tasks import sync_az_candidate_details, sync_az_elections

    detail = CandidateDetailData(
        name="Katie Hobbs",
        website_url="https://katiehobbs.org/",
        bio="Katie Hobbs bio text.",
        funding_type="Traditional Funding",
        facebook="https://facebook.com/hobbskatie",
    )

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.az_sos.tasks.cache") as mc, \
         patch("integrations.az_sos.tasks.sync_az_candidate_details"):
        MC.return_value.fetch_candidate_list.return_value = b"<html>mock</html>"
        mc.get.return_value = None
        sync_az_elections.apply()

    election_pk = Election.objects.get(state="AZ", election_type="primary").pk

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_detail", return_value=detail):
        MC.return_value.fetch_candidate_detail.return_value = b"<article>mock</article>"
        sync_az_candidate_details.apply(args=[election_pk])

    hobbs = Candidate.objects.get(name="Katie Hobbs")
    assert hobbs.source_metadata.get("az_website") == "https://katiehobbs.org/"
    assert hobbs.source_metadata.get("az_bio") == "Katie Hobbs bio text."
    assert hobbs.source_metadata.get("az_facebook") == "https://facebook.com/hobbskatie"


@pytest.mark.django_db
def test_sync_candidate_details_skips_already_enriched(mock_entries):
    """Candidates with az_bio in source_metadata should not be re-fetched."""
    from elections.models import Candidate, Election
    from integrations.az_sos.tasks import sync_az_candidate_details, sync_az_elections

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.az_sos.tasks.cache") as mc, \
         patch("integrations.az_sos.tasks.sync_az_candidate_details"):
        MC.return_value.fetch_candidate_list.return_value = b"<html>mock</html>"
        mc.get.return_value = None
        sync_az_elections.apply()

    # Pre-populate az_bio to simulate already-enriched candidates
    Candidate.objects.filter(name="Katie Hobbs").update(
        source_metadata={"az_candidate_id": 5577, "az_bio": "existing bio"}
    )

    election_pk = Election.objects.get(state="AZ", election_type="primary").pk

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_detail",
               return_value=CandidateDetailData(name="Amish Shah", bio="shah bio")):
        MC.return_value.fetch_candidate_detail.return_value = b"<article>mock</article>"
        sync_az_candidate_details.apply(args=[election_pk])

    # Hobbs should NOT have been re-fetched — az_bio unchanged
    hobbs = Candidate.objects.get(name="Katie Hobbs")
    assert hobbs.source_metadata.get("az_bio") == "existing bio"
