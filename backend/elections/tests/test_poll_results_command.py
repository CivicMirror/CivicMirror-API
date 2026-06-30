from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command


def test_poll_results_command_runs_poll_task_synchronously():
    stdout = StringIO()

    with patch("elections.management.commands.poll_results.poll_pending_results") as mock_poll:
        mock_poll.return_value = {"queued": 3}
        call_command("poll_results", stdout=stdout)

    mock_poll.assert_called_once_with()
    assert "Queued 3 elections for results polling." in stdout.getvalue()


# --- Post-implementation verification ---
# These tests exercise the REAL bound task (results.tasks.poll_pending_results is
# @shared_task(bind=True)) rather than a mock, confirming the command's direct
# synchronous call path actually works and reports the real queued count.


@pytest.mark.django_db
def test_poll_results_command_invokes_real_bound_task_no_pending():
    # No RESULTS_PENDING elections exist, so the real task returns {"queued": 0}
    # without enqueuing any ingestion. This proves the bound-task call path
    # (not mocked) succeeds end-to-end.
    stdout = StringIO()

    call_command("poll_results", stdout=stdout)

    assert "Queued 0 elections for results polling." in stdout.getvalue()


@pytest.mark.django_db
def test_poll_results_command_handles_non_dict_return():
    # Defensive: if the task ever returns a non-dict, the command must not raise
    # and should fall back to a queued count of 0.
    stdout = StringIO()

    with patch("elections.management.commands.poll_results.poll_pending_results") as mock_poll:
        mock_poll.return_value = None
        call_command("poll_results", stdout=stdout)

    assert "Queued 0 elections for results polling." in stdout.getvalue()
