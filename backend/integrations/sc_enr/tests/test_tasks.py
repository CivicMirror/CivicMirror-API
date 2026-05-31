"""
Tests for SC ENR Celery tasks.
"""
from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from integrations.sc_enr.models import ENRElection
from integrations.sc_enr.tasks import poll_sc_enr_elections, sync_sc_enr_results

# ------------------------------------------------------------------
# poll_sc_enr_elections
# ------------------------------------------------------------------

def _make_feed_entry(eid=130000, county=None, name="2026 General", dt="11/03/2026 07:00:00"):
    return {
        "ElectionName": name,
        "Date": dt,
        "State": "SC",
        "County": county,
        "EID": eid,
    }


def _make_mapped(eid=130000, county=None, scope=None):
    return {
        "eid": eid,
        "county": county,
        "scope": scope or "state",  # use literal string to avoid mock comparison issues
        "election_name": "2026 General",
        "election_date": date(2026, 11, 3),
        "enr_base_url": f"https://www.enr-scvotes.org/SC/{eid}/",
    }


@patch("integrations.sc_enr.tasks.ENRClient")
@patch("integrations.sc_enr.tasks.SyncLog")
def test_poll_sc_enr_empty_feed_no_creates(mock_synclog, mock_client_cls):
    """Empty feed → no create/update calls, is_active flag handled via bulk query."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.get_elections.return_value = []

    with patch("integrations.sc_enr.tasks.ENRElection") as mock_enr:
        mock_enr.objects.filter.return_value.__iter__ = MagicMock(return_value=iter([]))
        poll_sc_enr_elections()
        mock_enr.objects.create.assert_not_called()


@patch("integrations.sc_enr.tasks.ENRClient")
@patch("integrations.sc_enr.tasks.SyncLog")
def test_poll_sc_enr_creates_new_entry(mock_synclog, mock_client_cls):
    """New entry in feed → ENRElection.objects.create called."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.get_elections.return_value = [_make_feed_entry()]
    mock_client.resolve_url.return_value = "https://www.enr-scvotes.org/SC/130000/web.999/"

    with patch("integrations.sc_enr.tasks.map_enr_election") as mock_map, \
         patch("integrations.sc_enr.tasks.ENRElection") as mock_enr, \
         patch("integrations.sc_enr.tasks.attempt_election_link") as mock_link:

        mock_map.return_value = _make_mapped()

        # No existing record → create path
        mock_enr.objects.filter.return_value.first.return_value = None
        new_obj = MagicMock()
        new_obj.enr_resolved_url = ""
        new_obj.scope = "state"
        new_obj.election = None
        new_obj.link_confidence = ENRElection.LinkConfidence.AMBIGUOUS
        new_obj.election_id = None
        mock_enr.objects.create.return_value = new_obj
        # Stale query returns empty
        mock_enr.objects.filter.return_value.__iter__ = MagicMock(return_value=iter([]))

        mock_link.return_value = (None, ENRElection.LinkConfidence.AMBIGUOUS)

        poll_sc_enr_elections()

    mock_enr.objects.create.assert_called_once()


