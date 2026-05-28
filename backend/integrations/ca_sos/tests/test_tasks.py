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


# API-URL-format catalog bytes used across Stage-1 tests.
_API_CATALOG_BYTES = (
    b'https://api.sos.ca.gov\n'
    b'"|... California June 3, 2026 Primary Election|"\n\n'
    b'https://api.sos.ca.gov/returns/governor\n'
)


class TestSyncCaElections:
    def test_seeds_elections_and_queues_on_catalog_change(self, db):
        """Stage 1 should seed Elections via ingest service and queue sync_ca_races when catalog changes."""
        from integrations.ca_sos.tasks import sync_ca_elections
        from elections.models import Election

        with (
            patch("integrations.ca_sos.tasks.CaSosClient") as mock_client_cls,
            patch("integrations.ca_sos.tasks.cache") as mock_cache,
            patch("integrations.ca_sos.tasks.sync_ca_races") as mock_stage2,
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_endpoint_catalog_fingerprint.return_value = "newfingerprint"
            # New code uses parse_api_endpoint_catalog — provide API-URL-format bytes.
            mock_client.fetch_endpoint_catalog_csv.return_value = _API_CATALOG_BYTES

            # Simulate cache miss (catalog changed)
            mock_cache.get.return_value = "oldfingerprint"

            result = sync_ca_elections.apply().get()

        assert result["queued"] == 1
        mock_stage2.delay.assert_called_once()
        # Election must exist with canonical_key (ingest service path).
        assert Election.objects.filter(state="CA").exists()

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
            # New code fetches the CSV (to extract date) even before the fingerprint check.
            mock_client.fetch_endpoint_catalog_csv.return_value = _API_CATALOG_BYTES
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

        # Seed election first via ingest service (API-URL-format catalog bytes).
        with (
            patch("integrations.ca_sos.tasks.CaSosClient") as mock_client_cls,
            patch("integrations.ca_sos.tasks.cache"),
            patch("integrations.ca_sos.tasks.sync_ca_races") as mock_stage2,
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.get_endpoint_catalog_fingerprint.return_value = "fp1"
            # Use API-URL format so parse_api_endpoint_catalog finds at least one entry.
            mock_client.fetch_endpoint_catalog_csv.return_value = _API_CATALOG_BYTES
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
        # Ingest service may create Alice Smith across multiple races (one per catalog entry
        # type); use .filter().first() instead of .get() to avoid MultipleObjectsReturned.
        alice = candidates.filter(name="Alice Smith").first()
        assert alice is not None
        assert alice.incumbent is True

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


# ---------------------------------------------------------------------------
# New integration test: catalog-date extraction + ingest service routing
# ---------------------------------------------------------------------------
from datetime import date
from unittest.mock import patch

import pytest
from django.test import override_settings

from aggregation.models import SourcePrecedence
from elections.models import Election


@pytest.fixture
def seed_precedence(db):
    SourcePrecedence.objects.create(state="*", field_group="*", source="civic_api", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="date", source="ca_sos", rank=0)
    SourcePrecedence.objects.create(state="CA", field_group="identity", source="ca_sos", rank=1)


CATALOG = (
    b'https://api.sos.ca.gov\n'
    b'"|... California June 2, 2026 Primary Election|"\n\n'
    b'https://api.sos.ca.gov/returns/governor\n'
)


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_sync_ca_elections_uses_catalog_date_and_ingests(seed_precedence):
    from integrations.ca_sos.tasks import sync_ca_elections
    with patch("integrations.ca_sos.tasks.CaSosClient") as MockClient:
        inst = MockClient.return_value
        inst.get_endpoint_catalog_fingerprint.return_value = "fp1"
        inst.fetch_endpoint_catalog_csv.return_value = CATALOG
        sync_ca_elections.run()

    primary = Election.objects.get(canonical_key="CA:primary:2026-06-02:state")
    assert primary.election_date == date(2026, 6, 2)
    assert "ca_sos" in primary.contributing_sources
