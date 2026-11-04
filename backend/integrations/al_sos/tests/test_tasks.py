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


_SAME_DATE_SPECIALS_HTML = (
    "<h3>Special Primary Election, Congressional Districts 1, 2, 6, and 7 "
    "– August 11, 2026</h3><blockquote></blockquote>"
    "<h3>Special Primary Election, State Senate Districts 25 and 26 "
    "– August 11, 2026</h3><blockquote></blockquote>"
)


@pytest.mark.django_db
def test_sync_al_elections_keeps_same_date_specials_at_different_jurisdiction_levels_separate():
    from elections.models import Election
    from integrations.al_sos.tasks import sync_al_elections

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        MC.return_value.fetch_election_year_page.return_value = _SAME_DATE_SPECIALS_HTML
        sync_al_elections.apply(kwargs={"year": 2026})

    elections = Election.objects.filter(state="AL", election_type="special", election_date="2026-08-11")
    assert elections.count() == 2
    assert set(elections.values_list("jurisdiction_level", flat=True)) == {"national", "state"}


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


@pytest.mark.django_db
def test_sync_al_certifications_creates_party_specific_races_and_candidate_provenance():
    from elections.models import Candidate, Election, Race
    from integrations.al_sos.tasks import sync_al_certifications

    election = _make_al_election(
        election_type="primary",
        election_date="2026-05-19",
        name="2026 Primary Election",
        source_metadata={
            "al_document_links": [
                {"label": "State Certification of Democratic Party Candidates", "url": "https://www.sos.alabama.gov/dem.pdf"},
                {"label": "State Certification of Republican Party Candidates", "url": "https://www.sos.alabama.gov/rep.pdf"},
            ]
        },
    )

    def parsed_rows(_content, *, party, document_label, source_url, sha256):
        candidate_name = "Alice Democrat" if party == "DEM" else "Robert Republican"
        return [{
            "office_title": "Governor",
            "candidate_name": candidate_name,
            "party": party,
            "document_label": document_label,
            "source_url": source_url,
            "source_sha256": sha256,
        }]

    with patch("integrations.al_sos.tasks.AlSosClient") as MC, patch(
        "integrations.al_sos.tasks.parse_candidate_certification_pdf", side_effect=parsed_rows,
    ):
        MC.return_value.fetch_candidate_certification_pdf.return_value = b"%PDF-1.4 certification"
        sync_al_certifications.apply(kwargs={"year": 2026})

    races = list(Race.objects.filter(election=election).order_by("party"))
    assert len(races) == 2
    assert {race.party for race in races} == {"DEM", "REP"}
    assert {race.source_metadata["contest_variant"] for race in races} == {"al:DEM", "al:REP"}
    assert all(race.source_metadata["al_certification_ocr_review_required"] for race in races)
    candidates = list(Candidate.objects.filter(race__election=election))
    assert {candidate.name for candidate in candidates} == {"Alice Democrat", "Robert Republican"}
    assert all(candidate.source_metadata["al_certification_sources"] for candidate in candidates)
    assert all(candidate.source_metadata["al_certification_ocr_review_required"] for candidate in candidates)
    election.refresh_from_db()
    assert election.source_metadata["al_certification_documents"]


@pytest.mark.django_db
def test_sync_al_certifications_uses_latest_linked_amendment_and_skips_unchanged_ocr():
    from elections.models import Candidate, Election, Race
    from integrations.al_sos.tasks import sync_al_certifications

    election = _make_al_election(
        election_type="general",
        name="2026 General Election",
        source_id="al_sos_test_general_certifications",
        source_metadata={
            "al_document_links": [
                {"label": "Republican Party Certification of Candidates", "url": "https://www.sos.alabama.gov/rep-original.pdf"},
                {"label": "State Certification of Republican Party Candidates", "url": "https://www.sos.alabama.gov/rep-state.pdf"},
                {"label": "Republican Party Amended Certification of Candidates", "url": "https://www.sos.alabama.gov/rep-amended.pdf"},
            ]
        },
    )
    with patch("integrations.al_sos.tasks.AlSosClient") as MC, patch(
        "integrations.al_sos.tasks.parse_candidate_certification_pdf",
    ) as parser:
        MC.return_value.fetch_candidate_certification_pdf.return_value = b"%PDF-1.4 amended"
        parser.return_value = [{
            "office_title": "State House - District 51",
            "candidate_name": "Allen Treadaway",
            "party": "REP",
            "document_label": "Republican Party Amended Certification of Candidates",
            "source_url": "https://www.sos.alabama.gov/rep-amended.pdf",
            "source_sha256": "unused",
        }]
        sync_al_certifications.apply(kwargs={"year": 2026})
        sync_al_certifications.apply(kwargs={"year": 2026})

    parser.assert_called_once()
    assert parser.call_args.kwargs["source_url"] == "https://www.sos.alabama.gov/rep-amended.pdf"
    assert Race.objects.filter(election=election, office_title="State House - District 51").count() == 1
    candidate = Candidate.objects.get(race__election=election, name="Allen Treadaway")
    assert candidate.source_metadata["al_certification_sources"][0]["url"].endswith("rep-amended.pdf")


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
def test_sync_al_fcpa_candidates_state_board_of_education_districts_stay_distinct():
    import json as _json

    from elections.models import Race
    from integrations.al_sos.tasks import sync_al_fcpa_candidates

    _make_al_election()

    search_page_district_3 = {
        "data": {
            "totalRecords": 1,
            "list": [
                {"COMMITTEEID": 9101, "CANDIDATE": "ALPHA, ANN", "CANDIDATESTATUS": "Active", "YEAR": 2026},
            ],
        },
        "success": True,
    }
    search_page_district_5 = {
        "data": {
            "totalRecords": 1,
            "list": [
                {"COMMITTEEID": 9102, "CANDIDATE": "BETA, BOB", "CANDIDATESTATUS": "Active", "YEAR": 2026},
            ],
        },
        "success": True,
    }
    detail_by_committee = {
        9101: {**_COMMITTEE_DETAIL, "committee_id": 9101, "office": "State Board of Education",
               "district": "3", "candidateFirstName": "Ann", "candidateLastName": "Alpha"},
        9102: {**_COMMITTEE_DETAIL, "committee_id": 9102, "office": "State Board of Education",
               "district": "5", "candidateFirstName": "Bob", "candidateLastName": "Beta"},
    }

    def _fetch_race_search(election_id, office_id, page_number, page_size=100):
        if office_id != 39 or page_number != 1:
            return _json.dumps(_SEARCH_PAGE_EMPTY)
        # SBOE search results aren't split by district; both candidates come
        # back under office_id=39 and district is only known from the detail page.
        return _json.dumps({
            "data": {
                "totalRecords": 2,
                "list": search_page_district_3["data"]["list"] + search_page_district_5["data"]["list"],
            },
            "success": True,
        })

    with patch("integrations.al_sos.tasks.AlSosClient") as MC:
        client = MC.return_value
        client.fetch_fcpa_race_search.side_effect = _fetch_race_search
        client.fetch_fcpa_committee_detail.side_effect = lambda committee_id: str(committee_id)
        with patch(
            "integrations.al_sos.tasks.parse_fcpa_committee_detail",
            side_effect=lambda html: detail_by_committee[int(html)],
        ):
            sync_al_fcpa_candidates.apply()

    assert Race.objects.filter(
        election__state="AL", office_title="State Board of Education - District 3"
    ).exists()
    assert Race.objects.filter(
        election__state="AL", office_title="State Board of Education - District 5"
    ).exists()
    assert Race.objects.filter(office_title__startswith="State Board of Education").count() == 2


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