@patch("integrations.sc_enr.tasks.ENRClient")
@patch("integrations.sc_enr.tasks.SyncLog")
def test_poll_sc_enr_skips_resolve_if_url_already_set(mock_synclog, mock_client_cls):
    """resolve_url should not be called if enr_resolved_url is already populated."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.get_elections.return_value = [_make_feed_entry()]

    with patch("integrations.sc_enr.tasks.map_enr_election") as mock_map, \
         patch("integrations.sc_enr.tasks.ENRElection") as mock_enr, \
         patch("integrations.sc_enr.tasks.attempt_election_link") as mock_link:

        mock_map.return_value = _make_mapped()

        existing = MagicMock()
        existing.enr_resolved_url = "https://www.enr-scvotes.org/SC/130000/web.111/"
        existing.is_active = True
        existing.scope = "state"
        existing.election = None
        existing.election_id = None
        existing.link_confidence = ENRElection.LinkConfidence.AMBIGUOUS
        mock_enr.objects.filter.return_value.first.return_value = existing
        mock_enr.objects.filter.return_value.__iter__ = MagicMock(return_value=iter([]))

        mock_link.return_value = (None, ENRElection.LinkConfidence.AMBIGUOUS)

        poll_sc_enr_elections()

    mock_client.resolve_url.assert_not_called()


@patch("integrations.sc_enr.tasks.ENRClient")
@patch("integrations.sc_enr.tasks.SyncLog")
def test_poll_sc_enr_propagates_results_url_when_linked(mock_synclog, mock_client_cls):
    """Auto-linking a state ENRElection should route results_url through ingest."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.get_elections.return_value = [_make_feed_entry()]
    mock_client.resolve_url.return_value = "https://www.enr-scvotes.org/SC/130000/web.777/"

    with patch("integrations.sc_enr.tasks.map_enr_election") as mock_map, \
         patch("integrations.sc_enr.tasks.ENRElection") as mock_enr, \
         patch("integrations.sc_enr.tasks.attempt_election_link") as mock_link, \
         patch("aggregation.ingest.ingest_election") as mock_ingest_election:

        mock_map.return_value = _make_mapped()

        mock_enr.Scope.STATE = "state"
        mock_enr.Scope.COUNTY = "county"
        mock_enr.LinkConfidence.MANUAL = "manual"
        mock_enr.LinkConfidence.AMBIGUOUS = "ambiguous"
        mock_enr.LinkConfidence.AUTO = "auto"

        new_obj = MagicMock()
        new_obj.eid = 130000
        new_obj.enr_resolved_url = ""
        new_obj.scope = "state"
        new_obj.election = None
        new_obj.election_id = None
        new_obj.link_confidence = "ambiguous"
        mock_enr.objects.filter.return_value.first.return_value = None
        mock_enr.objects.create.return_value = new_obj
        mock_enr.objects.filter.return_value.__iter__ = MagicMock(return_value=iter([]))

        mock_election = MagicMock()
        mock_election.pk = 9
        mock_election.results_url = ""
        mock_link.return_value = (mock_election, "auto")
        mock_ingest_election.return_value = (mock_election, False)

        poll_sc_enr_elections()

    # results_url write goes through ingest_election, not direct save
    mock_election.save.assert_not_called()
    mock_ingest_election.assert_called_once()
    call_kwargs = mock_ingest_election.call_args.kwargs
    assert call_kwargs["source"] == "sc_enr"
    assert call_kwargs["fields"]["results_url"] == "https://www.enr-scvotes.org/SC/130000/web.777/"


# ------------------------------------------------------------------
# sync_sc_enr_results
# ------------------------------------------------------------------

@patch("integrations.sc_enr.tasks.ENRElection")
@patch("integrations.sc_enr.tasks.SyncLog")
def test_sync_sc_enr_results_skips_unlinked(mock_synclog, mock_enr):
    mock_enr.objects.filter.return_value.select_related.return_value = []
    with patch("results.tasks.ingest_official_results") as mock_ingest:
        sync_sc_enr_results()
        mock_ingest.apply_async.assert_not_called()


@patch("integrations.sc_enr.tasks.ENRElection")
@patch("integrations.sc_enr.tasks.SyncLog")
def test_sync_sc_enr_results_queues_linked_elections(mock_synclog, mock_enr):
    mock_e1 = MagicMock()
    mock_e1.election_id = 7
    mock_e1.enr_resolved_url = "https://www.enr-scvotes.org/SC/130000/web.777/"
    mock_e2 = MagicMock()
    mock_e2.election_id = 8
    mock_e2.enr_resolved_url = "https://www.enr-scvotes.org/SC/131000/web.888/"
    mock_enr.objects.filter.return_value.select_related.return_value = [mock_e1, mock_e2]

    with patch("results.tasks.ingest_official_results") as mock_ingest:
        sync_sc_enr_results()
        assert mock_ingest.apply_async.call_count == 2
        calls = mock_ingest.apply_async.call_args_list
        assert call(args=["SC", 7], countdown=0) in calls
        assert call(args=["SC", 8], countdown=5) in calls


@patch("integrations.sc_enr.tasks.ENRElection")
@patch("integrations.sc_enr.tasks.SyncLog")
def test_sync_sc_enr_results_filter_state_scope_only(mock_synclog, mock_enr):
    """Validate filter kwargs match state-only, linked, active selection."""
    mock_enr.objects.filter.return_value.select_related.return_value = []
    with patch("results.tasks.ingest_official_results"):
        sync_sc_enr_results()
    mock_enr.objects.filter.assert_called_once_with(
        is_active=True,
        scope=mock_enr.Scope.STATE,
        election__isnull=False,
    )


@patch("integrations.sc_enr.tasks.ENRElection")
@patch("integrations.sc_enr.tasks.SyncLog")
def test_sync_sc_enr_results_skips_entry_without_resolved_url(mock_synclog, mock_enr):
    """ENRElection with empty enr_resolved_url should be skipped."""
    mock_e = MagicMock()
    mock_e.election_id = 5
    mock_e.enr_resolved_url = ""
    mock_enr.objects.filter.return_value.select_related.return_value = [mock_e]

    with patch("results.tasks.ingest_official_results") as mock_ingest:
        sync_sc_enr_results()
        mock_ingest.apply_async.assert_not_called()
