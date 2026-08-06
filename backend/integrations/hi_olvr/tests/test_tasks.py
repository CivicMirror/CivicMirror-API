from __future__ import annotations

import textwrap
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db


_CSV = textwrap.dedent("""\
    "Contests","Party","BallotName","LegalName","MailingAddress","CityStateZip","Phone","Email","Website","IssueDate","FilingDate","Status"
    "U.S. REPRESENTATIVE, DIST I","DEMOCRATIC","BELATTI, Della Au","DELLA AU BELATTI ","P.O. BOX 900","HONOLULU, HI 96808","8083930594","della@example.com","www.della.example","02/17/2026","06/01/2026","In Primary"
    "U.S. REPRESENTATIVE, DIST I","REPUBLICAN","MCCARTNEY, Joe","JOE MCCARTNEY","P.O. BOX 1","HONOLULU, HI 96808","8085551212","joe@example.com","www.joe.example","03/01/2026","06/02/2026","In Primary"
    "GOVERNOR","DEMOCRATIC","ISSUED ONLY","ISSUED ONLY","","","","","","02/17/2026","","Issued"
""").encode()


@patch("integrations.hi_olvr.tasks.HawaiiOlvrClient")
def test_sync_hi_elections_ingests_primary_races_and_candidates(mock_client_cls):
    from elections.models import Candidate, Election, Race
    from integrations.hi_olvr.tasks import sync_hi_elections

    client = mock_client_cls.return_value
    client.resolve_candidate_report.return_value = (
        '<a href="https://elections.hawaii.gov/candidates/candidate-reports/">Candidate Report</a>',
        "https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=94",
        "94",
    )
    client.fetch_candidate_report_csv.return_value = _CSV

    result = sync_hi_elections()

    election = Election.objects.get(state="HI", election_type="primary")
    races = list(Race.objects.filter(election=election).order_by("party"))
    candidates = list(Candidate.objects.filter(race__election=election).order_by("name"))

    assert result["rows"] == 2
    assert election.name == "2026 Hawaii Primary Election"
    assert len(races) == 2
    assert {race.party for race in races} == {"DEMOCRATIC", "REPUBLICAN"}
    assert len(candidates) == 2
    assert {candidate.name for candidate in candidates} == {"BELATTI, Della Au", "MCCARTNEY, Joe"}
    assert candidates[0].source_metadata["hi_olvr_legal_name"] == "DELLA AU BELATTI"
    assert not Candidate.objects.filter(name="ISSUED ONLY").exists()


# After the primary the portal advances each surviving candidate's status.
# The pre-election sync sees "In Primary"; the post-election sync sees the
# advanced statuses for the same people.
_CSV_POST_ELECTION = textwrap.dedent("""\
    "Contests","Party","BallotName","LegalName","MailingAddress","CityStateZip","Phone","Email","Website","IssueDate","FilingDate","Status"
    "U.S. REPRESENTATIVE, DIST I","DEMOCRATIC","BELATTI, Della Au","DELLA AU BELATTI ","P.O. BOX 900","HONOLULU, HI 96808","8083930594","della@example.com","www.della.example","02/17/2026","06/01/2026","Elected After Primary"
    "U.S. REPRESENTATIVE, DIST I","REPUBLICAN","MCCARTNEY, Joe","JOE MCCARTNEY","P.O. BOX 1","HONOLULU, HI 96808","8085551212","joe@example.com","www.joe.example","03/01/2026","06/02/2026","In General"
""").encode()


@patch("integrations.hi_olvr.tasks.HawaiiOlvrClient")
def test_sync_hi_elections_keeps_advanced_candidates_running(mock_client_cls):
    """Primary winners must not be marked WITHDRAWN once their status advances."""
    from elections.models import Candidate
    from integrations.hi_olvr.tasks import sync_hi_elections

    client = mock_client_cls.return_value
    client.resolve_candidate_report.return_value = (
        '<a href="https://elections.hawaii.gov/candidates/candidate-reports/">Candidate Report</a>',
        "https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=94",
        "94",
    )

    client.fetch_candidate_report_csv.return_value = _CSV
    sync_hi_elections()

    client.fetch_candidate_report_csv.return_value = _CSV_POST_ELECTION
    result = sync_hi_elections()

    assert result["withdrawn"] == 0
    statuses = {c.name: c.candidate_status for c in Candidate.objects.all()}
    assert statuses["BELATTI, Della Au"] == Candidate.CandidateStatus.RUNNING
    assert statuses["MCCARTNEY, Joe"] == Candidate.CandidateStatus.RUNNING


@patch("integrations.hi_olvr.tasks.HawaiiOlvrClient")
def test_sync_hi_elections_passes_expected_elid(mock_client_cls):
    from integrations.hi_olvr.tasks import sync_hi_elections

    client = mock_client_cls.return_value
    client.resolve_candidate_report.return_value = (
        "<a>Candidate Report</a>",
        "https://olvr.hawaii.gov/Controls/CandidateFiling.aspx?elid=94",
        "94",
    )
    client.fetch_candidate_report_csv.return_value = _CSV

    sync_hi_elections()

    assert client.fetch_candidate_report_csv.call_args.kwargs["expected_elid"] == "94"
