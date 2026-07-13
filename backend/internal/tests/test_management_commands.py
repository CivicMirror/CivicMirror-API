from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.core.management import call_command


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_trigger_internal_task_enqueues_or_sos():
    output = StringIO()
    with patch.dict("internal.management.commands.trigger_internal_task.LOCAL_TASKS") as local_tasks:
        mock_task = MagicMock()
        mock_result = MagicMock()
        mock_result.id = "or-local-123"
        mock_task.apply_async.return_value = mock_result
        local_tasks["sync_or_sos"] = mock_task

        call_command("trigger_internal_task", "sync_or_sos", stdout=output)

    assert "enqueued task=sync_or_sos task_id=or-local-123" in output.getvalue()
    mock_task.apply_async.assert_called_once()


def test_trigger_internal_task_suppresses_duplicate_or_sos():
    output = StringIO()
    with patch.dict("internal.management.commands.trigger_internal_task.LOCAL_TASKS") as local_tasks:
        mock_task = MagicMock()
        mock_result = MagicMock()
        mock_result.id = "or-local-123"
        mock_task.apply_async.return_value = mock_result
        local_tasks["sync_or_sos"] = mock_task

        call_command("trigger_internal_task", "sync_or_sos", stdout=output)
        call_command("trigger_internal_task", "sync_or_sos", stdout=output)

    assert "already_running task=sync_or_sos" in output.getvalue()
    mock_task.apply_async.assert_called_once()
