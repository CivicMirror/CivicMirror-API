"""Unit tests for al_sos FCPA mappers."""
from __future__ import annotations

from integrations.al_sos.mappers import (
    CORE_OFFICE_IDS,
    OFFICE_LABELS,
    build_candidate_name,
    geography_scope,
    normalize_certification_office,
    normalize_office_title,
    party_abbrev,
    select_candidate_certification_links,
)


def test_office_ids_and_labels_match():
    assert CORE_OFFICE_IDS == set(OFFICE_LABELS)
    assert OFFICE_LABELS[23] == "Governor"
    assert OFFICE_LABELS[40] == "State Representative"
    assert OFFICE_LABELS[41] == "State Senator"


def test_normalize_office_title_statewide():
    assert normalize_office_title("Governor", "") == "Governor"
    assert normalize_office_title("Lt. Governor", "") == "Lieutenant Governor"


def test_normalize_office_title_legislative_district():
    assert normalize_office_title("State Senator", "27") == "State Senate - District 27"
    assert normalize_office_title("State Representative", "55") == "State House - District 55"
    assert normalize_office_title("State Senator", "") == "State Senate"


def test_geography_scope():
    assert geography_scope("State Senate - District 27") == "state_legislative_district"
    assert geography_scope("State House - District 55") == "state_legislative_district"
    assert geography_scope("Governor") == "statewide"


def test_normalize_office_title_state_board_of_education_with_district():
    assert normalize_office_title("State Board of Education", "3") == "State Board of Education - District 3"


def test_normalize_office_title_state_board_of_education_without_district():
    assert normalize_office_title("State Board of Education", "") == "State Board of Education"


def test_normalize_office_title_public_service_commissioner_with_place():
    assert normalize_office_title("Public Service Commissioner", "", place="1") == "Public Service Commissioner - Place 1"


def test_normalize_office_title_public_service_commissioner_without_place():
    assert normalize_office_title("Public Service Commissioner", "") == "Public Service Commissioner"


def test_geography_scope_state_board_of_education_is_legislative_district():
    assert geography_scope("State Board of Education - District 3") == "state_legislative_district"


def test_geography_scope_public_service_commissioner_is_statewide():
    assert geography_scope("Public Service Commissioner - Place 1") == "statewide"


def test_party_abbrev():
    assert party_abbrev("Republican") == "REP"
    assert party_abbrev("Democratic") == "DEM"
    assert party_abbrev("Independent") == "IND"
    assert party_abbrev("") == ""


def test_normalize_certification_office_maps_federal_statewide_and_judicial_seats():
    assert normalize_certification_office("U.S. Congress Congressional District 3") == "U.S. House - District 3"
    assert normalize_certification_office("Public Service Commission Place 1") == "Public Service Commissioner - Place 1"
    assert normalize_certification_office("Circuit Judge Circuit 6, Place 4") == "Circuit Judge - Circuit 6, Place 4"
    assert normalize_certification_office("District Judge Baldwin, Place 1") == "District Judge - Baldwin County, Place 1"
    assert normalize_certification_office("U.S. Congress Congressional District §") == "U.S. House - District 5"


def test_select_candidate_certification_links_uses_last_link_per_party_and_skips_other_documents():
    links = [
        {"label": "Sample Ballots", "url": "/ballots"},
        {"label": "Republican Party Certification of Candidates", "url": "/rep-original.pdf"},
        {"label": "Democratic Party Certification of Candidates", "url": "/dem-original.pdf"},
        {"label": "State Certification of Statewide Amendments", "url": "/amendments.pdf"},
        {"label": "State Certification of Democratic Party Candidates", "url": "/dem-state.pdf"},
        {"label": "State Certification of Republican Party Candidates", "url": "/rep-state.pdf"},
        {"label": "State Certification of Independent Candidate", "url": "/independent.pdf"},
        {"label": "State Certification of General Election Results", "url": "/results.pdf"},
    ]

    selected = select_candidate_certification_links(links)

    assert [(item["party"], item["url"]) for item in selected] == [
        ("REP", "/rep-state.pdf"),
        ("DEM", "/dem-state.pdf"),
        ("IND", "/independent.pdf"),
    ]


def test_build_candidate_name_joins_structured_fields():
    detail = {
        "candidateFirstName": "JIMMY",
        "candidateMiddleName": "",
        "candidateLastName": "ABBETT",
        "suffix": "",
    }
    assert build_candidate_name(detail) == "JIMMY ABBETT"


def test_build_candidate_name_includes_suffix():
    detail = {
        "candidateFirstName": "John",
        "candidateMiddleName": "Q",
        "candidateLastName": "Public",
        "suffix": "Jr.",
    }
    assert build_candidate_name(detail) == "John Q Public Jr."
