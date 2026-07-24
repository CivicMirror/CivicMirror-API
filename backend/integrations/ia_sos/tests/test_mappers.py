"""
Tests for Iowa SOS mappers.
"""
from datetime import date
from unittest.mock import MagicMock

import pytest

from elections.models import Election, Race
from integrations.ia_sos.mappers import (
    build_election_source_id,
    build_race_canonical_key,
    build_race_groups,
    infer_election_status,
    map_candidate,
    map_election,
    map_race,
    normalize,
)


class TestNormalize:
    def test_lowercases_and_trims(self):
        assert normalize("  U.S. Senator  ") == "u.s. senator"

    def test_collapses_whitespace(self):
        assert normalize("U.S.  Senator") == "u.s. senator"


class TestBuildElectionSourceId:
    def test_format(self):
        assert build_election_source_id(2026, "primary") == "ia_sos_2026_primary"

    def test_general(self):
        assert build_election_source_id(2026, "general") == "ia_sos_2026_general"

    def test_municipal_source_id_includes_date(self):
        assert (
            build_election_source_id(2025, "municipal", date(2025, 11, 4))
            == "ia_sos_2025_municipal_2025_11_04"
        )
        assert (
            build_election_source_id(2025, "municipal", "2025-12-02")
            == "ia_sos_2025_municipal_2025_12_02"
        )

    def test_primary_and_general_source_ids_remain_stable(self):
        assert build_election_source_id(2026, "primary", date(2026, 6, 2)) == "ia_sos_2026_primary"
        assert build_election_source_id(2026, "general", date(2026, 11, 3)) == "ia_sos_2026_general"


class TestBuildRaceCanonicalKey:
    def test_basic(self):
        key = build_race_canonical_key("ia_sos_2026_primary", "Governor", "", "DEM")
        assert key == "ia_sos:ia_sos_2026_primary:governor:statewide:dem"

    def test_with_district(self):
        key = build_race_canonical_key("ia_sos_2026_primary", "State Representative", "HD-3", "REP")
        assert key == "ia_sos:ia_sos_2026_primary:state representative:hd-3:rep"

    def test_nonpartisan(self):
        key = build_race_canonical_key("ia_sos_2026_general", "Governor", "", "")
        assert key == "ia_sos:ia_sos_2026_general:governor:statewide:nonpartisan"


class TestInferElectionStatus:
    def test_upcoming(self, monkeypatch):
        import django.utils.timezone as tz
        monkeypatch.setattr(tz, "localdate", lambda: date(2026, 1, 1))
        assert infer_election_status(date(2026, 6, 2)) == Election.Status.UPCOMING

    def test_active(self, monkeypatch):
        import django.utils.timezone as tz
        monkeypatch.setattr(tz, "localdate", lambda: date(2026, 6, 2))
        assert infer_election_status(date(2026, 6, 2)) == Election.Status.ACTIVE

    def test_results_pending(self, monkeypatch):
        import django.utils.timezone as tz
        monkeypatch.setattr(tz, "localdate", lambda: date(2026, 6, 3))
        assert infer_election_status(date(2026, 6, 2)) == Election.Status.RESULTS_PENDING


class TestMapElection:
    def test_maps_all_fields(self, monkeypatch):
        import django.utils.timezone as tz
        monkeypatch.setattr(tz, "localdate", lambda: date(2025, 1, 1))
        parsed = {
            "name": "2026 Iowa Primary Election",
            "election_date": "2026-06-02",
            "election_year": 2026,
            "election_type": "primary",
        }
        result = map_election(parsed)
        assert result["source_id"] == "ia_sos_2026_primary"
        assert result["state"] == "IA"
        assert result["election_date"] == date(2026, 6, 2)
        assert result["status"] == Election.Status.UPCOMING


