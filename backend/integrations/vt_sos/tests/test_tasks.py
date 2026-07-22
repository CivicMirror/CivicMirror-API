"""
Integration tests for Vermont SOS Celery tasks — real DB, mocked HTTP client.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from elections.models import Candidate, Election, Race
from integrations.vt_sos.exceptions import VtSosError
from integrations.vt_sos.tasks import sync_vt_elections, sync_vt_races

_FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((_FIXTURES / name).read_text())


@pytest.fixture
def elections_index():
    return _load("elections.json")


@pytest.fixture
def manifest():
    return _load("election_manifest.json")


@pytest.fixture
def federal_category():
    return _load("federal_category.json")


@pytest.fixture
def house_category():
    return _load("house_category.json")


@pytest.mark.django_db
class TestSyncVtElections:
    def test_seeds_only_statewide_elections(self, elections_index):
        """Phase 1 scope: local (isStateWideElection=False) elections are
        excluded — see VT-Creation-Pipeline-Review.md section 7.3."""
        with patch("integrations.vt_sos.tasks.VermontSosClient") as mock_client_cls, \
             patch("integrations.vt_sos.tasks.sync_vt_races"):
            mock_client_cls.return_value.list_elections.return_value = elections_index
            sync_vt_elections.apply().get()

        assert Election.objects.filter(state="VT").count() == 2  # primary + general only
        assert not Election.objects.filter(name="BRADFORD TOWN MEETING").exists()

    def test_queues_race_sync_for_active_elections(self, elections_index):
        with patch("integrations.vt_sos.tasks.VermontSosClient") as mock_client_cls, \
             patch("integrations.vt_sos.tasks.sync_vt_races") as mock_stage2:
            mock_client_cls.return_value.list_elections.return_value = elections_index
            result = sync_vt_elections.apply().get()

        assert result["queued"] == 2  # both statewide elections are upcoming
        assert mock_stage2.delay.call_count == 2

    def test_does_not_queue_certified_election(self, elections_index):
        certified_row = dict(elections_index[0])
        certified_row["isOfficial"] = True
        with patch("integrations.vt_sos.tasks.VermontSosClient") as mock_client_cls, \
             patch("integrations.vt_sos.tasks.sync_vt_races"):
            mock_client_cls.return_value.list_elections.return_value = [certified_row, elections_index[1]]
            result = sync_vt_elections.apply().get()

        assert result["queued"] == 1  # certified one skipped

    def test_creates_election_with_expected_canonical_key(self, elections_index):
        with patch("integrations.vt_sos.tasks.VermontSosClient") as mock_client_cls, \
             patch("integrations.vt_sos.tasks.sync_vt_races"):
            mock_client_cls.return_value.list_elections.return_value = elections_index
            sync_vt_elections.apply().get()

        primary = Election.objects.get(canonical_key="VT:primary:2026-08-11:state")
        assert primary.name == "AUGUST PRIMARY"
        assert "vt_sos" in primary.contributing_sources

    def test_resync_does_not_duplicate_elections(self, elections_index):
        with patch("integrations.vt_sos.tasks.VermontSosClient") as mock_client_cls, \
             patch("integrations.vt_sos.tasks.sync_vt_races"):
            mock_client_cls.return_value.list_elections.return_value = elections_index
            sync_vt_elections.apply().get()
            result2 = sync_vt_elections.apply().get()

        assert result2["created"] == 0
        assert result2["updated"] == 2
        assert Election.objects.filter(state="VT").count() == 2


@pytest.mark.django_db
class TestSyncVtRaces:
    def _make_election(self):
        return Election.objects.create(
            canonical_key="VT:primary:2026-08-11:state",
            state="VT", election_type="primary",
            election_date="2026-08-11", jurisdiction_level="state",
            name="AUGUST PRIMARY", status=Election.Status.UPCOMING,
        )

    def test_creates_distinct_races_for_each_primary_party(self, manifest, federal_category):
        """The core regression this whole effort exists for: three parties
        sharing oid=4 must produce three distinct Race rows, not one."""
        election = self._make_election()

        with patch("integrations.vt_sos.tasks.VermontSosClient") as mock_client_cls, \
             patch("integrations.vt_sos.tasks.cache") as mock_cache:
            mock_cache.get.return_value = None
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            client.get_category.side_effect = lambda path: (
                federal_category if "-f-" in path else {"d": []}
            )
            result = sync_vt_races.apply(args=[election.pk, manifest["electionDetails"]["electionGuid"]]).get()

        races = Race.objects.filter(election=election, office_title="REPRESENTATIVE TO CONGRESS")
        assert races.count() == 3
        assert result["created"] == 3
        ballot_types = set(races.values_list("ballot_type", flat=True))
        assert ballot_types == {"D", "PR", "R"}

    def test_creates_candidates_and_skips_other_write_in(self, manifest, federal_category):
        election = self._make_election()

        with patch("integrations.vt_sos.tasks.VermontSosClient") as mock_client_cls, \
             patch("integrations.vt_sos.tasks.cache") as mock_cache:
            mock_cache.get.return_value = None
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            client.get_category.side_effect = lambda path: (
                federal_category if "-f-" in path else {"d": []}
            )
            sync_vt_races.apply(args=[election.pk, manifest["electionDetails"]["electionGuid"]]).get()

        rep_race = Race.objects.get(election=election, office_title="REPRESENTATIVE TO CONGRESS", ballot_type="R")
        candidate_names = set(rep_race.candidates.values_list("name", flat=True))
        assert candidate_names == {"MARK COESTER", "GERALD MALLOY"}
        assert not Candidate.objects.filter(name="OTHER WRITE-IN").exists()

    def test_multi_seat_house_district_sets_max_selections(self, manifest, house_category):
        election = self._make_election()

        with patch("integrations.vt_sos.tasks.VermontSosClient") as mock_client_cls, \
             patch("integrations.vt_sos.tasks.cache") as mock_cache:
            mock_cache.get.return_value = None
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            client.get_category.side_effect = lambda path: (
                house_category if "-h-" in path else {"d": []}
            )
            sync_vt_races.apply(args=[election.pk, manifest["electionDetails"]["electionGuid"]]).get()

        multi_seat_race = Race.objects.get(election=election, source_metadata__office_id=12)
        assert multi_seat_race.max_selections == 2
        assert multi_seat_race.vote_method == Race.VoteMethod.MULTI_SEAT
        assert multi_seat_race.candidates.count() == 2

    def test_house_districts_stay_separate_races(self, manifest, house_category):
        """Same office_title, different districts — must not merge."""
        election = self._make_election()

        with patch("integrations.vt_sos.tasks.VermontSosClient") as mock_client_cls, \
             patch("integrations.vt_sos.tasks.cache") as mock_cache:
            mock_cache.get.return_value = None
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            client.get_category.side_effect = lambda path: (
                house_category if "-h-" in path else {"d": []}
            )
            sync_vt_races.apply(args=[election.pk, manifest["electionDetails"]["electionGuid"]]).get()

        assert Race.objects.filter(election=election, office_title="STATE REPRESENTATIVE").count() == 2

    def test_resync_is_idempotent(self, manifest, federal_category):
        election = self._make_election()

        with patch("integrations.vt_sos.tasks.VermontSosClient") as mock_client_cls, \
             patch("integrations.vt_sos.tasks.cache") as mock_cache:
            mock_cache.get.return_value = None
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            client.get_category.side_effect = lambda path: (
                federal_category if "-f-" in path else {"d": []}
            )
            sync_vt_races.apply(args=[election.pk, manifest["electionDetails"]["electionGuid"]]).get()
            result2 = sync_vt_races.apply(args=[election.pk, manifest["electionDetails"]["electionGuid"]]).get()

        assert result2["created"] == 0
        assert result2["updated"] == 3
        assert Race.objects.filter(election=election, office_title="REPRESENTATIVE TO CONGRESS").count() == 3

    def test_skips_disabled_town_category(self, manifest):
        """Manifest sets town.isEnable=false; town must never be fetched."""
        election = self._make_election()

        with patch("integrations.vt_sos.tasks.VermontSosClient") as mock_client_cls, \
             patch("integrations.vt_sos.tasks.cache") as mock_cache:
            mock_cache.get.return_value = None
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            client.get_category.return_value = {"d": []}
            sync_vt_races.apply(args=[election.pk, manifest["electionDetails"]["electionGuid"]]).get()

        fetched_paths = [call.args[0] for call in client.get_category.call_args_list]
        assert not any("-t-" in path for path in fetched_paths)

    def test_unchanged_manifest_fingerprint_skips_refetch(self, manifest, federal_category):
        election = self._make_election()

        with patch("integrations.vt_sos.tasks.VermontSosClient") as mock_client_cls, \
             patch("integrations.vt_sos.tasks.cache") as mock_cache:
            mock_cache.get.return_value = manifest["lastUpdatedDate"]  # already cached
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            result = sync_vt_races.apply(args=[election.pk, manifest["electionDetails"]["electionGuid"]]).get()

        assert result.get("unchanged") is True
        client.get_category.assert_not_called()

    def test_missing_election_returns_none(self, manifest):
        result = sync_vt_races.apply(args=[999999, "some-guid"]).get()
        assert result is None

    def test_category_fetch_error_increments_error_count_but_continues(self, manifest, federal_category):
        election = self._make_election()

        with patch("integrations.vt_sos.tasks.VermontSosClient") as mock_client_cls, \
             patch("integrations.vt_sos.tasks.cache") as mock_cache:
            mock_cache.get.return_value = None
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest

            def _side_effect(path):
                if "-s-" in path:
                    raise VtSosError("boom")
                if "-f-" in path:
                    return federal_category
                return {"d": []}

            client.get_category.side_effect = _side_effect
            result = sync_vt_races.apply(args=[election.pk, manifest["electionDetails"]["electionGuid"]]).get()

        assert result["errors"] == 1
        # federal category still processed despite statewide's failure
        assert Race.objects.filter(election=election, office_title="REPRESENTATIVE TO CONGRESS").exists()

    def test_withdrawn_candidate_marked_when_absent_from_rerun(self, manifest, federal_category):
        election = self._make_election()

        with patch("integrations.vt_sos.tasks.VermontSosClient") as mock_client_cls, \
             patch("integrations.vt_sos.tasks.cache") as mock_cache:
            mock_cache.get.return_value = None
            client = mock_client_cls.return_value
            client.get_election_manifest.return_value = manifest
            client.get_category.side_effect = lambda path: (
                federal_category if "-f-" in path else {"d": []}
            )
            sync_vt_races.apply(args=[election.pk, manifest["electionDetails"]["electionGuid"]]).get()

            # Second run: Mark Coester withdraws from the Republican field.
            trimmed = json.loads(json.dumps(federal_category))
            rep_contest = trimmed["d"][2]["o"][0]
            rep_contest["cs"][0]["rc"] = [
                c for c in rep_contest["cs"][0]["rc"] if c["cn"] != "MARK COESTER"
            ]
            client.get_category.side_effect = lambda path: (
                trimmed if "-f-" in path else {"d": []}
            )
            mock_cache.get.return_value = None  # force refetch (fingerprint unchanged in fixture)
            sync_vt_races.apply(args=[election.pk, manifest["electionDetails"]["electionGuid"]]).get()

        coester = Candidate.objects.get(name="MARK COESTER")
        assert coester.candidate_status == Candidate.CandidateStatus.WITHDRAWN
        malloy = Candidate.objects.get(name="GERALD MALLOY")
        assert malloy.candidate_status == Candidate.CandidateStatus.RUNNING
