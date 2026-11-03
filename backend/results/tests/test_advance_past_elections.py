"""Tests for advance_past_elections (issue #231).

The task closes a gap between the two pollers: an election dated in the past
whose status is still upcoming/active is excluded by poll_upcoming_results (date
too old) AND by poll_pending_results (wrong status), so it can never be polled
again.
"""
import datetime

import pytest
from django.utils import timezone

from elections.models import Election
from ops.models import SyncLog
from results.tasks import advance_past_elections

pytestmark = pytest.mark.django_db


def _election(status, days_offset, *, state="CA", name="Test Election"):
    return Election.objects.create(
        name=name,
        election_date=timezone.localdate() + datetime.timedelta(days=days_offset),
        election_type=Election.ElectionType.GENERAL,
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state=state,
        status=status,
    )


def test_advances_past_dated_upcoming():
    e = _election(Election.Status.UPCOMING, -1)

    advance_past_elections()

    e.refresh_from_db()
    assert e.status == Election.Status.RESULTS_PENDING


def test_advances_past_dated_active():
    """Kentucky's case: 'active' falls through both pollers just as 'upcoming' does."""
    e = _election(Election.Status.ACTIVE, -1, state="KY")

    advance_past_elections()

    e.refresh_from_db()
    assert e.status == Election.Status.RESULTS_PENDING


def test_leaves_todays_election_alone():
    """Still reachable today by poll_upcoming_results; advancing early would be wrong."""
    e = _election(Election.Status.ACTIVE, 0)

    advance_past_elections()

    e.refresh_from_db()
    assert e.status == Election.Status.ACTIVE


def test_leaves_future_election_alone():
    e = _election(Election.Status.UPCOMING, 7)

    advance_past_elections()

    e.refresh_from_db()
    assert e.status == Election.Status.UPCOMING


@pytest.mark.parametrize("terminal", sorted(Election.TERMINAL_STATUSES))
def test_never_reopens_a_terminal_election(terminal):
    """An election that finished must not be dragged back to results_pending."""
    e = _election(terminal, -30)

    advance_past_elections()

    e.refresh_from_db()
    assert e.status == terminal


def test_leaves_already_pending_election_untouched():
    e = _election(Election.Status.RESULTS_PENDING, -5)

    advance_past_elections()

    e.refresh_from_db()
    assert e.status == Election.Status.RESULTS_PENDING


def test_advances_a_long_orphaned_election():
    """The 2024 Minnesota primary case -- stranded for over a year."""
    e = _election(Election.Status.UPCOMING, -450, state="MN")

    result = advance_past_elections()

    e.refresh_from_db()
    assert e.status == Election.Status.RESULTS_PENDING
    assert e.pk in result["elections"]


def test_reports_count_and_writes_a_synclog():
    _election(Election.Status.UPCOMING, -1)
    _election(Election.Status.ACTIVE, -2)
    _election(Election.Status.UPCOMING, 5)  # future, untouched

    result = advance_past_elections()

    assert result["advanced"] == 2
    log = SyncLog.objects.get(task_name="advance_past_elections")
    assert log.status == SyncLog.Status.COMPLETED
    assert log.records_updated == 2


def test_is_idempotent():
    _election(Election.Status.UPCOMING, -1)

    first = advance_past_elections()
    second = advance_past_elections()

    assert first["advanced"] == 1
    assert second["advanced"] == 0
