"""
Unit tests for wa_votewa mappers. No DB required.
"""
from datetime import date
from unittest.mock import MagicMock

import pytest

from integrations.wa_votewa.mappers import (
    _get_text,
    infer_election_type,
    infer_election_status,
    map_candidate,
    map_election,
    map_measure_option,
    map_race,
    normalize,
    parse_election_date,
    parse_election_date_from_slug,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def test_get_text_english():
    names = [{"languageId": "en", "text": "Governor"}, {"languageId": "es", "text": "Gobernador"}]
    assert _get_text(names) == "Governor"


def test_get_text_fallback_to_first():
    names = [{"languageId": "es", "text": "Gobernador"}]
    assert _get_text(names) == "Gobernador"


def test_get_text_empty():
    assert _get_text([]) == ""


def test_normalize():
    assert normalize("  Governor  ") == "governor"
    assert normalize("Member,  House   of  Delegates") == "member, house of delegates"
    assert normalize(None) == ""


def test_parse_election_date_from_meta():
    meta = {"electionDate": "2026-04-28"}
    assert parse_election_date(meta) == date(2026, 4, 28)


def test_parse_election_date_missing():
    assert parse_election_date({}) is None


def test_parse_election_date_from_slug():
    assert parse_election_date_from_slug("20260428") == date(2026, 4, 28)


def test_parse_election_date_from_slug_bad():
    assert parse_election_date_from_slug("not-a-date") is None


# ---------------------------------------------------------------------------
# infer_election_type
# ---------------------------------------------------------------------------

def test_infer_type_general():
    assert infer_election_type(date(2026, 11, 3)) == "general"


def test_infer_type_primary():
    assert infer_election_type(date(2026, 8, 4)) == "primary"


def test_infer_type_special():
    assert infer_election_type(date(2026, 4, 28)) == "special"
    assert infer_election_type(date(2026, 2, 10)) == "special"


# ---------------------------------------------------------------------------
# map_election
# ---------------------------------------------------------------------------

def test_map_election_basic():
    meta = {"electionDate": "2026-04-28", "isOfficialResults": True}
    result = map_election("20260428", meta)

    assert result["source_id"] == "wa_votewa:20260428"
    assert result["state"] == "WA"
    assert result["election_date"] == date(2026, 4, 28)
    assert result["election_type"] == "special"
    assert result["jurisdiction_level"] == "state"
    assert result["source_metadata"]["enr_slug"] == "20260428"
    assert result["source_metadata"]["votewa_jurisdiction_slug"] == "washington"


def test_map_election_uses_api_name():
    meta = {"electionDate": "2026-11-03", "electionName": "2026 November General Election"}
    result = map_election("20261103", meta)
    assert result["name"] == "2026 November General Election"


def test_map_election_constructs_name_when_missing():
    meta = {"electionDate": "2026-04-28"}
    result = map_election("20260428", meta)
    assert "Washington" in result["name"]


# ---------------------------------------------------------------------------
# map_race
# ---------------------------------------------------------------------------

def _make_election(status="results_pending", slug="20260428"):
    e = MagicMock()
    e.status = status
    e.source_metadata = {"enr_slug": slug}
    return e


def _make_ballot_item(contest_type="BallotMeasure", name_text="Proposition 1", item_id="item-001"):
    return {
        "id": item_id,
        "contestType": contest_type,
        "name": [{"languageId": "en", "text": name_text}],
        "summaryResults": {"ballotOptions": []},
    }


def test_map_race_measure():
    election = _make_election()
    item = _make_ballot_item(contest_type="BallotMeasure", name_text="Proposition 1")
    result = map_race(election, item)

    assert result["race_type"] == "measure"
    assert result["office_title"] == "Proposition 1"
    assert result["source_metadata"]["votewa_ballot_item_id"] == "item-001"
    assert result["source_metadata"]["contest_type"] == "BallotMeasure"
    assert result["geography_scope"] == "statewide"
    assert result["jurisdiction"] == "Washington"


def test_map_race_candidate():
    election = _make_election()
    item = _make_ballot_item(contest_type="Candidate", name_text="State Senator")
    result = map_race(election, item)

    assert result["race_type"] == "candidate"
    assert result["office_title"] == "State Senator"
    assert result["vote_method"] == "single_choice"


def test_map_race_county_scope():
    election = _make_election()
    item = _make_ballot_item(contest_type="BallotMeasure", name_text="Fire District Levy")
    item["parentId"] = "parent-agg-001"
    result = map_race(election, item, jurisdiction_slug="mason-county-wa")

    assert result["geography_scope"] == "county"
    assert result["source_metadata"]["votewa_parent_ballot_item_id"] == "parent-agg-001"
    assert "Mason" in result["jurisdiction"]


# ---------------------------------------------------------------------------
# map_candidate
# ---------------------------------------------------------------------------

def test_map_candidate_with_party():
    opt = {
        "nativeId": "opt-001",
        "isWriteIn": False,
        "party": {"abbreviation": "D", "name": "Democratic"},
    }
    result = map_candidate(opt)

    assert result["party"] == "Democratic"
    assert result["source_metadata"]["votewa_native_id"] == "opt-001"
    assert result["source_metadata"]["is_write_in"] is False
    assert result["incumbent"] is False


def test_map_candidate_write_in():
    opt = {"nativeId": "wi-001", "isWriteIn": True, "party": {}}
    result = map_candidate(opt)
    assert result["source_metadata"]["is_write_in"] is True


def test_map_candidate_no_party():
    opt = {"nativeId": "opt-002", "isWriteIn": False}
    result = map_candidate(opt)
    assert result["party"] == ""


# ---------------------------------------------------------------------------
# map_measure_option
# ---------------------------------------------------------------------------

def test_map_measure_option_yes():
    opt = {
        "nativeId": "yes-001",
        "name": [{"languageId": "en", "text": "Yes"}],
    }
    result = map_measure_option(opt)
    assert result["option_label"] == "Yes"
    assert result["source_metadata"]["votewa_native_id"] == "yes-001"


def test_map_measure_option_falls_back_to_native_id():
    opt = {"nativeId": "fallback-id", "name": []}
    result = map_measure_option(opt)
    assert result["option_label"] == "fallback-id"
