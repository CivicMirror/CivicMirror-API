"""
Tests for the Colorado SOS mappers.
"""
import calendar
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from integrations.co_sos.mappers import (
    _first_tuesday_after_first_monday_of_november,
    _last_tuesday_of_june,
    build_election_source_id,
    build_race_canonical_key,
    build_race_groups,
    co_election_date,
    map_candidate,
    map_election,
    map_race,
)


class TestElectionDateComputation:
    def test_last_tuesday_of_june_2026(self):
        d = _last_tuesday_of_june(2026)
        assert d.month == 6
        assert d.weekday() == calendar.TUESDAY
        # Verify no later Tuesday exists in June 2026
        assert (d + timedelta(days=7)).month == 7

    def test_last_tuesday_of_june_2024(self):
        d = _last_tuesday_of_june(2024)
        assert d.month == 6
        assert d.weekday() == calendar.TUESDAY
        assert (d + timedelta(days=7)).month == 7

    def test_general_election_2026_is_tuesday_after_first_monday(self):
        d = _first_tuesday_after_first_monday_of_november(2026)
        assert d.month == 11
        assert d.weekday() == calendar.TUESDAY
        # The day before (Monday) must be a Monday
        assert (d - timedelta(days=1)).weekday() == calendar.MONDAY
        # And the Monday before it must be in October or it's the 1st/2nd Monday
        prior_monday = d - timedelta(days=1)
        assert prior_monday.day <= 8  # first Monday is always in days 1-7

    def test_co_election_date_primary(self):
        d = co_election_date(2026, "primary")
        assert d == _last_tuesday_of_june(2026)

    def test_co_election_date_general(self):
        d = co_election_date(2026, "general")
        assert d == _first_tuesday_after_first_monday_of_november(2026)

    def test_co_election_date_raises_for_unknown_type(self):
        with pytest.raises(ValueError):
            co_election_date(2026, "special")


class TestBuildElectionSourceId:
    def test_format(self):
        assert build_election_source_id(2026, "primary") == "co_sos_2026_primary"
        assert build_election_source_id(2026, "general") == "co_sos_2026_general"


class TestMapElection:
    def test_returns_expected_fields(self):
        result = map_election(2026, "primary")
        assert result["source_id"] == "co_sos_2026_primary"
        assert result["state"] == "CO"
        assert result["name"] == "2026 Colorado Primary Election"
        assert result["election_date"] == co_election_date(2026, "primary")
        assert result["jurisdiction_level"] == "state"


class TestBuildRaceGroups:
    def _candidates(self):
        return [
            {"candidate_name": "Alice", "office": "Governor", "district": "Statewide", "party": "Democratic Party", "is_write_in": False, "is_withdrawn": False},
            {"candidate_name": "Bob", "office": "Governor", "district": "Statewide", "party": "Republican Party", "is_write_in": False, "is_withdrawn": False},
            {"candidate_name": "Carol", "office": "Governor", "district": "Statewide", "party": "Democratic Party", "is_write_in": False, "is_withdrawn": False},
        ]

    def test_primary_groups_by_office_district_party(self):
        groups = build_race_groups(self._candidates(), is_primary=True)
        # Dem Governor and Rep Governor are separate races
        assert len(groups) == 2
        offices = {g["office"] for g in groups}
        assert offices == {"Governor"}
        parties = {g["party_group"] for g in groups}
        assert "Democratic Party" in parties
        assert "Republican Party" in parties

    def test_primary_dem_group_has_two_candidates(self):
        groups = build_race_groups(self._candidates(), is_primary=True)
        dem = next(g for g in groups if g["party_group"] == "Democratic Party")
        assert len(dem["candidates"]) == 2

    def test_general_groups_by_office_district_only(self):
        groups = build_race_groups(self._candidates(), is_primary=False)
        # All 3 candidates are for Governor Statewide, so 1 race
        assert len(groups) == 1
        assert groups[0]["party_group"] == ""


class TestMapCandidate:
    def test_running_status(self):
        row = {"is_withdrawn": False, "is_write_in": False, "party": "Democratic Party", "office": "Governor", "district": "Statewide"}
        result = map_candidate(row)
        assert result["candidate_status"] == "running"

    def test_withdrawn_takes_precedence(self):
        row = {"is_withdrawn": True, "is_write_in": True, "party": "Democratic Party", "office": "Governor", "district": "Statewide"}
        result = map_candidate(row)
        assert result["candidate_status"] == "withdrawn"

    def test_write_in_status(self):
        row = {"is_withdrawn": False, "is_write_in": True, "party": "Unity Party", "office": "Governor", "district": "Statewide"}
        result = map_candidate(row)
        assert result["candidate_status"] == "write_in"

    def test_party_stored(self):
        row = {"is_withdrawn": False, "is_write_in": False, "party": "Republican Party", "office": "Governor", "district": "Statewide"}
        result = map_candidate(row)
        assert result["party"] == "Republican Party"


# ---------------------------------------------------------------------------
# Mapper bug-fix tests (TDD: written before fixes applied)
# ---------------------------------------------------------------------------

class TestMapElectionIncludesElectionType:
    def test_primary_election_type_present(self):
        result = map_election(2026, "primary")
        assert "election_type" in result, "map_election must include 'election_type'"
        assert result["election_type"] == "primary"

    def test_general_election_type_present(self):
        result = map_election(2026, "general")
        assert result["election_type"] == "general"


class TestMapRaceNullSourceId:
    def _make_election(self, source_id=None):
        mock = MagicMock()
        mock.source_id = source_id
        mock.canonical_key = "CO:primary:2026-06-28:state"
        mock.status = "upcoming"
        return mock

    def _race_group(self):
        return {
            "office": "Governor",
            "district": "Statewide",
            "party_group": "Democratic Party",
            "candidates": [],
        }

    def test_map_race_does_not_crash_with_null_source_id(self):
        result = map_race(self._make_election(source_id=None), self._race_group())
        assert isinstance(result["canonical_key"], str)
        assert "None" not in result["canonical_key"]

    def test_map_race_source_metadata_election_id_not_none(self):
        result = map_race(self._make_election(source_id=None), self._race_group())
        election_id = result["source_metadata"]["co_sos_election_id"]
        assert election_id is not None, "co_sos_election_id must not be None when source_id is None"
        assert isinstance(election_id, str)