class TestBuildRaceGroups:
    def _candidates(self):
        return [
            {"office": "Governor", "candidate_name": "Jane Smith", "party": "DEM", "district": ""},
            {"office": "Governor", "candidate_name": "Bob Jones", "party": "REP", "district": ""},
            {"office": "Governor", "candidate_name": "Dave Lee", "party": "REP", "district": ""},
            {"office": "U.S. Senator", "candidate_name": "Alice Green", "party": "DEM", "district": ""},
        ]

    def test_primary_splits_by_party(self):
        groups = build_race_groups("2026 Iowa Primary Election", self._candidates())
        keys = {(g["office"], g["party_group"]) for g in groups}
        assert ("Governor", "DEM") in keys
        assert ("Governor", "REP") in keys

    def test_general_ignores_party(self):
        groups = build_race_groups("2026 Iowa General Election", self._candidates())
        governor_groups = [g for g in groups if g["office"] == "Governor"]
        assert len(governor_groups) == 1

    def test_candidate_counts(self):
        groups = build_race_groups("2026 Iowa Primary Election", self._candidates())
        rep_gov = next(
            (g for g in groups if g["office"] == "Governor" and g["party_group"] == "REP"),
            None,
        )
        assert rep_gov is not None
        assert len(rep_gov["candidates"]) == 2


class TestMapRace:
    def _election(self):
        e = MagicMock(spec=Election)
        e.source_id = "ia_sos_2026_primary"
        e.name = "2026 Iowa Primary Election"
        e.status = Election.Status.UPCOMING
        return e

    def test_returns_candidate_race_type(self):
        group = {"office": "Governor", "district": "", "party_group": "DEM", "candidates": []}
        result = map_race(self._election(), group)
        assert result["race_type"] == Race.RaceType.CANDIDATE

    def test_source_is_ia_sos(self):
        group = {"office": "Governor", "district": "", "party_group": "DEM", "candidates": []}
        result = map_race(self._election(), group)
        assert result["source"] == Race.Source.IA_SOS

    def test_canonical_key_format(self):
        group = {"office": "Governor", "district": "", "party_group": "DEM", "candidates": []}
        result = map_race(self._election(), group)
        assert result["canonical_key"].startswith("ia_sos:ia_sos_2026_primary:governor:")


class TestMapCandidate:
    def test_maps_party(self):
        row = {"office": "Governor", "candidate_name": "Jane Smith", "party": "DEM", "district": ""}
        result = map_candidate(row)
        assert result["party"] == "DEM"

    def test_incumbent_defaults_false(self):
        row = {"office": "Governor", "candidate_name": "Jane Smith", "party": "DEM", "district": ""}
        result = map_candidate(row)
        assert result["incumbent"] is False


# ---------------------------------------------------------------------------
# Mapper bug-fix tests (TDD)
# ---------------------------------------------------------------------------

class TestMapElectionIncludesElectionType:
    def test_primary_election_type_present(self):
        parsed = {
            "name": "2026 Iowa Primary Election",
            "election_date": "2026-06-02",
            "election_year": 2026,
            "election_type": "primary",
        }
        result = map_election(parsed)
        assert "election_type" in result, "map_election must include 'election_type'"
        assert result["election_type"] == "primary"

    def test_general_election_type_present(self):
        parsed = {
            "name": "2026 Iowa General Election",
            "election_date": "2026-11-03",
            "election_year": 2026,
            "election_type": "general",
        }
        result = map_election(parsed)
        assert result["election_type"] == "general"


class TestMapRaceNullSourceId:
    def _make_election(self, source_id=None):
        mock = MagicMock()
        mock.source_id = source_id
        mock.canonical_key = "IA:primary:2026-06-02:state"
        mock.status = "upcoming"
        mock.name = "2026 Iowa Primary Election"
        return mock

    def _race_group(self):
        return {
            "office": "Governor",
            "district": "",
            "party_group": "DEM",
            "candidates": [],
        }

    def test_map_race_does_not_crash_with_null_source_id(self):
        result = map_race(self._make_election(source_id=None), self._race_group())
        assert isinstance(result["canonical_key"], str)
        assert "None" not in result["canonical_key"]

    def test_map_race_source_metadata_election_id_not_none(self):
        result = map_race(self._make_election(source_id=None), self._race_group())
        election_id = result["source_metadata"]["ia_sos_election_id"]
        assert election_id is not None
        assert isinstance(election_id, str)
