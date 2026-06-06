"""
Unit tests for the NC SBE Stage 1 task (sync_nc_elections).
All HTTP calls are mocked — no network access required.
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DATE_STRS = ["2024_11_05", "2026_03_03"]


# ---------------------------------------------------------------------------
# sync_nc_elections
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_sync_nc_elections_creates_election_records():
    from elections.models import Election
    from integrations.nc_sbe.tasks import sync_nc_elections

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_election_date_strs.return_value = _DATE_STRS
        sync_nc_elections.apply()

    assert Election.objects.filter(state="NC", election_type="general").exists()
    assert Election.objects.filter(state="NC", election_type="primary").exists()


@pytest.mark.django_db
def test_sync_nc_elections_sets_results_pending_for_past():
    from elections.models import Election
    from integrations.nc_sbe.tasks import sync_nc_elections

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_election_date_strs.return_value = ["2024_11_05"]
        sync_nc_elections.apply()

    election = Election.objects.get(state="NC", election_date=datetime.date(2024, 11, 5))
    assert election.status == Election.Status.RESULTS_PENDING


@pytest.mark.django_db
def test_sync_nc_elections_stores_results_url_in_metadata():
    from elections.models import Election
    from integrations.nc_sbe.tasks import sync_nc_elections

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_election_date_strs.return_value = ["2024_11_05"]
        sync_nc_elections.apply()

    election = Election.objects.get(state="NC", election_date=datetime.date(2024, 11, 5))
    meta = election.source_metadata or {}
    assert "results_url" in meta
    assert "2024_11_05" in meta["results_url"]
    assert meta["nc_date_str"] == "2024_11_05"


@pytest.mark.django_db
def test_sync_nc_elections_skips_pre_2010():
    from elections.models import Election
    from integrations.nc_sbe.tasks import sync_nc_elections

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_election_date_strs.return_value = [
            "1998_05_05", "2024_11_05"
        ]
        result = sync_nc_elections.apply()

    assert Election.objects.filter(state="NC").count() == 1
    assert result.result["skipped"] == 1


@pytest.mark.django_db
def test_sync_nc_elections_is_idempotent():
    from elections.models import Election
    from integrations.nc_sbe.tasks import sync_nc_elections

    with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
        MockClient.return_value.list_election_date_strs.return_value = _DATE_STRS
        sync_nc_elections.apply()
        sync_nc_elections.apply()

    # Running twice should not duplicate records
    assert Election.objects.filter(state="NC").count() == len(_DATE_STRS)


@pytest.mark.django_db
def test_sync_nc_elections_retries_on_retryable_error():
    from celery.exceptions import Retry

    from integrations.nc_sbe.exceptions import NcSbeRetryableError
    from integrations.nc_sbe.tasks import sync_nc_elections

    with pytest.raises(Retry):
        with patch("integrations.nc_sbe.tasks.NcSbeClient") as MockClient:
            MockClient.return_value.list_election_date_strs.side_effect = NcSbeRetryableError("timeout")
            sync_nc_elections.apply()


@pytest.mark.django_db
def test_sync_nc_elections_retries_on_requests_timeout():
    """Network timeouts during S3 listing should be wrapped as NcSbeRetryableError and retried."""
    import requests as req
    from celery.exceptions import Retry

    from integrations.nc_sbe.tasks import sync_nc_elections

    with pytest.raises(Retry):
        with patch("integrations.nc_sbe.client.requests.Session.get", side_effect=req.Timeout("timed out")):
            sync_nc_elections.apply()
