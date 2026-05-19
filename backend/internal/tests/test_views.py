import pytest
from unittest.mock import patch, MagicMock
from django.test import Client, override_settings
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def internal_token(settings):
    settings.INTERNAL_TASK_TOKEN = "test-secret-token"
    return "test-secret-token"


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_sync_elections_valid_token(client, internal_token):
    with patch("internal.views.sync_elections") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "abc-123"
        mock_task.delay.return_value = mock_result
        response = client.post(
            "/internal/tasks/sync-elections/",
            HTTP_AUTHORIZATION=f"Bearer {internal_token}",
        )
    assert response.status_code == 202
    data = response.json()
    assert data["task_id"] == "abc-123"
    mock_task.delay.assert_called_once()


@pytest.mark.django_db
def test_sync_elections_invalid_token(client, internal_token):
    response = client.post(
        "/internal/tasks/sync-elections/",
        HTTP_AUTHORIZATION="Bearer wrong-token",
    )
    assert response.status_code == 401
    assert response.json()["error"] == "Unauthorized"


@pytest.mark.django_db
def test_sync_elections_no_auth(client, internal_token):
    response = client.post("/internal/tasks/sync-elections/")
    assert response.status_code == 401


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=False, INTERNAL_TASK_TOKEN="")
def test_sync_elections_no_token_configured(client):
    response = client.post(
        "/internal/tasks/sync-elections/",
        HTTP_AUTHORIZATION="Bearer anything",
    )
    assert response.status_code == 401


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_sync_elections_idempotency(client, internal_token):
    with patch("internal.views.sync_elections") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "abc-123"
        mock_task.delay.return_value = mock_result

        r1 = client.post(
            "/internal/tasks/sync-elections/",
            HTTP_AUTHORIZATION=f"Bearer {internal_token}",
        )
        r2 = client.post(
            "/internal/tasks/sync-elections/",
            HTTP_AUTHORIZATION=f"Bearer {internal_token}",
        )
    assert r1.status_code == 202
    assert r1.json()["task_id"] == "abc-123"
    assert r2.status_code == 202
    assert r2.json()["status"] == "already_running"
    mock_task.delay.assert_called_once()


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_poll_results_valid_token(client, internal_token):
    with patch("internal.views.poll_pending_results") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "def-456"
        mock_task.delay.return_value = mock_result
        response = client.post(
            "/internal/tasks/poll-results/",
            HTTP_AUTHORIZATION=f"Bearer {internal_token}",
        )
    assert response.status_code == 202
    assert response.json()["task_id"] == "def-456"


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_sync_openstates_valid_token(client, internal_token):
    with patch("internal.views.sync_openstates_all_states") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "ghi-789"
        mock_task.delay.return_value = mock_result
        response = client.post(
            "/internal/tasks/sync-openstates/",
            HTTP_AUTHORIZATION=f"Bearer {internal_token}",
        )
    assert response.status_code == 202
    assert response.json()["task_id"] == "ghi-789"


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_sync_openstates_idempotency(client, internal_token):
    with patch("internal.views.sync_openstates_all_states") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "ghi-789"
        mock_task.delay.return_value = mock_result

        first = client.post(
            "/internal/tasks/sync-openstates/",
            HTTP_AUTHORIZATION=f"Bearer {internal_token}",
        )
        second = client.post(
            "/internal/tasks/sync-openstates/",
            HTTP_AUTHORIZATION=f"Bearer {internal_token}",
        )
    assert first.status_code == 202
    assert first.json()["task_id"] == "ghi-789"
    assert second.status_code == 202
    assert second.json()["status"] == "already_running"
    mock_task.delay.assert_called_once()


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_sync_fec_valid_token(client, internal_token):
    with patch("internal.views.sync_fec_candidates") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "jkl-012"
        mock_task.delay.return_value = mock_result
        response = client.post(
            "/internal/tasks/sync-fec/",
            HTTP_AUTHORIZATION=f"Bearer {internal_token}",
        )
    assert response.status_code == 202
    assert response.json()["task_id"] == "jkl-012"


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_sync_fec_idempotency(client, internal_token):
    with patch("internal.views.sync_fec_candidates") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "jkl-012"
        mock_task.delay.return_value = mock_result

        first = client.post(
            "/internal/tasks/sync-fec/",
            HTTP_AUTHORIZATION=f"Bearer {internal_token}",
        )
        second = client.post(
            "/internal/tasks/sync-fec/",
            HTTP_AUTHORIZATION=f"Bearer {internal_token}",
        )
    assert first.status_code == 202
    assert first.json()["task_id"] == "jkl-012"
    assert second.status_code == 202
    assert second.json()["status"] == "already_running"
    mock_task.delay.assert_called_once()
