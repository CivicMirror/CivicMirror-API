"""Tests for the Vermont results adapter (results/adapters/vt.py)."""
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from elections.models import Election, Race
from integrations.vt_sos.exceptions import VtSosError, VtSosRetryableError
from results.adapters.vt import VermontAdapter
from results.models import OfficialResult

_FIXTURES = Path(__file__).parent.parent.parent / "integrations" / "vt_sos" / "tests" / "fixtures"


def _load(name):
    return json.loads((_FIXTURES / name).read_text())


@pytest.fixture
def manifest():
    return _load("election_manifest.json")


@pytest.fixture
def federal_category():
    return _load("federal_category.json")


def _make_election(guid="a18f77e0-89f8-4a01-8d97-61a7c75ba200"):
    return Election.objects.create(
        canonical_key="VT:primary:2026-08-11:state",
        state="VT", election_type="primary",
        election_date=date(2026, 8, 11), jurisdiction_level="state",
        name="AUGUST PRIMARY", status=Election.Status.UPCOMING,
        source_metadata={"election_guid": guid},
    )


def _make_race(election, party_code, office_id=4, category="federal"):
    variant = f"vt:{category}:{party_code}:{office_id}:statewide"
    return Race.objects.create(
        election=election, race_type=Race.RaceType.CANDIDATE,
        office_title="REPRESENTATIVE TO CONGRESS", jurisdiction="Vermont",
        geography_scope="statewide", source=Race.Source.VT_SOS,
        ballot_type=party_code,
        source_metadata={
            "category": category, "party_code": party_code, "office_id": office_id,
            "district_code": "", "contest_variant": variant, "contest_code": variant,
        },
    )


