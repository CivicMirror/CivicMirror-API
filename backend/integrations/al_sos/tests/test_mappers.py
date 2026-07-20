"""Unit tests for al_sos FCPA mappers."""
from __future__ import annotations

from integrations.al_sos.mappers import (
    CORE_OFFICE_IDS,
    OFFICE_LABELS,
    build_candidate_name,
    geography_scope,
    normalize_office_title,
    party_abbrev,
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


def test_party_abbrev():
    assert party_abbrev("Republican") == "REP"
    assert party_abbrev("Democratic") == "DEM"
    assert party_abbrev("Independent") == "IND"
    assert party_abbrev("") == ""


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
