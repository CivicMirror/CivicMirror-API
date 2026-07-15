from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from ops.models import SyncLog


@pytest.fixture
def client():
    return Client()


def _make_log(source, status=SyncLog.Status.COMPLETED, completed_at=None, **kwargs):
    return SyncLog.objects.create(
        source=source,
        status=status,
        completed_at=completed_at or timezone.now(),
        **kwargs,
    )


@pytest.mark.django_db
def test_public_no_auth_required(client):
    response = client.get("/api/coverage/sync-status/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_adapter_states_reflects_live_registry(client):
    with patch("ops.views.list_supported_states", return_value=["GA", "OH", "CA"]):
        response = client.get("/api/coverage/sync-status/")
    assert response.json()["adapter_states"] == ["CA", "GA", "OH"]


@pytest.mark.django_db
def test_state_specific_source_grouped_by_state(client):
    _make_log("wv_sos", records_updated=42)
    response = client.get("/api/coverage/sync-status/")
    data = response.json()
    assert "WV" in data["by_state"]
    assert data["by_state"]["WV"]["wv_sos"]["records_updated"] == 42


@pytest.mark.django_db
def test_multiple_sources_for_same_state_both_included(client):
    _make_log("sc_enr")
    _make_log("sc_vrems")
    response = client.get("/api/coverage/sync-status/")
    sc = response.json()["by_state"]["SC"]
    assert set(sc.keys()) == {"sc_enr", "sc_vrems"}


@pytest.mark.django_db
def test_civic_api_goes_to_global_not_by_state(client):
    _make_log("civic_api", records_created=12)
    response = client.get("/api/coverage/sync-status/")
    data = response.json()
    assert data["global"]["civic_api"]["records_created"] == 12
    assert "civic_api" not in data["by_state"]
    assert not any("civic_api" in sources for sources in data["by_state"].values())


@pytest.mark.django_db
def test_non_state_sources_excluded_from_by_state():
    """openstates/fec/congress/census/election_calendar are national sources
    with no single associated state and must not appear anywhere in the
    per-state breakdown (and specifically must not be misattributed to a
    state via an accidental 2-letter-prefix collision, e.g. 'congress' -> 'CO')."""
    _make_log("openstates")
    _make_log("fec")
    _make_log("congress")
    _make_log("census")
    _make_log("election_calendar")
    client = Client()
    response = client.get("/api/coverage/sync-status/")
    data = response.json()
    all_sources = {src for sources in data["by_state"].values() for src in sources}
    assert all_sources == set()
    # Specifically: 'congress' must never be misread as Colorado.
    assert "CO" not in data["by_state"]


@pytest.mark.django_db
def test_failed_and_in_progress_logs_excluded(client):
    _make_log("wv_sos", status=SyncLog.Status.FAILED)
    _make_log("co_sos", status=SyncLog.Status.STARTED, completed_at=None)
    response = client.get("/api/coverage/sync-status/")
    data = response.json()
    assert "WV" not in data["by_state"]
    assert "CO" not in data["by_state"]


@pytest.mark.django_db
def test_completed_with_warnings_included(client):
    _make_log("wv_sos", status=SyncLog.Status.COMPLETED_WITH_WARNINGS)
    response = client.get("/api/coverage/sync-status/")
    assert "WV" in response.json()["by_state"]


@pytest.mark.django_db
def test_only_latest_completed_entry_per_source_returned(client):
    now = timezone.now()
    _make_log("wv_sos", records_updated=1, completed_at=now - timedelta(hours=2))
    _make_log("wv_sos", records_updated=2, completed_at=now)
    response = client.get("/api/coverage/sync-status/")
    assert response.json()["by_state"]["WV"]["wv_sos"]["records_updated"] == 2


@pytest.mark.django_db
def test_sync_status_uses_non_correlated_latest_source_query(client):
    """The public coverage page calls this on load, so avoid the old correlated
    subquery shape that timed out against production-sized SyncLog tables.
    """
    now = timezone.now()
    for idx in range(3):
        _make_log("wv_sos", completed_at=now - timedelta(minutes=idx))
        _make_log("sc_enr", completed_at=now - timedelta(minutes=idx))

    with CaptureQueriesContext(connection) as queries:
        response = client.get("/api/coverage/sync-status/")

    assert response.status_code == 200
    synclog_queries = [query["sql"] for query in queries if "ops_synclog" in query["sql"]]
    assert len(synclog_queries) == 1
    assert "SELECT U0" not in synclog_queries[0]


@pytest.mark.django_db
def test_empty_source_excluded(client):
    _make_log("")
    response = client.get("/api/coverage/sync-status/")
    data = response.json()
    assert data["by_state"] == {}
    assert data["global"] == {}
