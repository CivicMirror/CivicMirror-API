"""Tests for Vermont SOS mappers."""
import datetime
import json
from pathlib import Path

import pytest

from elections.models import Candidate, Election, Race
from integrations.vt_sos.mappers import (
    build_election_source_id,
    contest_variant_key,
    infer_election_status,
    iter_named_candidates,
    map_candidate,
    map_election_identity,
    map_election_type,
    map_race_identity,
    parse_election_date,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((_FIXTURES / name).read_text())


class TestMapElectionType:
    @pytest.mark.parametrize("code,expected", [
        ("P", "primary"),
        ("PP", "primary"),
        ("G", "general"),
        ("L", "municipal"),
        ("LS", "special"),
        ("p", "primary"),  # case-insensitive
        ("", "other"),
        ("XYZ", "other"),
    ])
    def test_maps_known_codes(self, code, expected):
        assert map_election_type(code) == expected


class TestParseElectionDate:
    def test_parses_iso_datetime_string(self):
        assert parse_election_date("2026-08-11T00:00:00") == datetime.date(2026, 8, 11)

    def test_returns_none_for_empty_string(self):
        assert parse_election_date("") is None

    def test_returns_none_for_unparseable_string(self):
        assert parse_election_date("not-a-date") is None


class TestInferElectionStatus:
    def test_official_is_always_certified(self):
        assert infer_election_status(datetime.date(2020, 1, 1), is_official=True) == Election.Status.RESULTS_CERTIFIED

    def test_future_date_is_upcoming(self):
        future = datetime.date.today() + datetime.timedelta(days=30)
        assert infer_election_status(future, is_official=False) == Election.Status.UPCOMING

    def test_past_date_not_official_is_results_pending(self):
        past = datetime.date.today() - datetime.timedelta(days=30)
        assert infer_election_status(past, is_official=False) == Election.Status.RESULTS_PENDING

    def test_today_not_official_is_active(self):
        assert infer_election_status(datetime.date.today(), is_official=False) == Election.Status.ACTIVE


class TestMapElectionIdentity:
    def test_maps_statewide_row(self):
        rows = _load("elections.json")
        row = rows[0]  # AUGUST PRIMARY
        identity, fields = map_election_identity(row)

        assert identity["state"] == "VT"
        assert identity["election_type"] == "primary"
        assert identity["election_date"] == datetime.date(2026, 8, 11)
        assert identity["jurisdiction_level"] == Election.JurisdictionLevel.STATE
        assert fields["name"] == "AUGUST PRIMARY"
        assert fields["source_metadata"]["election_guid"] == "a18f77e0-89f8-4a01-8d97-61a7c75ba200"
        assert fields["source_metadata"]["is_statewide"] is True

    def test_general_election_type(self):
        rows = _load("elections.json")
        row = rows[1]  # NOVEMBER GENERAL
        identity, _ = map_election_identity(row)
        assert identity["election_type"] == "general"

    def test_results_url_points_to_per_election_manifest(self):
        rows = _load("elections.json")
        _, fields = map_election_identity(rows[0])
        assert fields["results_url"] == (
            "https://static.electionresults.vermont.gov/elections/a18f77e0-89f8-4a01-8d97-61a7c75ba200.json"
        )


def test_build_election_source_id():
    assert build_election_source_id("abc-123") == "vt_sos_abc-123"


class TestContestVariantKey:
    def test_builds_expected_format(self):
        # Case is preserved here — normalization to lowercase happens later,
        # in aggregation.identity.race_canonical_key's _normalize_variant().
        assert contest_variant_key("federal", "D", 4, "") == "vt:federal:D:4:statewide"

    def test_defaults_party_to_all_when_blank(self):
        assert contest_variant_key("statewide", "", 5) == "vt:statewide:all:5:statewide"

    def test_includes_district_when_present(self):
        assert contest_variant_key("house", "D", 11, "ADD RUT") == "vt:house:D:11:ADD RUT"

    def test_disambiguates_same_office_across_parties(self):
        """The exact VT bug this exists for: three parties, same oid."""
        dem = contest_variant_key("federal", "D", 4)
        prog = contest_variant_key("federal", "PR", 4)
        rep = contest_variant_key("federal", "R", 4)
        assert len({dem, prog, rep}) == 3


class TestMapRaceIdentity:
    def test_maps_single_choice_contest(self):
        category_data = _load("federal_category.json")
        dem_wrapper = category_data["d"][0]
        contest = dem_wrapper["o"][0]

        identity, fields = map_race_identity("federal", contest, "D")

        assert identity["office_title"] == "REPRESENTATIVE TO CONGRESS"
        assert identity["race_type"] == Race.RaceType.CANDIDATE
        assert identity["contest_variant"] == "vt:federal:D:4:statewide"
        assert fields["vote_method"] == Race.VoteMethod.SINGLE_CHOICE
        assert fields["max_selections"] == 1
        assert fields["ballot_type"] == "D"
        assert fields["source"] == Race.Source.VT_SOS

    def test_maps_multi_seat_contest(self):
        house_data = _load("house_category.json")
        dem_wrapper = house_data["d"][0]
        multi_seat_contest = dem_wrapper["o"][1]  # vf=2

        identity, fields = map_race_identity(
            "house", multi_seat_contest, "D", district_code="CHI 1", district_name="CHITTENDEN 1",
        )

        assert fields["vote_method"] == Race.VoteMethod.MULTI_SEAT
        assert fields["max_selections"] == 2
        assert identity["contest_variant"] == "vt:house:D:12:CHI 1"
        assert fields["location_name"] == "CHITTENDEN 1"

    def test_three_parties_same_office_id_produce_distinct_variants(self):
        """Direct regression test for the review's core finding: Democratic,
        Progressive, and Republican all publish oid=4 for the same office."""
        category_data = _load("federal_category.json")
        variants = set()
        for party_wrapper in category_data["d"]:
            contest = party_wrapper["o"][0]
            identity, _ = map_race_identity("federal", contest, party_wrapper["pc"])
            variants.add(identity["contest_variant"])
        assert len(variants) == 3


class TestIterNamedCandidates:
    def test_extracts_named_candidate_across_multiple_cs_rows(self):
        """A candidate appears in every town's cs row; must dedupe to one."""
        category_data = _load("federal_category.json")
        dem_contest = category_data["d"][0]["o"][0]
        candidates = iter_named_candidates(dem_contest)
        assert len(candidates) == 1
        assert candidates[0]["cn"] == "BECCA BALINT"

    def test_skips_other_write_in_aggregate(self):
        category_data = _load("federal_category.json")
        dem_contest = category_data["d"][0]["o"][0]
        candidates = iter_named_candidates(dem_contest)
        assert all(c["cn"] != "OTHER WRITE-IN" for c in candidates)
        assert all(c["cid"] != 0 for c in candidates)

    def test_progressive_contest_with_only_aggregate_returns_empty(self):
        category_data = _load("federal_category.json")
        prog_contest = category_data["d"][1]["o"][0]
        assert iter_named_candidates(prog_contest) == []

    def test_two_named_candidates_in_republican_contest(self):
        category_data = _load("federal_category.json")
        rep_contest = category_data["d"][2]["o"][0]
        candidates = iter_named_candidates(rep_contest)
        names = {c["cn"] for c in candidates}
        assert names == {"MARK COESTER", "GERALD MALLOY"}

    def test_multi_seat_house_district_has_two_candidates(self):
        house_data = _load("house_category.json")
        multi_seat_contest = house_data["d"][0]["o"][1]
        candidates = iter_named_candidates(multi_seat_contest)
        names = {c["cn"] for c in candidates}
        assert names == {"PAT NORTH", "SAM SOUTH"}


class TestMapCandidate:
    def test_named_candidate_is_running(self):
        raw = {"cid": 210001, "cn": "BECCA BALINT", "isWriteIn": False, "pn": "DEMOCRATIC", "pco": "007ABC"}
        fields = map_candidate(raw)
        assert fields["candidate_status"] == Candidate.CandidateStatus.RUNNING
        assert fields["source_metadata"]["candidate_id"] == 210001
        assert fields["source_metadata"]["is_write_in"] is False

    def test_named_write_in_gets_write_in_status(self):
        raw = {"cid": 999001, "cn": "SOME WRITEIN", "isWriteIn": True, "pn": "DEMOCRATIC", "pco": "007ABC"}
        fields = map_candidate(raw)
        assert fields["candidate_status"] == Candidate.CandidateStatus.WRITE_IN
