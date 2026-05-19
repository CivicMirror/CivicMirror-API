from datetime import date, timedelta

import pytest
from django.utils import timezone

from elections.models import Election, Race
from integrations.civic.mappers import (
    extract_contest_title,
    infer_election_status,
    infer_race_type,
    map_candidate_defaults,
    map_election_payload,
    measure_option_labels,
    parse_jurisdiction_level,
    parse_state_from_ocd,
)


def test_parse_state_from_ocd():
    assert parse_state_from_ocd("ocd-division/country:us/state:wv") == "WV"
    assert parse_state_from_ocd("ocd-division/country:us") is None
    assert parse_state_from_ocd("") is None


def test_parse_jurisdiction_level():
    assert parse_jurisdiction_level("ocd-division/country:us") == Election.JurisdictionLevel.NATIONAL
    assert parse_jurisdiction_level("ocd-division/country:us/state:wv") == Election.JurisdictionLevel.STATE
    assert parse_jurisdiction_level("ocd-division/country:us/state:wv/county:kanawha") == Election.JurisdictionLevel.LOCAL


@pytest.mark.django_db
def test_infer_election_status():
    future = date.today() + timedelta(days=10)
    assert infer_election_status(future) == Election.Status.UPCOMING
    assert infer_election_status(date.today()) == Election.Status.ACTIVE
    past_recent = date.today() - timedelta(days=7)
    assert infer_election_status(past_recent) == Election.Status.RESULTS_PENDING
    past_old = date.today() - timedelta(days=60)
    assert infer_election_status(past_old) == Election.Status.ARCHIVED


@pytest.mark.django_db
def test_map_election_payload_string_date():
    payload = {
        "source_id": "9530",
        "name": "Louisiana 2026 Primary",
        "election_date": "2026-03-21",
        "ocd_division_id": "ocd-division/country:us/state:la",
    }
    result = map_election_payload(payload)
    assert result["source_id"] == "9530"
    assert result["state"] == "LA"
    assert result["jurisdiction_level"] == Election.JurisdictionLevel.STATE
    assert isinstance(result["election_date"], date)


def test_infer_race_type_referendum():
    contest = {"type": "Referendum", "referendumTitle": "Question 1"}
    assert infer_race_type(contest) == Race.RaceType.MEASURE


def test_infer_race_type_candidate():
    contest = {"type": "General", "office": "Governor"}
    assert infer_race_type(contest) == Race.RaceType.CANDIDATE


def test_extract_contest_title_office():
    assert extract_contest_title({"office": "Governor", "type": "General"}) == "Governor"


def test_extract_contest_title_referendum():
    contest = {"type": "Referendum", "referendumTitle": "Question 1 — Bond Measure"}
    assert extract_contest_title(contest) == "Question 1 — Bond Measure"


def test_map_candidate_defaults():
    payload = {
        "name": "Jane Smith",
        "party": "Democratic",
        "urls": ["https://example.com"],
        "photoUrl": "https://example.com/photo.jpg",
        "biography": "A candidate.",
    }
    result = map_candidate_defaults(payload)
    assert result["party"] == "Democratic"
    assert result["website_url"] == "https://example.com"
    assert result["image_url"] == "https://example.com/photo.jpg"


def test_measure_option_labels():
    labels = measure_option_labels()
    assert "Yes" in labels
    assert "No" in labels