@pytest.mark.django_db
class TestFetchResults:
    def test_missing_election_returns_none_confidence(self):
        adapter = VermontAdapter()
        result = adapter.fetch_results(None, election_id=999999)
        assert result.mapping_confidence == "none"
        assert result.rows == []

    def test_election_missing_guid_returns_none_confidence(self):
        election = Election.objects.create(
            canonical_key="VT:primary:2026-08-11:state",
            state="VT", election_type="primary", election_date=date(2026, 8, 11),
            jurisdiction_level="state", name="AUGUST PRIMARY",
            source_metadata={},
        )
        adapter = VermontAdapter()
        result = adapter.fetch_results(None, election_id=election.pk)
        assert result.mapping_confidence == "none"
        assert "election_guid" in result.notes

    def test_no_vt_races_returns_none_confidence(self):
        election = _make_election()
        adapter = VermontAdapter()
        result = adapter.fetch_results(None, election_id=election.pk)
        assert result.mapping_confidence == "none"
        assert "No VT SOS races" in result.notes

    def test_manifest_retryable_error_propagates_for_task_retry(self, manifest):
        election = _make_election()
        _make_race(election, "D")
        adapter = VermontAdapter()

        with patch("results.adapters.vt.VermontSosClient") as mock_client_cls:
            mock_client_cls.return_value.get_election_manifest.side_effect = VtSosRetryableError("timeout")
            with pytest.raises(VtSosRetryableError):
                adapter.fetch_results(None, election_id=election.pk)

    def test_manifest_non_retryable_error_returns_none_confidence(self, manifest):
        election = _make_election()
        _make_race(election, "D")
        adapter = VermontAdapter()

        with patch("results.adapters.vt.VermontSosClient") as mock_client_cls:
            mock_client_cls.return_value.get_election_manifest.side_effect = VtSosError("bad shape")
            result = adapter.fetch_results(None, election_id=election.pk)

        assert result.mapping_confidence == "none"
        assert "Failed to fetch VT election manifest" in result.notes

    def test_unchanged_fingerprint_skips_category_fetch(self, manifest, federal_category):
        election = _make_election()
        _make_race(election, "D")
        adapter = VermontAdapter()

        with patch("results.adapters.vt.VermontSosClient") as mock_client_cls, \
             patch("results.adapters.vt.cache") as mock_cache:
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            mock_cache.get.return_value = manifest["lastUpdatedDate"]
            result = adapter.fetch_results(None, election_id=election.pk)

        assert result.unchanged is True
        client.get_category.assert_not_called()

    def test_produces_distinct_rows_per_primary_party(self, manifest, federal_category):
        """The core scenario: three races (D/PR/R) for the same office_title
        must each get their own correctly-attributed result rows."""
        election = _make_election()
        dem_race = _make_race(election, "D")
        _make_race(election, "PR")
        rep_race = _make_race(election, "R")
        adapter = VermontAdapter()

        with patch("results.adapters.vt.VermontSosClient") as mock_client_cls, \
             patch("results.adapters.vt.cache") as mock_cache:
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            client.get_category.return_value = federal_category
            mock_cache.get.return_value = None
            result = adapter.fetch_results(None, election_id=election.pk)

        dem_rows = [r for r in result.rows if r.raw.get("contest_code") == dem_race.source_metadata["contest_code"]]
        rep_rows = [r for r in result.rows if r.raw.get("contest_code") == rep_race.source_metadata["contest_code"]]

        assert {r.candidate_name for r in dem_rows if r.candidate_name} == {"BECCA BALINT"}
        assert {r.candidate_name for r in rep_rows if r.candidate_name} == {"MARK COESTER", "GERALD MALLOY"}

    def test_write_in_aggregate_row_is_flagged_not_a_candidate(self, manifest, federal_category):
        election = _make_election()
        _make_race(election, "D")
        adapter = VermontAdapter()

        with patch("results.adapters.vt.VermontSosClient") as mock_client_cls, \
             patch("results.adapters.vt.cache") as mock_cache:
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            client.get_category.return_value = federal_category
            mock_cache.get.return_value = None
            result = adapter.fetch_results(None, election_id=election.pk)

        write_in_rows = [r for r in result.rows if r.is_write_in_aggregate]
        assert len(write_in_rows) == 1
        assert write_in_rows[0].candidate_name is None
        assert write_in_rows[0].option_label == "Write-in"

    def test_official_manifest_maps_to_official_result_type(self, manifest, federal_category):
        election = _make_election()
        _make_race(election, "D")
        adapter = VermontAdapter()
        official_manifest = json.loads(json.dumps(manifest))
        official_manifest["electionDetails"]["isOfficial"] = True

        with patch("results.adapters.vt.VermontSosClient") as mock_client_cls, \
             patch("results.adapters.vt.cache") as mock_cache:
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = official_manifest
            client.get_category.return_value = federal_category
            mock_cache.get.return_value = None
            result = adapter.fetch_results(None, election_id=election.pk)

        assert all(r.result_type == OfficialResult.ResultType.OFFICIAL for r in result.rows)

    def test_unofficial_manifest_maps_to_unofficial_result_type(self, manifest, federal_category):
        election = _make_election()
        _make_race(election, "D")
        adapter = VermontAdapter()

        with patch("results.adapters.vt.VermontSosClient") as mock_client_cls, \
             patch("results.adapters.vt.cache") as mock_cache:
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            client.get_category.return_value = federal_category
            mock_cache.get.return_value = None
            result = adapter.fetch_results(None, election_id=election.pk)

        assert all(r.result_type == OfficialResult.ResultType.UNOFFICIAL for r in result.rows)

    def test_disabled_category_race_is_skipped_without_crashing(self, manifest):
        """town category is isEnable=false in the fixture manifest; a race
        pointed at a disabled category must be silently skipped."""
        election = _make_election()
        _make_race(election, "D", category="town")
        adapter = VermontAdapter()

        with patch("results.adapters.vt.VermontSosClient") as mock_client_cls, \
             patch("results.adapters.vt.cache") as mock_cache:
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            mock_cache.get.return_value = None
            result = adapter.fetch_results(None, election_id=election.pk)

        assert result.rows == []
        client.get_category.assert_not_called()

    def test_category_fetch_error_is_noted_but_other_categories_continue(self, manifest, federal_category):
        election = _make_election()
        _make_race(election, "D", category="federal")
        _make_race(election, "D", category="stateWide", office_id=5)
        adapter = VermontAdapter()

        def _side_effect(path):
            if "-s-" in path:
                raise VtSosError("boom")
            return federal_category

        with patch("results.adapters.vt.VermontSosClient") as mock_client_cls, \
             patch("results.adapters.vt.cache") as mock_cache:
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            client.get_category.side_effect = _side_effect
            mock_cache.get.return_value = None
            result = adapter.fetch_results(None, election_id=election.pk)

        assert "category_error:stateWide" in result.notes
        assert any(r.candidate_name == "BECCA BALINT" for r in result.rows)

    def test_no_matching_contest_produces_no_rows_for_that_race(self, manifest, federal_category):
        """A race pointing at an office_id that doesn't exist in the fetched
        category must not crash — it just contributes no rows."""
        election = _make_election()
        _make_race(election, "D", office_id=999)
        adapter = VermontAdapter()

        with patch("results.adapters.vt.VermontSosClient") as mock_client_cls, \
             patch("results.adapters.vt.cache") as mock_cache:
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            client.get_category.return_value = federal_category
            mock_cache.get.return_value = None
            result = adapter.fetch_results(None, election_id=election.pk)

        assert result.rows == []

    def test_adapter_is_registered(self):
        from results.adapters import vt  # noqa: F401
        from results.adapters.registry import get_adapter, list_supported_states

        assert "VT" in list_supported_states()
        assert get_adapter("VT") is VermontAdapter
