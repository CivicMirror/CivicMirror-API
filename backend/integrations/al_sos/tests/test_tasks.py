"""Integration tests for al_sos Celery tasks. All network access is mocked."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

_FIXTURES = Path(__file__).parent / "fixtures"


def _year_page_html() -> str:
    return (_FIXTURES / "al_year_page_2026.html").read_text()


@pytest.mark.django_db
def test_sync_al_elections_creates_elections():
    from elections.models import Election
    from integrations.al_sos.tasks import sync_al_elections

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        MC.return_value.fetch_election_year_page.return_value = _year_page_html()
        sync_al_elections.apply(kwargs={"year": 2026})

    assert Election.objects.filter(state="AL", election_type="primary").exists()
    assert Election.objects.filter(state="AL", election_type="general").exists()
    assert Election.objects.filter(state="AL", election_type="primary_runoff").exists()


@pytest.mark.django_db
def test_sync_al_elections_stores_document_links_in_metadata():
    from elections.models import Election
    from integrations.al_sos.tasks import sync_al_elections

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        MC.return_value.fetch_election_year_page.return_value = _year_page_html()
        sync_al_elections.apply(kwargs={"year": 2026})

    primary = Election.objects.get(state="AL", election_type="primary")
    links = primary.source_metadata["al_document_links"]
    assert any("Sample Ballots" == link["label"] for link in links)


@pytest.mark.django_db
def test_sync_al_elections_is_idempotent():
    from elections.models import Election
    from integrations.al_sos.tasks import sync_al_elections

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        MC.return_value.fetch_election_year_page.return_value = _year_page_html()
        sync_al_elections.apply(kwargs={"year": 2026})
        sync_al_elections.apply(kwargs={"year": 2026})

    assert Election.objects.filter(state="AL").count() == 4


@pytest.mark.django_db
def test_sync_al_elections_preserves_curated_fcpa_election_id_on_resync():
    from elections.models import Election
    from integrations.al_sos.tasks import sync_al_elections

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        MC.return_value.fetch_election_year_page.return_value = _year_page_html()
        sync_al_elections.apply(kwargs={"year": 2026})

    primary = Election.objects.get(state="AL", election_type="primary")
    primary.source_metadata["al_fcpa_election_id"] = "160"
    primary.save(update_fields=["source_metadata"])

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        MC.return_value.fetch_election_year_page.return_value = _year_page_html()
        sync_al_elections.apply(kwargs={"year": 2026})

    primary.refresh_from_db()
    assert primary.source_metadata["al_fcpa_election_id"] == "160"
    links = primary.source_metadata["al_document_links"]
    assert any("Sample Ballots" == link["label"] for link in links)


def _make_al_election(**overrides):
    from elections.models import Election

    defaults = dict(
        name="2026 General Election",
        election_date="2026-11-03",
        election_type="general",
        jurisdiction_level="state",
        state="AL",
        source_id="al_sos_2026_general_election",
        source_metadata={"al_fcpa_election_id": "160"},
    )
    defaults.update(overrides)
    return Election.objects.create(**defaults)


_SEARCH_PAGE_1 = {
    "data": {
        "totalRecords": 1,
        "list": [
            {"COMMITTEEID": 9001, "CANDIDATE": "SMITH, JANE", "CANDIDATESTATUS": "Active", "YEAR": 2026},
        ],
    },
    "success": True,
}

_SEARCH_PAGE_EMPTY = {"data": {"totalRecords": 1, "list": []}, "success": True}

_COMMITTEE_DETAIL = {
    "id": 9001,
    "candidateFirstName": "Jane",
    "candidateMiddleName": "",
    "candidateLastName": "Smith",
    "suffix": "",
    "office": "State Senator",
    "jurisdiction": "Jefferson County",
    "district": "15",
    "party": "Democratic",
    "committeeStatus": "Active",
    "dissolved": False,
}


@pytest.mark.django_db
def test_sync_al_fcpa_candidates_creates_race_and_candidate():
    import json as _json

    from elections.models import Candidate, Race
    from integrations.al_sos.tasks import sync_al_fcpa_candidates

    _make_al_election()

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        client = MC.return_value
        client.fetch_fcpa_race_search.side_effect = (
            lambda election_id, office_id, page_number, page_size=100: (
                _json.dumps(_SEARCH_PAGE_1) if office_id == 41 and page_number == 1 else _json.dumps(_SEARCH_PAGE_EMPTY)
            )
        )
        client.fetch_fcpa_committee_detail.return_value = "<html></html>"
        with patch("integrations.al_sos.tasks.parse_fcpa_committee_detail", return_value=_COMMITTEE_DETAIL):
            sync_al_fcpa_candidates.apply()

    assert Race.objects.filter(election__state="AL", office_title="State Senate - District 15").exists()
    candidate = Candidate.objects.get(name="Jane Smith")
    assert candidate.party == "DEM"
    assert candidate.source_metadata["al_fcpa_committee_id"] == 9001
    assert candidate.candidate_status == Candidate.CandidateStatus.RUNNING


@pytest.mark.django_db
def test_sync_al_fcpa_candidates_skips_elections_without_fcpa_id():
    from elections.models import Race
    from integrations.al_sos.tasks import sync_al_fcpa_candidates

    _make_al_election(source_metadata={}, source_id="al_sos_2026_primary_election", election_type="primary", election_date="2026-05-19")

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        sync_al_fcpa_candidates.apply()
        MC.return_value.fetch_fcpa_race_search.assert_not_called()

    assert not Race.objects.filter(election__state="AL").exists()


@pytest.mark.django_db
def test_sync_al_fcpa_candidates_marks_dissolved_committee_withdrawn():
    import json as _json

    from elections.models import Candidate
    from integrations.al_sos.tasks import sync_al_fcpa_candidates

    _make_al_election()
    dissolved_detail = {**_COMMITTEE_DETAIL, "dissolved": True}

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        client = MC.return_value
        client.fetch_fcpa_race_search.side_effect = (
            lambda election_id, office_id, page_number, page_size=100: (
                _json.dumps(_SEARCH_PAGE_1) if office_id == 41 and page_number == 1 else _json.dumps(_SEARCH_PAGE_EMPTY)
            )
        )
        client.fetch_fcpa_committee_detail.return_value = "<html></html>"
        with patch("integrations.al_sos.tasks.parse_fcpa_committee_detail", return_value=dissolved_detail):
            sync_al_fcpa_candidates.apply()

    candidate = Candidate.objects.get(source_metadata__al_fcpa_committee_id=9001)
    assert candidate.candidate_status == Candidate.CandidateStatus.WITHDRAWN
