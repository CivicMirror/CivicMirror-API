"""Tests for CA SOS mappers."""
import pytest
from datetime import date

from integrations.ca_sos.mappers import (
    ca_election_date,
    ca_general_date,
    ca_primary_date,
    infer_geography_scope,
    map_election,
    normalize,
)


class TestElectionDates:
    def test_primary_2026(self):
        d = ca_primary_date(2026)
        assert d.year == 2026
        assert d.month == 3
        assert d.weekday() == 1  # Tuesday

    def test_general_2026(self):
        d = ca_general_date(2026)
        assert d.year == 2026
        assert d.month == 11
        assert d.weekday() == 1  # Tuesday

    def test_general_2024(self):
        d = ca_general_date(2024)
        assert d == date(2024, 11, 5)

    def test_primary_2024(self):
        d = ca_primary_date(2024)
        # CA 2024 primary was March 5, 2024
        assert d == date(2024, 3, 5)

    def test_ca_election_date_primary(self):
        d = ca_election_date(2026, "primary")
        assert d.month == 3

    def test_ca_election_date_general(self):
        d = ca_election_date(2026, "general")
        assert d.month == 11

    def test_ca_election_date_unknown_type(self):
        with pytest.raises(ValueError):
            ca_election_date(2026, "runoff")


class TestMapElection:
    def test_map_election_primary(self):
        result = map_election(2026, "primary")
        assert result["source_id"] == "ca_sos_2026_primary"
        assert result["state"] == "CA"
        assert result["name"] == "2026 California Primary Election"
        assert result["election_date"].month == 3

    def test_map_election_general(self):
        result = map_election(2026, "general")
        assert result["source_id"] == "ca_sos_2026_general"
        assert result["name"] == "2026 California General Election"
        assert result["election_date"].month == 11

    def test_map_election_has_required_fields(self):
        result = map_election(2026, "general")
        assert "jurisdiction_level" in result
        assert "status" in result


class TestInferGeographyScope:
    def test_governor_is_statewide(self):
        assert infer_geography_scope("Governor - Statewide Results") == "statewide"

    def test_us_senate_is_statewide(self):
        assert infer_geography_scope("US Senate") == "statewide"

    def test_ballot_measure_is_statewide(self):
        assert infer_geography_scope("Ballot Measure - Proposition 1") == "statewide"

    def test_district_race(self):
        assert infer_geography_scope("US House District 12") == "district"

    def test_assembly_district(self):
        assert infer_geography_scope("State Assembly District 10") == "district"
