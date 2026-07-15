from unittest.mock import patch

import pytest

from elections.models import Candidate, Election, Race
from integrations.mi_sos.tasks import sync_mi_elections


@pytest.fixture
def parsed_candidate_rows():
    return [
        {
            "office_title": "GOVERNOR 4 Year Term (1) Position",
            "party": "Democratic",
            "incumbent": "",
            "filing_method": "Petitions",
            "status": "",
            "candidate_name": "Jane Candidate",
            "candidate_address": "1 Main St",
            "filed_on": "4/21/2026",
        },
        {
            "office_title": "UNITED STATES REPRESENTATIVE 7th District",
            "party": "Republican",
            "incumbent": "Incumbent",
            "filing_method": "Petitions",
            "status": "DISQ",
            "candidate_name": "John Disqualified",
            "candidate_address": "2 Main St",
            "filed_on": "4/21/2026",
        },
    ]


@pytest.mark.django_db
def test_sync_mi_elections_creates_election_race_and_candidates(parsed_candidate_rows):
    with patch("integrations.mi_sos.tasks.MiSosClient") as client_cls, \
         patch("integrations.mi_sos.tasks.parse_boe_candidate_listing", return_value=parsed_candidate_rows):
        client_cls.return_value.fetch_candidate_listing.return_value = "<html>fixture</html>"
        result = sync_mi_elections()

    assert result["created"] >= 3
    election = Election.objects.get(state="MI", election_type="primary", election_date="2026-08-04")
    race = Race.objects.get(election=election, office_title="Governor")
    candidate = Candidate.objects.get(race=race, name="Jane Candidate")
    assert candidate.party == "DEM"
    assert candidate.candidate_status == Candidate.CandidateStatus.RUNNING

    house_race = Race.objects.get(election=election, office_title="U.S. House - District 7")
    disq = Candidate.objects.get(race=house_race, name="John Disqualified")
    assert disq.candidate_status == Candidate.CandidateStatus.DISQUALIFIED
    assert disq.source_metadata["mi_candidate_status_raw"] == "DISQ"


@pytest.mark.django_db
def test_sync_mi_elections_marks_absent_running_candidate_withdrawn(parsed_candidate_rows):
    with patch("integrations.mi_sos.tasks.MiSosClient") as client_cls, \
         patch("integrations.mi_sos.tasks.parse_boe_candidate_listing", return_value=parsed_candidate_rows):
        client_cls.return_value.fetch_candidate_listing.return_value = "<html>fixture</html>"
        sync_mi_elections()

    election = Election.objects.get(state="MI", election_type="primary", election_date="2026-08-04")
    race = Race.objects.get(election=election, office_title="Governor")
    stale = Candidate.objects.create(
        race=race,
        name="Stale Candidate",
        party="DEM",
        candidate_status=Candidate.CandidateStatus.RUNNING,
    )

    with patch("integrations.mi_sos.tasks.MiSosClient") as client_cls, \
         patch("integrations.mi_sos.tasks.parse_boe_candidate_listing", return_value=parsed_candidate_rows):
        client_cls.return_value.fetch_candidate_listing.return_value = "<html>fixture</html>"
        sync_mi_elections()

    stale.refresh_from_db()
    assert stale.candidate_status == Candidate.CandidateStatus.WITHDRAWN
