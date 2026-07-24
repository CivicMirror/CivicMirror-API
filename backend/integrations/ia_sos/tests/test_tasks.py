"""
Tests for Iowa SOS Celery tasks.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from elections.models import Candidate, Election, ElectionSourceLink, Race
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
    MockClient.return_value.get_results_url.return_value = None
    MockCache.get.return_value = None

    from integrations.ia_sos.tasks import sync_ia_elections
    result = sync_ia_elections()

    assert ElectionSourceLink.objects.filter(
        source="ia_sos", source_id="ia_sos_2026_primary"
    ).exists()
    assert result["created"] == 1
    assert result["updated"] == 0


@pytest.mark.django_db
@patch("integrations.ia_sos.tasks.IowaSosClient")
@patch("integrations.ia_sos.tasks.parse_calendar_pdf", return_value=[PARSED_ELECTION])
@patch("integrations.ia_sos.tasks.cache")
def test_sync_ia_elections_sets_results_url(MockCache, mock_parse, MockClient):
    MockClient.return_value.fetch_calendar_pdf.return_value = b"%PDF"
    MockClient.return_value.get_candidate_pdf_info.return_value = None
    MockClient.return_value.get_results_url.return_value = "https://electionresults.iowa.gov/IA/123456/"
    MockCache.get.return_value = None

    from integrations.ia_sos.tasks import sync_ia_elections

    sync_ia_elections()

    election = Election.objects.get(state="IA", election_type="primary", election_date=date(2026, 6, 2))
    assert election.results_url == "https://electionresults.iowa.gov/IA/123456/"


@pytest.mark.django_db
@patch("integrations.ia_sos.tasks.IowaSosClient")
@patch("integrations.ia_sos.tasks.parse_calendar_pdf", return_value=[PARSED_ELECTION])
@patch("integrations.ia_sos.tasks.cache")
def test_sync_ia_elections_continues_when_results_url_discovery_fails(MockCache, mock_parse, MockClient):
    """A results portal error must not prevent calendar election ingestion."""
    MockClient.return_value.fetch_calendar_pdf.return_value = b"%PDF"
    MockClient.return_value.get_candidate_pdf_info.return_value = None
    MockClient.return_value.get_results_url.side_effect = RuntimeError("Clarity unavailable")
    MockCache.get.return_value = None

    from integrations.ia_sos.tasks import sync_ia_elections

    result = sync_ia_elections()

    assert result["created"] == 1
    election = Election.objects.get(state="IA", election_type="primary", election_date=date(2026, 6, 2))
    assert election.results_url == ""


@pytest.mark.django_db
@patch("integrations.ia_sos.tasks.IowaSosClient")
@patch("integrations.ia_sos.tasks.parse_calendar_pdf", return_value=[PARSED_ELECTION])
@patch("integrations.ia_sos.tasks.cache")
def test_sync_ia_elections_idempotent(MockCache, mock_parse, MockClient):
    """Running sync twice should increment updated, not created again."""
    MockClient.return_value.fetch_calendar_pdf.return_value = b"%PDF"
    MockClient.return_value.get_candidate_pdf_info.return_value = None
    MockClient.return_value.get_results_url.return_value = None
    MockCache.get.return_value = None

    from integrations.ia_sos.tasks import sync_ia_elections
    sync_ia_elections()
    result = sync_ia_elections()

    assert ElectionSourceLink.objects.filter(source="ia_sos", source_id="ia_sos_2026_primary").count() == 1
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
    MockClient.return_value.get_results_url.return_value = None
    MockCache.get.return_value = None  # no cached fingerprint → new PDF

    from integrations.ia_sos.tasks import sync_ia_elections
    result = sync_ia_elections()

    # After ingest, election is looked up from the dict built in the ingest loop
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
    MockClient.return_value.get_results_url.return_value = None
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
    MockClient.return_value.get_results_url.return_value = None
    MockCache.get.return_value = None

    from integrations.ia_sos.tasks import sync_ia_elections
    sync_ia_elections()

    assert SyncLog.objects.filter(source="ia_sos", status=SyncLog.Status.COMPLETED).exists()


@pytest.mark.django_db
@patch("integrations.ia_sos.tasks.IowaSosClient")
@patch("integrations.ia_sos.tasks.parse_calendar_pdf")
@patch("integrations.ia_sos.tasks.sync_ia_candidates")
@patch("integrations.ia_sos.tasks.cache")
def test_sync_ia_elections_queues_2026_primary_pdf_for_2026_primary(
    MockCache, mock_sync_cands, mock_parse, MockClient
):
    parsed_2026_primary = {
        "name": "2026 Iowa Primary Election",
        "election_date": "2026-06-02",
        "election_year": 2026,
        "election_type": "primary",
    }
    parsed_2027_primary = {
        "name": "2027 Iowa Primary Election",
        "election_date": "2027-10-05",
        "election_year": 2027,
        "election_type": "primary",
    }
    pdf_info = {
        "url": "https://sos.iowa.gov/sites/default/files/2026-04/2026%20Primary%20-%20Candidate%20List.pdf",
        "etag": '"abc123"',
        "last_modified": "Wed, 22 Apr 2026 21:27:05 GMT",
    }
    MockClient.return_value.fetch_calendar_pdf.return_value = b"%PDF"
    MockClient.return_value.get_candidate_pdf_info.side_effect = [pdf_info, None]
    MockClient.return_value.get_results_url.return_value = None
    mock_parse.return_value = [parsed_2026_primary, parsed_2027_primary]
    MockCache.get.return_value = None

    from integrations.ia_sos.tasks import sync_ia_elections

    result = sync_ia_elections()

    assert result["queued"] == 1
    queued_election_pk = mock_sync_cands.delay.call_args.args[0]
    queued_election = Election.objects.get(pk=queued_election_pk)
    assert queued_election.election_date == date(2026, 6, 2)
    assert ElectionSourceLink.objects.filter(
        election=queued_election,
        source="ia_sos",
        source_id="ia_sos_2026_primary",
    ).exists()


# ---------------------------------------------------------------------------
# sync_ia_candidates
# ---------------------------------------------------------------------------

@pytest.mark.django_db
@patch("integrations.ia_sos.tasks.IowaSosClient")
@patch("integrations.ia_sos.tasks.parse_candidate_list_pdf", return_value=PARSED_CANDIDATES)
@patch("integrations.ia_sos.tasks.cache")
def test_sync_ia_candidates_creates_races_and_candidates(MockCache, mock_parse, MockClient):
    """Stage 2 should upsert Race + Candidate records from a candidate PDF."""
    from aggregation.models import SourcePrecedence
    MockClient.return_value.fetch_pdf.return_value = b"%PDF"
    MockCache.get.return_value = None

    SourcePrecedence.objects.get_or_create(state="*", field_group="*", source="civic_api", defaults={"rank": 0})
    election = Election.objects.create(
        canonical_key="IA:primary:2026-06-02:state",
        name="2026 Iowa Primary Election",
        election_date=date(2026, 6, 2),
        election_type="primary",
        state="IA",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.UPCOMING,
        contributing_sources=["ia_sos"],
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
    from aggregation.models import SourcePrecedence
    MockClient.return_value.fetch_pdf.return_value = b"%PDF"
    MockCache.get.return_value = None

    SourcePrecedence.objects.get_or_create(state="*", field_group="*", source="civic_api", defaults={"rank": 0})
    election = Election.objects.create(
        canonical_key="IA:primary:2026-06-02:state",
        name="2026 Iowa Primary Election",
        election_date=date(2026, 6, 2),
        election_type="primary",
        state="IA",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.UPCOMING,
        contributing_sources=["ia_sos"],
    )
    race = Race.objects.create(
        election=election,
        office_title="Governor",
        jurisdiction="Iowa",
        geography_scope="statewide",
        race_type=Race.RaceType.CANDIDATE,
        source=Race.Source.IA_SOS,
        canonical_key="IA:primary:2026-06-02:state|governor:statewide:candidate",
        certification_status=Race.CertificationStatus.UPCOMING,
        contributing_sources=["ia_sos"],
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
        canonical_key="IA:primary:2026-06-02:state",
        name="2026 Iowa Primary Election",
        election_date=date(2026, 6, 2),
        election_type="primary",
        state="IA",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        status=Election.Status.UPCOMING,
        contributing_sources=["ia_sos"],
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
    MockCache.set.assert_not_called()


@pytest.mark.django_db
def test_sync_ia_candidates_missing_election():
    """Stage 2 should log and return gracefully when the election does not exist."""
    from integrations.ia_sos.tasks import sync_ia_candidates
    result = sync_ia_candidates(99999, "https://sos.iowa.gov/elections/pdf/x.pdf", "", "key")
    assert result is None


# ---------------------------------------------------------------------------
# Integration tests — ingest service routing (real DB)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_sync_ia_elections_routes_through_ingest_service():
    """Each IA election lands as a canonical Election with contributing_sources=['ia_sos']."""
    from aggregation.models import SourcePrecedence
    from elections.models import ElectionSourceLink
    from integrations.ia_sos.tasks import sync_ia_elections

    SourcePrecedence.objects.get_or_create(state="*", field_group="*", source="civic_api", defaults={"rank": 0})

    with (
        patch("integrations.ia_sos.tasks.IowaSosClient") as MockClient,
        patch("integrations.ia_sos.tasks.parse_calendar_pdf", return_value=[PARSED_ELECTION]),
        patch("integrations.ia_sos.tasks.cache") as mock_cache,
        patch("integrations.ia_sos.tasks.sync_ia_candidates"),
    ):
        MockClient.return_value.fetch_calendar_pdf.return_value = b"%PDF"
        MockClient.return_value.get_candidate_pdf_info.return_value = None
        MockClient.return_value.get_results_url.return_value = None
        mock_cache.get.return_value = None
        sync_ia_elections()

    link = ElectionSourceLink.objects.filter(source="ia_sos", source_id="ia_sos_2026_primary").first()
    assert link is not None
    assert "ia_sos" in link.election.contributing_sources
    assert link.election.canonical_key.startswith("IA:")


@pytest.mark.django_db
def test_sync_ia_candidates_routes_through_ingest_service():
    """sync_ia_candidates writes canonical Race + Candidate via ingest."""
    from aggregation.models import SourcePrecedence
    from elections.models import Candidate, Election, Race
    from integrations.ia_sos.tasks import sync_ia_candidates

    SourcePrecedence.objects.get_or_create(state="*", field_group="*", source="civic_api", defaults={"rank": 0})

    e = Election.objects.create(
        name="2026 Iowa Primary Election",
        election_date=date(2026, 6, 2),
        election_type="primary",
        jurisdiction_level="state",
        state="IA",
        canonical_key="IA:primary:2026-06-02:state",
        contributing_sources=["ia_sos"],
    )

    html = [
        {"office": "Governor", "candidate_name": "Alice Johnson", "party": "DEM", "district": ""},
    ]

    with (
        patch("integrations.ia_sos.tasks.IowaSosClient") as MockClient,
        patch("integrations.ia_sos.tasks.parse_candidate_list_pdf", return_value=html),
        patch("integrations.ia_sos.tasks.cache") as mock_cache,
    ):
        MockClient.return_value.fetch_pdf.return_value = b"%PDF"
        mock_cache.set = MagicMock()
        sync_ia_candidates(e.pk, "https://sos.iowa.gov/candidates.pdf", "fp123", "ia_sos:fingerprint:primary")

    race = Race.objects.filter(election=e).first()
    assert race is not None
    assert "ia_sos" in race.contributing_sources
    cands = list(Candidate.objects.filter(race=race))
    assert len(cands) == 1
    assert cands[0].name == "Alice Johnson"
