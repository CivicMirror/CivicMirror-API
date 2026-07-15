import os
from unittest.mock import patch

import pytest

from elections.models import Candidate, Election, Race
from integrations.ky_sos.tasks import sync_ky_sos

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


@pytest.mark.django_db
def test_sync_ky_sos_creates_election_races_and_candidates():
    directory_html = _load_fixture("office_directory.html")
    senator_html = _load_fixture("office_us_senator.html")
    rep_html = _load_fixture("office_us_representative.html")
    withdrawn_html = _load_fixture("withdrawn.html")

    def fake_fetch_office(office_id):
        return {3: senator_html, 4: rep_html}.get(office_id, "<html></html>")

    with patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_directory",
        return_value=directory_html,
    ), patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_office",
        side_effect=fake_fetch_office,
    ), patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_withdrawn",
        return_value=withdrawn_html,
    ):
        result = sync_ky_sos()

    election = Election.objects.get(state="KY")
    assert election.election_type == "general"
    assert election.election_date.isoformat() == "2026-11-03"

    # US Senator: statewide race, 4 candidates (from fixture)
    senator_race = Race.objects.get(election=election, office_title="US Senator")
    assert senator_race.candidates.count() == 4
    assert senator_race.source == Race.Source.KY_SOS

    # US Representative: 6 district races from the 21-row fixture
    rep_races = Race.objects.filter(election=election, office_title__startswith="US Representative")
    assert rep_races.count() == 6

    # State Senator / State Representative office ids (11, 12) weren't mocked
    # with real fixtures above, so they fetch "<html></html>" and parse to
    # zero rows/races — that's fine, this test only asserts the two mocked
    # groups landed correctly.

    # Withdrawn candidate ingested with WITHDRAWN status on its own race.
    withdrawn_candidate = Candidate.objects.get(name="Alisha Dawn Chaffin")
    assert withdrawn_candidate.candidate_status == Candidate.CandidateStatus.WITHDRAWN
    assert withdrawn_candidate.race.office_title == "State Representative District 88th"

    assert result["created"] > 0


_WITHDRAWN_OUT_OF_SCOPE_HTML = """
<html><body>
<div class="cf-office-body">
    <table style="width: 100%;" cellpadding="0" cellspacing="0">
        <tr style="background-color: #b7dfe9; font-weight: bold;">
            <td>Name</td>
            <td>POBox Address</td>
            <td>Office</td>
            <td>District/Division</td>
            <td>Party</td>
        </tr>
        <tr class="boldleft">
            <td><a href="Default.aspx?cand=99999">Jane Q. Justice</a></td>
            <td><a class="email-link" href="mailto:jane@example.com">jane@example.com</a></td>
            <td>Justice of the Supreme Court</td>
            <td><a href="Default.aspx?office=14&amp;district=1">1st</a></td>
            <td>Nonpartisan</td>
        </tr>
    </table>
</div>
</body></html>
"""


@pytest.mark.django_db
def test_sync_ky_sos_skips_out_of_scope_withdrawn_rows():
    directory_html = _load_fixture("office_directory.html")

    with patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_directory",
        return_value=directory_html,
    ), patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_office",
        return_value="<html></html>",
    ), patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_withdrawn",
        return_value=_WITHDRAWN_OUT_OF_SCOPE_HTML,
    ):
        sync_ky_sos()

    assert not Candidate.objects.filter(name="Jane Q. Justice").exists()
    assert not Race.objects.filter(office_title__icontains="Justice of the Supreme Court").exists()


@pytest.mark.django_db
def test_sync_ky_sos_still_ingests_in_scope_withdrawn_rows():
    directory_html = _load_fixture("office_directory.html")
    withdrawn_html = _load_fixture("withdrawn.html")

    with patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_directory",
        return_value=directory_html,
    ), patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_office",
        return_value="<html></html>",
    ), patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_withdrawn",
        return_value=withdrawn_html,
    ):
        sync_ky_sos()

    withdrawn_candidate = Candidate.objects.get(name="Alisha Dawn Chaffin")
    assert withdrawn_candidate.candidate_status == Candidate.CandidateStatus.WITHDRAWN


@pytest.mark.django_db
def test_sync_ky_sos_is_idempotent_on_rerun():
    directory_html = _load_fixture("office_directory.html")
    senator_html = _load_fixture("office_us_senator.html")

    with patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_directory",
        return_value=directory_html,
    ), patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_office",
        return_value=senator_html,
    ), patch(
        "integrations.ky_sos.tasks.KentuckySosClient.fetch_withdrawn",
        return_value="<html></html>",
    ):
        sync_ky_sos()
        second_result = sync_ky_sos()

    # Second run should update existing rows, not duplicate them.
    assert Election.objects.filter(state="KY").count() == 1
    assert second_result["created"] == 0
