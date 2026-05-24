"""
Tests for Iowa SOS Celery tasks.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from elections.models import Candidate, Election, Race
from ops.models import SyncLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PARSED_ELECTION = {
    "name": "2026 Iowa Primary Election",
    "election_date": "2026-06-02",
    "election_year": 2026,
    "election_type": "primary",
}

PARSED_CANDIDATES = [
    {"office": "Governor", "candidate_name": "Jane Smith", "party": "DEM", "district": ""},
    {"office": "Governor", "candidate_name": "Bob Jones", "party": "REP", "district": ""},
    {"office": "U.S. Senator", "candidate_name": "Alice Green", "party": "DEM", "district": ""},
]


# ---------------------------------------------------------------------------
# sync_ia_elections
# ---------------------------------------------------------------------------

@pytest.mark.django_db
@patch("integrations.ia_sos.tasks.IowaSosClient")
@patch("integrations.ia_sos.tasks.parse_calendar_pdf", return_value=[PARSED_ELECTION])
@patch("integrations.ia_sos.tasks.cache")
def test_sync_ia_elections_creates_election(MockCache, mock_parse, MockClient):
    """Stage 1 should create an Election record from the calendar PDF."""
    MockClient.return_value.fetch_calendar_pdf.return_value = b"%PDF"
    MockClient.return_value.get_candidate_pdf_info.return_value = None  # no PDFs
    MockCache.get.return_value = None

    from integrations.ia_sos.tasks import sync_ia_elections
    result = sync_ia_elections()

    assert Election.objects.filter(source_id="ia_sos_2026_primary").exists()
    assert result["created"] == 1
    assert result["updated"] == 0


@pytest.mark.django_db
@patch("integrations.ia_sos.tasks.IowaSosClient")
@patch("integrations.ia_sos.tasks.parse_calendar_pdf", return_value=[PARSED_ELECTION])
@patch("integrations.ia_sos.tasks.cache")
def test_sync_ia_elections_idempotent(MockCache, mock_parse, MockClient):
    """Running sync twice should increment updated, not created again."""
    MockClient.return_value.fetch_calendar_pdf.return_value = b"%PDF"
    MockClient.return_value.get_candidate_pdf_info.return_value = None
    MockCache.get.return_value = None

    from integrations.ia_sos.tasks import sync_ia_elections
    sync_ia_elections()
    result = sync_ia_elections()

    assert Election.objects.filter(source_id="ia_sos_2026_primary").count() == 1
    assert result["updated"] == 1


@pytest.mark.django_db
@patch("integrations.ia_sos.tasks.IowaSosClient")
@patch("integrations.ia_sos.tasks.parse_calendar_pdf", return_value=[PARSED_ELECTION])
@patch("integrations.ia_sos.tasks.sync_ia_candidates")
@patch("integrations.ia_sos.tasks.cache")
def test_sync_ia_elections_queues_candidate_sync_on_new_pdf(
    MockCache, mock_sync_cands, mock_parse, MockClient
):
    """Stage 1 should queue Stage 2 when the candidate PDF fingerprint is new."""
    pdf_info = {
        "url": "https://sos.iowa.gov/elections/pdf/candidates_primary.pdf",
        "etag": '"abc123"',
        "last_modified": "Mon, 01 Jan 2026",
    }
    MockClient.return_value.fetch_calendar_pdf.return_value = b"%PDF"
    MockClient.return_value.get_candidate_pdf_info.return_value = pdf_info
    MockCache.get.return_value = None  # no cached fingerprint → new PDF

    # Ensure the election record exists so _resolve_election_for_type finds it
    Election.objects.create(
        source_id="ia_sos_2026_primary",
        name="2026 Iowa Primary Election",
        election_date=date(2026, 6, 2),
        state="IA",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.UPCOMING,
    )

    from integrations.ia_sos.tasks import sync_ia_elections
    result = sync_ia_elections()

    mock_sync_cands.delay.assert_called_once()
    assert result["queued"] == 1


@pytest.mark.django_db
@patch("integrations.ia_sos.tasks.IowaSosClient")
@patch("integrations.ia_sos.tasks.parse_calendar_pdf", return_value=[PARSED_ELECTION])
@patch("integrations.ia_sos.tasks.sync_ia_candidates")
@patch("integrations.ia_sos.tasks.cache")
def test_sync_ia_elections_skips_unchanged_pdf(
    MockCache, mock_sync_cands, mock_parse, MockClient
):
    """Stage 1 should NOT re-queue Stage 2 if the PDF fingerprint is unchanged."""
    existing_fingerprint = "https://sos.iowa.gov/elections/pdf/candidates.pdf||"
    pdf_info = {
        "url": "https://sos.iowa.gov/elections/pdf/candidates.pdf",
        "etag": "",
        "last_modified": "",
    }
    MockClient.return_value.fetch_calendar_pdf.return_value = b"%PDF"
    MockClient.return_value.get_candidate_pdf_info.return_value = pdf_info
    MockCache.get.return_value = existing_fingerprint  # cached → no change

    from integrations.ia_sos.tasks import sync_ia_elections
    result = sync_ia_elections()

    mock_sync_cands.delay.assert_not_called()
    assert result["queued"] == 0


@pytest.mark.django_db
@patch("integrations.ia_sos.tasks.IowaSosClient")
@patch("integrations.ia_sos.tasks.parse_calendar_pdf")
@patch("integrations.ia_sos.tasks.cache")
def test_sync_ia_elections_records_synclog(MockCache, mock_parse, MockClient):
    mock_parse.return_value = [PARSED_ELECTION]
    MockClient.return_value.fetch_calendar_pdf.return_value = b"%PDF"
    MockClient.return_value.get_candidate_pdf_info.return_value = None
    MockCache.get.return_value = None

    from integrations.ia_sos.tasks import sync_ia_elections
    sync_ia_elections()

    assert SyncLog.objects.filter(source="ia_sos", status=SyncLog.Status.COMPLETED).exists()


# ---------------------------------------------------------------------------
# sync_ia_candidates
# ---------------------------------------------------------------------------

@pytest.mark.django_db
@patch("integrations.ia_sos.tasks.IowaSosClient")
@patch("integrations.ia_sos.tasks.parse_candidate_list_pdf", return_value=PARSED_CANDIDATES)
@patch("integrations.ia_sos.tasks.cache")
def test_sync_ia_candidates_creates_races_and_candidates(MockCache, mock_parse, MockClient):
    """Stage 2 should upsert Race + Candidate records from a candidate PDF."""
    MockClient.return_value.fetch_pdf.return_value = b"%PDF"
    MockCache.get.return_value = None

    election = Election.objects.create(
        source_id="ia_sos_2026_primary",
        name="2026 Iowa Primary Election",
        election_date=date(2026, 6, 2),
        state="IA",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.UPCOMING,
    )

    from integrations.ia_sos.tasks import sync_ia_candidates
    result = sync_ia_candidates(
        election.pk,
        "https://sos.iowa.gov/elections/pdf/candidates.pdf",
        "url||",
        "ia_sos:candidate_pdf_fingerprint:primary",
    )

    assert Race.objects.filter(election=election).exists()
    assert Candidate.objects.filter(race__election=election).exists()
    assert result["created"] > 0


@pytest.mark.django_db
@patch("integrations.ia_sos.tasks.IowaSosClient")
@patch("integrations.ia_sos.tasks.parse_candidate_list_pdf")
@patch("integrations.ia_sos.tasks.cache")
def test_sync_ia_candidates_marks_withdrawn(MockCache, mock_parse, MockClient):
    """
    Candidates in the DB but absent from the latest PDF should be marked WITHDRAWN.
    """
    MockClient.return_value.fetch_pdf.return_value = b"%PDF"
    MockCache.get.return_value = None

    election = Election.objects.create(
        source_id="ia_sos_2026_primary",
        name="2026 Iowa Primary Election",
        election_date=date(2026, 6, 2),
        state="IA",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.UPCOMING,
    )
    race = Race.objects.create(
        election=election,
        office_title="Governor",
        jurisdiction="Iowa",
        geography_scope="statewide",
        race_type=Race.RaceType.CANDIDATE,
        source=Race.Source.IA_SOS,
        canonical_key="ia_sos:ia_sos_2026_primary:governor:statewide:dem",
        certification_status=Race.CertificationStatus.UPCOMING,
    )
    # This candidate is in the DB but not in the next PDF run
    withdrawn = Candidate.objects.create(
        race=race,
        name="Old Candidate",
        candidate_status=Candidate.CandidateStatus.RUNNING,
    )

    # PDF now only has one candidate, not "Old Candidate"
    mock_parse.return_value = [
        {"office": "Governor", "candidate_name": "Jane Smith", "party": "DEM", "district": ""},
    ]

    from integrations.ia_sos.tasks import sync_ia_candidates
    result = sync_ia_candidates(
        election.pk,
        "https://sos.iowa.gov/elections/pdf/candidates.pdf",
        "url||",
        "ia_sos:candidate_pdf_fingerprint:primary",
    )

    withdrawn.refresh_from_db()
    assert withdrawn.candidate_status == Candidate.CandidateStatus.WITHDRAWN
    assert result["withdrawn"] == 1


@pytest.mark.django_db
@patch("integrations.ia_sos.tasks.IowaSosClient")
@patch("integrations.ia_sos.tasks.parse_candidate_list_pdf", return_value=[])
@patch("integrations.ia_sos.tasks.cache")
def test_sync_ia_candidates_handles_empty_pdf(MockCache, mock_parse, MockClient):
    """Stage 2 should complete without error when PDF yields no candidates."""
    MockClient.return_value.fetch_pdf.return_value = b"%PDF"
    MockCache.get.return_value = None

    election = Election.objects.create(
        source_id="ia_sos_2026_primary",
        name="2026 Iowa Primary Election",
        election_date=date(2026, 6, 2),
        state="IA",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.UPCOMING,
    )

    from integrations.ia_sos.tasks import sync_ia_candidates
    result = sync_ia_candidates(
        election.pk,
        "https://sos.iowa.gov/elections/pdf/candidates.pdf",
        "url||",
        "ia_sos:candidate_pdf_fingerprint:primary",
    )

    assert result["created"] == 0
    assert result["withdrawn"] == 0


@pytest.mark.django_db
def test_sync_ia_candidates_missing_election():
    """Stage 2 should log and return gracefully when the election does not exist."""
    from integrations.ia_sos.tasks import sync_ia_candidates
    result = sync_ia_candidates(99999, "https://sos.iowa.gov/elections/pdf/x.pdf", "", "key")
    assert result is None
