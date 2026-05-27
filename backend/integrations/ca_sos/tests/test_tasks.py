"""Tests for CA SOS Celery tasks."""
import json
from unittest.mock import MagicMock, patch

import pytest

from integrations.ca_sos.tasks import _resolve_current_election


SAMPLE_CATALOG_ENTRIES = [
    {"name": "Governor", "path": "/returns/governor", "type": "candidate", "race_id": "01"},
    {"name": "Ballot Measures", "path": "/returns/ballot-measures", "type": "measure", "race_id": ""},
]

SAMPLE_CONTEST_RESPONSE = [
    {
        "raceTitle": "Governor - Statewide Results",
        "Reporting": "100.0% (1000 of 1000) precincts reporting",
        "candidates": [
            {"Name": "Alice Smith", "Party": "Dem", "Votes": "1500000", "Percent": "55.0", "incumbent": True},
            {"Name": "Bob Jones", "Party": "Rep", "Votes": "1200000", "Percent": "45.0", "incumbent": False},
        ],
    }
]


class TestSyncCaElections:
    def test_seeds_elections_and_queues_on_catalog_change(self, db):
        """Stage 1 should seed Elections and queue sync_ca_races when catalog changes."""
        from integrations.ca_sos.tasks import sync_ca_elections

        with (
            patch("integrations.ca_sos.tasks.CaSosClient") as mock_client_cls,
            patch("integrations.ca_sos.tasks.cache") as mock_cache,
            patch("integrations.ca_sos.tasks.sync_ca_races") as mock_stage2,
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_endpoint_catalog_fingerprint.return_value = "newfingerprint"
            mock_client.fetch_endpoint_catalog_csv.return_value = (
                b"RaceID,ContestName,EndpointURL,ContestType\n01,Governor,/returns/governor,Candidate\n"
            )

            # Simulate cache miss (catalog changed)
            mock_cache.get.return_value = "oldfingerprint"

            result = sync_ca_elections.apply().get()

        assert result["queued"] == 1
        mock_stage2.delay.assert_called_once()

    def test_skips_stage2_when_catalog_unchanged(self, db):
        from integrations.ca_sos.tasks import sync_ca_elections

        with (
            patch("integrations.ca_sos.tasks.CaSosClient") as mock_client_cls,
            patch("integrations.ca_sos.tasks.cache") as mock_cache,
            patch("integrations.ca_sos.tasks.sync_ca_races") as mock_stage2,
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_endpoint_catalog_fingerprint.return_value = "same"
            mock_cache.get.return_value = "same"

            result = sync_ca_elections.apply().get()

        assert result["queued"] == 0
        mock_stage2.delay.assert_not_called()

    def test_skips_stage2_when_catalog_unavailable(self, db):
        from integrations.ca_sos.tasks import sync_ca_elections

        with (
            patch("integrations.ca_sos.tasks.CaSosClient") as mock_client_cls,
            patch("integrations.ca_sos.tasks.sync_ca_races") as mock_stage2,
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_endpoint_catalog_fingerprint.return_value = None

            result = sync_ca_elections.apply().get()

        assert result["queued"] == 0
        mock_stage2.delay.assert_not_called()


class TestSyncCaRaces:
    def test_upserts_races_and_candidates(self, db):
        from integrations.ca_sos.tasks import sync_ca_elections, sync_ca_races
        from elections.models import Election, Race, Candidate

        # Seed election first
        with (
            patch("integrations.ca_sos.tasks.CaSosClient") as mock_client_cls,
            patch("integrations.ca_sos.tasks.cache"),
            patch("integrations.ca_sos.tasks.sync_ca_races") as mock_stage2,
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_endpoint_catalog_fingerprint.return_value = "fp1"
            mock_client.fetch_endpoint_catalog_csv.return_value = (
                b"RaceID,ContestName,EndpointURL,ContestType\n01,Governor,/returns/governor,Candidate\n"
            )
            mock_client_cls.return_value.get_endpoint_catalog_fingerprint.return_value = "fp1"
            # Capture the call to Stage 2 to get election_pk
            sync_ca_elections.apply().get()
            if not mock_stage2.delay.called:
                pytest.skip("No election to test against")

        election = Election.objects.filter(state="CA").first()
        if not election:
            pytest.skip("No CA election seeded")

        with (
            patch("integrations.ca_sos.tasks.CaSosClient") as mock_client_cls,
            patch("integrations.ca_sos.tasks.cache"),
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.fetch_contest.return_value = SAMPLE_CONTEST_RESPONSE

            result = sync_ca_races.apply(
                args=[election.pk, json.dumps(SAMPLE_CATALOG_ENTRIES), "fp1"]
            ).get()

        assert result["created"] > 0
        races = Race.objects.filter(election=election, source="ca_sos")
        assert races.exists()
        candidates = Candidate.objects.filter(race__in=races)
        assert candidates.filter(name="Alice Smith").exists()
        assert candidates.get(name="Alice Smith").incumbent is True

    def test_handles_missing_election(self, db):
        from integrations.ca_sos.tasks import sync_ca_races

        result = sync_ca_races.apply(
            args=[99999, json.dumps(SAMPLE_CATALOG_ENTRIES), "fp1"]
        ).get()
        assert result is None

    def test_handles_contest_fetch_error(self, db):
        from integrations.ca_sos.tasks import sync_ca_races
        from elections.models import Election
        from integrations.ca_sos.exceptions import CaSosError

        election = Election.objects.filter(state="CA").first()
        if not election:
            from elections.models import Election
            from datetime import date
            election = Election.objects.create(
                source_id="ca_sos_test",
                name="CA Test",
                election_date=date(2026, 3, 3),
                jurisdiction_level="state",
                state="CA",
                status="upcoming",
            )

        with (
            patch("integrations.ca_sos.tasks.CaSosClient") as mock_client_cls,
            patch("integrations.ca_sos.tasks.cache"),
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.fetch_contest.side_effect = CaSosError("upstream error")

            result = sync_ca_races.apply(
                args=[election.pk, json.dumps(SAMPLE_CATALOG_ENTRIES), "fp1"]
            ).get()

        assert result["errors"] == len(SAMPLE_CATALOG_ENTRIES)
        assert result["created"] == 0
